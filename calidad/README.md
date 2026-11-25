# Pipeline de calidad, proyecto de extracción documental

Recibe las salidas del pipeline del equipo, mide cada estadístico contra su umbral y entrega un **veredicto**
(`APROBADO`, `APROBADO CON OBSERVACIONES` o `RECHAZADO`) con su reporte. Usa la misma lógica del curso:
`f1_por_campo` (S04), `evaluar_bandeja` y `alucinaciones.py` (S05), CER y puntaje del OCR (S03),
cuarentena e idempotencia (S06).

> ⚠ Solo documentos y datos ficticios. Nada sale de la VM hacia servicios en la nube.

## Uso

```powershell
cd pipeline_calidad
pip install -r requirements.txt
python generar_datos_ejemplo.py                      # opcional: crea un lote de prueba en datos_ejemplo/
python -m calidad_qa --config config/calidad.yaml    # evalúa y escribe salidas_calidad/
python -m pytest tests -q                            # 13 passed
```

Para evaluar el lote real del equipo, solo se cambian las rutas de la sección `entradas` del YAML.

| Código de salida | Significado |
|---|---|
| `0` | Aprobado (con o sin observaciones) |
| `1` | Rechazado: falló al menos un chequeo crítico |
| `2` | Una entrada o la configuración no son válidas (se detiene antes de evaluar) |

## Estructura

```
pipeline_calidad/
├── config/calidad.yaml        # entradas, campos, umbrales y salida
├── calidad_qa/
│   ├── config.py              # lee y valida el YAML (pydantic)
│   ├── cargar.py              # resultados, ground truth, registro (.duckdb/.parquet/.csv), texto OCR
│   ├── normalizar.py          # plano, a_iso, a_numero, normalizar_valor, es_correcto
│   ├── validadores.py         # RUC módulo 11, DNI, fecha, monto, moneda, correo, teléfono, emisor, TEA<TCEA
│   ├── metricas.py            # precisión, exhaustividad, F1, exactitud por campo/fase/tipo; F1 macro; CER
│   ├── control.py             # cobertura, cuarentena con acción del supervisor, idempotencia
│   ├── evidencia.py           # «aparece» en el texto y la lista «revisar»
│   ├── evaluar.py             # orquesta todo y compara con los umbrales
│   ├── reporte.py             # HTML, Excel y JSON
│   └── __main__.py            # línea de comandos
├── tests/test_calidad.py
└── generar_datos_ejemplo.py
```

## Contrato de entrada

| Entrada (YAML) | Obligatoria | Formato |
|---|---|---|
| `resultados` | Sí | Carpeta con un `.json` por documento, o un `.json`/`.jsonl` con la lista |
| `ground_truth` | Sí | Carpeta con un `.json` por documento, con su nombre sin extensión (`REC-0001.json`). Formato `{campo: valor}` o `{"campos": {...}}` |
| `registro.corrida_1` | Recomendada | Registro del lote: `.duckdb` (tabla `registro`), `.parquet` o `.csv` con `archivo`, `estado`, `motivo` (y si existen `sha256`, `intentos`, `segundos`) |
| `registro.corrida_2` | Para idempotencia | El mismo registro después de repetir la corrida sobre la misma salida |
| `ocr_referencia` | Para el CER | Carpeta con el texto correcto de cada documento leído con OCR (`REC-0001.txt`) |

Cada resultado (solo `archivo` es obligatorio; lo demás activa más chequeos):

```json
{
  "archivo": "REC-0001.eml",
  "tipo": "reclamo",
  "estado": "ok",
  "campos": {"dni": "99123456", "monto_reclamado": 2643.0, "fecha": "2026-09-10", "motivo": "cobro indebido"},
  "fases": {"1_ingesta": {...}, "2_ocr": {...}, "3_pln": {...}, "4_llm": {...}},
  "texto": "texto completo que leyó el pipeline (para verificar la evidencia)",
  "ocr": {"texto": "...", "confianza": 0.91, "puntaje": 0.88, "decision": "aceptar"},
  "revisar": ["ruta del OCR"]
}
```

Si falta una entrada opcional, sus chequeos salen como **«no evaluado»** y el veredicto queda, como mucho,
«con observaciones». Un documento que tiene valores correctos pero no llegó en los resultados, o no terminó
`ok`, se mide con todos sus campos vacíos: no se esconde.

## Umbrales y buenas prácticas

`crítico` bloquea la aprobación; `advertencia` aprueba con observaciones. Todos se ajustan en el YAML.

| Estadístico | Umbral | Severidad | De dónde sale |
|---|---|---|---|
| `cobertura_registro` | ≥ 1,00 | crítico | Curso S06, criterio R3: cada archivo con estado y motivo |
| `cuarentena_con_motivo` | ≥ 1,00 | crítico | Curso S06: nada en cuarentena sin su motivo |
| `tasa_error_lote` | ≤ 0,02 | crítico | Práctica operativa: lo dañado va a cuarentena; un «error» es una falla del pipeline |
| `idempotencia` | sí | crítico | Curso S06: la segunda corrida no reprocesa y las tablas no cambian |
| `f1_por_campo` | ≥ 0,80 | advertencia | Curso S04: umbral de éxito por campo |
| `proporcion_campos_ok` | ≥ 0,88 | crítico | Curso S04, criterio R3: F1 ≥ 0,80 en al menos 8 de 9 campos |
| `f1_campo_critico` | ≥ 0,95 | crítico | Criterio de riesgo: DNI, RUC, monto y fecha identifican a la persona o al importe; un error ahí tiene consecuencia directa |
| `f1_global` | ≥ 0,90 | crítico | Por encima del mínimo por campo, para que el lote completo sea confiable |
| `precision_global` | ≥ 0,95 | crítico | Curso S04/S05: «un dato que no consta no se inventa». En supervisión es peor un valor falso que uno vacío |
| `exactitud_final` | ≥ 0,90 | advertencia | Referencia del curso S05: la cadena completa llegó a 96,5 % |
| `exactitud_sube_por_fase` | sí | advertencia | Curso S05, control C11: la exactitud debe subir en cada fase |
| `f1_macro_clasificacion` | ≥ 0,80 | advertencia | Curso S04: F1 macro del motivo (el caso llegó a 0,917) |
| `cer_medio` | ≤ 0,10 | advertencia | Referencia para texto impreso: CER de 1–2 % es bueno, de 2–10 % es promedio y más de 10 % es pobre (Holley, 2009) |
| `cer_documento` | ≤ 0,20 | advertencia | En textos difíciles, un CER de hasta 20 % puede ser satisfactorio; por encima, el documento va a «revisar» |
| `puntaje_ocr_aceptar` | 0,85 | parámetro | Curso S03: `umbral_score` del YAML |
| `tasa_validadores_ok` | ≥ 0,98 | crítico | Curso S03/S05: un RUC, DNI, fecha o moneda que no pasa su validador es un error seguro |
| `tasa_sin_evidencia` | ≤ 0,02 | advertencia | Curso S05: detector de alucinaciones |
| `similitud_evidencia` | 90 | parámetro | `rapidfuzz.partial_ratio`, como `aparece` en S05 |
| `tasa_revision_humana` | ≤ 0,15 | advertencia | Práctica operativa: si más del 15 % va a revisión, la automatización no ahorra trabajo. En el caso S04 fue 5 de 60 (8 %) |

Las referencias de CER son para texto impreso escaneado. En la sesión 3, la mejor receta de limpieza dejó un CER
medio de 0,147 sobre comprobantes difíciles: con estos umbrales ese lote saldría con observación, y eso es
correcto, porque esos documentos deben pasar por revisión.

## Salidas (`salidas_calidad/`)

- **`reporte_calidad.html`**: veredicto, tabla de estadísticos frente a sus umbrales, métricas por campo,
  por fase y por tipo, lista «revisar», cuarentena, idempotencia, CER, errores y matriz de confusión.
- **`metricas_calidad.xlsx`**: una hoja por tabla (Resumen, Metricas_campo, Por_tipo, Por_fase, Errores,
  OCR_CER, Validadores, Revisar, Cuarentena, Idempotencia, Confusion_*). Sirve para llenar las hojas
  de la plantilla del curso.
- **`veredicto.json`**: el veredicto y cada chequeo, para que otro script lo lea.

## Límites que conviene declarar en la exposición

- **El detector de evidencia tiene dos puntos ciegos** (mismo hallazgo que en S05). No ve un valor equivocado
  que sí figura en el texto. Además, con OCR ruidoso marca como «no figura» valores que sí eran correctos.
  Por eso se revisa una muestra a mano aunque la lista «revisar» salga vacía.
- **La cuadratura de tablas** (S03) no está incluida, porque depende de la estructura de cada tabla.
  Se agrega como un validador más en `validadores.py` si el equipo procesa estados financieros.
- El DNI se valida como 8 cifras. En el corpus del curso empieza con «99»; si hace falta, se ajusta en `validar_dni`.
