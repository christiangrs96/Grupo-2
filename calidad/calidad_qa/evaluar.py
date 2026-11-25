"""Evaluación completa: carga las entradas, calcula todo y compara cada estadístico con su umbral."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from . import cargar, control, evidencia, metricas
from .config import Config
from .normalizar import vacio


@dataclass
class Chequeo:
    """Un estadístico comparado con su umbral."""

    nombre: str
    descripcion: str
    valor: Any
    umbral: str
    cumple: bool | None          # None = no se pudo evaluar (falta la entrada)
    severidad: str
    detalle: str = ""


@dataclass
class Evaluacion:
    """Todo lo que produce el pipeline de calidad."""

    chequeos: list[Chequeo]
    veredicto: str
    tablas: dict[str, pd.DataFrame] = field(default_factory=dict)
    resumen: dict[str, Any] = field(default_factory=dict)


def _chequeo(cfg: Config, nombre: str, descripcion: str, valor: Any, detalle: str = "") -> Chequeo:
    u = cfg.umbrales[nombre]
    if u.requerido is not None:
        umbral, cumple = "sí", (None if valor is None else bool(valor) == u.requerido)
    elif u.minimo is not None:
        umbral, cumple = f"≥ {u.minimo:g}", (None if valor is None else valor >= u.minimo)
    else:
        umbral, cumple = f"≤ {u.maximo:g}", (None if valor is None else valor <= u.maximo)
    if isinstance(valor, float):
        valor = round(valor, 4)
    return Chequeo(nombre, descripcion, valor, umbral, cumple, u.severidad, detalle)


def veredicto_de(chequeos: list[Chequeo]) -> str:
    """RECHAZADO si falla un crítico; CON OBSERVACIONES si falla una advertencia o algo no se evaluó."""
    if any(c.cumple is False and c.severidad == "critico" for c in chequeos):
        return "RECHAZADO"
    if any(c.cumple is not True for c in chequeos):
        return "APROBADO CON OBSERVACIONES"
    return "APROBADO"


def evaluar(cfg: Config) -> Evaluacion:
    # 1. Entradas
    resultados = cargar.cargar_resultados(cfg.ruta(cfg.entradas.resultados))
    for r in resultados:
        r["_id"] = cargar.id_de(r["archivo"])
    correctos = cargar.cargar_ground_truth(cfg.ruta(cfg.entradas.ground_truth))
    registro_1 = cargar.cargar_registro(cfg.ruta(cfg.entradas.registro.corrida_1))
    registro_2 = cargar.cargar_registro(cfg.ruta(cfg.entradas.registro.corrida_2))
    referencias = cargar.cargar_ocr_referencia(cfg.ruta(cfg.entradas.ocr_referencia))

    numericos, fechas = set(cfg.campos.numericos), set(cfg.campos.fechas)
    es_correcto = metricas.comparador(numericos, fechas, cfg.campos.tolerancia_monto)
    campos = metricas.campos_a_medir(correctos, cfg.campos.medir)
    criticos = [c for c in cfg.campos.criticos if c in campos]
    U = cfg.umbrales
    chequeos: list[Chequeo] = []

    # 2. Control del lote (S06)
    cob = control.cobertura(resultados, registro_1)
    cuarentena = control.tabla_cuarentena(registro_1, resultados)
    idem = control.idempotencia(registro_1, registro_2)
    chequeos += [
        _chequeo(cfg, "cobertura_registro", "Archivos con estado final en el registro", cob["cobertura"],
                 f"{cob['con_estado']} de {cob['archivos']} ({cob['fuente']})"),
        _chequeo(cfg, "cuarentena_con_motivo", "Archivos en cuarentena que tienen motivo",
                 control.cuarentena_con_motivo(cuarentena), f"{(cuarentena['estado'] == 'cuarentena').sum()} en cuarentena"),
        _chequeo(cfg, "tasa_error_lote", "Archivos que terminaron con error", cob["tasa_error"],
                 ", ".join(f"{k}: {v}" for k, v in cob["por_estado"].items())),
        _chequeo(cfg, "idempotencia", "La segunda corrida no reprocesa ni cambia el registro", idem["ok"], idem["detalle"]),
    ]

    # 3. Exactitud contra los valores correctos (S04, S05)
    pares = metricas.pares_de(resultados, correctos, campos, lambda r: r["campos"])
    por_campo = metricas.f1_por_campo(pares, es_correcto)
    no_criticos = por_campo[~por_campo["campo"].isin(criticos + cfg.campos.categoricos)]
    bajo = no_criticos[no_criticos["f1"] < U["f1_por_campo"].minimo]["campo"].tolist()
    chequeos.append(_chequeo(cfg, "f1_por_campo", "F1 mínimo entre los campos no críticos",
                             float(no_criticos["f1"].min()) if len(no_criticos) else None,
                             f"bajo el umbral: {', '.join(bajo) or 'ninguno'}"))
    crit = por_campo[por_campo["campo"].isin(criticos)]
    bajo_c = crit[crit["f1"] < U["f1_campo_critico"].minimo]["campo"].tolist()
    chequeos.append(_chequeo(cfg, "f1_campo_critico", f"F1 mínimo entre los campos críticos ({', '.join(criticos)})",
                             float(crit["f1"].min()) if len(crit) else None,
                             f"bajo el umbral: {', '.join(bajo_c) or 'ninguno'}"))
    ok_campos = (por_campo["f1"] >= U["f1_por_campo"].minimo).mean() if len(por_campo) else None
    chequeos.append(_chequeo(cfg, "proporcion_campos_ok", f"Campos con F1 ≥ {U['f1_por_campo'].minimo:g}",
                             None if ok_campos is None else float(ok_campos),
                             f"{int((por_campo['f1'] >= U['f1_por_campo'].minimo).sum())} de {len(por_campo)}"))
    globales = metricas.contar([(c, p, v) for _, _, c, p, v in pares], es_correcto)
    chequeos += [
        _chequeo(cfg, "f1_global", "F1 de todos los campos juntos", globales["f1"],
                 f"{globales['bien_entregados']} bien de {globales['entregados']} entregados; {globales['no_nulos']} con valor"),
        _chequeo(cfg, "precision_global", "De lo que se entregó, cuánto era correcto", globales["precision"]),
        _chequeo(cfg, "exactitud_final", "Campos correctos / campos esperados", globales["exactitud"],
                 f"{globales['correctos']} de {globales['esperados']}"),
    ]
    fases = metricas.por_fase(resultados, correctos, campos, cfg.fases, es_correcto)
    if fases.empty:
        sube, detalle_fases = None, "Los resultados no traen «fases»."
    else:
        valores = fases["exactitud"].tolist()
        sube = all(b >= a for a, b in zip(valores, valores[1:]))
        detalle_fases = " → ".join(f"{f}: {e:.1%}" for f, e in zip(fases["fase"], valores))
    chequeos.append(_chequeo(cfg, "exactitud_sube_por_fase", "La exactitud no baja de una fase a la siguiente",
                             sube, detalle_fases))
    clasif = [c for c in (metricas.clasificacion(pares, campo) for campo in cfg.campos.categoricos) if c]
    chequeos.append(_chequeo(cfg, "f1_macro_clasificacion", "F1 macro de los campos de clasificación (mínimo)",
                             min(c["f1_macro"] for c in clasif) if clasif else None,
                             "; ".join(f"{c['campo']}: {c['f1_macro']:.3f} (n={c['n']})" for c in clasif)
                             or "No hay campos categóricos con valores correctos."))

    # 4. OCR (S03)
    cer_docs = metricas.cer_por_documento(resultados, referencias)
    if cer_docs.empty:
        chequeos += [_chequeo(cfg, "cer_medio", "CER medio del OCR", None, "Sin texto de referencia u OCR."),
                     _chequeo(cfg, "cer_documento", "CER del peor documento", None, "Sin texto de referencia u OCR.")]
    else:
        altos = cer_docs[cer_docs["cer"] > U["cer_documento"].maximo]["archivo"].tolist()
        chequeos += [_chequeo(cfg, "cer_medio", "CER medio del OCR", float(cer_docs["cer"].mean()),
                              f"{len(cer_docs)} documentos medidos"),
                     _chequeo(cfg, "cer_documento", "CER del peor documento", float(cer_docs["cer"].max()),
                              f"sobre el umbral: {', '.join(altos) or 'ninguno'}")]

    # 5. Validadores y evidencia (S03, S05)
    valores = evidencia.revisar_valores(resultados, campos, fechas, numericos, U["similitud_evidencia"].minimo)
    validados = valores[valores["validador"].notna()]
    con_texto = valores[valores["evidencia"].notna()]
    chequeos += [
        _chequeo(cfg, "tasa_validadores_ok", "Valores que pasan su validador de formato o coherencia",
                 float(validados["validador"].astype(bool).mean()) if len(validados) else None,
                 f"{int((~validados['validador'].astype(bool)).sum())} fallan de {len(validados)} validados"),
        _chequeo(cfg, "tasa_sin_evidencia", "Valores que no figuran en el texto del documento",
                 float((~con_texto["evidencia"].astype(bool)).mean()) if len(con_texto) else None,
                 f"{int((~con_texto['evidencia'].astype(bool)).sum())} de {len(con_texto)} con texto disponible"),
    ]

    # 6. Revisión humana
    revisar = evidencia.lista_revisar(resultados, valores, cer_docs, criticos, U["puntaje_ocr_aceptar"].minimo,
                                      U["cer_documento"].maximo)
    ok_docs = sum(r.get("estado") == "ok" for r in resultados)
    chequeos.append(_chequeo(cfg, "tasa_revision_humana", "Documentos que pasan a revisión humana",
                             len(revisar) / ok_docs if ok_docs else None, f"{len(revisar)} de {ok_docs} documentos ok"))

    # 7. Errores campo por campo, para el análisis de errores y el caso límite
    errores = pd.DataFrame([{"id": i, "tipo": t, "campo": c, "predicho": p, "correcto": v,
                             "tipo_error": "faltante" if vacio(p) else ("inventado" if vacio(v) else "valor distinto")}
                            for i, t, c, p, v in pares if not es_correcto(c, p, v)],
                           columns=["id", "tipo", "campo", "predicho", "correcto", "tipo_error"])

    tablas = {"Metricas_campo": por_campo, "Por_tipo": metricas.por_tipo(pares, es_correcto), "Por_fase": fases,
              "Errores": errores, "OCR_CER": cer_docs, "Validadores": valores, "Revisar": revisar,
              "Cuarentena": cuarentena, "Idempotencia": pd.DataFrame([idem])}
    for c in clasif:
        tablas[f"Confusion_{c['campo']}"[:31]] = c["matriz"].reset_index()
    resumen = {"documentos_resultados": len(resultados), "documentos_ground_truth": len(correctos),
               "sin_resultado": sorted(set(correctos) - {r["_id"] for r in resultados}),
               "campos_medidos": campos, "campos_criticos": criticos, "por_estado": cob["por_estado"],
               "errores_por_tipo": errores["tipo_error"].value_counts().to_dict()}
    return Evaluacion(chequeos, veredicto_de(chequeos), tablas, resumen)
