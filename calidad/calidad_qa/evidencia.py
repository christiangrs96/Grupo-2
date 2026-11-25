"""Validación sin valores correctos (S03 y S05): validadores, evidencia en el texto y la lista «revisar»."""
from __future__ import annotations

from typing import Any

import pandas as pd
from rapidfuzz import fuzz

from .normalizar import a_iso, a_numero, plano, vacio
from .validadores import validar_campo


def formas_de_fecha(iso: str) -> list[str]:
    """Las formas en que una fecha AAAA-MM-DD puede aparecer escrita en un documento."""
    from .normalizar import MESES

    a, m, d = iso.split("-")
    mes = next(k for k, v in MESES.items() if v == int(m))
    return [iso, f"{d}/{m}/{a}", f"{int(d)}/{int(m)}/{a}", f"{int(d)} de {mes} de {a}"]


def aparece(valor: Any, texto: str, similitud: float = 90) -> bool:
    """Dice si el valor figura en el texto (evidencia literal, sin tildes ni mayúsculas)."""
    if vacio(valor) or not texto:
        return True
    base = plano(texto)
    candidatos = [plano(valor)]
    iso = a_iso(valor)
    if iso:
        candidatos += formas_de_fecha(iso)
    numero = a_numero(valor) if not iso else None
    if numero is not None:
        candidatos += [f"{numero:,.2f}", f"{numero:.2f}", f"{numero:,.0f}", f"{numero:.0f}"]
    return any(c in base or fuzz.partial_ratio(c, base) >= similitud for c in candidatos if c)


def revisar_valores(resultados: list[dict[str, Any]], campos: list[str], fechas: set[str], numericos: set[str],
                    similitud: float) -> pd.DataFrame:
    """Cada valor entregado, con su validador y su evidencia. Lo que falla pasa a «revisar» con su causa."""
    filas = []
    for r in resultados:
        if r.get("estado") != "ok":
            continue
        texto = r.get("texto") or (r.get("ocr") or {}).get("texto") or ""
        for campo in campos:
            valor = r["campos"].get(campo)
            if vacio(valor):
                continue
            validacion = validar_campo(campo, valor, r["campos"], fechas, numericos)
            evidencia = aparece(valor, texto, similitud) if texto else None
            causa = ""
            if validacion is not None and not validacion[0]:
                causa = f"no pasa el validador ({validacion[1]})"
            elif evidencia is False:
                causa = "no figura en el texto"
            filas.append({"archivo": r["archivo"], "tipo": r["tipo"], "campo": campo, "valor": valor,
                          "validador": None if validacion is None else validacion[0],
                          "regla": None if validacion is None else validacion[1],
                          "evidencia": evidencia, "causa": causa})
    return pd.DataFrame(filas, columns=["archivo", "tipo", "campo", "valor", "validador", "regla", "evidencia", "causa"])


def lista_revisar(resultados: list[dict[str, Any]], valores: pd.DataFrame, cer_docs: pd.DataFrame,
                  campos_criticos: list[str], umbral_puntaje: float, umbral_cer: float) -> pd.DataFrame:
    """Documentos que una persona debe mirar, con todas sus causas juntas."""
    causas: dict[str, list[str]] = {}

    def agregar(archivo: str, causa: str) -> None:
        causas.setdefault(archivo, [])
        if causa not in causas[archivo]:
            causas[archivo].append(causa)

    for r in resultados:
        if r.get("estado") != "ok":
            continue
        for c in r.get("revisar") or r.get("causas_revision") or []:
            agregar(r["archivo"], f"pipeline: {c}")
        puntaje = (r.get("ocr") or {}).get("puntaje")
        if puntaje is not None and puntaje < umbral_puntaje:
            agregar(r["archivo"], f"puntaje OCR {puntaje:.2f} < {umbral_puntaje}")
        for campo in campos_criticos:
            if campo in r["campos"] and vacio(r["campos"][campo]):
                agregar(r["archivo"], f"campo crítico vacío: {campo}")
    for _, f in valores[valores["causa"] != ""].iterrows():
        agregar(f["archivo"], f"{f['campo']}: {f['causa']}")
    if not cer_docs.empty:
        for _, f in cer_docs[cer_docs["cer"] > umbral_cer].iterrows():
            agregar(f["archivo"], f"CER {f['cer']:.2f} > {umbral_cer}")
    return pd.DataFrame([{"archivo": a, "n_causas": len(c), "causas": " | ".join(c)} for a, c in causas.items()],
                        columns=["archivo", "n_causas", "causas"])
