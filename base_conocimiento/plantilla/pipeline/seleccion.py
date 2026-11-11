"""
PASO 7 · EMBUDO DE SELECCIÓN (decisiones solo con train; PSI compara train vs validación).

  F1 copias      : dos variables con los mismos valores -> se queda una
  F2 estabilidad : PSI > 0.25 -> la variable cambió de distribución entre periodos;
                   el modelo aprendería un mundo que ya no existe. (También atrapa fugas.)
  F3 fuga        : Gini individual > 0.5 -> una sola variable "adivina" demasiado: casi
                   siempre es información posterior al corte. NO se borra sola: va a revisión.
  F4 sin señal   : Gini < 0.02 -> no separa nada
  F5 redundancia : Spearman > 0.9 entre dos -> me quedo con la de mayor Gini
  IV (Information Value): lenguaje de riesgo bancario. <0.02 nada, 0.1-0.3 media,
                   >0.5 sospechosa. Lo pide cualquier jurado de banco.

Gini = 2*AUC - 1 : 0 = azar, 1 = perfecto. Es la métrica estándar de scoring en banca.
"""
import numpy as np
import pandas as pd

import config as C


def auc_rapido(x, y):
    """AUC por rangos (Mann-Whitney), sin sklearn. Nulos = grupo propio en el extremo bajo."""
    x = pd.Series(x).astype(float)
    x = x.fillna(x.min() - 1 if x.notna().any() else 0)
    r = x.rank(method="average").values
    y = np.asarray(y)
    n1 = y.sum(); n0 = len(y) - n1
    if n1 == 0 or n0 == 0:
        return 0.5
    return (r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)


def gini(x, y):
    return abs(2 * auc_rapido(x, y) - 1)


def _bins(x_ref, n=10):
    q = np.unique(np.nanquantile(x_ref, np.linspace(0, 1, n + 1)))
    return q if len(q) > 2 else np.unique(np.concatenate([q, [np.nanmin(x_ref) - 1, np.nanmax(x_ref) + 1]]))


def psi(ref, act, n=10):
    """Population Stability Index: <0.1 estable, 0.1-0.25 vigilar, >0.25 cambió."""
    ref, act = pd.Series(ref).astype(float), pd.Series(act).astype(float)
    if ref.notna().sum() < 10:
        return 0.0
    b = _bins(ref.dropna().values, n)
    def dist(s):
        h = np.histogram(s.dropna().clip(b[0], b[-1]), bins=b)[0].astype(float)
        h = np.append(h, s.isna().sum())
        return np.clip(h / max(h.sum(), 1), 1e-4, None)
    p, q = dist(ref), dist(act)
    return float(np.sum((q - p) * np.log(q / p)))


def iv(x, y, n=10):
    x = pd.Series(x).astype(float)
    try:
        g = pd.qcut(x, n, duplicates="drop").cat.add_categories("NULO").fillna("NULO")
    except Exception:
        return 0.0
    t = pd.DataFrame({"g": g, "y": np.asarray(y)}).groupby("g", observed=True).y.agg(["sum", "count"])
    b = (t["sum"] + 0.5) / (t["sum"].sum() + 0.5)
    m = (t["count"] - t["sum"] + 0.5) / ((t["count"] - t["sum"]).sum() + 0.5)
    return float(((b - m) * np.log(b / m)).sum())


def embudo(df, target="target", split="split", excluir=("id", "target_monto", "fecha_corte")):
    U = C.U
    tr = df[df[split] == "train"] if split in df else df
    va = df[df[split] != "train"] if split in df else None
    cand = [c for c in df.columns if c not in set(excluir) | {target, split}]
    filas = []
    num = {}
    for c in cand:
        s = tr[c]
        if not pd.api.types.is_numeric_dtype(s):  # categóricas: se evalúan por su tasa (frecuencia)
            s = s.astype("string").map(s.astype("string").value_counts(normalize=True)).astype(float)
        num[c] = s
        filas.append(dict(variable=c, gini=gini(s, tr[target]), iv=iv(s, tr[target]),
                          psi=psi(s, va[c] if (va is not None and pd.api.types.is_numeric_dtype(tr[c])) else s),
                          pct_nulo=float(tr[c].isna().mean())))
    r = pd.DataFrame(filas).set_index("variable")
    r["decision"], r["motivo"] = "QUEDA", ""
    def marcar(mask, dec, mot):
        sel = mask & (r.decision == "QUEDA")
        r.loc[sel, "decision"], r.loc[sel, "motivo"] = dec, mot
    # F1 copias
    h = {c: pd.util.hash_pandas_object(num[c].fillna(-9.99e18), index=False).sum() for c in cand}
    vistos = {}
    for c in r.sort_values("gini", ascending=False).index:
        if h[c] in vistos:
            r.loc[c, ["decision", "motivo"]] = ["FUERA", f"F1 copia de {vistos[h[c]]}"]
        vistos.setdefault(h[c], c)
    marcar(r.psi > U["psi_drop"], "FUERA", "F2 inestable (PSI > 0.25)")
    marcar((r.gini > U["gini_fuga"]) | (r.iv > U["iv_fuga"]), "REVISAR_FUGA", "F3 demasiado buena: ¿existe el día de decidir?")
    marcar(r.gini < U["gini_min"], "FUERA", "F4 sin señal (Gini < 0.02)")
    # F5 redundancia, de mayor a menor Gini
    vivas = r[r.decision == "QUEDA"].sort_values("gini", ascending=False).index.tolist()
    if len(vivas) > 1:
        corr = pd.DataFrame({c: num[c] for c in vivas}).rank().corr().abs()
        quedan = []
        for c in vivas:
            par = next((q for q in quedan if corr.loc[c, q] > U["spearman_max"]), None)
            if par:
                r.loc[c, ["decision", "motivo"]] = ["FUERA", f"F5 redundante con {par} (ρ={corr.loc[c, par]:.2f})"]
            else:
                quedan.append(c)
    r["alerta_psi"] = np.where(r.psi > U["psi_alerta"], "vigilar", "")
    orden = {"REVISAR_FUGA": 0, "QUEDA": 1, "FUERA": 2}
    return r.assign(_o=r.decision.map(orden)).sort_values(["_o", "gini"], ascending=[True, False]).drop(columns="_o").reset_index()


def leer_ordenado(path):
    """Tabla de modelo siempre en el mismo orden (por id): el split 70/30 depende de la posición."""
    df = pd.read_parquet(path)
    return df.sort_values("id", kind="stable").reset_index(drop=True) if "id" in df else df


def embudo_fuera_de_tiempo(train, actual, target="target"):
    """Embudo HONESTO cuando existe la tabla de un corte anterior (tabla_modelo_t1).

    Por qué existe (huecos 1, 2 y 4 de la revisión):
      - La selección se decide SOLO con la tabla de entrenamiento (corte anterior). La del corte
        actual es el examen: si se eligen variables mirando su target, el examen deja de ser ciego.
      - PSI entre CORTES (no entre dos mitades al azar del mismo periodo): así sí detecta las
        variables que cambiaron con el tiempo (conteos acumulados, cambios de sistema).
      - Fuga en CUALQUIERA de las dos tablas: una columna de una tabla "foto" (sin fecha, tomada
        hoy) puede verse inocente en el corte anterior (Gini 0.16) y ser el futuro en el actual
        (Gini 0.91). Se marca REVISAR_FUGA si es demasiado buena en train O en el corte actual.
    """
    comunes = [c for c in train.columns if c in actual.columns]
    a = train[comunes].assign(split="train")
    b = actual[comunes].assign(split="valid")
    r = embudo(pd.concat([a, b], ignore_index=True), target=target)
    r = r.set_index("variable")          # aquí 'psi' = PSI ENTRE CORTES (train = corte anterior, valid = actual)
    r["motivo"] = r.motivo.str.replace("F2 inestable (PSI > 0.25)", "F2 cambió entre cortes (PSI > 0.25)", regex=False)
    r["gini_actual"], r["iv_actual"] = np.nan, np.nan
    if target in actual and actual[target].nunique() > 1:
        U = C.U
        for v in r.index:
            s = actual[v]
            if not pd.api.types.is_numeric_dtype(s):
                s = s.astype("string").map(s.astype("string").value_counts(normalize=True)).astype(float)
            r.loc[v, "gini_actual"] = gini(s, actual[target])
            r.loc[v, "iv_actual"] = iv(s, actual[target])
        fuga = (r.gini_actual > U["gini_fuga"]) | (r.iv_actual > U["iv_fuga"])
        nuevas = fuga & (r.decision != "REVISAR_FUGA")
        r.loc[nuevas, "motivo"] = ("F3 fuga en el CORTE ACTUAL (Gini " + r.loc[nuevas, "gini_actual"].round(2).astype(str)
                                   + " vs " + r.loc[nuevas, "gini"].round(2).astype(str)
                                   + " en train): ¿tabla foto tomada hoy? ¿existe el día de decidir?")
        r.loc[fuga, "decision"] = "REVISAR_FUGA"
    orden = {"REVISAR_FUGA": 0, "QUEDA": 1, "FUERA": 2}
    r = r.reset_index()
    return r.assign(_o=r.decision.map(orden)).sort_values(["_o", "gini"], ascending=[True, False]).drop(columns="_o")


def ejecutar(bit, path_modelo, split_fn=None):
    print("\n== PASO 7 · SELECCIÓN ==")
    path_t1 = C.OUT_DIR / "tabla_modelo_t1.parquet"
    if split_fn is None and path_t1.exists():
        tr, ac = leer_ordenado(path_t1), leer_ordenado(path_modelo)
        if "target" in tr and tr["target"].nunique() > 1:
            print(f"  modo FUERA DE TIEMPO: decide con {path_t1.name}; PSI entre cortes; fugas en ambas tablas")
            r = embudo_fuera_de_tiempo(tr, ac)
            r.to_csv(C.OUT_DIR / "seleccion_variables.csv", index=False, encoding="utf-8-sig")
            bit.registrar("seleccion", "tabla_modelo_t1+actual", len(tr), int((r.decision == "QUEDA").sum()),
                          {"embudo": r.decision.value_counts().to_dict(), "modo": "fuera_de_tiempo"})
            for _, x in r[r.decision == "REVISAR_FUGA"].iterrows():
                print(f"  ⚠ REVISAR FUGA: {x.variable}  Gini train={x.gini:.2f}  Gini actual={x.gini_actual:.2f}  IV={x.iv:.2f}")
            inest = r[r.motivo.str.startswith("F2", na=False)]
            if len(inest):
                print(f"  ✂ {len(inest)} variable(s) FUERA por PSI entre cortes > {C.U['psi_drop']}: "
                      + ", ".join(inest.variable.head(8)))
            return r
    df = leer_ordenado(path_modelo)
    if "target" not in df:
        print("  (sin target definido en config.TARGET -> se omite el embudo)")
        return None
    if split_fn:
        df["split"] = split_fn(df)
    elif "split" not in df:  # por defecto: 70/30 aleatorio estratificado. Mejor: fuera de tiempo.
        rng = np.random.default_rng(42)
        df["split"] = np.where(rng.random(len(df)) < 0.7, "train", "valid")
    r = embudo(df)
    r.to_csv(C.OUT_DIR / "seleccion_variables.csv", index=False, encoding="utf-8-sig")
    resumen = r.decision.value_counts().to_dict()
    bit.registrar("seleccion", "tabla_modelo", len(df), int((r.decision == "QUEDA").sum()), {"embudo": resumen})
    for _, x in r[r.decision == "REVISAR_FUGA"].iterrows():
        print(f"  ⚠ REVISAR FUGA: {x.variable}  Gini={x.gini:.2f}  IV={x.iv:.2f}")
    return r
