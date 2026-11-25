"""Control del lote (S06): cobertura del registro, cuarentena con motivo, errores e idempotencia."""
from __future__ import annotations

from typing import Any

import pandas as pd

QUE_HARIA_EL_SUPERVISOR = {
    "extension_falsa": "Pedir el archivo con la extensión correcta o renombrarlo y volver a procesar.",
    "docx_corrupto": "Pedir al remitente que reenvíe el documento.",
    "pdf_cifrado": "Pedir la contraseña o una copia sin cifrar.",
    "pdf_danado": "Pedir que se reenvíe; el archivo no se puede abrir.",
    "archivo_vacio": "Avisar al remitente: llegó sin contenido.",
    "formato_no_soportado": "Convertir a un formato con lector (PDF, DOCX, HTML, EML o imagen).",
}


def cobertura(resultados: list[dict[str, Any]], registro: pd.DataFrame | None) -> dict[str, Any]:
    """Qué parte de los archivos tiene un estado final y cuántos terminaron en cada estado."""
    if registro is not None:
        estados = registro["estado"].str.strip().str.lower()
        total = len(registro)
        con_estado = int((estados != "").sum())
    else:
        estados = pd.Series([str(r.get("estado", "")).lower() for r in resultados])
        total = len(resultados)
        con_estado = int((estados != "").sum())
    conteo = estados.value_counts().to_dict()
    return {"archivos": total, "con_estado": con_estado, "cobertura": con_estado / total if total else 0.0,
            "por_estado": {k or "(sin estado)": int(v) for k, v in conteo.items()},
            "tasa_error": conteo.get("error", 0) / total if total else 0.0,
            "fuente": "registro" if registro is not None else "resultados"}


def tabla_cuarentena(registro: pd.DataFrame | None, resultados: list[dict[str, Any]]) -> pd.DataFrame:
    """Archivos en cuarentena o duplicados, con su motivo y qué haría el supervisor."""
    if registro is not None:
        base = registro[["archivo", "estado", "motivo"]].copy()
    else:
        base = pd.DataFrame([{"archivo": r["archivo"], "estado": r.get("estado", ""),
                              "motivo": r.get("motivo", "")} for r in resultados])
    base = base[base["estado"].str.lower().isin(["cuarentena", "duplicado"])].reset_index(drop=True)
    base["accion_supervisor"] = [
        "Ninguna: su contenido ya se procesó con el original." if e.lower() == "duplicado"
        else QUE_HARIA_EL_SUPERVISOR.get(m, "Revisar el archivo a mano y registrar la causa.")
        for e, m in zip(base["estado"], base["motivo"])]
    return base


def cuarentena_con_motivo(tabla: pd.DataFrame) -> float:
    """Proporción de archivos en cuarentena que tienen motivo (1.0 si no hay ninguno)."""
    en_cuarentena = tabla[tabla["estado"].str.lower() == "cuarentena"]
    if en_cuarentena.empty:
        return 1.0
    return float((en_cuarentena["motivo"].str.strip() != "").mean())


def idempotencia(corrida_1: pd.DataFrame | None, corrida_2: pd.DataFrame | None) -> dict[str, Any]:
    """La segunda corrida sobre la misma salida no debe cambiar nada: mismas filas, mismos estados y,
    si el registro guarda segundos o intentos, los mismos valores (si cambian, el archivo se reprocesó)."""
    if corrida_1 is None or corrida_2 is None:
        return {"evaluada": False, "ok": None, "detalle": "Falta el registro de una de las dos corridas."}
    clave = ["archivo"] + (["sha256"] if "sha256" in corrida_1.columns and "sha256" in corrida_2.columns else [])
    columnas = [c for c in ("estado", "motivo", "intentos", "segundos") if c in corrida_1.columns and c in corrida_2.columns]
    a = corrida_1[clave + columnas].astype(str).set_index(clave).sort_index()
    b = corrida_2[clave + columnas].astype(str).set_index(clave).sort_index()
    nuevos = sorted(set(b.index) - set(a.index), key=str)
    perdidos = sorted(set(a.index) - set(b.index), key=str)
    comunes = a.index.intersection(b.index)
    cambiados = [str(i) for i in comunes if not a.loc[i].equals(b.loc[i])]
    ok = not nuevos and not perdidos and not cambiados
    return {"evaluada": True, "ok": ok, "filas_corrida_1": len(a), "filas_corrida_2": len(b),
            "filas_nuevas": len(nuevos), "filas_perdidas": len(perdidos), "reprocesados_o_cambiados": len(cambiados),
            "detalle": "La segunda corrida no cambió el registro." if ok else
            f"Nuevas: {nuevos[:5]} | perdidas: {perdidos[:5]} | cambiadas: {cambiados[:5]}"}
