"""Genera un lote de ejemplo, con datos ficticios, para probar el pipeline de calidad de punta a punta.

Uso: python generar_datos_ejemplo.py  (crea la carpeta datos_ejemplo/)
Reemplace estos datos por las salidas reales de su equipo antes de evaluar."""
from __future__ import annotations

import csv
import hashlib
import json
import random
import shutil
from pathlib import Path

RAIZ = Path(__file__).resolve().parent / "datos_ejemplo"
FASES = ["1_ingesta", "2_ocr", "3_pln", "4_llm"]
ENTIDADES = ["Banco Cordillera DEMO S.A.", "Financiera Andina DEMO S.A.", "Caja Rural Sol DEMO S.A."]
PRODUCTOS = ["tarjeta de crédito", "cuenta sueldo", "préstamo personal"]
MOTIVOS = ["cobro indebido", "demora en entrega", "cuenta cerrada"]
NOMBRES = ["Ana Ruiz Soto", "Luis Paz Vera", "Rosa Quispe Lima", "Carlos Díaz León", "Elena Rojas Mesa"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre"]


def ruc_valido(base10: str) -> str:
    pesos = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
    resto = 11 - sum(int(d) * p for d, p in zip(base10, pesos)) % 11
    return base10 + str({10: 0, 11: 1}.get(resto, resto))


def ensuciar(texto: str, tasa: float, rnd: random.Random) -> str:
    """Simula errores del OCR: confunde letras y cifras parecidas."""
    cambios = {"0": "O", "1": "l", "5": "S", "e": "c", "a": "o", "m": "rn"}
    return "".join(cambios.get(c, c) if rnd.random() < tasa else c for c in texto)


def documento(i: int, rnd: random.Random) -> tuple[dict, dict, str]:
    doc_id = f"REC-{i:04d}"
    dia, mes = rnd.randint(1, 28), rnd.randint(1, 10)
    monto = round(rnd.uniform(80, 5000), 2)
    correcto = {
        "dni": f"99{rnd.randint(100000, 999999)}", "nombre": rnd.choice(NOMBRES),
        "monto_reclamado": monto, "entidad": rnd.choice(ENTIDADES),
        "telefono": f"999000{rnd.randint(100, 999)}", "correo": f"cliente{i}@correo.demo",
        "producto": rnd.choice(PRODUCTOS), "fecha": f"2026-{mes:02d}-{dia:02d}", "motivo": rnd.choice(MOTIVOS),
        "ruc": ruc_valido(f"2099{rnd.randint(100000, 999999)}"),
    }
    texto = (f"Asunto: Reclamo {doc_id}\nSoy {correcto['nombre']}, DNI {correcto['dni']}. Reclamo a "
             f"{correcto['entidad']} (RUC {correcto['ruc']}) por mi {correcto['producto']}: {correcto['motivo']}.\n"
             f"Cargo del {dia} de {MESES[mes - 1]} de 2026 por S/ {monto:,.2f}.\n"
             f"Teléfono {correcto['telefono']} | {correcto['correo']}")
    return {"id": doc_id}, correcto, texto


def main() -> None:
    rnd = random.Random(2026)
    if RAIZ.exists():
        shutil.rmtree(RAIZ)
    for sub in ("resultados", "ground_truth", "ocr_referencia"):
        (RAIZ / sub).mkdir(parents=True)
    registro = []
    for i in range(1, 61):
        meta, correcto, texto = documento(i, rnd)
        doc_id = meta["id"]
        tasa_ocr = 0.25 if i in (7, 33) else rnd.choice([0.0, 0.005, 0.01, 0.02])
        leido = ensuciar(texto, tasa_ocr, rnd)
        final = dict(correcto)
        # Errores típicos del pipeline (para que el reporte tenga qué mostrar)
        if i in (4, 21):
            final["fecha"] = "2026-13-40" if i == 4 else final["fecha"]
            final["telefono"] = None if i == 21 else final["telefono"]
        if i in (12, 45):
            final["motivo"] = "cobro indebido" if correcto["motivo"] != "cobro indebido" else "cuenta cerrada"
        if i == 18:
            final["entidad"] = "Banco Cordillera"                     # entidad incompleta
        if i == 27:
            final["monto_reclamado"] = round(correcto["monto_reclamado"] * 10, 2)   # coma mal leída
        if i == 39:
            final["nombre"] = "Jorge Inventado Pérez"                 # no figura en el texto
        if i in (7, 33):
            final["dni"] = ensuciar(correcto["dni"], 0.4, rnd)
        fases = {
            "1_ingesta": {k: (v if k in ("correo", "telefono") else None) for k, v in final.items()},
            "2_ocr": {k: (v if k in ("correo", "telefono", "dni", "ruc", "monto_reclamado", "fecha") else None)
                      for k, v in final.items()},
            "3_pln": {k: (None if k == "motivo" else v) for k, v in final.items()},
            "4_llm": final,
        }
        puntaje = round(max(0.3, 0.97 - tasa_ocr * 2.5 - rnd.uniform(0, 0.05)), 3)
        resultado = {"archivo": f"{doc_id}.eml", "tipo": "reclamo", "estado": "ok", "campos": final, "fases": fases,
                     "texto": leido, "ocr": {"texto": leido, "confianza": round(puntaje + 0.02, 3), "puntaje": puntaje,
                                            "decision": "aceptar" if puntaje >= 0.85 else "revisar"},
                     "revisar": ["ruta del OCR"] if puntaje < 0.85 else []}
        (RAIZ / "resultados" / f"{doc_id}.json").write_text(json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8")
        (RAIZ / "ground_truth" / f"{doc_id}.json").write_text(json.dumps(correcto, ensure_ascii=False, indent=1), encoding="utf-8")
        (RAIZ / "ocr_referencia" / f"{doc_id}.txt").write_text(texto, encoding="utf-8")
        registro.append({"sha256": hashlib.sha256(texto.encode()).hexdigest(), "archivo": f"{doc_id}.eml",
                         "estado": "ok", "motivo": "", "intentos": 1, "segundos": round(rnd.uniform(0.2, 1.5), 3)})
    # Las trampas del lote (como LOT-* de S02/S06): cuarentena con motivo y un duplicado
    for archivo, motivo in [("LOT-0002.pdf", "extension_falsa"), ("LOT-0006.docx", "docx_corrupto"),
                            ("LOT-0007.pdf", "pdf_cifrado"), ("LOT-0014.pdf", "pdf_danado"), ("LOT-0016.pdf", "archivo_vacio")]:
        registro.append({"sha256": hashlib.sha256(archivo.encode()).hexdigest(), "archivo": archivo,
                         "estado": "cuarentena", "motivo": motivo, "intentos": 1, "segundos": 0.01})
    registro.append({"sha256": registro[0]["sha256"], "archivo": "REC-0061.eml", "estado": "duplicado",
                     "motivo": "mismo contenido que REC-0001.eml", "intentos": 1, "segundos": 0.0})
    for nombre in ("registro_corrida_1.csv", "registro_corrida_2.csv"):
        with open(RAIZ / nombre, "w", newline="", encoding="utf-8") as archivo:
            escritor = csv.DictWriter(archivo, fieldnames=list(registro[0]))
            escritor.writeheader()
            escritor.writerows(registro)
    print(f"Datos de ejemplo en {RAIZ}: 60 resultados, 5 en cuarentena, 1 duplicado y 2 corridas del registro.")


if __name__ == "__main__":
    main()
