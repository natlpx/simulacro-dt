"""
HIPERPARÁMETROS: cuáles mover, cómo buscarlos y CÓMO SABER CUÁLES IMPORTAN.

Hiperparámetro = perilla que NO se aprende de los datos (la eliges tú). En LightGBM las que
más suelen importar, en orden aproximado:
  learning_rate + n_estimators  cuánto aprende por árbol y cuántos árboles (se fijan juntos:
                                early stopping elige n_estimators solo)
  num_leaves / max_depth        complejidad de cada árbol (más hojas = más interacciones = más sobreajuste)
  min_child_samples             mínimo de filas por hoja: el freno principal con pocos positivos
  subsample, colsample_bytree   aleatoriedad por filas/columnas: reduce varianza
  reg_lambda, reg_alpha         penalización de los pesos de las hojas

Cómo se busca: Optuna (búsqueda bayesiana TPE): prueba una combinación, mide Gini en validación
cruzada, y propone la siguiente donde espera mejorar. Mejor que grid search (que gasta pruebas en
zonas malas) y que random search (que no aprende de lo probado).

Cómo se sabe CUÁL IMPORTA: optuna.importance (fANOVA) mide qué parte de la variación del Gini
entre pruebas explica cada perilla. Si learning_rate explica 60% y reg_alpha 2%, la próxima vez
solo se busca learning_rate. Esto es medido, no opinión.

Regla práctica de concurso: afinar AL FINAL, con tiempo límite. Lo medido en el simulacro:
35 pruebas en 15 min dieron +0.001 de Gini. Las variables mueven más que las perillas.
"""
import numpy as np

from pipeline.modelado import metricas as M
from pipeline.modelado.candidatos import fit_lgbm, oof
from pipeline.modelado.datos import pliegues


def buscar(D, segundos=90, max_pruebas=40, folds_k=3):
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    tr, vs = D["train"], D["vars"]
    X, y = tr[vs], tr["target"].astype(int)
    folds = pliegues(y, k=folds_k, semilla=7)

    def objetivo(trial):
        params = dict(
            learning_rate=trial.suggest_float("learning_rate", 0.01, 0.2, log=True),
            num_leaves=trial.suggest_int("num_leaves", 7, 127, log=True),
            min_child_samples=trial.suggest_int("min_child_samples", 10, 300, log=True),
            subsample=trial.suggest_float("subsample", 0.5, 1.0),
            colsample_bytree=trial.suggest_float("colsample_bytree", 0.3, 1.0),
            reg_lambda=trial.suggest_float("reg_lambda", 1e-3, 30, log=True),
            reg_alpha=trial.suggest_float("reg_alpha", 1e-3, 10, log=True),
        )
        return M.gini(y, oof(fit_lgbm, X, y, folds, params=params))

    estudio = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=42))
    estudio.enqueue_trial(dict(learning_rate=0.05, num_leaves=31, min_child_samples=50, subsample=0.8,
                               colsample_bytree=0.8, reg_lambda=1.0, reg_alpha=1e-3))  # prueba 0 = default
    estudio.optimize(objetivo, n_trials=max_pruebas, timeout=segundos)
    try:
        imp = optuna.importance.get_param_importances(estudio)
    except Exception:
        imp = {}
    pruebas = estudio.trials_dataframe()[["number", "value"]].rename(columns={"value": "gini_cv"})
    default = float(pruebas.gini_cv.iloc[0])
    print(f"  {len(pruebas)} pruebas · default {default:.4f} -> mejor {estudio.best_value:.4f} "
          f"(+{estudio.best_value - default:.4f})")
    print("  importancia de hiperparámetros:", {k: round(v, 2) for k, v in imp.items()})
    return dict(mejores=estudio.best_params, mejor=estudio.best_value, default=default,
                importancia=imp, pruebas=pruebas)
