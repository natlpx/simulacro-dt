# Escenarios: para qué casos funciona la plantilla y qué cambiar en cada uno

La transcripción del 23/10 y la lámina del reto describen **una** forma probable de los datos. Pueden pasar muchas otras cosas. Esta guía dice, caso por caso, si la plantilla lo resuelve **sola**, con un **cambio en `config.py`**, o con **código** (y dónde).

Leyenda: ✅ sola · ⚙️ cambiar `config.py` · 🛠️ tocar código · ❌ fuera del alcance (qué hacer).

Todo lo marcado con *(probado)* se corrió con datos de prueba: `generar_datos_prueba.py` (5 archivos) y `experimentos/generar_variante.py` (6 archivos con trampas distintas).

---

## 1. Cuántos archivos y en qué formato

| Si les dan… | Qué pasa | Qué hacen ustedes |
|---|---|---|
| 4 CSV | ✅ *(probado)* | nada |
| 3 a 20 archivos (CSV, xlsx, xls, parquet, json) | ✅ *(probado con 5 y 6)*: cada archivo es una tabla; las llaves se descubren midiendo coberturas | revisar `relaciones.csv` |
| **1 solo archivo** con todo ya unido | ✅ la entidad es la llave única de esa tabla; no hay eventos, así que solo entran atributos | si trae columnas por mes, salen tendencias solas (ver §2) |
| Excel con varias hojas **de distinta tabla** | ✅ una tabla por hoja | nada |
| Excel con varias hojas **de la misma tabla** (partido por el límite de 1M de filas) | ✅ *(probado)* se unen solas si tienen las mismas columnas | nada |
| La misma tabla **partida por mes o año** (`facturas_2024.csv`, `facturas_2025.csv`) | ✅ *(probado)* se unen si el nombre solo difiere en dígitos y las columnas son iguales | nada |
| Un `.zip` | ✅ se descomprime en una carpeta hermana | nada |
| CSV con `;`, `\|` o tabulador | ✅ DuckDB detecta el separador | nada |
| CSV en **latin-1** (Excel de Windows) | ✅ *(probado)* se detecta antes de leer | nada. Ojo: sin esta detección la tabla quedaba en **0 filas sin error** |
| Filas rotas (saltos de línea dentro de celdas) | ✅ se cuentan; si se pierde > 1% salta una **ALARMA** | abrir el archivo y revisar |
| Encabezado que no está en la fila 1 (títulos arriba) | 🛠️ | en `ingesta.py`, pasar `header_row=k` a fastexcel o `skip=k` a `read_csv` |
| **Train y test** como dos archivos de la misma tabla | ⚙️ *(probado)* `UNIR_TABLAS = {"empresas": ["train_empresas","test_empresas"]}` y `EVALUAR = dict(tabla="empresas", id=..., archivo="test_empresas.csv")` | — |
| Lista de empresas a puntuar (sin target) | ⚙️ `EVALUAR = dict(tabla=..., id=...)` | — |
| Una base SQL / `.db` / `.sqlite` | 🛠️ DuckDB la lee: `ATTACH 'x.sqlite'` y luego `COPY tabla TO 'x.parquet'` | dejar el parquet en `data/raw` |

## 2. Cómo viene cada tabla

| Si la tabla viene… | Qué pasa | Qué hacen |
|---|---|---|
| Transacciones **una fila por evento** | ✅ cantidad, monto, ventanas de 3/6/12 meses, recencia, tendencia, HHI, contagio | nada |
| Transacciones **ya resumidas por mes** (empresa × mes × monto) | ✅ entra como eventos: `n_total` pasa a significar "meses con movimiento" y las sumas siguen valiendo | leer el diccionario con ese sentido |
| Eventos con **dos fechas** (emisión y pago o vencimiento) | ✅ *(probado)* se calcula el **plazo** promedio y el máximo | nada; es la variable estrella del factoring |
| Sin plazo de factura | 🛠️ aproximarlo con el segmento o rubro del pagador (el Estado y las grandes pagan tarde). Agregar en `features.py` un JOIN del pagador contra el maestro | — |
| Perfil **ancho** por mes (`saldo_202401` … `saldo_202512`) | ✅ *(probado)* por familia: nivel de los últimos 3 meses, tendencia, volatilidad y último mes. **Los meses ≥ corte se excluyen** *(se encontró y corrigió una fuga aquí)* | nada |
| Perfil **largo** (empresa × mes × producto × saldo) | ⚙️ *(probado)* `PIVOTAR = {"tabla": dict(id, fecha, variable, valor)}` | — |
| Columna con nombre ambiguo (`estado_actual`, `flag_factoring_activo`) | ✅ se marca "¿POSTERIOR AL CORTE?"; si predice demasiado, el embudo la manda a REVISAR_FUGA | **preguntar al mentor** si está al corte o es de hoy |
| Misma operación en dos fuentes (interno + SPI) | ⚙️ *(probado)* `DEDUP_EVENTOS = {"tabla": [llaves de la operación]}` | — |
| Códigos de banco o estados (BCP, ANULADA) | ⚙️ `TARGET["filtro"] = "estado <> 'ANULADA' AND banco = 'BCP'"` | verificar los valores reales en el `top5` del perfil |
| Montos en USD y PEN | ✅ si hay columna de moneda; tipo de cambio en `TIPO_CAMBIO` | — |
| Columnas sin significado (`x17`, `var_032`) | ✅ la **forma** se detecta bien; el **papel** (monto, rubro) no | `decisiones_manual.csv` (columna `rol`) |
| Fechas en formato EE. UU. (`03/05/2024` = 5 de marzo) | 🛠️ en `db.py`, macro `_fecha_s`: cambiar `%d/%m/%Y` por `%m/%d/%Y` | verificarlo con el `top5` de una fecha (si aparece un `13/01`, el formato es día/mes) |

## 3. Qué falta o qué no está claro

| Situación | Qué hacer | Dónde |
|---|---|---|
| **El target viene hecho** (columna 0/1) | ⚙️ `TARGET = dict(tabla, id, columna="...")`. **No lo reconstruyan**: verifiquen a qué ventana corresponde y que ninguna variable use esa ventana | config |
| El target hay que construirlo | ⚙️ `TARGET = dict(tabla, id, fecha, filtro)` y **validar la definición con el mentor en la primera hora** | config |
| También piden predecir monto | ⚙️ agregar `monto="columna"` al TARGET | config |
| No viene el flag de **cliente** | ✅ cada tabla unida aporta `<tabla>__presente` (1 si la empresa aparece). Cliente = aparece en perfiles de productos o saldos. **Escribirlo como supuesto en el README del repo** | automático |
| No viene el flag de **lead** | ⚙️ `SEGMENTO = None`. La forma A pasa a ser "clientes Pyme"; decirlo explícitamente | config + preguntar al mentor |
| No se sabe cuál es el corte | El corte es el día de decidir. Regla: el último mes en que **todas** las tablas tienen datos completos, menos el horizonte del target | `FECHA_CORTE` |

## 4. Restricciones del concurso

| Restricción | Cómo la maneja la plantilla |
|---|---|
| Laptop propia de 8 GB | DuckDB con `MEMORY_LIMIT = "5GB"` y disco temporal. Medido: 4.4 M de filas con 1.15 GB de RAM |
| Sin internet o internet lento | `preparar_offline.py` en casa: instala todo y descarga la extensión de Excel. Si falta, usa fastexcel u openpyxl |
| **Solo Copilot en VS Code, sin Colab** | Todo son scripts `.py` (nada de notebooks obligatorios). La carpeta `docs/` explica cada decisión, así que Copilot la lee y responde con el criterio del equipo |
| GitHub con ramas y PR | Cada paso escribe en disco y se retoma con `--desde`. Sugerencia: `config.py` y `decisiones_manual.csv` solo cambian por PR aprobado por el líder; cada rol trabaja en su rama |
| Tiempo (24 h) | `--desde perfil` evita releer el Excel; `run_modelo.py --rapido` itera en segundos; Optuna va al final y con `--optuna <segundos>` |
| Varias definiciones a probar en paralelo | `--config otra_config.py` *(probado)*: dos personas corren dos targets o cortes distintos sin pisarse |
| El repo debe mostrar trazabilidad | `bitacora.jsonl` + `perfil_columnas.csv` + reportes HTML = evidencia de cada decisión para la revisión de código |

## 5. Métrica y capacidad (se conocen el día 13)

| Si la métrica es… | Qué priorizar | Dónde |
|---|---|---|
| **Gini / AUC** | el ordenamiento: `prob` de `predicciones.csv`. Reponderar no ayuda (y aquí lo empeoró) | `run_modelo.py` |
| **R²** del monto | preguntar si es en soles o en log. En soles, tamaño de la empresa; en log, orden de magnitud. Se comparan dos partes vs Tweedie | `segmentos_monto.py` |
| Ambas | valor esperado = prob × monto (ya calculado) | `predicciones.csv` |
| F1, precisión o recall (con umbral) | elegir el umbral en las predicciones OOF que maximiza la métrica oficial; aquí **sí** puede convenir reponderar | agregar en `metricas.py` |
| Error en soles (MAE o RMSE) | predecir el monto directo (Tweedie) | `segmentos_monto.py` |

| Si la capacidad viene como… | Método |
|---|---|
| Un porcentaje o número total | voraz (ordenar y cortar) |
| Cupos por zona | voraz por zona: es óptimo. Se compara con PuLP y salen iguales *(probado)* |
| Zona **y** mínimo de Pyme **y** tope por ejecutivo (restricciones cruzadas) | PuLP: `priorizar.entero(..., restricciones_extra=[("es_pyme", 0.6)])` |
| Canales con costos distintos (llamada, visita, correo) | un modelo de probabilidad por canal (si hay datos por canal) y luego asignar a cada empresa el canal con mayor `prob_canal × monto − costo_canal` (ver `MODELADO.md` §5) |

## 6. Si el problema NO es factoring

Pasos 1 a 4 (ingesta, perfil, limpieza, llaves) y el monitor sirven **para cualquier caso**, porque no dependen del problema. Lo que cambia:

| Tipo de problema | Qué cambia |
|---|---|
| Otro producto (leasing, tarjeta, seguro) | solo `TARGET` y `FECHA_CORTE` |
| Fuga de clientes | TARGET = "dejó de tener movimiento en el horizonte"; las variables de recencia y tendencia ya existen |
| Riesgo o mora | TARGET = "más de 30 días de atraso en el horizonte"; cuidado con fugas (pagos posteriores) |
| **Pronóstico** (caso 2024: efectivo por agencia y día) | 🛠️ la fila deja de ser la empresa y pasa a ser agencia × fecha. Se reutilizan la ingesta, la limpieza y el monitor; las variables pasan a ser rezagos (t−1, t−7, t−28), día de la semana y feriados, y la validación es por bloques de tiempo. `run_modelo.py` sirve con `monto` como objetivo y validación temporal |
| Canal óptimo (caso 2025) | una tabla de contactos (cliente × canal × resultado): un modelo por canal o un modelo con el canal como variable; ver `MODELADO.md` §5 |
