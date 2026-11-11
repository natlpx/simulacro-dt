"""
EXPERIMENTO: ¿cuándo cambia la decisión de modelado? Datos sintéticos controlados.

  Escenario A · segmentos OPUESTOS: en el segmento 1 la variable x1 sube la probabilidad,
                en el segmento 0 la BAJA. Un modelo global lineal no puede representarlo.
  Escenario B · igual que A pero con POCOS positivos en un segmento: separar ya no conviene.
  Escenario C · desbalance SEVERO (0.5%): el Gini se ve bien pero el AUC-PR cuenta otra historia.
  Escenario D · señal lineal pura con pocas filas: la logística le gana a LightGBM.

  python experimentos/escenarios_modelado.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config as C  # noqa: E402
from pipeline.modelado import candidatos, diagnostico, segmentos_monto  # noqa: E402

C.SEGMENTO = "seg"


def tabla(n, tasa_base, opuesto=True, frac_seg1=0.5, lineal=False, semilla=0):
    rng = np.random.default_rng(semilla)
    X = pd.DataFrame(rng.normal(size=(n, 8)), columns=[f"x{i}" for i in range(1, 9)])
    seg = (rng.random(n) < frac_seg1).astype(int)
    if lineal:
        z = 1.2 * X.x1 - 0.8 * X.x2 + 0.5 * X.x3
    else:
        signo = np.where(seg == 1, 1.0, -1.0) if opuesto else 1.0
        z = signo * 1.5 * X.x1 + 0.6 * X.x2 * X.x3 + 0.4 * X.x4
    b = np.log(tasa_base / (1 - tasa_base))
    y = (rng.random(n) < 1 / (1 + np.exp(-(b + z)))).astype(int)
    df = X.assign(seg=seg, target=y, id=np.arange(n).astype(str))
    vs = [c for c in df.columns if c.startswith("x")] + ["seg"]
    return dict(train=df, score=None, vars=vs, cats=[], modo="validación cruzada", examen=False)


def correr(nombre, D, segmentos=True):
    print(f"\n===== {nombre} =====")
    med, recs = diagnostico.diagnosticar(D)
    for t, txt in recs[:4]:
        print(f"  diag · {t}")
    t, preds, _ = candidatos.comparar(D)
    if segmentos:
        print("  -- si el elegido fuera LightGBM:")
        segmentos_monto.comparar_segmentos(D, preds, elegido="lgbm")
        print("  -- si el elegido fuera la logística:")
        segmentos_monto.comparar_segmentos(D, preds, elegido="logistica")
        # misma pregunta con LOGÍSTICA: global vs una por segmento
        from pipeline.modelado import metricas as M
        from pipeline.modelado.datos import pliegues
        tr, y = D["train"], D["train"].target
        p = np.zeros(len(tr))
        for g in tr.seg.unique():
            m = (tr.seg == g).values
            yg = y[m].reset_index(drop=True)
            if yg.sum() >= 30:
                p[m] = candidatos.oof(candidatos.fit_logistica, tr.loc[m, D["vars"]].reset_index(drop=True), yg, pliegues(yg))
        print(f"  logística global {M.gini(y, preds['logistica']):.4f} vs logística por segmento {M.gini(y, p):.4f}")


correr("A · segmentos opuestos, muchos datos", tabla(30000, 0.10, opuesto=True))
correr("B · segmentos opuestos, segmento 1 chico (3%)", tabla(30000, 0.10, opuesto=True, frac_seg1=0.03))
correr("C · desbalance severo (<1%)", tabla(80000, 0.0012, opuesto=False), segmentos=False)
correr("D · señal lineal, pocas filas (1.500)", tabla(1500, 0.15, lineal=True), segmentos=False)
