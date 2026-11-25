"""Carga de las entradas: resultados del pipeline, valores correctos, registro del lote y texto de referencia del OCR."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


class EntradaInvalida(Exception):
    """Una entrada no existe o no cumple el contrato."""


def _leer_json(ruta: Path) -> Any:
    with open(ruta, encoding="utf-8") as archivo:
        return json.load(archivo)


def cargar_resultados(ruta: Path) -> list[dict[str, Any]]:
    """Resultados del pipeline: una carpeta con un .json por documento, un .json con una lista o un .jsonl.

    Cada resultado debe traer al menos ``archivo``. Si falta ``estado`` se asume ``ok``;
    si falta ``campos`` se toman los de la última fase.
    """
    if ruta is None or not ruta.exists():
        raise EntradaInvalida(f"No existen los resultados: {ruta}")
    if ruta.is_dir():
        resultados = [_leer_json(p) for p in sorted(ruta.glob("*.json"))]
    elif ruta.suffix.lower() == ".jsonl":
        with open(ruta, encoding="utf-8") as archivo:
            resultados = [json.loads(linea) for linea in archivo if linea.strip()]
    else:
        datos = _leer_json(ruta)
        resultados = datos if isinstance(datos, list) else [datos]
    for i, r in enumerate(resultados):
        if "archivo" not in r:
            raise EntradaInvalida(f"El resultado {i} no trae la clave «archivo»")
        r.setdefault("estado", "error" if r.get("error") else "ok")
        if "campos" not in r and r.get("fases"):
            r["campos"] = dict(list(r["fases"].values())[-1])
        r.setdefault("campos", {})
        r.setdefault("tipo", "sin_tipo")
    return resultados


def cargar_ground_truth(carpeta: Path) -> dict[str, dict[str, Any]]:
    """Valores correctos: un .json por documento, con su nombre sin extensión como clave.

    Acepta el formato plano ``{campo: valor}`` o ``{"campos": {...}}``.
    """
    if carpeta is None or not carpeta.is_dir():
        raise EntradaInvalida(f"No existe la carpeta de valores correctos: {carpeta}")
    correctos = {}
    for ruta in sorted(carpeta.glob("*.json")):
        datos = _leer_json(ruta)
        correctos[ruta.stem] = datos.get("campos", datos) if isinstance(datos, dict) else {}
    if not correctos:
        raise EntradaInvalida(f"La carpeta de valores correctos está vacía: {carpeta}")
    return correctos


def cargar_registro(ruta: Path | None) -> pd.DataFrame | None:
    """El registro del lote (S06): .duckdb (tabla «registro»), .parquet o .csv. None si no se entregó."""
    if ruta is None:
        return None
    if not ruta.is_file():
        raise EntradaInvalida(f"No existe el registro: {ruta}")
    sufijo = ruta.suffix.lower()
    if sufijo == ".duckdb":
        import duckdb

        with duckdb.connect(str(ruta), read_only=True) as con:
            tabla = con.execute("SELECT * FROM registro").df()
    elif sufijo == ".parquet":
        tabla = pd.read_parquet(ruta)
    elif sufijo == ".csv":
        tabla = pd.read_csv(ruta, dtype=str, keep_default_na=False)
    else:
        raise EntradaInvalida(f"Formato de registro no soportado: {ruta.name}")
    faltan = {"archivo", "estado"} - set(tabla.columns)
    if faltan:
        raise EntradaInvalida(f"Al registro le faltan columnas: {', '.join(sorted(faltan))}")
    if "motivo" not in tabla.columns:
        tabla["motivo"] = ""
    return tabla.fillna("").astype({"archivo": str, "estado": str, "motivo": str})


def cargar_ocr_referencia(carpeta: Path | None) -> dict[str, str]:
    """Texto correcto de cada documento leído con OCR: un .txt por documento. Vacío si no se entregó."""
    if carpeta is None or not carpeta.is_dir():
        return {}
    return {ruta.stem: ruta.read_text(encoding="utf-8") for ruta in sorted(carpeta.glob("*.txt"))}


def id_de(archivo: str) -> str:
    """Nombre sin extensión: la clave que une resultados y valores correctos."""
    return Path(archivo).stem
