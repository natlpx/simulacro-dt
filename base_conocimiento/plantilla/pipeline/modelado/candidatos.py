"""
CANDIDATOS: desde "sin modelo" hasta LightGBM. Siempre se empieza por lo simple.

  regla_1var      sin modelo: ordenar por la variable con más Gini. Es la LÍNEA BASE que hay que
                  superar ("¿cuánto mejora el modelo frente a lo que haría un ejecutivo?").
  regla_top3      sin modelo: promedio de rankings de las 3 mejores (tipo scorecard manual).
  logistica       lineal, explicable con coeficientes. Gana cuando hay pocos datos o señal lineal.
  lgbm            árboles con boosting: no linealidades e interacciones, nulos y categorías nativas.
                  Suele ganar en datos tabulares con >5k filas.
  lgbm_pesos      mismo lgbm con class weights (desbalance). Mismo Gini, probabilidades infladas.
  lgbm_submuestra entrena con 1 negativo cada k y CORRIGE la probabilidad después (prior correction).
  ensamble        promedio de rankings de logística + lgbm: gana si se equivocan en cosas distintas.
  xgb             XGBoost (árboles por NIVELES, regularización en el objetivo). Referencia estándar.
  catboost        CatBoost (árboles SIMÉTRICOS + categorías con "ordered target statistics"): gana
                  cuando hay categorías de alta cardinalidad (CIIU, ubigeo, pagador). Más lento.
                  xgb y catboost solo entran si están instalados y no se usa --rapido.

Todo se evalúa con predicciones OOF (fuera de pliegue): la comparación es justa.
"""
import warnings

import numpy as np
import pandas as pd

from pipeline.modelado import metricas as M
from pipeline.modelado.datos import pliegues
from pipeline.regularizar import Regularizador

warnings.filterwarnings("ignore")

LGBM_BASE = dict(n_estimators=600, learning_rate=0.05, num_leaves=31, min_child_samples=50,
                 subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0, verbose=-1, n_jobs=-1,
                 deterministic=True, force_col_wise=True)   # mismo resultado en cada corrida (ver CAMBIOS_REVISION)


def _rank(x):
    return pd.Series(x).rank(pct=True).values


# ------------------------------------------------------------------ ajustadores (fit -> predict)
def fit_lgbm(Xtr, ytr, Xva, params=None, peso=None, submuestra=None, semilla=42, monto=False, devolver=False):
    import lightgbm as lgb
    p = {**LGBM_BASE, **(params or {}), "random_state": semilla}
    Xt, yt = Xtr, ytr
    factor = 1.0
    if submuestra:  # 1 de cada `submuestra` negativos
        rng = np.random.default_rng(semilla)
        keep = (ytr.values == 1) | (rng.random(len(ytr)) < 1 / submuestra)
        Xt, yt = Xtr[keep], ytr[keep]
        factor = submuestra
    if monto:
        m = lgb.LGBMRegressor(**p)
    else:
        m = lgb.LGBMClassifier(**p, **({"is_unbalance": True} if peso else {}))
    # early stopping con un 10% interno del train (no toca la validación)
    rng = np.random.default_rng(semilla + 1)
    es = rng.random(len(yt)) < 0.1
    m.fit(Xt[~es], yt[~es], eval_set=[(Xt[es], yt[es])],
          callbacks=[lgb.early_stopping(50, verbose=False)])
    pred = m.predict(Xva) if monto else m.predict_proba(Xva)[:, 1]
    if submuestra and not monto:  # corrección de prior: devuelve la probabilidad a la escala real
        pred = pred / (pred + (1 - pred) * factor)
    return (pred, m) if devolver else pred


def _parada_temprana(n, semilla):
    """10% interno del train para early stopping (igual que fit_lgbm: no toca la validación)."""
    return np.random.default_rng(semilla + 1).random(n) < 0.1


def fit_xgb(Xtr, ytr, Xva, params=None, semilla=42, devolver=False):
    """XGBoost con la MISMA receta que fit_lgbm (600 árboles, lr 0.05, submuestreo 0.8, early stopping
    con 10% interno) para que la comparación sea de algoritmo y no de perillas.
    tree_method='hist' = el mismo truco de histogramas que LightGBM (rápido con datos grandes).
    enable_categorical=True usa las columnas category de pandas sin one-hot."""
    import xgboost as xgb
    p = dict(n_estimators=600, learning_rate=0.05, max_depth=6, min_child_weight=5, subsample=0.8,
             colsample_bytree=0.8, reg_lambda=1.0, tree_method="hist", enable_categorical=True,
             max_cat_to_onehot=8, eval_metric="logloss", early_stopping_rounds=50, n_jobs=-1,
             random_state=semilla, **(params or {}))
    es = _parada_temprana(len(ytr), semilla)
    m = xgb.XGBClassifier(**p)
    m.fit(Xtr[~es], ytr[~es], eval_set=[(Xtr[es], ytr[es])], verbose=False)
    pred = m.predict_proba(Xva)[:, 1]
    return (pred, m) if devolver else pred


def _cat_listo(X):
    """CatBoost exige categorías como texto sin nulos; los números pueden tener NaN."""
    cats = [c for c in X.columns if not pd.api.types.is_numeric_dtype(X[c])]
    X = X.copy()
    for c in cats:
        X[c] = X[c].astype("string").fillna("NA").astype(str)
    return X, cats


def fit_catboost(Xtr, ytr, Xva, params=None, semilla=42, devolver=False):
    """CatBoost: árboles simétricos (la misma pregunta en todo un nivel) y codificación de categorías
    'ordenada' (cada fila se codifica solo con filas anteriores en una permutación al azar): evita la
    fuga del target encoding sin que tengamos que hacerlo a mano."""
    from catboost import CatBoostClassifier
    p = dict(iterations=600, learning_rate=0.05, depth=6, l2_leaf_reg=3.0, random_seed=semilla,
             eval_metric="Logloss", early_stopping_rounds=50, thread_count=-1, verbose=False,
             allow_writing_files=False, **(params or {}))
    A, cats = _cat_listo(Xtr)
    B, _ = _cat_listo(Xva)
    es = _parada_temprana(len(ytr), semilla)
    m = CatBoostClassifier(**p)
    m.fit(A[~es], ytr[~es], cat_features=cats, eval_set=(A[es], ytr[es]))
    pred = m.predict_proba(B)[:, 1]
    return (pred, m) if devolver else pred


def fit_logistica(Xtr, ytr, Xva, C_=1.0, peso=None):
    from sklearn.linear_model import LogisticRegression
    R = Regularizador("lineal")
    A = R.fit_transform(Xtr, ytr)
    B = R.transform(Xva)[A.columns]
    A = A.select_dtypes("number"); B = B[A.columns]
    m = LogisticRegression(C=C_, max_iter=3000, class_weight="balanced" if peso else None)
    m.fit(A, ytr)
    return m.predict_proba(B)[:, 1]


def explicar_logistica(Xtr, ytr, Xcaso=None, C_=1.0):
    """Explicación del modelo LOGÍSTICO cuando es el elegido (hueco 3 de la revisión: antes se
    explicaba siempre con LightGBM aunque se entregara la logística).

    Las variables numéricas salen ESTANDARIZADAS del Regularizador (media 0, desv. 1), así que:
      coef        cuánto suben los log-odds si la variable sube 1 desviación estándar
      odds_ratio  exp(coef): multiplica las chances (1.5 = +50%; 0.7 = −30%)
    Aporte de cada variable a UN caso = coef × (valor − promedio de train): es el SHAP exacto
    de un modelo lineal, así que se lee igual que el gráfico de SHAP de LightGBM."""
    from sklearn.linear_model import LogisticRegression
    R = Regularizador("lineal")
    A = R.fit_transform(Xtr, ytr).select_dtypes("number")
    m = LogisticRegression(C=C_, max_iter=3000).fit(A, ytr)
    coef = pd.Series(m.coef_[0], index=A.columns)
    t = pd.DataFrame({"variable": coef.index, "coef": coef.values, "odds_ratio": np.exp(coef.values)})
    t["sentido"] = np.where(t.coef > 0, "más -> sube prob", "más -> baja prob")
    t = t.reindex(t.coef.abs().sort_values(ascending=False).index).reset_index(drop=True)
    caso = None
    if Xcaso is not None and len(Xcaso):
        B = R.transform(Xcaso)[A.columns]
        p = m.predict_proba(B)[:, 1]
        i = int(np.argmax(p))
        aporte = coef * (B.iloc[i] - A.mean())
        caso = pd.DataFrame({"variable": A.columns, "valor": [f"{v:,.2f}" for v in B.iloc[i].values],
                             "aporte": aporte.values})
        caso = caso.reindex(caso.aporte.abs().sort_values(ascending=False).index).head(10).reset_index(drop=True)
        caso["valor"] = caso["valor"] + " (escala estandarizada)"
    return t, caso


def regla(Xtr, ytr, Xva, k=1):
    """Sin modelo: elige (con train) las k variables numéricas de mayor Gini y su dirección."""
    g = {}
    for v in Xtr.columns:
        if pd.api.types.is_numeric_dtype(Xtr[v]) and Xtr[v].notna().mean() > 0.5:
            x = Xtr[v].fillna(Xtr[v].median())
            if x.nunique() > 1:
                g[v] = M.gini(ytr, x)
    top = sorted(g, key=lambda v: -abs(g[v]))[:k]
    s = np.zeros(len(Xva))
    for v in top:
        x = Xva[v].fillna(Xtr[v].median())
        s += _rank(x if g[v] > 0 else -x)
    return s / max(len(top), 1)


# ------------------------------------------------------------------ OOF
def oof(fn, X, y, folds, **kw):
    p = np.zeros(len(y))
    for tr, va in folds:
        p[va] = fn(X.iloc[tr], y.iloc[tr], X.iloc[va], **kw)
    return p


CANDIDATOS = {
    "regla_1var": (regla, dict(k=1)),
    "regla_top3": (regla, dict(k=3)),
    "logistica": (fit_logistica, {}),
    "lgbm": (fit_lgbm, {}),
    "lgbm_pesos": (fit_lgbm, dict(peso=True)),
    "lgbm_submuestra": (fit_lgbm, dict(submuestra=4)),
}


def _instalado(modulo):
    import importlib.util
    return importlib.util.find_spec(modulo) is not None


CANDIDATOS_EXTRA = {k: v for k, v in {
    "xgb": (fit_xgb, {}) if _instalado("xgboost") else None,
    "catboost": (fit_catboost, {}) if _instalado("catboost") else None,
}.items() if v is not None}


def comparar(D, params_lgbm=None, extra=True):
    """extra=True suma XGBoost y CatBoost (si están instalados) con los MISMOS pliegues."""
    tr, vs = D["train"], D["vars"]
    X, y = tr[vs], tr["target"].astype(int)
    folds = pliegues(y)
    preds, filas = {}, []
    todos = {**CANDIDATOS, **(CANDIDATOS_EXTRA if extra else {})}
    if extra and len(CANDIDATOS_EXTRA) < 2:
        print("  (para comparar también XGBoost/CatBoost: pip install xgboost catboost)")
    for nombre, (fn, kw) in todos.items():
        kw = dict(kw)
        if nombre.startswith("lgbm") and params_lgbm:
            kw["params"] = params_lgbm
        preds[nombre] = oof(fn, X, y, folds, **kw)
        filas.append(dict(modelo=nombre, **M.resumen_clasif(y, preds[nombre])))
        print(f"  {nombre:<16} Gini OOF {filas[-1]['gini']:.4f}  AUC-PR {filas[-1]['auc_pr']:.4f}  "
              f"prob media {filas[-1]['prob_media']:.3f} (real {filas[-1]['tasa_real']:.3f})")
    preds["ensamble"] = (_rank(preds["lgbm"]) + _rank(preds["logistica"])) / 2
    filas.append(dict(modelo="ensamble", **M.resumen_clasif(y, preds["ensamble"])))
    print(f"  {'ensamble':<16} Gini OOF {filas[-1]['gini']:.4f}")
    tabla = pd.DataFrame(filas)
    # las reglas y el ensamble de rankings no son probabilidades: su brier no aplica
    tabla.loc[tabla.modelo.str.startswith(("regla", "ensamble")), ["brier", "prob_media"]] = np.nan
    return tabla, preds, folds
