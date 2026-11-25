"""Pruebas del pipeline de calidad: python -m pytest tests -q"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from calidad_qa.__main__ import main
from calidad_qa.config import ErrorConfiguracion, cargar_config
from calidad_qa.control import idempotencia, tabla_cuarentena
from calidad_qa.evaluar import Chequeo, veredicto_de
from calidad_qa.evidencia import aparece
from calidad_qa.metricas import cer, contar
from calidad_qa.normalizar import a_iso, a_numero, es_correcto
from calidad_qa.validadores import validar_campo, validar_ruc

RAIZ = Path(__file__).resolve().parent.parent
CONFIG = RAIZ / "config" / "calidad.yaml"


# --- Normalización y validadores (S03, S04, S05) ---
def test_fechas_y_montos_comparables():
    assert a_iso("24 de junio de 2026") == a_iso("24/06/2026") == a_iso("Lima, 2026-06-24") == "2026-06-24"
    assert a_iso("31/02/2026") is None
    assert a_numero("S/ 2,643.00") == a_numero(2643) == 2643.0


def test_es_correcto_por_valor_normalizado():
    assert es_correcto("entidad", "BANCO ANDINO DEMO S.A.", "Banco Andino DEMO S.A")
    assert es_correcto("monto", "S/ 2,643.00", 2643.004, numericos={"monto"})
    assert es_correcto("fecha", "10/09/2026", "2026-09-10", fechas={"fecha"})
    assert es_correcto("numero_reclamo", None, None)          # no consta y no se inventó
    assert not es_correcto("nombre", "Ana", None)               # inventado


def test_ruc_modulo_11_con_los_ejemplos_del_curso():
    assert validar_ruc("20992371634") and validar_ruc("20997531206")
    assert not validar_ruc("20992371635") and not validar_ruc("2099237163")


def test_validadores_de_coherencia():
    assert validar_campo("tea", 22.34, {"tcea": 22.34}, set(), set()) == (False, "TEA menor que TCEA")
    assert validar_campo("tea", 20.81, {"tcea": 22.34}, set(), set())[0]
    assert not validar_campo("moneda", "S/", {}, set(), set())[0]
    assert validar_campo("moneda", "PEN", {}, set(), set())[0]
    assert not validar_campo("emisor", "Ana Ruiz Soto", {}, set(), set())[0]
    assert validar_campo("nombre", "Ana", {}, set(), set()) is None   # sin validador


def test_evidencia_en_el_texto():
    assert aparece(39317.0, "Total activo 39,317") and aparece("2026-06-24", "Lima, 24 de junio de 2026")
    assert not aparece("2021-04-18", "Fecha: 26/03/2026")


# --- Métricas ---
def test_contar_con_las_definiciones_del_curso():
    igual = lambda c, p, v: p == v
    m = contar([("dni", "1", "1"), ("dni", "2", "3"), ("dni", None, "4"), ("dni", None, None)], igual)
    assert (m["correctos"], m["entregados"], m["bien_entregados"], m["no_nulos"]) == (2, 2, 1, 3)
    assert m["precision"] == 0.5 and m["exhaustividad"] == pytest.approx(1 / 3) and m["exactitud"] == 0.5


def test_cer():
    assert cer("hola mundo", "hola mundo") == 0.0
    assert cer("abcd", "abcf") == 0.25
    assert cer("", "") == 0.0 and cer("", "x") == 1.0


# --- Control del lote (S06) ---
def test_idempotencia_detecta_reproceso():
    a = pd.DataFrame({"archivo": ["A.pdf", "B.pdf"], "estado": ["ok", "ok"], "motivo": ["", ""], "segundos": ["1.0", "2.0"]})
    assert idempotencia(a, a.copy())["ok"]
    b = a.copy()
    b.loc[1, "segundos"] = "2.5"
    r = idempotencia(a, b)
    assert not r["ok"] and r["reprocesados_o_cambiados"] == 1
    assert idempotencia(a, None)["ok"] is None


def test_cuarentena_con_accion_del_supervisor():
    reg = pd.DataFrame({"archivo": ["X.pdf", "Y.pdf", "Z.pdf"], "estado": ["cuarentena", "duplicado", "ok"],
                        "motivo": ["pdf_cifrado", "mismo contenido que W.pdf", ""]})
    t = tabla_cuarentena(reg, [])
    assert list(t["archivo"]) == ["X.pdf", "Y.pdf"] and "contraseña" in t.loc[0, "accion_supervisor"]


def test_veredicto():
    c = lambda cumple, sev: Chequeo("x", "", 0, "", cumple, sev)
    assert veredicto_de([c(True, "critico"), c(True, "advertencia")]) == "APROBADO"
    assert veredicto_de([c(True, "critico"), c(False, "advertencia")]) == "APROBADO CON OBSERVACIONES"
    assert veredicto_de([c(None, "critico")]) == "APROBADO CON OBSERVACIONES"
    assert veredicto_de([c(False, "critico"), c(True, "advertencia")]) == "RECHAZADO"


# --- De punta a punta ---
def _lote(carpeta: Path, monto_pipeline: float) -> Path:
    """Un lote mínimo: 2 documentos y un registro, con el YAML del proyecto apuntando a esta carpeta."""
    (carpeta / "res").mkdir()
    (carpeta / "gt").mkdir()
    for i, monto in ((1, 100.0), (2, 250.5)):
        gt = {"dni": f"9900000{i}", "ruc": "20992371634", "monto_reclamado": monto, "fecha": "2026-03-26"}
        pred = dict(gt, monto_reclamado=monto_pipeline if i == 2 else monto)
        texto = f"DNI {gt['dni']} RUC 20992371634 S/ {pred['monto_reclamado']:,.2f} Fecha: 26/03/2026"
        (carpeta / "gt" / f"DOC-{i}.json").write_text(json.dumps(gt), encoding="utf-8")
        (carpeta / "res" / f"DOC-{i}.json").write_text(json.dumps(
            {"archivo": f"DOC-{i}.pdf", "tipo": "poliza", "estado": "ok", "campos": pred, "texto": texto}), encoding="utf-8")
    pd.DataFrame({"archivo": ["DOC-1.pdf", "DOC-2.pdf"], "estado": ["ok", "ok"], "motivo": ["", ""]}).to_parquet(carpeta / "reg.parquet")
    texto = CONFIG.read_text(encoding="utf-8")
    for viejo, nuevo in (("datos_ejemplo/resultados", "res"), ("datos_ejemplo/ground_truth", "gt"),
                         ("datos_ejemplo/registro_corrida_1.csv", "reg.parquet"),
                         ("datos_ejemplo/registro_corrida_2.csv", "reg.parquet"), ("datos_ejemplo/ocr_referencia", "")):
        texto = texto.replace(viejo, nuevo)
    (carpeta / "calidad.yaml").write_text(texto, encoding="utf-8")
    return carpeta / "calidad.yaml"


def test_lote_bueno_se_aprueba(tmp_path):
    yaml = _lote(tmp_path, monto_pipeline=250.5)
    assert main(["--config", str(yaml), "--base", str(tmp_path)]) == 0
    veredicto = json.loads((tmp_path / "salidas_calidad" / "veredicto.json").read_text(encoding="utf-8"))
    assert veredicto["veredicto"].startswith("APROBADO")
    assert (tmp_path / "salidas_calidad" / "reporte_calidad.html").is_file()
    assert (tmp_path / "salidas_calidad" / "metricas_calidad.xlsx").is_file()


def test_campo_critico_equivocado_rechaza(tmp_path):
    yaml = _lote(tmp_path, monto_pipeline=2505.0)      # la coma mal leída multiplica el monto por 10
    assert main(["--config", str(yaml), "--base", str(tmp_path)]) == 1
    veredicto = json.loads((tmp_path / "salidas_calidad" / "veredicto.json").read_text(encoding="utf-8"))
    fallan = {c["nombre"] for c in veredicto["chequeos"] if c["cumple"] is False}
    assert veredicto["veredicto"] == "RECHAZADO" and "f1_campo_critico" in fallan


def test_configuracion_invalida_se_detiene_al_inicio(tmp_path):
    (tmp_path / "malo.yaml").write_text("entradas: {resultados: x}\numbrales: {}\n", encoding="utf-8")
    with pytest.raises(ErrorConfiguracion):
        cargar_config(tmp_path / "malo.yaml")
    assert main(["--config", str(tmp_path / "malo.yaml")]) == 2
