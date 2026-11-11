"""
PRIORIZAR CON CAPACIDAD: a quién contactar si solo se puede llamar al k% de la base.

  valor esperado = P(convierte) × E[monto | convierte]   (o solo P si no hay monto)

Dos métodos, y cuándo usar cada uno:
  voraz por zona   ordenar por valor y llenar el cupo de cada zona. Es ÓPTIMO cuando hay una sola
                   restricción por grupo (cada empresa pertenece a una zona y cada zona tiene su cupo).
  PuLP + HiGHS     programación entera: maximizar valor sujeto a VARIAS restricciones que se cruzan
                   (cupo por zona Y mínimo de Pyme Y tope por ejecutivo Y presupuesto por canal).
                   Cuando las restricciones se cruzan, ordenar y cortar deja de ser óptimo.
Se corren los dos: si dan lo mismo, se presenta el voraz (más fácil de explicar).
"""
import numpy as np
import pandas as pd

import config as C


def voraz(df, valor="valor_esperado", zona=None, capacidad=None, cupos=None):
    cap = capacidad if capacidad is not None else C.CAPACIDAD
    n_total = int(cap * len(df)) if cap < 1 else int(cap)
    df = df.sort_values(valor, ascending=False).copy()
    df["priorizado"] = 0
    if zona and zona in df and cupos:
        cupos = _normalizar_cupos(df, zona, cupos)
        tot = sum(cupos.values())
        for z, pct in cupos.items():
            k = int(round(n_total * pct / tot))
            idx = df.index[df[zona].astype("string") == z][:k]
            df.loc[idx, "priorizado"] = 1
        # zonas fuera de la lista (DESCONOCIDA, NULL) no consumen cupo: se reporta
        resto = n_total - int(df.priorizado.sum())
        if resto > 0:
            print(f"  ⚠ voraz: faltan {resto} empresas para llegar a la capacidad (zona sin empresas suficientes o "
                  f"fuera de CUPOS_ZONA): se completan con las de mayor valor SIN respetar cupos")
        if resto > 0:
            idx = df.index[df.priorizado == 0][:resto]
            df.loc[idx, "priorizado"] = 1
    else:
        df.loc[df.index[:n_total], "priorizado"] = 1
    return df


def _normalizar_cupos(df, zona, cupos):
    """Los datos llegan en MAYÚSCULAS (txt() de la limpieza); 'Lima' en la config no calzaría con 'LIMA'
    y el cupo se ignoraría sin aviso."""
    import unicodedata
    norm = lambda z: unicodedata.normalize("NFKD", str(z)).encode("ascii", "ignore").decode().strip().upper()
    c = {norm(z): v for z, v in cupos.items()}
    presentes = set(df[zona].astype("string").dropna().unique())
    faltan = [z for z in c if z not in presentes]
    if faltan:
        print(f"  ⚠ CUPOS_ZONA: {faltan} no existen en {zona} (valores reales: {sorted(presentes)[:10]})")
    return c


def entero(df, valor="valor_esperado", zona=None, capacidad=None, cupos=None, restricciones_extra=None):
    """restricciones_extra: lista de (columna_binaria, minimo_fraccion) p.ej. [("es_pyme", 0.6)]."""
    import pulp
    cap = capacidad if capacidad is not None else C.CAPACIDAD
    n_total = int(cap * len(df)) if cap < 1 else int(cap)
    cand = df.nlargest(min(len(df), n_total * 20), valor).copy()   # podar: el óptimo está arriba
    prob = pulp.LpProblem("priorizar", pulp.LpMaximize)
    # PuLP 4 crea variables desde el problema; PuLP 2 con LpVariable(..., cat=)
    nueva = (lambda n: prob.add_variable(n, cat=pulp.LpBinary)) if hasattr(prob, "add_variable") \
        else (lambda n: pulp.LpVariable(n, cat="Binary"))
    x = {i: nueva(f"x_{k}") for k, i in enumerate(cand.index)}
    prob += pulp.lpSum(x[i] * float(cand.at[i, valor]) for i in cand.index)
    prob += pulp.lpSum(x.values()) <= n_total
    if zona and cupos:
        cupos = _normalizar_cupos(df, zona, cupos)
        tot = sum(cupos.values())
        for z, pct in cupos.items():
            ids = cand.index[cand[zona].astype("string") == z]
            prob += pulp.lpSum(x[i] for i in ids) <= int(round(n_total * pct / tot))
    for col, minimo in (restricciones_extra or []):
        prob += pulp.lpSum(x[i] * float(cand.at[i, col]) for i in cand.index) >= minimo * n_total
    res = prob.solve(pulp.HiGHS(msg=False))
    df = df.copy()
    df["priorizado"] = 0
    df.loc[[i for i in cand.index if (x[i].value() or 0) > 0.5], "priorizado"] = 1
    if hasattr(prob, "status"):                       # PuLP 2.x
        estado = pulp.LpStatus[prob.status]
    else:                                             # PuLP 4.x: solve() devuelve un resultado
        estado = getattr(res, "status", None)
        estado = str(estado) if estado is not None else str(res).split("status:")[-1].split("\n")[0].strip()
    if estado in ("1", "Optimal") or "ptimal" in estado:
        estado = "Optimal"
    return df, estado
