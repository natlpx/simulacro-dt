# Plantilla DataFest · Pipeline de datos crudos → tabla de modelo

**Para:** 4 archivos (Excel o CSV) que suman hasta 8 GB, con columnas inútiles y nombres que no conocemos de antemano. Está pensado para un caso de **factoring por rubros**, pero sirve igual para riesgo, fuga de clientes o venta cruzada, porque detecta la **forma** y el **papel** de cada columna, no su nombre exacto.

```
USB (xlsx/csv) ─► bronze (parquet, todo texto) ─► PERFIL (ficha por columna + decisión)
      │                                                   │  ◄── decisiones_manual.csv (humano)
      ▼                                                   ▼
  bitácora ◄──────── silver (tipado y limpio) ─► LLAVES (grano + cómo se unen)
      │                                                   ▼
      │                              VARIABLES (RFM, ventanas, red; todo < corte)
      │                                                   ▼
      └──────────► MONITOR.html ◄────────── EMBUDO (PSI, Gini, Spearman, IV, fugas)
```

## Mapa de la repo

```
config.py                     ← lo ÚNICO que se edita el día del concurso (corte, target, segmento, capacidad)
decisiones_manual.csv         ← correcciones humanas al perfil automático
run_pipeline.py               ← datos crudos → tabla_modelo.parquet + monitor.html
run_modelo.py                 ← tabla_modelo → diagnóstico, modelos, importancia, monto, priorización
pipeline/                     ← ingesta, perfil, limpieza, llaves, features, selección, monitor
pipeline/modelado/            ← datos, diagnóstico, candidatos, afinamiento, importancia, segmentos_monto, priorizar
docs/ESCENARIOS.md            ← qué pasa si los datos vienen distinto (archivos, formas, faltantes, restricciones)
docs/MODELADO.md              ← qué modelo según la data, desbalance, hiperparámetros, importancia, "varios modelos"
experimentos/                 ← pruebas de escenarios (USB distinto, segmentos opuestos, desbalance severo)
```

## Cómo se usa

> **Windows, macOS o Linux:** la instalación y los comandos de cada sistema (entorno virtual, `py` vs `python3`,
> `brew install libomp`, OneDrive/iCloud, problemas frecuentes) están en **[docs/GUIA_EJECUCION.md](docs/GUIA_EJECUCION.md)**.
> La RAM y los núcleos se detectan solos en cada laptop.
>
> **Repo del evento (Datafest-BCP):** cómo pasar esta plantilla a `base_conocimiento/`, correrla sin editarla
> y generar `entregas/submission.csv` y `presentacion/index.html` → **[docs/PASOS_EVENTO.md](docs/PASOS_EVENTO.md)** y carpeta `evento/`.

```bash
python preparar_offline.py                        # EN CASA, con internet, en las 5 laptops
# el día del concurso:
#   1) copiar los archivos a data/raw  (o usar --raw /ruta/al/usb)
#   2) editar config.py: FECHA_CORTE, HORIZONTE_MESES, TARGET  (sale del enunciado)
python run_pipeline.py
#   3) abrir salidas/monitor.html  y  salidas/perfil_columnas.csv
#   4) corregir lo que haga falta en decisiones_manual.csv
python run_pipeline.py --desde perfil             # re-corre sin volver a leer el Excel
#   5) (recomendado) tabla de un corte anterior para validar fuera de tiempo
python run_pipeline.py --desde features --corte 2025-01-01 --sufijo _t1
#   6) modelado completo (ver docs/MODELADO.md)
python run_modelo.py                 # + --optuna 300 al final si sobra tiempo
#   abrir salidas/modelo/reporte_modelo.html ; la entrega es salidas/modelo/predicciones.csv
```

`--config otra_config.py` en ambos scripts permite probar otra definición (otro target, otro corte) sin tocar `config.py`.

| Salida (`salidas/`) | Qué es | Quién la mira |
|---|---|---|
| `monitor.html` | todo en gráficos, funciona sin internet | todos |
| `perfil_columnas.csv` | 1 fila por columna: forma, papel, decisión y **motivo** | Data Engineer + Negocio |
| `limpieza_detalle.csv` | cuántos valores se anularon al convertir cada columna | Data Engineer |
| `granos.csv`, `relaciones.csv` | qué identifica cada fila y cómo se unen las tablas | Data Engineer + Analytics |
| `tabla_modelo.parquet` | 1 fila por entidad, variables + target | Data Scientist |
| `diccionario_variables.csv` | cada variable con su **frase de negocio** | Presentador |
| `seleccion_variables.csv` | embudo: queda / fuera / revisar fuga, con motivo | Data Scientist |
| `bitacora.jsonl` | filas, columnas, segundos y suma de montos por paso | todos (conciliación) |

## Por qué cada herramienta

| Herramienta | Problema que resuelve | Por qué no la alternativa |
|---|---|---|
| **DuckDB** | SQL sobre archivos más grandes que la RAM; usa disco si falta memoria | pandas carga todo en RAM (pico de 3-4 veces el tamaño) → `MemoryError` con 8 GB |
| **Parquet** | columnar + comprimido + con tipos: 334 MB de CSV → 63 MB; lee solo las columnas que pides | CSV/Excel se re-parsean enteros en cada lectura |
| **Polars lazy** (plan B) | dataframes con plan optimizado: solo lee columnas y filas necesarias | se deja como alternativa probada (`features_polars.py` da **idéntico** resultado que DuckDB) |
| **fastexcel/calamine** | lee xlsx unas 10 veces más rápido que openpyxl | openpyxl solo queda como último recurso (lento, pero con memoria constante) |
| **pandas** | solo al final, con la tabla chica del modelo (miles de filas) | — |
| **Plotly → HTML** | gráficos interactivos en un archivo que se abre sin internet | — |

Regla del equipo: **una herramienta por paso**. Nadie mezcla pandas en el medio de un paso de DuckDB.

## ¿Cuándo una columna es importante y cuándo se elimina?

Hay dos preguntas distintas y el pipeline las separa:

**1. ¿Tiene forma de información? → se mide automáticamente (`perfil.py`)**

| Forma detectada | Regla | Decisión | Por qué |
|---|---|---|---|
| vacía | > 98% nulos (incluye 'S/D', '-', '#N/A', '') | **DROP** | no hay nada que aprender |
| constante | un valor ocupa > 99.5% | **DROP** | no distingue a nadie |
| presencia | 1 solo valor + muchos vacíos | **indicador `tiene_x`** | lo que informa es si HAY dato (ej. fecha de cancelación) |
| duplicada | hash idéntico a otra columna | **DROP** | ruido redundante |
| texto libre | largo > 40 y > 50 valores distintos | **DROP** | no es modelable sin NLP |
| identificador | nombre de llave, o ≥ 90% distintos con largo fijo | **LLAVE** | sirve para unir, nunca como variable |
| fecha | ≥ 95% parsea como fecha | **FECHA** → "días desde" | el modelo no entiende fechas, sí distancias |
| número | ≥ 95% parsea como número | **NUMERO** | — |
| categoría | ≤ 50 valores / > 50 valores | **CATEGORIA** | baja: one-hot o nativa; alta: frecuencia/target encoding |
| casi nula | 70-98% nulos | valor + **`tiene_x`** | la ausencia también informa |

**2. ¿Sirve para predecir y es legal usarla? → se mide con el objetivo (`seleccion.py`)**

| Filtro | Regla | Por qué |
|---|---|---|
| F1 copias | mismos valores que otra | redundante |
| F2 estabilidad | PSI > 0.25 entre train y validación | el mundo cambió: lo aprendido no aplica |
| F3 **fuga** | Gini individual > 0.5 o IV > 0.5 | demasiado buena = casi siempre es información posterior. **No se borra sola: va a revisión humana** |
| F4 sin señal | Gini < 0.02 | no separa |
| F5 redundancia | Spearman > 0.9 con otra de mayor Gini | dos que dicen lo mismo |

La prueba final, que ningún código reemplaza: **¿este dato existía el día de decidir?** El perfil marca nombres sospechosos (`cancel`, `resultado`, `final`, `cierre`, `castigo`, `desembolso`…) con "¿POSTERIOR AL CORTE?".

## Funciones de limpieza (macros SQL en `pipeline/db.py`)

| Función | Arregla | Ejemplo |
|---|---|---|
| `txt(x)` | espacios, tildes, mayúsculas, centinelas → NULL | `' Comércio '` → `COMERCIO`; `'S/D'` → NULL |
| `idn(x)` | llaves que no calzan en los JOIN | `'20123456789.0'` → `20123456789` |
| `num(x)` | números escritos como texto | `'S/ 1,234.50'`→1234.5 · `'1.234,50'`→1234.5 · `'(500)'`→-500 · `'12%'`→12 |
| `fecha(x, serial)` | 11 formatos, `AAAAMM`, serial de Excel, 1900-01-01 → NULL | `'05/03/2024'`, `'20240305'`, `45356` → 2024-03-05 |
| centinelas numéricos | -1, 9999, 999999… → NULL **solo** si pesan ≥ 0.5% y son el mínimo/máximo o la columna es continua | así no se borra un -1 legítimo |

Regla de oro: **la limpieza no aprende de los datos** (solo transforma fila por fila). Todo lo que aprende (percentiles, medianas, categorías raras, tasas) está en `regularizar.py` y se ajusta **solo con train**.

## Regularización (`pipeline/regularizar.py`)

```python
from pipeline.regularizar import Regularizador
R = Regularizador(modo="arbol")          # LightGBM: mira el ORDEN -> no escala, deja nulos
# R = Regularizador(modo="lineal")       # logística: mira la DISTANCIA -> recorta p1/p99, log, mediana+indicador, estandariza, one-hot
X_train = R.fit_transform(train[vars], train.target)   # target encoding FUERA DE MUESTRA (5 folds)
X_valid = R.transform(valid[vars])                     # aplica lo aprendido sin volver a mirar
R.guardar("salidas/regularizador.json")
```

## Variables que se construyen solas (todas con fecha < corte)

`n` y `monto` total/promedio/máximo/desviación · ventanas de 3, 6 y 12 meses · **tendencia** (3m contra el promedio trimestral) · recencia, antigüedad y meses activos · diversificación por rubro · **HHI de contrapartes** (concentración en pocos pagadores) · **contagio de red** (% de vecinos que ya hicieron factoring antes del corte) · conversión USD→PEN si hay columna de moneda. Cada variable sale con su frase en `diccionario_variables.csv`.

## Lo que la autodetección NO hace (y hay que revisar a mano)

1. **El papel de una columna se adivina por el nombre.** Si la columna se llama `x17`, el pipeline sabe que es un número, pero no sabe que es un monto. Corríjanlo en `decisiones_manual.csv` (columnas `decision` y `rol`).
2. **El objetivo (`TARGET`) siempre lo define el enunciado**, nunca la autodetección.
3. **Una fecha como `05/03/2024` se lee como 5 de marzo** (formato peruano). Si el caso viene en formato de EE. UU., hay que cambiarlo en `db.py`.
4. **`QUITAR_DUPLICADOS_EXACTOS=True` elimina filas idénticas.** Si una tabla no tiene identificador por fila, dos facturas legítimas iguales se fusionarían. Revisen `duplicados_quitados` en la bitácora.
5. **La entidad y las tablas de eventos se detectan solas.** Si `relaciones.csv` muestra otra cosa, fíjenlas en `config.ENTIDAD` / `config.EVENTOS`.

## Rendimiento medido

Medido en una máquina de 2 núcleos con 8 GB: **4.4 M filas (384 MB crudos) → 134 s, pico de RAM 1.15 GB**. El perfil usa una muestra de 1 M de filas por tabla (su costo no crece con el tamaño). La ingesta y la limpieza crecen de forma lineal. Para 8 GB de **CSV** esperen unos 25 minutos con 2 núcleos o 10-15 con 4-8. En **xlsx** tarda más: leer el Excel es el paso lento. Por eso se convierte a Parquet **una sola vez** y luego se usa `--desde perfil`.

## Reparto del equipo sobre este pipeline

| Rol | Durante el pipeline | Entrega |
|---|---|---|
| **Data Engineer** | corre la ingesta, vigila la bitácora y la conciliación, corrige formatos | tablas silver correctas |
| **Analytics (red)** | valida `relaciones.csv`, la entidad y las contrapartes; ajusta el contagio | grafo pagador-proveedor |
| **Data Scientist** | revisa el embudo, las fugas y la regularización; entrena el modelo | modelo + Gini |
| **Negocio/BI** | revisa `perfil_columnas.csv` (¿qué significa cada columna?) y las gráficas de rubros | historia de negocio |
| **Líder/Presentador** | decide el TARGET y el corte con el enunciado; usa `diccionario_variables.csv` | presentación |

## Trabajo en equipo con GitHub

### Preparar el entorno

Cada integrante debe aceptar la invitación al repositorio y clonar el proyecto. Se recomienda trabajar en un entorno virtual e instalar las dependencias según las instrucciones del equipo. No compartan credenciales ni suban datos confidenciales del BCP o del concurso.

```bash
git clone https://github.com/Lizzz7/plantilla_2026.git
cd plantilla_2026
git switch -c tipo/descripcion-corta
```

Usen ramas descriptivas, por ejemplo `feat/validacion-datos`, `fix/fechas-ingesta` o `docs/instrucciones`. Eviten trabajar directamente en `main`.

### Flujo de tareas

1. Abran un **Issue por tarea**, indicando responsable, contexto y qué significa que esté terminada.
2. Muevan las tareas por el tablero: **Pendiente → En curso → En revisión → Terminado**.
3. Cada integrante trabaja en su rama y hace commits pequeños con mensajes claros.
4. Al terminar, abre un **pull request** hacia `main`, enlaza el Issue y explica qué cambió y cómo lo probó.
5. Otra persona revisa el cambio; resuelvan comentarios y comprueben que no haya datos, secretos o archivos generados antes de incorporarlo.
6. Mantengan `main` integrado y ejecutable; comuniquen conflictos pronto y coordinen antes de modificar los mismos módulos.

### Reparto sugerido

Adapten estos frentes al tamaño del equipo; una persona puede cubrir más de uno:

| Frente | Archivos / foco | Resultado esperado |
|---|---|---|
| Datos e ingesta | `pipeline/ingesta.py`, `limpieza.py`, `llaves.py` | datos cargados, conciliados y con calidad documentada |
| Variables | `pipeline/features.py`, `seleccion.py` | variables útiles, interpretables y sin fuga de información |
| Modelado | `pipeline/modelado/`, `run_modelo.py` | modelos evaluados con validación y métricas reproducibles |
| Negocio y entrega | `README.md`, `docs/`, presentación | problema, hallazgos, impacto, limitaciones y demo claros |
| Coordinación e integración | Issues, pull requests y pruebas de punta a punta | cambios revisados y proyecto integrado para la entrega |

### Reproducibilidad y entrega

- Registren para cada experimento la configuración, el corte temporal, las métricas y la versión del código; usen semillas cuando corresponda.
- Documenten aquí los pasos para instalar y ejecutar el proyecto desde un entorno limpio cuando el equipo los haya verificado.
- Antes de entregar, ejecuten el flujo completo, revisen las salidas y preparen una demo que explique **problema → solución → resultados → valor para el negocio → limitaciones**.
- Confirmen las bases del DataFest: fechas, formato de entrega, métrica de evaluación y reglas sobre uso y publicación de datos. No publiquen datos del concurso sin autorización.
