"""
DATOS PARA MODELAR: qué filas entrenan, cuáles se puntúan y cómo se valida.

Tres situaciones reales (se elige sola, en este orden):
  1. EVALUAR definido  -> el banco dio la lista de empresas a puntuar (sin target).
                          Entrenar = resto de empresas con target. Puntuar = la lista.
  2. existe tabla_modelo_t1 (corte anterior) -> FUERA DE TIEMPO, la más honesta:
                          Entrenar = corte anterior (su target ya ocurrió dentro de los datos).
                          Puntuar = corte actual (el "día de decidir").
                          Si el corte actual también trae target (simulacro), se mide ahí: es el
                          examen que más se parece a la evaluación ciega del banco.
  3. solo tabla_modelo -> validación cruzada estratificada (5 pliegues) sobre la misma tabla.
Dentro del entrenamiento SIEMPRE se elige modelo con validación cruzada (predicciones OOF):
cada fila se predice con un modelo que no la vio.
"""
import numpy as np
import pandas as pd

import config as C
from pipeline.seleccion import leer_ordenado

META = {"id", "target", "target_monto", "fecha_corte", "split"}


def variables(df, incluir_revisar=False):
    """Variables que pasaron el embudo (QUEDA). Las REVISAR_FUGA no entran salvo decisión humana."""
    p = C.OUT_DIR / "seleccion_variables.csv"
    if p.exists():
        s = pd.read_csv(p)
        ok = {"QUEDA", "REVISAR_FUGA"} if incluir_revisar else {"QUEDA"}
        vs = [v for v in s[s.decision.isin(ok)].variable if v in df.columns]
    else:
        vs = [c for c in df.columns if c not in META]
    if C.SEGMENTO and C.SEGMENTO in df.columns and C.SEGMENTO not in vs:
        vs.append(C.SEGMENTO)  # el segmento siempre entra (el modelo global debe poder distinguirlo)
    return vs


def tipificar(train, otros, vs):
    """Texto -> category con las MISMAS categorías en train y en el resto (si no, LightGBM las
    codifica distinto y el modelo se rompe en silencio)."""
    cats = [v for v in vs if not pd.api.types.is_numeric_dtype(train[v])]
    for v in cats:
        niveles = train[v].astype("string").dropna().unique().tolist()
        train[v] = pd.Categorical(train[v].astype("string"), categories=niveles)
        for o in otros:
            if o is not None and v in o:
                o[v] = pd.Categorical(o[v].astype("string"), categories=niveles)
    return cats


def cargar():
    base = leer_ordenado(C.OUT_DIR / "tabla_modelo.parquet")   # mismo orden = mismos pliegues = mismo Gini
    t1 = C.OUT_DIR / "tabla_modelo_t1.parquet"
    if C.EVALUAR:
        from pipeline.db import conectar
        con = conectar()
        if C.EVALUAR.get("archivo"):  # train y test unidos: el origen está en la columna _archivo del bronze
            ids = con.execute(f"""SELECT DISTINCT idn("{C.EVALUAR['id']}") FROM '{(C.WORK_DIR / "bronze" / f"{C.EVALUAR['tabla']}.parquet").as_posix()}'
                                  WHERE _archivo = '{C.EVALUAR['archivo']}'""").fetchdf().iloc[:, 0].astype(str)
        else:
            ids = pd.read_parquet(C.WORK_DIR / "silver" / f"{C.EVALUAR['tabla']}.parquet")[C.EVALUAR["id"]].astype(str)
        score = base[base.id.isin(ids)].copy()
        train = base[~base.id.isin(ids) & base.target.notna()].copy()
        modo = "lista de evaluación del banco"
    elif t1.exists():
        train, score = leer_ordenado(t1), base.copy()
        modo = f"fuera de tiempo: entrena corte {train.fecha_corte.iloc[0]}, puntúa corte {score.fecha_corte.iloc[0]}"
    else:
        train, score = base.copy(), None
        modo = "validación cruzada sobre una sola tabla"
    tiene_examen = score is not None and "target" in score and score.target.nunique() > 1
    vs = variables(train)
    cats = tipificar(train, [score], vs)
    return dict(train=train.reset_index(drop=True),
                score=None if score is None else score.reset_index(drop=True),
                vars=vs, cats=cats, modo=modo, examen=tiene_examen)


def pliegues(y, k=5, semilla=42):
    """Estratificado: cada pliegue conserva la tasa de positivos (crítico con desbalance:
    un pliegue con 0 positivos no mide nada)."""
    from sklearn.model_selection import StratifiedKFold
    return list(StratifiedKFold(k, shuffle=True, random_state=semilla).split(np.zeros(len(y)), y))
