"""
PASO 6 · REGULARIZACIÓN DE DATOS (lo que SÍ aprende de los datos -> solo con TRAIN).

  .fit(train)  aprende: percentiles, medianas, categorías frecuentes, tasas por categoría.
  .transform(cualquiera)  aplica lo aprendido sin volver a mirar.
Si se ajusta con todo (train + test), el modelo "ve" el futuro y el Gini de validación miente.

Dos modos, porque cada modelo mira distinto:
  modo="arbol"  (LightGBM/XGBoost) -> mira el ORDEN de los valores:
      no necesita escalar ni log; nulos se dejan (LightGBM los maneja);
      categorías: raras -> 'OTROS', alta cardinalidad -> frecuencia + target encoding.
  modo="lineal" (logística, scorecard) -> mira la DISTANCIA:
      recorte de extremos p1/p99 (winsorizar), log de montos sesgados,
      nulos -> mediana + indicador, estandarizar (media 0, desv. 1), one-hot de categorías bajas.
"""
import json

import numpy as np
import pandas as pd


class Regularizador:
    def __init__(self, modo="arbol", p_bajo=0.01, p_alto=0.99, min_freq=0.01, card_alta=50,
                 suavizado=50, excluir=("id", "target", "split")):
        self.modo, self.pb, self.pa = modo, p_bajo, p_alto
        self.min_freq, self.card_alta, self.k = min_freq, card_alta, suavizado
        self.excluir = set(excluir)
        self.p = {}

    # ------------------------------------------------------------------ FIT (solo train)
    def fit(self, df, y=None):
        num = [c for c in df.select_dtypes("number").columns if c not in self.excluir]
        cat = [c for c in df.columns if c not in self.excluir and c not in num]
        self.p = dict(num={}, cat={}, prior=float(y.mean()) if y is not None else None)
        for c in num:
            s = df[c].astype(float)
            lo, hi = s.quantile([self.pb, self.pa]).tolist()
            sesgo = float(s.skew()) if s.notna().sum() > 2 else 0.0
            usar_log = self.modo == "lineal" and sesgo > 2
            t = self._num(s.clip(lo, hi), usar_log)
            self.p["num"][c] = dict(lo=lo, hi=hi, mediana=float(s.median()) if s.notna().any() else 0.0,
                                    log=usar_log, media=float(t.mean()) if t.notna().any() else 0.0,
                                    std=float(t.std()) if t.notna().sum() > 1 and t.std() > 0 else 1.0,
                                    con_nulos=bool(s.isna().any()))
        for c in cat:
            s = df[c].astype("string").fillna("SIN_DATO")
            frec = s.value_counts(normalize=True)
            frecuentes = frec[frec >= self.min_freq].index.tolist()
            info = dict(frecuentes=frecuentes, frec=frec.to_dict(), alta=len(frecuentes) > self.card_alta)
            if y is not None:  # target encoding suavizado (se aplica fuera de muestra en fit_transform)
                g = pd.DataFrame({"c": s.where(s.isin(frecuentes), "OTROS"), "y": y.values}).groupby("c").y.agg(["sum", "count"])
                info["te"] = ((g["sum"] + self.k * self.p["prior"]) / (g["count"] + self.k)).to_dict()
            self.p["cat"][c] = info
        return self

    @staticmethod
    def _num(s, log):
        return np.sign(s) * np.log1p(np.abs(s)) if log else s

    # ------------------------------------------------------------------ TRANSFORM
    def transform(self, df, te_oof=None):
        out = {}
        for c in self.excluir & set(df.columns):
            out[c] = df[c]
        for c, p in self.p["num"].items():
            s = df[c].astype(float).clip(p["lo"], p["hi"]) if c in df else pd.Series(np.nan, index=df.index)
            if self.modo == "lineal":
                if p["con_nulos"]:
                    out[f"{c}__nulo"] = s.isna().astype("int8")
                s = (self._num(s.fillna(p["mediana"]), p["log"]) - p["media"]) / p["std"]
            out[c] = s
        for c, p in self.p["cat"].items():
            s = df[c].astype("string").fillna("SIN_DATO") if c in df else pd.Series("SIN_DATO", index=df.index)
            s = s.where(s.isin(p["frecuentes"]), "OTROS")
            out[f"{c}__frec"] = s.map(p["frec"]).fillna(0).astype(float)
            if "te" in p:
                te = te_oof[c] if te_oof is not None and c in te_oof else s.map(p["te"]).fillna(self.p["prior"])
                out[f"{c}__te"] = te.astype(float)
            if not p["alta"]:
                if self.modo == "lineal":
                    for v in p["frecuentes"][:30]:
                        out[f"{c}=={v}"] = (s == v).astype("int8")
                else:
                    out[c] = s.astype("category")
        return pd.DataFrame(out, index=df.index)

    def fit_transform(self, df, y, n_folds=5, semilla=42):
        """Target encoding FUERA DE MUESTRA: cada fila recibe la tasa calculada SIN ella.
        Si no, la variable 'se sabe la respuesta' y el modelo sobreajusta."""
        self.fit(df, y)
        te_oof = {}
        folds = np.random.default_rng(semilla).integers(0, n_folds, len(df))
        for c, p in self.p["cat"].items():
            s = df[c].astype("string").fillna("SIN_DATO")
            s = s.where(s.isin(p["frecuentes"]), "OTROS")
            res = pd.Series(np.nan, index=df.index)
            for k in range(n_folds):
                tr = folds != k
                g = pd.DataFrame({"c": s[tr], "y": y[tr].values}).groupby("c").y.agg(["sum", "count"])
                tasa = (g["sum"] + self.k * self.p["prior"]) / (g["count"] + self.k)
                res[~tr] = s[~tr].map(tasa).fillna(self.p["prior"]).values
            te_oof[c] = res
        return self.transform(df, te_oof)

    def guardar(self, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(dict(modo=self.modo, p=self.p), f, ensure_ascii=False, default=str, indent=1)
