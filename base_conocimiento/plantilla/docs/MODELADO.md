# Modelado: qué usar según los datos, y cómo justificarlo

```bash
python run_modelo.py                  # diagnóstico + 7 candidatos + segmentos + importancia + monto + priorización
python run_modelo.py --optuna 300     # además busca hiperparámetros durante 5 minutos
python run_modelo.py --rapido         # sin permutación ni segmentos, para iterar
python experimentos/escenarios_modelado.py   # los 4 experimentos de abajo
```

Salidas: `salidas/modelo/reporte_modelo.html` (todo visual), `comparacion_modelos.csv`, `importancia_variables.csv`, `segmentos.csv`, `predicciones.csv` (la entrega) y `resumen.json`.

**Idea central:** no se elige el modelo por costumbre ni porque otro equipo usó tal cosa. El diagnóstico **mide** la data y propone hipótesis. Después todos los candidatos se comparan con **la misma validación**, y gana el que mide más. Si uno más simple queda a menos de 0.005 de Gini del mejor, gana el simple (parsimonia: se explica mejor, se rompe menos y el jurado lo entiende).

---

## 1. ¿Con modelo o sin modelo?

Siempre se empieza **sin modelo**, porque es la línea base que hay que superar:

| Candidato | Qué es | Cuándo gana |
|---|---|---|
| `regla_1var` | ordenar por la variable con más Gini | señal concentrada en una sola variable; también sirve como "lo que haría un ejecutivo hoy" |
| `regla_top3` | promedio de los rankings de las 3 mejores (un scorecard manual) | pocas filas, se necesita algo explicable en 1 minuto |
| `logistica` | lineal y regularizada; explicable con coeficientes | **pocos datos o señal lineal** (experimento D) |
| `lgbm` | árboles con boosting: no linealidades, interacciones, nulos y categorías | **más de 5k filas con interacciones** (experimento A) |
| `ensamble` | promedio de rankings de logística + lgbm | cuando los dos se equivocan en cosas distintas |

Frase para el jurado: *"Una regla simple da Gini X; el modelo da Y; o sea, encuentra Z% más conversiones en el mismo número de llamadas."*

**Resultado con los datos de prueba** (fuera de tiempo, 20k empresas):

| | regla 1 var | regla top 3 | logística | lgbm | lgbm + Optuna | ensamble |
|---|---|---|---|---|---|---|
| Gini OOF | 0.263 | 0.292 | **0.319** | 0.305 | 0.318 | 0.319 |

*(Los decimales cambian levemente entre corridas, porque al agregar variables o volver a correr Optuna se mueve la tercera cifra; en la última corrida la logística dio 0.322. El orden de los modelos se mantuvo.)* Ganó la **logística**: la señal sintética es casi lineal. En el examen fuera de tiempo dio Gini 0.321 y priorizar al top convierte **47.6% contra 19.6%** de la base (2.4x).

## 2. Datos desbalanceados

| Tasa de positivos | Qué hacer | Por qué |
|---|---|---|
| > 10% (leve) | nada especial; validación estratificada | — |
| 1-10% (moderado) | estratificar; reportar AUC-PR además del Gini | en cada pliegue de validación debe haber positivos |
| < 1% (severo) | AUC-PR y captura@k **obligatorios**; probar pesos | el Gini puede verse alto aunque el top tenga pocos aciertos |

**Medido, no supuesto** (`experimentos/escenarios_modelado.py`):

| Escenario | lgbm sin tratar | lgbm con pesos | Prob. media con pesos (real) |
|---|---|---|---|
| Datos de prueba (19%) | 0.305 | **0.205** | 0.212 (0.189) |
| A (18%) | 0.657 | **0.461** | 0.275 (0.180) |
| C, severo (0.4%) | 0.705 | **0.620** | 0.007 (0.004) |

Conclusiones que pueden defender:

- **Reponderar no mejoró el Gini en ningún caso, y lo empeoró en todos.** La teoría dice que no cambia el orden; en la práctica el árbol se concentra en los positivos y el early stopping se desajusta. Por eso se mide.
- **Reponderar infla la probabilidad.** Si después se multiplica probabilidad × monto, se infla el valor esperado. El submuestreo con **corrección de prior** devuelve la probabilidad a su escala real (0.185 contra 0.189).
- **Con 0.4% de positivos:** Gini 0.70 pero AUC-PR 0.066. El Gini "se ve bien", pero en el top de la lista hay pocos aciertos. Por eso con desbalance severo se reporta captura@k: *"el 10% de arriba contiene el X% de los que convierten"*.
- **¿Cuándo sí reponderar?** Cuando la métrica oficial usa un **umbral** (F1, recall) y no el ordenamiento.

## 3. Hiperparámetros: cuáles importan y cómo saberlo

Un hiperparámetro es una perilla que no se aprende de los datos. En LightGBM, en orden aproximado de impacto:

- `learning_rate` + `n_estimators`: se fijan juntos; el early stopping elige cuántos árboles.
- `num_leaves`: complejidad de cada árbol.
- `min_child_samples`: el freno principal cuando hay pocos positivos.
- `subsample` y `colsample_bytree`: aleatoriedad que reduce la varianza.
- `reg_lambda` y `reg_alpha`: penalizaciones.

**Cómo se buscan:** Optuna (TPE, búsqueda bayesiana) aprende de cada prueba dónde buscar la siguiente. Le gana a grid search (gasta pruebas en zonas malas) y a random search (no aprende). La prueba 0 es siempre el default, así se ve cuánto se ganó.

**Cómo saber cuál importa:** `optuna.importance` (fANOVA) mide qué parte de la variación del Gini entre pruebas explica cada perilla. Medido aquí:

| Corrida | Default → mejor | Perilla #1 | Perilla #2 |
|---|---|---|---|
| 1 (36 pruebas) | 0.309 → 0.324 | `num_leaves` 36% | `min_child_samples` 20% |
| 2 (28 pruebas) | 0.305 → 0.325 | `subsample` 26% | `colsample_bytree` 25% |

Lecciones:

1. **Con 30 pruebas el ranking de perillas no es estable.** Para afirmar "esta perilla importa" hacen falta unas 100 pruebas o repetir la corrida.
2. **Afinar ganó +0.015 en el Optuna (3 pliegues), pero en la validación de 5 pliegues `lgbm_afinado` (0.318) no le ganó a la logística sin afinar (0.319).** Las variables y el tipo de modelo mueven más que las perillas. Optuna va **al final**, con tiempo límite.

## 4. ¿Qué variables importan más? (tres medidas, tres preguntas)

| Medida | Responde | Cuidado |
|---|---|---|
| **gain** | ¿cuánto la usó el modelo al entrenar? | premia variables con muchos valores distintos aunque no generalicen |
| **permutación** | si la desordeno en **validación**, ¿cuánto cae el Gini? | la más honesta. Dos variables correlacionadas se reparten el crédito |
| **SHAP** | ¿cuánto aporta a cada predicción y en qué dirección? | sirve para explicar **un caso** al jurado; LightGBM lo calcula nativo (`pred_contrib`) |
| **estabilidad** | ranking mínimo y máximo de gain entre pliegues | una variable que es #1 en un pliegue y #40 en otro es frágil |

Lectura del resultado real:

| Variable | gain | permutación | SHAP | Lectura |
|---|---|---|---|---|
| `ventas_anuales` | 0.23 | **0.073** | 0.22 | importante de verdad (ranking 1 en todos los pliegues) |
| `rubro_economico` | 0.13 | 0.032 | 0.18 | importante; diferencia por rubro (hallazgo de negocio) |
| `monto_financiado_total` | 0.18 | 0.009 | 0.09 | gain alto pero permutación baja: el modelo la usa, aunque `n_total` dice casi lo mismo |
| `var_buro_35` | 0.014 | −0.0002 | 0.014 | se puede quitar |

**Alarma de fuga:** una variable con permutación muy alta y una frase de negocio rara.

## 5. ¿Uno o varios modelos? (lo de "los 6 modelos")

Un equipo termina con varios modelos por la **descomposición de la decisión**, no por apilar algoritmos. Cada modelo responde una pregunta distinta:

- **Caso 2025 (canal óptimo):** P(acepta | llamada), P(acepta | SMS), P(acepta | correo), P(acepta | app), un modelo de monto y uno de momento. Eso da unos 6, porque la decisión era **qué canal** y había resultados **por canal**.
- **Factoring:** P(convierte | con lead), P(convierte | sin lead) para habilitar, y E[monto | convierte]. Son 2 a 4, **solo si los datos lo justifican**.

La data "se presta" para varios modelos cuando se cumplen tres cosas:

1. La decisión necesita **varias cantidades** (probabilidad **y** monto, o una probabilidad por canal).
2. Hay **subpoblaciones que se comportan distinto**: no solo con otra tasa, sino con **relaciones invertidas** (una variable que sube la probabilidad en un grupo y la baja en otro).
3. **Cada grupo tiene datos suficientes** (más o menos 200 positivos o más).

**Experimentos** (`experimentos/escenarios_modelado.py`, datos controlados):

| Escenario | El diagnóstico detecta | lgbm global vs lgbm por segmento | Logística global vs logística por segmento | Decisión |
|---|---|---|---|---|
| **A**: x1 sube en un segmento y baja en el otro | ✅ "x1 cambia de SIGNO" | 0.652/0.662 vs 0.645/0.658: **global** | **0.152 vs 0.634** | árboles global, **o** una logística por segmento |
| **B**: igual, pero un segmento tiene 3% de los datos | ✅ | global | 0.596 vs 0.636 | global con árboles |
| **C**: desbalance severo, sin segmentos reales | sin falsa alarma ✅ | — | — | 1 modelo |
| **D**: señal lineal, 1,500 filas | sin falsa alarma ✅ | — | — | 1 logística |

La lección más valiosa: **LightGBM global aprende la interacción solo** (mete el segmento en sus árboles), así que separar no le gana. Separar le sirve a la **logística**, que no puede representar un efecto que cambia de signo (pasó de 0.15 a 0.63). Por eso "cuántos modelos" depende del **tipo** de modelo y no solo de los datos.

*(El detector usa un umbral de significancia: el efecto en cada segmento debe superar 2.5 veces su error estándar. Sin ese umbral, C y D daban falsas alarmas por ruido; se encontró y corrigió en las pruebas.)*

Con los datos de prueba de factoring, el resultado fue **un solo modelo global**: los segmentos con y sin lead se comportan parecido, y el modelo separado perdió en los dos (0.313 vs 0.312; 0.355 vs 0.286).

## 6. El monto

| Opción | Qué es | Cuándo |
|---|---|---|
| **Dos partes** | P(convierte) × E[monto \| convierte]; la parte 2 en log con corrección de Duan (×1.33 aquí) | muchos ceros + cola larga; además explica las dos cosas por separado |
| **Tweedie directo** | una sola regresión que tolera muchos ceros | cuando la métrica es error en soles sobre todos |

Medido: R² en soles **0.147 (dos partes) vs 0.149 (Tweedie)**, Spearman 0.238 vs 0.236, R² condicional en log 0.47. El diagnóstico recomendó dos partes y **la medición dijo empate**. Las recomendaciones son hipótesis. Para la presentación conviene dos partes, porque separa *"¿convierte?"* de *"¿cuánto?"*.

## 7. Validación: la decisión que más pesa

| Situación | Validación | Por qué |
|---|---|---|
| Hay un corte anterior posible (`tabla_modelo_t1`) | **fuera de tiempo**: entrenar con el corte viejo y examinar con el actual | es lo que hará el banco con su set ciego |
| El banco da una lista de evaluación | entrenar con el resto y examinar con la lista | lo mismo que el banco |
| Solo una tabla | 5 pliegues estratificados (OOF) | — |
| **Nunca** | validación aleatoria cuando la evaluación es un periodo posterior | da un Gini optimista que se cae en el filtro |

```bash
python run_pipeline.py --desde features --corte 2025-01-01 --sufijo _t1   # tabla del corte anterior
python run_modelo.py                                                        # la detecta y valida fuera de tiempo
```

Señal de alerta: si el Gini OOF en train está muy por encima del examen fuera de tiempo, hay sobreajuste o fuga. Aquí: OOF 0.319 vs examen 0.321, sano. El diagnóstico también avisa variables con PSI > 0.25 entre cortes. Aquí salieron 6: conteos acumulados (`n_total`, `antiguedad`) que crecen solo porque el corte posterior tiene más historia. Es un sesgo real a mencionar.

## 8. Árbol de decisión rápido (para el día 13)

```
¿El target es 0/1?
├─ sí → ¿tasa < 1%?  sí → reportar AUC-PR + captura@k, probar pesos
│       ¿filas < 3k o EPV < 10?  sí → logística / regla primero
│       ¿hay segmentos con efectos invertidos?  sí → árboles global vs logística por segmento
│       └─ comparar: regla → logística → lgbm → ensamble; gana el mejor (o el más simple a < 0.005)
├─ es monto → ¿> 50% ceros?  sí → dos partes vs Tweedie (medir)  ·  no → regresión en log
└─ es pronóstico en el tiempo → rezagos + validación por bloques (ver ESCENARIOS.md §6)
Después: Optuna solo con tiempo · importancia por permutación + SHAP · priorizar con capacidad
```
