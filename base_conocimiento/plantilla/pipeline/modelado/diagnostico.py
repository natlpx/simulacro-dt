"""
DIAGNÓSTICO: "¿qué uso SEGÚN LA DATA?" — mide la tabla y devuelve recomendaciones con su porqué.

No decide por moda ni por lo que usó otro equipo. Cada regla se apoya en una medida:

  medida                         -> qué decide
  tipo de target (0/1, monto,    -> clasificación, regresión, dos partes, multiclase
    clases, conteo)
  tasa de positivos              -> nivel de desbalance -> métrica (Gini vs AUC-PR) y si reponderar
  positivos por variable (EPV)   -> si hay pocos positivos por variable, modelo simple/regularizado
  n de filas                     -> si un árbol potente tiene con qué aprender
  % de montos en cero            -> si el monto necesita modelo de DOS PARTES
  diferencia entre segmentos     -> si vale la pena un modelo por segmento (¿1 modelo o varios?)
  PSI train vs puntuación        -> si el mundo cambió entre cortes (validar fuera de tiempo)

Las recomendaciones son HIPÓTESIS: el comparador de modelos las confirma o las descarta midiendo.
"""
import numpy as np
import pandas as pd

import config as C
from pipeline.seleccion import psi


def diagnosticar(D):
    tr, vs = D["train"], D["vars"]
    y = tr["target"]
    recs, med = [], {}

    # ---------------- tipo de objetivo
    nval = y.nunique()
    if nval == 2:
        tipo = "binario"
    elif nval <= 10 and (y.dropna() % 1 == 0).all():
        tipo = "multiclase/conteo"
    else:
        tipo = "continuo"
    med["tipo_target"] = tipo
    med["filas_train"] = len(tr)
    med["variables"] = len(vs)

    if tipo == "binario":
        tasa = float(y.mean()); npos = int(y.sum())
        med.update(tasa_positivos=round(tasa, 4), positivos=npos, epv=round(npos / max(len(vs), 1), 1))
        if tasa < 0.01:
            nivel = "SEVERO"
            recs.append(("Desbalance severo (<1%)",
                         "Reportar AUC-PR y captura@k además del Gini: con 1% de positivos el Gini se ve alto aunque el "
                         "top tenga pocos aciertos. Probar class weights; NO submuestrear sin corregir probabilidades."))
        elif tasa < 0.10:
            nivel = "MODERADO"
            recs.append(("Desbalance moderado (1-10%)",
                         "Validación ESTRATIFICADA. El Gini no cambia con reponderar: solo reponderar si la métrica oficial "
                         "es de clasificación con umbral (F1, recall). Si se multiplica prob × monto, mantener la probabilidad calibrada."))
        else:
            nivel = "LEVE"
            recs.append(("Desbalance leve (>10%)", "No hace falta tratamiento especial: modelo normal + estratificar."))
        med["desbalance"] = nivel
        epv = npos / max(len(vs), 1)
        if epv < 10:
            recs.append((f"Pocos positivos por variable (EPV={epv:.1f} < 10)",
                         "Riesgo de sobreajuste: preferir logística regularizada o LightGBM con min_child_samples alto "
                         "y menos variables (subir el umbral del embudo)."))
        else:
            recs.append((f"EPV = {epv:.0f}", "Hay suficientes positivos por variable para un modelo de árboles."))

    if len(tr) < 3000:
        recs.append(("Pocas filas (<3k)", "Árboles potentes sobreajustan: priorizar regla de negocio y logística; "
                     "LightGBM solo con hojas pequeñas y validación repetida."))
    elif len(tr) > 2_000_000:
        recs.append(("Muchas filas (>2M)", "Entrenar en una muestra estratificada para elegir el modelo; el final, con todo."))
    else:
        recs.append((f"{len(tr):,} filas", "Tamaño cómodo: comparar regla vs logística vs LightGBM con validación cruzada."))

    # ---------------- monto
    if "target_monto" in tr:
        m = tr["target_monto"]
        ceros = float((m <= 0).mean())
        med["pct_monto_cero"] = round(ceros, 3)
        if ceros > 0.5:
            recs.append((f"Monto con {ceros:.0%} de ceros",
                         "Modelo de DOS PARTES: P(convierte) × E[monto | convierte]. Un solo regresor aprende a predecir "
                         "'casi cero' para todos. La parte 2 en log (los montos tienen cola larga)."))
        else:
            recs.append(("Monto mayormente positivo", "Una regresión directa (en log) es suficiente."))
        pos = m[m > 0]
        if len(pos) > 10:
            med["monto_asimetria"] = round(float(pos.skew()), 2)

    # ---------------- segmentos: ¿uno o varios modelos?
    if C.SEGMENTO and C.SEGMENTO in tr:
        g = tr.groupby(tr[C.SEGMENTO].astype("string").fillna("NA"))["target"].agg(["mean", "size", "sum"])
        med["segmentos"] = {k: dict(tasa=round(v["mean"], 4), n=int(v["size"]), pos=int(v["sum"])) for k, v in g.iterrows()}
        razon = g["mean"].max() / max(g["mean"].min(), 1e-9)
        min_pos = int(g["sum"].min())
        # además de la TASA, mirar la RELACIÓN: ¿alguna variable importante invierte su efecto?
        from pipeline.seleccion import auc_rapido
        sg = tr[C.SEGMENTO].astype("string").fillna("NA")
        num = [v for v in vs if v != C.SEGMENTO and pd.api.types.is_numeric_dtype(tr[v])]
        top = sorted(num, key=lambda v: -abs(2 * auc_rapido(tr[v], y) - 1))[:15]
        efecto_seg = {}
        def ee_gini(n1, n0):  # error estándar del Gini bajo azar (Hanley-McNeil): evita "inversiones" por ruido
            return 2 * np.sqrt((n1 + n0 + 1) / (12 * max(n1, 1) * max(n0, 1)))
        for v in num[:80]:
            e, umbral = {}, {}
            for k in g.index:
                n1 = int(g.loc[k, "sum"]); n0 = int(g.loc[k, "size"]) - n1
                if n1 >= 30:
                    e[k] = 2 * auc_rapido(tr.loc[sg == k, v], y[sg == k]) - 1
                    umbral[k] = max(0.05, 2.5 * ee_gini(n1, n0))
            sube = [k for k in e if e[k] > umbral[k]]
            baja = [k for k in e if e[k] < -umbral[k]]
            if sube and baja:
                efecto_seg[v] = {k: round(x, 3) for k, x in e.items()}
        med["efectos_invertidos"] = efecto_seg
        if efecto_seg:
            recs.append((f"{len(efecto_seg)} variable(s) cambian de SIGNO entre segmentos ({', '.join(list(efecto_seg)[:3])})",
                         "Interacción fuerte con el segmento. Un modelo LINEAL global no la puede representar: usar árboles "
                         "(que la aprenden solos) o un modelo lineal POR segmento. Se comparan ambos."))
        if razon > 3 and min_pos >= 200:
            recs.append((f"Segmentos muy distintos (tasa ×{razon:.1f}) y con datos ({min_pos} positivos mínimo)",
                         "CANDIDATO a un modelo por segmento: el comparador probará global vs separados y se queda con el "
                         "que gane en CADA segmento. Así se llega a 'varios modelos' por evidencia, no por costumbre."))
        elif not efecto_seg:
            recs.append(("Segmentos con tasa y relaciones parecidas (o pocos positivos)",
                         "Un modelo GLOBAL con el segmento como variable. Separar dividiría los datos sin ganancia."))

    # ---------------- estabilidad entre cortes
    sc = D.get("score")
    if sc is not None:
        num = [v for v in vs if pd.api.types.is_numeric_dtype(tr[v])][:60]
        ps = pd.Series({v: psi(tr[v], sc[v]) for v in num}).sort_values(ascending=False)
        med["psi_max"] = round(float(ps.iloc[0]), 3) if len(ps) else 0
        med["vars_inestables"] = ps[ps > 0.25].index.tolist()[:10]
        if len(ps) and ps.iloc[0] > 0.25:
            recs.append(("Variables que cambiaron entre cortes", f"{len(med['vars_inestables'])} con PSI>0.25: revisar si "
                         "son estacionales o cambios de sistema; en duda, sacarlas."))
    recs.append(("Modo de validación", D["modo"]))
    return med, recs
