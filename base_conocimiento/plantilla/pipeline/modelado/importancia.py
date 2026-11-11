"""
¿QUÉ VARIABLES IMPORTAN MÁS? Tres medidas que responden preguntas distintas:

  gain (ganancia)   cuánto mejoró el modelo cada vez que partió por esa variable, durante el
                    ENTRENAMIENTO. Rápida, pero sesgada: premia variables con muchos valores
                    distintos (montos, ids) aunque no generalicen.
  permutación       se DESORDENA la variable en VALIDACIÓN y se mide cuánto cae el Gini.
                    Responde "¿cuánto depende el modelo de esto en datos que no vio?". Es la más
                    honesta. Si cae ~0, la variable sobra. Si dos variables están correlacionadas
                    se reparten el crédito (ambas pueden salir bajas).
  SHAP              reparte cada predicción entre las variables (suma exacta). El promedio de
                    |SHAP| = importancia global; el SIGNO dice la dirección ("más plazo -> más
                    probabilidad") y sirve para explicar UN caso al jurado. LightGBM lo calcula
                    nativo con pred_contrib=True (no hace falta la librería shap).
  estabilidad       ranking de gain en cada pliegue: una variable que es #1 en un pliegue y #40
                    en otro es frágil.

Cuándo preocuparse: una variable con permutación MUY alta y frase de negocio rara = fuga.
"""
import numpy as np
import pandas as pd

from pipeline.modelado import metricas as M


def calcular(modelo, Xva, yva, folds_models=None, top_perm=30, repeticiones=3, semilla=0):
    vs = list(Xva.columns)
    gain = pd.Series(modelo.booster_.feature_importance("gain"), index=vs)
    split = pd.Series(modelo.booster_.feature_importance("split"), index=vs)
    base = M.gini(yva, modelo.predict_proba(Xva)[:, 1])

    rng = np.random.default_rng(semilla)
    perm = pd.Series(0.0, index=vs)
    for v in gain.sort_values(ascending=False).index[:top_perm]:
        caidas = []
        for _ in range(repeticiones):
            Xp = Xva.copy()
            Xp[v] = Xp[v].values[rng.permutation(len(Xp))]
            caidas.append(base - M.gini(yva, modelo.predict_proba(Xp)[:, 1]))
        perm[v] = float(np.mean(caidas))

    contrib = modelo.booster_.predict(Xva, pred_contrib=True)[:, :-1]   # última col = sesgo
    shap_abs = pd.Series(np.abs(contrib).mean(0), index=vs)
    direccion = {}
    for j, v in enumerate(vs):
        x = Xva[v]
        if pd.api.types.is_numeric_dtype(x) and x.notna().sum() > 10 and x.nunique() > 1:
            direccion[v] = float(pd.Series(contrib[:, j]).corr(x.reset_index(drop=True).astype(float), method="spearman"))
    t = pd.DataFrame({"gain": gain / gain.sum(), "splits": split, "permutacion_gini": perm,
                      "shap_medio": shap_abs, "direccion": pd.Series(direccion)})
    if folds_models:
        ranks = pd.DataFrame({i: pd.Series(m.booster_.feature_importance("gain"), index=vs).rank(ascending=False)
                              for i, m in enumerate(folds_models)})
        t["rank_min"], t["rank_max"] = ranks.min(1), ranks.max(1)
    t["sentido"] = np.where(t.direccion > 0.2, "más -> sube prob", np.where(t.direccion < -0.2, "más -> baja prob", "mixto/categ."))
    return t.sort_values("shap_medio", ascending=False).reset_index(names="variable"), contrib
