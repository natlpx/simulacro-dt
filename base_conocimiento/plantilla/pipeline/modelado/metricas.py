"""
MÉTRICAS: qué mide cada una y cuándo usarla.

  Gini = 2·AUC − 1      ¿ORDENA bien? (positivos arriba). Estándar en banca. No le importa si la
                        probabilidad es 0.2 o 0.02 mientras el orden sea correcto -> NO cambia con
                        reponderar o submuestrear clases.
  AUC-PR (precisión-    con MUCHO desbalance (1% positivos) el Gini puede verse alto aunque el
  recall)               top de la lista tenga pocos positivos. AUC-PR mira solo a los positivos.
                        Su piso es la tasa de positivos (no 0.5).
  Lift decil 1          "el 10% de arriba convierte X veces más que el promedio". Es la frase para
                        el jurado de negocio. Captura@k = % de positivos que caen en el top k%.
  Brier / calibración   ¿la probabilidad es REAL? (0.30 debería convertir ~30%). Importa cuando se
                        multiplica probabilidad × monto o se calcula ROI. Reponderar la rompe.
  R²                    % de la variación del monto que explica el modelo. En montos con cola larga
                        conviene medirlo también en log (si no, 3 empresas gigantes dominan).
"""
import numpy as np
import pandas as pd


def gini(y, p):
    from sklearn.metrics import roc_auc_score
    y = np.asarray(y)
    return float(2 * roc_auc_score(y, p) - 1) if 0 < y.sum() < len(y) else float("nan")


def auc_pr(y, p):
    from sklearn.metrics import average_precision_score
    return float(average_precision_score(y, p))


def lift(y, p, top=0.10):
    y, p = np.asarray(y), np.asarray(p)
    n = max(int(len(y) * top), 1)
    idx = np.argsort(-p)[:n]
    return float(y[idx].mean() / max(y.mean(), 1e-12))


def captura(y, p, top=0.10):
    y, p = np.asarray(y), np.asarray(p)
    n = max(int(len(y) * top), 1)
    return float(y[np.argsort(-p)[:n]].sum() / max(y.sum(), 1))


def brier(y, p):
    return float(np.mean((np.asarray(p) - np.asarray(y)) ** 2))


def calibracion(y, p, n=10):
    d = pd.DataFrame({"y": y, "p": p})
    d["bin"] = pd.qcut(d.p.rank(method="first"), n, labels=False)
    return d.groupby("bin").agg(prob_media=("p", "mean"), tasa_real=("y", "mean"), n=("y", "size")).reset_index()


def deciles(y, p, n=10):
    d = pd.DataFrame({"y": y, "p": p})
    d["decil"] = n - pd.qcut(d.p.rank(method="first"), n, labels=False)
    t = d.groupby("decil").agg(n=("y", "size"), positivos=("y", "sum"), tasa=("y", "mean")).reset_index()
    t["lift"] = t.tasa / d.y.mean()
    t["captura_acum"] = t.positivos.cumsum() / max(d.y.sum(), 1)
    return t


def r2(y, yhat):
    y, yhat = np.asarray(y, float), np.asarray(yhat, float)
    return float(1 - np.sum((y - yhat) ** 2) / max(np.sum((y - y.mean()) ** 2), 1e-12))


def resumen_clasif(y, p):
    return dict(gini=gini(y, p), auc_pr=auc_pr(y, p), lift_d1=lift(y, p), captura_10=captura(y, p),
                brier=brier(y, p), prob_media=float(np.mean(p)), tasa_real=float(np.mean(y)))
