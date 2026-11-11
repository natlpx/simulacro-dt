# Cambios de la revisión (10/11): 5 huecos + XGBoost y CatBoost

Probado de punta a punta con los datos de prueba (20k empresas) y con 100k empresas / 2M facturas.

| # | Hueco | Archivo(s) | Qué cambió | Efecto medido |
|---|---|---|---|---|
| 1 | Fuga en tablas "foto" (sin fecha) | `pipeline/seleccion.py` | Con `tabla_modelo_t1` presente, una variable es REVISAR_FUGA si es demasiado buena en el corte anterior **o** en el actual (`gini_actual`, `iv_actual`) | `ops_ultimo_semestre` (Gini 0.16 en train, 0.91 en el actual) ahora se detecta aunque la selección se haga con train |
| 2 | La selección miraba el target del examen | `pipeline/seleccion.py`, `run_pipeline.py` | Al correr `--sufijo _t1`, la selección se rehace con el corte anterior como train | El examen fuera de tiempo vuelve a ser ciego |
| 4 | PSI entre dos mitades del mismo periodo | `pipeline/seleccion.py` | En modo fuera de tiempo, la columna `psi` es el PSI **entre cortes**. F2 saca las que cambiaron | 11 variables acumuladas fuera. Examen: Gini 0.329 → **0.348**, lift 2.0x → **2.2x** |
| 3 | Se explicaba LightGBM aunque se entregara la logística | `candidatos.explicar_logistica`, `run_modelo.py`, `reporte_modelo.py` | Si gana la logística: `coeficientes_logistica.csv` (coef. estandarizado + odds ratio) y el caso top se explica con la logística (aporte = coef × (valor − promedio), SHAP exacto de un modelo lineal) | El reporte dice qué modelo explica cada gráfico |
| 5 | Segmentos: solo se probaba LightGBM y el ganador no se usaba | `segmentos_monto.py`, `run_modelo.py` | Se compara la familia del elegido (logística o árboles) y la otra queda de referencia; si gana `separado`, la predicción final de ese segmento usa su propio modelo | Escenario A: logística global 0.15 → por segmento 0.62–0.64 |
| + | XGBoost y CatBoost | `candidatos.py`, `run_modelo.py`, `requirements.txt`, `preparar_offline.py` | Nuevos candidatos con la misma receta y los mismos pliegues; entran si están instalados y no se usa `--rapido` | 100k empresas: modelado 113 s → 191 s (2 núcleos) |

## Cómo leer las salidas nuevas

- `salidas/seleccion_variables.csv`: en modo fuera de tiempo, `gini` = en el corte anterior, `gini_actual` = en el corte actual. Si `gini_actual` es mucho mayor que `gini`, la variable sabe el futuro en el corte actual.
- `salidas/modelo/coeficientes_logistica.csv`: `odds_ratio` 1.5 = multiplica las chances por 1.5 cuando la variable sube 1 desviación estándar.
- `segmentos.csv`: `familia`, `gini_global_<familia>`, `gini_separado_<familia>`, `gana`.

## Cuidados

- Corran primero `run_pipeline.py` y después `--sufijo _t1`: es la segunda corrida la que deja la selección honesta.
- Coeficientes de la logística: una misma categoría aparece como `__te` (tasa) y como `==VALOR` (one-hot), así que se reparten el efecto. Para explicar un rubro, miren la suma.
- CatBoost es el más lento. Con datos muy grandes, iteren con `--rapido` (sin XGBoost ni CatBoost) y corran el torneo completo una vez.

## Portabilidad Windows / macOS / Linux (11/11)

| Problema | Archivo(s) | Arreglo | Verificado |
|---|---|---|---|
| En Windows, el primer `⚠` detenía el pipeline (`UnicodeEncodeError: 'charmap'`) si la salida iba a un archivo o a una consola antigua | `pipeline/plataforma.py`, `config.py` | Consola en UTF-8 al cargar la config | Simulado con `PYTHONIOENCODING=cp1252`: antes `rc=1`, ahora corre completo |
| `MEMORY_LIMIT="5GB"` y `THREADS=4` fijos: se quedan cortos en una Mac de 24 GB y ajustados en una laptop de 8 GB | `config.py`, `run_pipeline.py`, `pipeline/ingesta.py` | 60 % de la RAM y núcleos − 1, detectados en cada sistema sin librerías extra | Se imprimen al inicio de cada script |
| `Path.rename` falla en Windows si el destino existe | `pipeline/ingesta.py` | `plataforma.reemplazar` (`Path.replace`) | — |
| Finales de línea distintos (CRLF/LF) generan diffs falsos entre Windows y Mac | `.gitattributes` | `text=auto eol=lf` | — |
| La instalación no detectaba problemas por sistema | `preparar_offline.py` | Revisa la versión de Python y OneDrive/iCloud, instala desde `requirements.txt`, prueba cada librería y da el arreglo para cada sistema; imprime un resumen OK/FALTA | Corrido con Python 3.10 en una ruta con espacios, tildes y ñ |
| No había instrucciones por sistema | `docs/GUIA_EJECUCION.md`, `README.md` | Guía paso a paso con comandos para Windows, macOS y Linux | — |

## Preparación para el repo del evento (11/11, según el PDF de participación)

| Requisito del PDF | Archivo | Qué hace |
|---|---|---|
| Base de conocimiento sin datos, ≤ 20 MB, con INVENTARIO.md | `evento/copiar_a_base.py` | Copia solo archivos versionados (sin historial ni datos), verifica tamaño, genera el inventario declarando la asistencia de IA |
| La base se cierra a las 14:00 y no se edita después | `evento/config_evento.py` | Se copia a `trabajo/`; corre la plantilla desde la base, apaga los valores de ejemplo, manda salidas fuera del repo |
| No subir .csv al repo | `pipeline/perfil.py`, `config_evento.py` | `DECISIONES_MANUAL` dentro de la config reemplaza `decisiones_manual.csv` |
| `entregas/submission.csv` + `python -m datafest.validar` | `evento/exportar_submission.py` | Convierte `predicciones.csv` al formato (ajustable) y revisa duplicados y nulos |
| `presentacion/index.html` para negocio y técnicos | `evento/presentacion_index.html` | Estructura de 9 diapositivas, sin librerías externas; tecla `t` oculta el anexo técnico |
| `docs/BITACORA_FUENTES.md` y `docs/USO_DE_IA.md` | `evento/BITACORA_FUENTES_inicial.md`, `evento/USO_DE_IA_ejemplo.md` | Filas iniciales y formato |
| Calendario y reglas | `docs/PASOS_EVENTO.md` | Checklist del jueves al sábado |

Probado simulando el repo del evento: base de 47 archivos (0.29 MB, sin datos); pipeline, corte anterior, modelo y
submission corridos desde la raíz con `--config trabajo/config_evento.py`; `git status` solo muestra `trabajo/` y
`entregas/submission.csv`.

## Reproducibilidad: mismos datos = mismo resultado (11/11)

**Problema (ya existía en la versión original):** dos corridas seguidas, con la misma versión y los mismos datos,
cambiaban la decisión de 4 variables en la selección (`saldo_ultimo`, `saldo_vol`, `var_buro_04`, `var_buro_11`)
y el Gini de LightGBM en ±0.0025. En la evaluación técnica, "lo corrí de nuevo y salió otro número" es difícil de defender.

**Causas medidas y arreglos:**

| Causa | Arreglo | Archivo |
|---|---|---|
| DuckDB devuelve las filas en otro orden en cada corrida, y el split 70/30 y los pliegues se arman por posición | La tabla se guarda y se lee ordenada por `id` (`leer_ordenado`) | `pipeline/features.py`, `pipeline/seleccion.py`, `pipeline/modelado/datos.py` |
| Las sumas en paralelo cambian el último decimal (~1e-15) y LightGBM corta distinto | Variables decimales a `round(round(x, 9), 6)` al guardar la tabla | `pipeline/features.py` |
| Paralelismo interno de LightGBM | `deterministic=True, force_col_wise=True` | `pipeline/modelado/candidatos.py` |

**Verificado:** dos corridas completas con 4 hilos dan resultados idénticos en `tabla_modelo`, `tabla_modelo_t1`,
`seleccion_variables`, la comparación de los 9 modelos, las predicciones, la importancia, los coeficientes y los segmentos.
El resultado no cambia en lo sustancial: logística Gini OOF 0.3222, examen 0.3476.
