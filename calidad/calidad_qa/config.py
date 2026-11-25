"""Configuración validada del pipeline de calidad: se lee el YAML y se detiene aquí si algo no cumple."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, ValidationError, model_validator

RUTA_CONFIG = Path(__file__).resolve().parent.parent / "config" / "calidad.yaml"


class ErrorConfiguracion(Exception):
    """La configuración no cumple el contrato."""


class Umbral(BaseModel):
    """Un umbral: mínimo, máximo o requerido, con su severidad."""

    minimo: float | None = None
    maximo: float | None = None
    requerido: bool | None = None
    severidad: Literal["critico", "advertencia"] = "advertencia"

    @model_validator(mode="after")
    def _uno_definido(self) -> "Umbral":
        if self.minimo is None and self.maximo is None and self.requerido is None:
            raise ValueError("cada umbral necesita minimo, maximo o requerido")
        return self


class Registro(BaseModel):
    corrida_1: str | None = ""
    corrida_2: str | None = ""


class Entradas(BaseModel):
    resultados: str
    ground_truth: str
    registro: Registro = Field(default_factory=Registro)
    ocr_referencia: str | None = ""


class Campos(BaseModel):
    medir: list[str] = Field(default_factory=list)
    criticos: list[str] = Field(default_factory=list)
    categoricos: list[str] = Field(default_factory=list)
    numericos: list[str] = Field(default_factory=list)
    fechas: list[str] = Field(default_factory=list)
    tolerancia_monto: float = 0.01


class Salida(BaseModel):
    carpeta: str = "salidas_calidad"
    titulo: str = "Reporte de calidad del lote"


UMBRALES_REQUERIDOS = (
    "cobertura_registro", "cuarentena_con_motivo", "tasa_error_lote", "idempotencia",
    "f1_por_campo", "f1_campo_critico", "proporcion_campos_ok", "f1_global", "precision_global",
    "exactitud_final", "exactitud_sube_por_fase", "f1_macro_clasificacion",
    "cer_medio", "cer_documento", "puntaje_ocr_aceptar",
    "tasa_validadores_ok", "tasa_sin_evidencia", "similitud_evidencia", "tasa_revision_humana",
)


class Config(BaseModel):
    entradas: Entradas
    campos: Campos = Field(default_factory=Campos)
    fases: list[str] = Field(default_factory=list)
    umbrales: dict[str, Umbral]
    salida: Salida = Field(default_factory=Salida)
    base: Path = Path(".")

    @model_validator(mode="after")
    def _umbrales_completos(self) -> "Config":
        faltan = [u for u in UMBRALES_REQUERIDOS if u not in self.umbrales]
        if faltan:
            raise ValueError(f"faltan umbrales: {', '.join(faltan)}")
        return self

    def ruta(self, valor: str | None) -> Path | None:
        """Una ruta del YAML, relativa a la carpeta base; None si está vacía."""
        if not valor:
            return None
        ruta = Path(valor)
        return ruta if ruta.is_absolute() else self.base / ruta


def _explicar(error: ValidationError) -> str:
    """Los errores de Pydantic en una línea cada uno y en palabras llanas."""
    return "\n".join(f"- {'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in error.errors())


def cargar_config(ruta: str | Path | None = None, base: str | Path | None = None) -> Config:
    """Lee el YAML y lo valida; si algo no cumple, se detiene aquí y no en medio de la evaluación."""
    ruta = Path(ruta) if ruta else RUTA_CONFIG
    if not ruta.is_file():
        raise ErrorConfiguracion(f"No existe la configuración: {ruta}")
    with open(ruta, encoding="utf-8") as archivo:
        datos: dict[str, Any] = yaml.safe_load(archivo) or {}
    datos["base"] = Path(base) if base else Path.cwd()
    try:
        return Config(**datos)
    except ValidationError as error:
        raise ErrorConfiguracion("La configuración no es válida:\n" + _explicar(error)) from None
