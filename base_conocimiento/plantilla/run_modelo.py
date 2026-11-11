"""
PIPELINE DE MODELADO (después de run_pipeline.py).

  python run_modelo.py                    # diagnóstico + comparación + segmentos + monto + priorización
  python run_modelo.py --optuna 120       # además busca hiperparámetros por 120 segundos
  python run_modelo.py --rapido           # sin permutación ni segmentos (para iterar)

Orden (y por qué en este orden):
  1. diagnóstico      la data dice qué probar (no la costumbre)
  2. candidatos       de "sin modelo" a LightGBM, misma validación OOF -> comparación justa
  3. hiperparámetros  solo si sobra tiempo; se mide cuánto ganó y qué perilla importó
  4. segmentos        ¿1 modelo o varios? se decide midiendo en cada segmento
  5. importancia      gain vs permutación vs SHAP + estabilidad -> qué variables importan y por qué
  6. monto            dos partes vs directo, se queda el que mide más
  7. examen           si el corte actual trae target, nota honesta fuera de tiempo
  8. priorización     valor esperado + capacidad por zona (voraz y PuLP)
Salidas en salidas/modelo/ + reporte_modelo.html
"""
import argparse
import json
import sys

sys.dont_write_bytecode = True   # sin __pycache__: no ensucia base_conocimiento/ ni trabajo/
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
# --config otra_config.py : usar otra configuración (otro target, otro corte, otro caso) sin editar config.py
if "--config" in sys.argv:
    import importlib.util
    _ruta = sys.argv[sys.argv.index("--config") + 1]
    _spec = importlib.util.spec_from_file_location("config", _ruta)
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules["config"] = _mod
    _spec.loader.exec_module(_mod)
import config as C  # noqa: E402
from pipeline.modelado import afinamiento, candidatos, datos, diagnostico, importancia  # noqa: E402
from pipeline.modelado import metricas as M  # noqa: E402
from pipeline.modelado import priorizar, reporte_modelo, segmentos_monto  # noqa: E402

SIMPLICIDAD = ["regla_1var", "regla_top3", "logistica", "lgbm", "xgb", "catboost", "lgbm_pesos", "lgbm_submuestra",
               "lgbm_afinado", "ensamble"]   # a igual Gini (±0.005) gana el de más a la izquierda


def elegir(tabla, tolerancia=0.005):
    """El de mayor Gini... salvo que uno MÁS SIMPLE esté a menos de `tolerancia`: entonces el simple
    (parsimonia: se explica mejor, se rompe menos y el jurado lo entiende)."""
    t = tabla.dropna(subset=["gini"]).copy()
    mejor = t.gini.max()
    t["orden"] = t.modelo.map({m: i for i, m in enumerate(SIMPLICIDAD)}).fillna(99)
    ok = t[t.gini >= mejor - tolerancia].sort_values("orden")
    return ok.modelo.iloc[0], float(mejor)


def ajustar_final(nombre, D, params):
    tr, vs = D["train"], D["vars"]
    X, y = tr[vs], tr["target"].astype(int)
    destino = D["score"] if D["score"] is not None else tr
    Xs = destino[vs]
    if nombre == "logistica":
        return candidatos.fit_logistica(X, y, Xs), None
    if nombre.startswith("regla"):
        return candidatos.regla(X, y, Xs, k=1 if nombre == "regla_1var" else 3), None
    if nombre == "xgb":
        return candidatos.fit_xgb(X, y, Xs, devolver=True)
    if nombre == "catboost":
        return candidatos.fit_catboost(X, y, Xs, devolver=True)
    kw = dict(params=params)
    if nombre == "lgbm_pesos":
        kw["peso"] = True
    if nombre == "lgbm_submuestra":
        kw["submuestra"] = 4
    p, mod = candidatos.fit_lgbm(X, y, Xs, devolver=True, **kw)
    if nombre == "ensamble":
        p = (candidatos._rank(p) + candidatos._rank(candidatos.fit_logistica(X, y, Xs))) / 2
    return p, mod


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--optuna", type=int, default=0, help="segundos de búsqueda de hiperparámetros (0 = no)")
    ap.add_argument("--rapido", action="store_true")
    ap.add_argument("--config", default=None)
    a = ap.parse_args()
    from pipeline import plataforma
    print(f"{plataforma.NOMBRE_SISTEMA} · Python {sys.version.split()[0]} · RAM {getattr(C, 'RAM_GB', 0):.0f} GB · DuckDB memory_limit={C.MEMORY_LIMIT} threads={C.THREADS}")
    out = C.OUT_DIR / "modelo"
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    R = {}

    print("\n== 1 · DIAGNÓSTICO ==")
    D = datos.cargar()
    med, recs = diagnostico.diagnosticar(D)
    for t, txt in recs:
        print(f"  • {t}: {txt}")
    R["diagnostico"] = dict(medidas=med, recomendaciones=recs, modo=D["modo"], n_vars=len(D["vars"]))

    print("\n== 2 · CANDIDATOS (validación cruzada OOF, 5 pliegues estratificados) ==")
    tabla, preds, folds = candidatos.comparar(D, extra=not a.rapido)

    params = None
    if a.optuna:
        print(f"\n== 3 · HIPERPARÁMETROS (Optuna, {a.optuna}s) ==")
        H = afinamiento.buscar(D, segundos=a.optuna)
        params = H["mejores"]
        y = D["train"]["target"].astype(int)
        preds["lgbm_afinado"] = candidatos.oof(candidatos.fit_lgbm, D["train"][D["vars"]], y, folds, params=params)
        tabla = pd.concat([tabla, pd.DataFrame([dict(modelo="lgbm_afinado", **M.resumen_clasif(y, preds["lgbm_afinado"]))])])
        H["pruebas"].to_csv(out / "hiperparametros_pruebas.csv", index=False)
        R["hiper"] = {k: v for k, v in H.items() if k != "pruebas"}
        R["hiper_pruebas"] = H["pruebas"]

    elegido, g = elegir(tabla)
    print(f"\n  ELEGIDO: {elegido} (Gini OOF {tabla.set_index('modelo').gini[elegido]:.4f}; mejor {g:.4f})")
    tabla.to_csv(out / "comparacion_modelos.csv", index=False)
    R["comparacion"], R["elegido"] = tabla, elegido
    y = D["train"]["target"].astype(int)
    base = "lgbm_afinado" if "lgbm_afinado" in preds else "lgbm"
    R["deciles"] = M.deciles(y, preds[elegido])
    R["calibracion"] = {k: M.calibracion(y, preds[k]) for k in ["logistica", "lgbm", "lgbm_pesos", "lgbm_submuestra"]}

    ganan_seg = []
    if not a.rapido:
        print("\n== 4 · ¿UNO O VARIOS MODELOS? (segmentos) ==")
        seg, ganan_seg = segmentos_monto.comparar_segmentos(D, preds, params, elegido)
        if seg is not None:
            seg.to_csv(out / "segmentos.csv", index=False)
            R["segmentos"] = seg

    print("\n== 5 · IMPORTANCIA DE VARIABLES ==")
    tr, vs = D["train"], D["vars"]
    if D["examen"]:
        Xva, yva = D["score"][vs], D["score"]["target"].astype(int)
        _, mod = candidatos.fit_lgbm(tr[vs], y, Xva, params=params, devolver=True)
        donde = "corte actual (fuera de tiempo)"
    else:
        a_, b_ = folds[0]
        _, mod = candidatos.fit_lgbm(tr[vs].iloc[a_], y.iloc[a_], tr[vs].iloc[b_], params=params, devolver=True)
        Xva, yva = tr[vs].iloc[b_], y.iloc[b_]
        donde = "pliegue de validación"
    fold_models = [candidatos.fit_lgbm(tr[vs].iloc[i], y.iloc[i], tr[vs].iloc[j][:5], params=params, devolver=True)[1]
                   for i, j in folds[:3]] if not a.rapido else None
    imp, contrib = importancia.calcular(mod, Xva, yva, fold_models, top_perm=0 if a.rapido else 30)
    imp.to_csv(out / "importancia_variables.csv", index=False)
    print(imp.head(12)[["variable", "gain", "permutacion_gini", "shap_medio", "sentido"]].to_string(index=False))
    R["importancia"], R["importancia_donde"] = imp, donde
    # explicación de UN caso (el mejor puntuado): para responder "¿por qué esta empresa?"
    i = int(np.argmax(mod.predict_proba(Xva)[:, 1]))
    def _fmt(v):
        try:
            return f"{float(v):,.2f}".rstrip("0").rstrip(".")
        except (TypeError, ValueError):
            return str(v)
    caso = pd.DataFrame({"variable": vs, "valor": [_fmt(v) for v in Xva.iloc[i].values], "aporte": contrib[i]})
    R["caso"] = caso.reindex(caso.aporte.abs().sort_values(ascending=False).index).head(10)
    R["caso_modelo"] = "LightGBM (modelo de referencia)"
    # Si el ENTREGADO es la logística, se explica la logística (coeficientes + aporte exacto por caso):
    # en la presentación no se debe mostrar el SHAP de un modelo que no se entregó.
    if elegido == "logistica":
        coef, caso_log = candidatos.explicar_logistica(tr[vs], y, Xva)
        coef.to_csv(out / "coeficientes_logistica.csv", index=False)
        R["coef_logistica"] = coef
        if caso_log is not None:
            R["caso"], R["caso_modelo"] = caso_log, "logística (modelo elegido)"
        print("\n  Modelo elegido = logística -> coeficientes estandarizados (los que se explican al jurado):")
        print(coef.head(10)[["variable", "coef", "odds_ratio", "sentido"]].round(3).to_string(index=False))

    print("\n== 6 · MONTO ==")
    mon, mod_monto = segmentos_monto.dos_partes(D, preds[base], params)
    R["monto"] = mon

    print("\n== 7 · PREDICCIÓN FINAL ==")
    p_final, mod_final = ajustar_final(elegido, D, params)
    destino = (D["score"] if D["score"] is not None else D["train"]).copy()
    destino["prob"] = p_final if D["score"] is not None else preds[elegido]
    if ganan_seg and D["score"] is not None:
        if elegido in ("logistica", "lgbm", "lgbm_afinado"):
            destino["prob"] = segmentos_monto.predecir_por_segmento(D, destino, destino["prob"], ganan_seg, elegido, params)
        else:
            print(f"  (ganó 'separado' en {ganan_seg}, pero el elegido es {elegido}: no se mezclan escalas; se usa el global)")
    if mod_monto is not None:
        lp_pred = mod_monto.predict(destino[vs])
        destino["monto_si_convierte"] = np.expm1(lp_pred) * mon["factor_duan"]
        prob_cal = destino["prob"]
        if elegido.startswith(("regla", "ensamble")):
            # una regla o un promedio de rankings NO es probabilidad: se calibra con isotónica
            # aprendida sobre las predicciones OOF (percentil -> tasa real observada)
            from sklearn.isotonic import IsotonicRegression
            iso = IsotonicRegression(out_of_bounds="clip").fit(candidatos._rank(preds[elegido]), y)
            prob_cal = iso.predict(candidatos._rank(destino["prob"]))
        destino["prob_calibrada"] = prob_cal
        destino["valor_esperado"] = prob_cal * destino["monto_si_convierte"]
    else:
        destino["valor_esperado"] = destino["prob"]
    if D["examen"]:
        R["examen"] = M.resumen_clasif(destino["target"], destino["prob"])
        R["examen_deciles"] = M.deciles(destino["target"], destino["prob"])
        print(f"  EXAMEN ({D['modo']}): Gini {R['examen']['gini']:.4f} · lift D1 {R['examen']['lift_d1']:.2f}x "
              f"(OOF en train fue {tabla.set_index('modelo').gini[elegido]:.4f})")

    print("\n== 8 · PRIORIZACIÓN ==")
    zona = C.COLUMNA_ZONA if C.COLUMNA_ZONA in destino else None
    pv = priorizar.voraz(destino, zona=zona, cupos=C.CUPOS_ZONA)
    pe, estado = priorizar.entero(destino, zona=zona, cupos=C.CUPOS_ZONA)
    v1 = pv.loc[pv.priorizado == 1, "valor_esperado"].sum()
    v2 = pe.loc[pe.priorizado == 1, "valor_esperado"].sum()
    print(f"  voraz: {int(pv.priorizado.sum())} empresas, valor {v1:,.0f} · PuLP ({estado}): valor {v2:,.0f}  "
          f"-> {'iguales: usar voraz' if abs(v1 - v2) <= 1e-6 * max(v1, 1) else 'difieren: usar PuLP'}")
    R["prior"] = dict(voraz=v1, entero=v2, n=int(pv.priorizado.sum()), estado=estado)
    if zona:
        R["prior_zona"] = pv[pv.priorizado == 1].groupby(pv[zona].astype("string")).agg(
            empresas=("id", "size"), prob_media=("prob", "mean"), valor=("valor_esperado", "sum")).reset_index()
    if "target" in pv and D["examen"]:
        R["prior"]["conversion_priorizados"] = float(pv.loc[pv.priorizado == 1, "target"].mean())
        R["prior"]["conversion_base"] = float(pv["target"].mean())
    cols = ["id", "prob", "valor_esperado", "priorizado"] + [c for c in ["monto_si_convierte", zona] if c and c in pv]
    pv[cols].sort_values("valor_esperado", ascending=False).to_csv(out / "predicciones.csv", index=False)

    with open(out / "resumen.json", "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in R.items() if isinstance(v, (dict, str, float, int))}, f, ensure_ascii=False, indent=1, default=str)
    reporte_modelo.generar(R, out / "reporte_modelo.html")
    print(f"\nListo en {time.time() - t0:,.0f} s -> {out}")


if __name__ == "__main__":
    main()
