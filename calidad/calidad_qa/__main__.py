"""Línea de comandos: python -m calidad_qa --config config/calidad.yaml

Devuelve 0 si el lote se aprueba (con o sin observaciones), 1 si se rechaza y 2 si una entrada
o la configuración no son válidas. Así se puede usar como compuerta de calidad en otro script."""
from __future__ import annotations

import argparse
import sys

from .cargar import EntradaInvalida
from .config import ErrorConfiguracion, cargar_config
from .evaluar import evaluar
from .reporte import escribir_salidas


def main(argumentos: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="calidad_qa", description="Evalúa la calidad de un lote del pipeline.")
    parser.add_argument("--config", default=None, help="YAML de calidad (por defecto config/calidad.yaml)")
    parser.add_argument("--base", default=None, help="Carpeta desde la que se leen las rutas relativas del YAML")
    parser.add_argument("--salida", default=None, help="Carpeta de salida (reemplaza la del YAML)")
    args = parser.parse_args(argumentos)
    try:
        cfg = cargar_config(args.config, args.base)
        ev = evaluar(cfg)
    except (ErrorConfiguracion, EntradaInvalida) as error:
        print(f"✘ {error}", file=sys.stderr)
        return 2
    salidas = escribir_salidas(ev, cfg.ruta(args.salida or cfg.salida.carpeta), cfg.salida.titulo)

    simbolo = {True: "✔", False: "✘", None: "—"}
    for c in ev.chequeos:
        print(f"{simbolo[c.cumple]} [{c.severidad:<11}] {c.nombre:<26} {str(c.valor):<10} umbral {c.umbral}")
    print(f"\nVEREDICTO: {ev.veredicto}")
    for tipo, ruta in salidas.items():
        print(f"  {tipo}: {ruta}")
    return 1 if ev.veredicto == "RECHAZADO" else 0


if __name__ == "__main__":
    sys.exit(main())
