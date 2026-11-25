"""Validadores de formato y de coherencia (S03 puntuar y S05 validar_campo): no necesitan valores correctos."""
from __future__ import annotations

import re
from typing import Any, Callable

from .normalizar import a_iso, a_numero, plano, vacio

PESOS_RUC = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)


def validar_ruc(valor: Any) -> bool:
    """11 cifras y dígito verificador con módulo 11."""
    ruc = re.sub(r"\D", "", str(valor))
    if len(ruc) != 11:
        return False
    resto = 11 - sum(int(d) * p for d, p in zip(ruc[:10], PESOS_RUC)) % 11
    return int(ruc[10]) == {10: 0, 11: 1}.get(resto, resto)


def validar_dni(valor: Any) -> bool:
    return bool(re.fullmatch(r"\d{8}", str(valor).strip()))


def validar_fecha(valor: Any) -> bool:
    return a_iso(valor) is not None


def validar_monto(valor: Any) -> bool:
    numero = a_numero(valor)
    return numero is not None and numero >= 0


def validar_moneda(valor: Any) -> bool:
    return str(valor).strip().upper() in {"PEN", "USD"}


def validar_correo(valor: Any) -> bool:
    return bool(re.fullmatch(r"[\w.+-]+@[\w-]+(\.[\w-]+)+", str(valor).strip()))


def validar_telefono(valor: Any) -> bool:
    return bool(re.fullmatch(r"9\d{8}", re.sub(r"\D", "", str(valor))))


def validar_emisor(valor: Any) -> bool:
    """El emisor de un oficio es una intendencia."""
    return plano(valor).startswith("intendencia")


VALIDADORES: dict[str, Callable[[Any], bool]] = {
    "ruc": validar_ruc, "dni": validar_dni, "moneda": validar_moneda,
    "correo": validar_correo, "telefono": validar_telefono, "emisor": validar_emisor,
}


def validar_campo(campo: str, valor: Any, campos: dict[str, Any], fechas: set[str],
                  numericos: set[str]) -> tuple[bool, str] | None:
    """Aplica el validador del campo. Devuelve (pasa, regla) o None si el campo no tiene validador o está vacío."""
    if vacio(valor):
        return None
    if campo == "tea" and not vacio(campos.get("tcea")):
        tea, tcea = a_numero(valor), a_numero(campos["tcea"])
        return (tea is not None and tcea is not None and tea < tcea), "TEA menor que TCEA"
    if campo in VALIDADORES:
        return VALIDADORES[campo](valor), f"formato de {campo}"
    if campo in fechas:
        return validar_fecha(valor), "fecha que existe"
    if campo in numericos:
        return validar_monto(valor), "monto numérico y no negativo"
    return None
