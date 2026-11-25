"""Salida: veredicto en JSON, métricas en Excel (una hoja por tabla) y reporte HTML."""
from __future__ import annotations

import html
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import pandas as pd

from .evaluar import Evaluacion

COLORES = {"APROBADO": "#1b7f3b", "APROBADO CON OBSERVACIONES": "#b26a00", "RECHAZADO": "#b3261e"}


def _estado(cumple: bool | None) -> str:
    return {True: "✔ cumple", False: "✘ no cumple", None: "— no evaluado"}[cumple]


def tabla_chequeos(ev: Evaluacion) -> pd.DataFrame:
    filas = [{**asdict(c), "estado": _estado(c.cumple)} for c in ev.chequeos]
    return pd.DataFrame(filas)[["estado", "severidad", "nombre", "descripcion", "valor", "umbral", "detalle"]]


def escribir_json(ev: Evaluacion, ruta: Path) -> Path:
    datos = {"veredicto": ev.veredicto, "fecha": datetime.now().isoformat(timespec="seconds"),
             "chequeos": [asdict(c) for c in ev.chequeos], "resumen": ev.resumen}
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return ruta


def escribir_excel(ev: Evaluacion, ruta: Path) -> Path:
    with pd.ExcelWriter(ruta, engine="openpyxl") as libro:
        tabla_chequeos(ev).to_excel(libro, sheet_name="Resumen", index=False)
        for nombre, tabla in ev.tablas.items():
            (tabla if not tabla.empty else pd.DataFrame({"nota": ["Sin datos para esta tabla."]})).to_excel(
                libro, sheet_name=nombre[:31], index=False)
        for hoja in libro.sheets.values():
            for columna in hoja.columns:
                ancho = max(len(str(c.value or "")) for c in columna[:200])
                hoja.column_dimensions[columna[0].column_letter].width = min(max(ancho + 2, 10), 60)
    return ruta


def _html_tabla(tabla: pd.DataFrame, max_filas: int = 60) -> str:
    if tabla.empty:
        return "<p class='nota'>Ninguno.</p>"
    vista = tabla.head(max_filas).copy()
    for col in vista.select_dtypes("float").columns:
        vista[col] = vista[col].map(lambda x: "" if pd.isna(x) else f"{x:.3f}")
    extra = f"<p class='nota'>Se muestran {max_filas} de {len(tabla)} filas; el Excel trae todas.</p>" if len(tabla) > max_filas else ""
    return vista.to_html(index=False, escape=True, border=0, classes="t", na_rep="") + extra


def escribir_html(ev: Evaluacion, ruta: Path, titulo: str) -> Path:
    filas = "".join(
        f"<tr class='{ {True: 'ok', False: 'mal', None: 'na'}[c.cumple] }'><td>{_estado(c.cumple)}</td>"
        f"<td>{c.severidad}</td><td><b>{html.escape(c.nombre)}</b><br><span class='nota'>{html.escape(c.descripcion)}</span></td>"
        f"<td>{html.escape(str(c.valor))}</td><td>{html.escape(c.umbral)}</td><td>{html.escape(str(c.detalle))}</td></tr>"
        for c in ev.chequeos)
    secciones = [
        ("Métricas por campo", "Precisión = bien entregados / entregados; exhaustividad = bien entregados / con valor correcto; exactitud = correctos / esperados.", "Metricas_campo"),
        ("Exactitud por fase", "Debe subir (o mantenerse) en cada fase.", "Por_fase"),
        ("Exactitud por tipo de documento", "", "Por_tipo"),
        ("Lista «revisar»", "Documentos que una persona debe mirar, con todas sus causas.", "Revisar"),
        ("Cuarentena y duplicados", "Con el motivo y qué haría el supervisor.", "Cuarentena"),
        ("Idempotencia", "Primera frente a segunda corrida sobre la misma salida.", "Idempotencia"),
        ("CER del OCR por documento", "", "OCR_CER"),
        ("Errores campo por campo", "Base para el análisis de errores y para elegir el caso límite.", "Errores"),
    ] + [(f"Matriz de confusión: {n.split('_', 1)[1]}", "Filas: valor correcto; columnas: valor predicho.", n)
         for n in ev.tablas if n.startswith("Confusion_")]
    cuerpo = "".join(f"<h2>{t}</h2><p class='nota'>{n}</p>{_html_tabla(ev.tablas.get(k, pd.DataFrame()))}"
                     for t, n, k in secciones)
    r = ev.resumen
    pagina = f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8"><title>{html.escape(titulo)}</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;margin:32px auto;max-width:1150px;color:#1f2328;padding:0 16px}}
h1{{margin-bottom:4px}} h2{{margin-top:36px;border-bottom:1px solid #d0d7de;padding-bottom:4px}}
.veredicto{{display:inline-block;padding:10px 18px;border-radius:8px;color:#fff;font-size:20px;font-weight:600;background:{COLORES[ev.veredicto]}}}
table{{border-collapse:collapse;width:100%;font-size:13px}} th,td{{padding:6px 8px;border-bottom:1px solid #eaeef2;text-align:left;vertical-align:top}}
th{{background:#f6f8fa}} tr.ok td:first-child{{color:#1b7f3b;font-weight:600}} tr.mal td:first-child{{color:#b3261e;font-weight:600}}
tr.na td:first-child{{color:#6e7781}} .nota{{color:#57606a;font-size:12px}}
</style></head><body>
<h1>{html.escape(titulo)}</h1><p class="nota">Generado el {datetime.now():%d/%m/%Y %H:%M}. Documentos en resultados: {r['documentos_resultados']};
con valores correctos: {r['documentos_ground_truth']}; estados: {html.escape(str(r['por_estado']))}.</p>
<div class="veredicto">{ev.veredicto}</div>
<h2>Estadísticos frente a sus umbrales</h2>
<p class="nota">«crítico» bloquea la aprobación; «advertencia» aprueba con observaciones; «no evaluado» significa que faltó la entrada.</p>
<table><tr><th>Estado</th><th>Severidad</th><th>Estadístico</th><th>Valor</th><th>Umbral</th><th>Detalle</th></tr>{filas}</table>
{cuerpo}
<p class="nota">Solo documentos ficticios. Las métricas salen del código, no de valores escritos a mano.</p>
</body></html>"""
    ruta.write_text(pagina, encoding="utf-8")
    return ruta


def escribir_salidas(ev: Evaluacion, carpeta: Path, titulo: str) -> dict[str, Path]:
    carpeta.mkdir(parents=True, exist_ok=True)
    return {"html": escribir_html(ev, carpeta / "reporte_calidad.html", titulo),
            "excel": escribir_excel(ev, carpeta / "metricas_calidad.xlsx"),
            "json": escribir_json(ev, carpeta / "veredicto.json")}
