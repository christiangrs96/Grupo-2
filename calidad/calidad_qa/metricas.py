"""Métricas contra los valores correctos: F1 por campo (S04), exactitud por fase y por tipo (S05/S06),
F1 macro de la clasificación (S04) y CER del OCR (S03)."""
from __future__ import annotations

from collections import Counter
from typing import Any, Callable

import pandas as pd
from rapidfuzz.distance import Levenshtein
from sklearn.metrics import confusion_matrix, f1_score

from .normalizar import normalizar_valor, plano, vacio

Comparador = Callable[[str, Any, Any], bool]


def _f1(precision: float, exhaustividad: float) -> float:
    return 2 * precision * exhaustividad / (precision + exhaustividad) if precision + exhaustividad else 0.0


def contar(pares: list[tuple[str, Any, Any]], es_correcto: Comparador) -> dict[str, float]:
    """Cuenta sobre pares (campo, predicho, correcto) con las definiciones del curso (evaluar_bandeja, S05):
    precisión = bien entregados / entregados; exhaustividad = bien entregados / correctos no vacíos;
    exactitud = correctos / esperados (un vacío donde el dato no consta cuenta como acierto)."""
    esperados = len(pares)
    correctos = sum(es_correcto(c, p, v) for c, p, v in pares)
    entregados = sum(not vacio(p) for _, p, _ in pares)
    bien_entregados = sum(es_correcto(c, p, v) for c, p, v in pares if not vacio(p))
    no_nulos = sum(not vacio(v) for _, _, v in pares)
    precision = bien_entregados / entregados if entregados else 0.0
    exhaustividad = bien_entregados / no_nulos if no_nulos else 0.0
    return {"esperados": esperados, "correctos": correctos, "entregados": entregados,
            "bien_entregados": bien_entregados, "no_nulos": no_nulos,
            "exactitud": correctos / esperados if esperados else 0.0,
            "precision": precision, "exhaustividad": exhaustividad, "f1": _f1(precision, exhaustividad)}


def pares_de(resultados: list[dict[str, Any]], correctos: dict[str, dict[str, Any]], campos: list[str],
             clave: Callable[[dict[str, Any]], dict[str, Any]]) -> list[tuple[str, str, str, Any, Any]]:
    """(id, tipo, campo, predicho, correcto) de cada campo medido. Un documento con valores correctos que no
    llegó en los resultados, o que no terminó «ok», cuenta con todos sus campos vacíos: no se esconde."""
    por_id = {r["_id"]: r for r in resultados}
    filas = []
    for doc_id, correcto in correctos.items():
        r = por_id.get(doc_id)
        pred = clave(r) if r is not None and r.get("estado") == "ok" else {}
        tipo = r["tipo"] if r is not None else "sin_resultado"
        for campo in campos:
            if campo in correcto:
                filas.append((doc_id, tipo, campo, pred.get(campo), correcto[campo]))
    return filas


def f1_por_campo(pares: list[tuple[str, str, str, Any, Any]], es_correcto: Comparador) -> pd.DataFrame:
    """Precisión, exhaustividad, F1 y exactitud de cada campo."""
    filas = []
    for campo in dict.fromkeys(p[2] for p in pares):
        sub = [(c, pr, v) for _, _, c, pr, v in pares if c == campo]
        filas.append({"campo": campo, **contar(sub, es_correcto)})
    return pd.DataFrame(filas)


def por_tipo(pares: list[tuple[str, str, str, Any, Any]], es_correcto: Comparador) -> pd.DataFrame:
    """Las mismas métricas, agrupadas por tipo de documento."""
    filas = []
    for tipo in dict.fromkeys(p[1] for p in pares):
        sub = [(c, pr, v) for _, t, c, pr, v in pares if t == tipo]
        filas.append({"tipo": tipo, **contar(sub, es_correcto)})
    return pd.DataFrame(filas)


def por_fase(resultados: list[dict[str, Any]], correctos: dict[str, dict[str, Any]], campos: list[str],
             fases: list[str], es_correcto: Comparador) -> pd.DataFrame:
    """Exactitud después de cada fase, con la misma vara (S05 evaluar_bandeja). Vacía si no hay fases."""
    con_fases = [r for r in resultados if r.get("fases")]
    if not con_fases or not fases:
        return pd.DataFrame()
    filas = []
    for fase in fases:
        pares = pares_de(con_fases, {r["_id"]: correctos[r["_id"]] for r in con_fases if r["_id"] in correctos},
                         campos, lambda r, f=fase: (r.get("fases") or {}).get(f, {}))
        filas.append({"fase": fase, **contar([(c, p, v) for _, _, c, p, v in pares], es_correcto)})
    return pd.DataFrame(filas)


def clasificacion(pares: list[tuple[str, str, str, Any, Any]], campo: str) -> dict[str, Any] | None:
    """F1 macro y matriz de confusión de un campo categórico (S04). None si el campo no se mide."""
    sub = [(plano(pr) if not vacio(pr) else "(vacío)", plano(v)) for _, _, c, pr, v in pares if c == campo and not vacio(v)]
    if not sub:
        return None
    predichas, correctas = [p for p, _ in sub], [v for _, v in sub]
    etiquetas = sorted(set(correctas) | set(predichas))
    matriz = pd.DataFrame(confusion_matrix(correctas, predichas, labels=etiquetas), index=etiquetas, columns=etiquetas)
    matriz.index.name = "correcto \\ predicho"
    return {"campo": campo, "f1_macro": float(f1_score(correctas, predichas, labels=sorted(set(correctas)),
                                                       average="macro", zero_division=0)),
            "n": len(sub), "matriz": matriz}


def cer(referencia: str, hipotesis: str) -> float:
    """Tasa de error de caracteres: ediciones mínimas entre la lectura y el texto correcto / largo del correcto."""
    ref, hip = plano(referencia), plano(hipotesis)
    if not ref:
        return 0.0 if not hip else 1.0
    return Levenshtein.distance(ref, hip) / len(ref)


def cer_por_documento(resultados: list[dict[str, Any]], referencias: dict[str, str]) -> pd.DataFrame:
    """CER de cada documento que tiene texto de referencia y texto del OCR."""
    filas = []
    for r in resultados:
        ocr = r.get("ocr") or {}
        texto = ocr.get("texto") or r.get("texto")
        if r["_id"] in referencias and texto:
            filas.append({"archivo": r["archivo"], "tipo": r["tipo"], "cer": cer(referencias[r["_id"]], texto),
                          "confianza": ocr.get("confianza"), "puntaje": ocr.get("puntaje"),
                          "decision_ocr": ocr.get("decision")})
    return pd.DataFrame(filas)


def comparador(numericos: set[str], fechas: set[str], tolerancia: float) -> Comparador:
    from .normalizar import es_correcto

    return lambda campo, p, v: es_correcto(campo, p, v, numericos, fechas, tolerancia)


def campos_a_medir(correctos: dict[str, dict[str, Any]], pedidos: list[str]) -> list[str]:
    """Los campos del YAML o, si no se indican, todos los del ground truth (en orden de aparición)."""
    if pedidos:
        return pedidos
    return list(Counter(c for doc in correctos.values() for c in doc))


__all__ = ["contar", "pares_de", "f1_por_campo", "por_tipo", "por_fase", "clasificacion", "cer",
           "cer_por_documento", "comparador", "campos_a_medir", "normalizar_valor"]
