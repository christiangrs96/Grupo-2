"""Llevar valores a una forma comparable (como normalizar_valor de S04 y a_iso / a_numero de S05)."""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Any

MESES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
         "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12}


def plano(texto: Any) -> str:
    """Minúsculas, sin tildes y con un solo espacio."""
    texto = unicodedata.normalize("NFKD", str(texto))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto.lower()).strip()


def vacio(valor: Any) -> bool:
    """None, texto vacío o NaN cuentan como «no entregado»."""
    if valor is None:
        return True
    if isinstance(valor, float) and valor != valor:
        return True
    return isinstance(valor, str) and valor.strip() in ("", "null", "None")


def a_iso(valor: Any) -> str | None:
    """Fecha escrita (24/06/2026, 24 de junio de 2026 o 2026-06-24) a AAAA-MM-DD; None si no existe."""
    if vacio(valor):
        return None
    texto = plano(valor)
    for patron, orden in ((r"(\d{4})-(\d{1,2})-(\d{1,2})", "amd"), (r"(\d{1,2})/(\d{1,2})/(\d{4})", "dma")):
        m = re.search(patron, texto)
        if m:
            partes = dict(zip(orden, map(int, m.groups())))
            break
    else:
        m = re.search(r"(\d{1,2}) de (\w+) de (\d{4})", texto)
        if not m or m.group(2) not in MESES:
            return None
        partes = {"d": int(m.group(1)), "m": MESES[m.group(2)], "a": int(m.group(3))}
    try:
        return date(partes["a"], partes["m"], partes["d"]).isoformat()
    except ValueError:
        return None


def a_numero(valor: Any) -> float | None:
    """Monto a número: «S/ 2,643.00» y 2643 dan 2643.0."""
    if vacio(valor):
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = re.sub(r"[^\d.,-]", "", str(valor))
    if not texto:
        return None
    if "," in texto and "." in texto:
        texto = texto.replace(",", "")
    elif "," in texto:
        texto = texto.replace(",", "." if len(texto.split(",")[-1]) == 2 else "")
    try:
        return float(texto)
    except ValueError:
        return None


def normalizar_valor(campo: str, valor: Any, numericos: set[str] = frozenset(),
                     fechas: set[str] = frozenset()) -> Any:
    """Forma comparable según el campo: número, fecha ISO o texto plano sin signos sobrantes."""
    if vacio(valor):
        return None
    if campo in numericos:
        return a_numero(valor)
    if campo in fechas:
        return a_iso(valor) or plano(valor)
    return re.sub(r"[^\w@.\-/ ]", "", plano(valor)).strip(" .") or None


def es_correcto(campo: str, predicho: Any, correcto: Any, numericos: set[str] = frozenset(),
                fechas: set[str] = frozenset(), tolerancia: float = 0.01) -> bool:
    """Compara por valor normalizado. Dos vacíos son correctos: el dato no consta y no se inventó."""
    p = normalizar_valor(campo, predicho, numericos, fechas)
    c = normalizar_valor(campo, correcto, numericos, fechas)
    if p is None or c is None:
        return p is None and c is None
    if isinstance(p, float) and isinstance(c, float):
        return abs(p - c) <= tolerancia
    return p == c
