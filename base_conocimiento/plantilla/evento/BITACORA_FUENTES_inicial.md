# Filas iniciales para docs/BITACORA_FUENTES.md (repo del evento)

Copien estas filas al formato de `docs/BITACORA_FUENTES.md` del repo del evento: una línea por fuente, con dirección web, idea tomada y archivo donde se aplicó. Borren las que no usen y agreguen lo que consulten durante el evento.

| Fuente (dirección web) | Idea que tomamos | Archivo donde se aplicó |
|---|---|---|
| https://duckdb.org/docs/ | SQL sobre CSV/Parquet sin cargar todo a memoria; `memory_limit`, `temp_directory` | `pipeline/db.py`, `pipeline/ingesta.py` |
| https://scikit-learn.org/stable/modules/cross_validation.html | Validación cruzada estratificada (OOF) | `pipeline/modelado/datos.py`, `candidatos.py` |
| https://scikit-learn.org/stable/modules/linear_model.html#logistic-regression | Regresión logística regularizada | `pipeline/modelado/candidatos.py` |
| https://scikit-learn.org/stable/modules/permutation_importance.html | Importancia por permutación | `pipeline/modelado/importancia.py` |
| https://scikit-learn.org/stable/modules/isotonic.html | Calibración isotónica de rankings | `run_modelo.py` |
| https://lightgbm.readthedocs.io/ | Gradient boosting, early stopping, contribuciones tipo SHAP (`pred_contrib`) | `candidatos.py`, `importancia.py` |
| https://xgboost.readthedocs.io/ | XGBoost con `tree_method="hist"` y categorías nativas | `candidatos.py` |
| https://catboost.ai/docs/ | CatBoost y codificación ordenada de categorías | `candidatos.py` |
| https://optuna.readthedocs.io/ | Búsqueda de hiperparámetros con tiempo límite | `pipeline/modelado/afinamiento.py` |
| https://coin-or.github.io/pulp/ | Optimización con restricciones (asignación por capacidad y zona) | `pipeline/modelado/priorizar.py` |
| https://doi.org/10.1080/01621459.1983.10478017 | Duan (1983), "smearing": corregir la media al volver de log a soles | `pipeline/modelado/segmentos_monto.py` |
| [COMPLETAR] Fuente usada para PSI e IV (scoring crediticio) | Estabilidad entre periodos (PSI) y poder predictivo (IV) | `pipeline/seleccion.py` |
| — | La plantilla se preparó con asistencia de Claude (Anthropic) antes del evento (ver `base_conocimiento/INVENTARIO.md`) | `base_conocimiento/plantilla/` |
