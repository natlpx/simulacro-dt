"""
¿UNO O VARIOS MODELOS? y EL MONTO.

Por qué un equipo termina con "6 modelos": casi nunca es un ensamble de 6 algoritmos por gusto.
Es la DESCOMPOSICIÓN de la decisión en preguntas distintas, cada una con su modelo:
    caso 2025 (canal óptimo):  P(acepta | llamada), P(acepta | SMS), P(acepta | correo),
                               P(acepta | app), monto esperado, momento -> ~6 modelos
    caso factoring:            P(convierte | con lead), P(convierte | sin lead) (habilitar),
                               E[monto | convierte] -> 2 a 4 modelos
La data "se presta" cuando: (a) hay sub-poblaciones que se comportan distinto, (b) cada una
tiene suficientes positivos (≥200 aprox.), y (c) la decisión necesita varias cantidades
(probabilidad Y monto, o una probabilidad por canal).
Este módulo NO asume que separar es mejor: entrena global y separado, y gana el que mide más
en cada segmento. Si el global gana, se usa 1 modelo y se explica por qué.
"""
import numpy as np
import pandas as pd

import config as C
from pipeline.modelado import metricas as M
from pipeline.modelado.candidatos import fit_lgbm, oof
from pipeline.modelado.datos import pliegues


def familia_de(elegido):
    """Qué tipo de modelo se compara por segmento: el del modelo elegido."""
    return "logistica" if elegido in ("logistica", "regla_1var", "regla_top3") else "lgbm"


def comparar_segmentos(D, preds, params=None, elegido="lgbm"):
    """Global vs uno por segmento, DENTRO de cada segmento y con la MISMA familia que el elegido.

    Antes solo se probaba LightGBM. Pero el experimento A de docs/MODELADO.md mostró que separar
    le sirve sobre todo a la LOGÍSTICA (0.15 -> 0.63 cuando un efecto cambia de signo), porque un
    modelo lineal global no puede representar esa interacción y LightGBM sí. Ahora se comparan
    ambas familias; decide la del modelo elegido y la otra queda como referencia en la tabla.
    Devuelve la tabla y la lista de segmentos donde gana 'separado' (se aplican en la predicción final)."""
    from pipeline.modelado.candidatos import fit_logistica
    seg = C.SEGMENTO
    tr = D["train"]
    if not seg or seg not in tr:
        return None, []
    fam = familia_de(elegido)
    vs = [v for v in D["vars"] if v != seg]
    y = tr["target"].astype(int)
    s = tr[seg].astype("string").fillna("NA")
    ajustes = {"lgbm": (fit_lgbm, dict(params=params)), "logistica": (fit_logistica, {})}
    filas, ganan = [], []
    for g in s.unique():
        m = (s == g).to_numpy(dtype=bool)
        yg = y[m].reset_index(drop=True)
        fila = dict(segmento=g, familia=fam, n=int(m.sum()), positivos=int(yg.sum()), tasa=float(yg.mean()))
        if yg.sum() >= 30 and (len(yg) - yg.sum()) >= 30:
            Xg = tr.loc[m, vs].reset_index(drop=True)
            fg = pliegues(yg)
            for f, (fn, kw) in ajustes.items():
                fila[f"gini_global_{f}"] = M.gini(yg, preds[f][m])
                fila[f"gini_separado_{f}"] = M.gini(yg, oof(fn, Xg, yg, fg, **kw))
            fila["gini_global"], fila["gini_separado"] = fila[f"gini_global_{fam}"], fila[f"gini_separado_{fam}"]
            if fila["gini_separado"] > fila["gini_global"] + 0.005:
                fila["gana"] = "separado"
                ganan.append(g)
            else:
                fila["gana"] = "global"
        else:
            fila.update(gini_global=M.gini(yg, preds[fam][m]) if 0 < yg.sum() < len(yg) else np.nan,
                        gini_separado=np.nan, gana="global (pocos positivos)")
        filas.append(fila)
        print(f"  segmento {g} [{fam}]: n={fila['n']:,} tasa={fila['tasa']:.2%}  global {fila['gini_global']:.4f} vs "
              f"separado {fila.get('gini_separado', float('nan')):.4f} -> {fila['gana']}"
              + (f"   (ref. otra familia: global {fila.get('gini_global_' + ('lgbm' if fam == 'logistica' else 'logistica'), float('nan')):.4f}"
                 f" / separado {fila.get('gini_separado_' + ('lgbm' if fam == 'logistica' else 'logistica'), float('nan')):.4f})"
                 if 'gini_global_lgbm' in fila else ""))
    t = pd.DataFrame(filas)
    t["n_modelos_recomendado"] = 1 + len(ganan) - int(len(ganan) == len(t))
    return t, ganan


def predecir_por_segmento(D, destino, prob, ganan, elegido, params=None):
    """Aplica en la PREDICCIÓN FINAL los modelos por segmento que ganaron (antes se medían y se
    descartaban: la entrega siempre usaba el global). Entrena con el train del segmento y puntúa
    solo las filas de ese segmento; el resto conserva la probabilidad del modelo global."""
    from pipeline.modelado.candidatos import fit_logistica
    if not ganan:
        return prob
    seg, tr, vs = C.SEGMENTO, D["train"], [v for v in D["vars"] if v != C.SEGMENTO]
    fam = familia_de(elegido)
    p = np.asarray(prob, dtype=float).copy()
    s_tr = tr[seg].astype("string").fillna("NA")
    s_de = destino[seg].astype("string").fillna("NA").to_numpy()
    for g in ganan:
        mt, md = (s_tr == g).to_numpy(), (s_de == g)
        if md.sum() == 0:
            continue
        Xg, yg = tr.loc[mt, vs].reset_index(drop=True), tr.loc[mt, "target"].astype(int).reset_index(drop=True)
        Xd = destino.loc[md, vs].reset_index(drop=True)
        p[md] = fit_logistica(Xg, yg, Xd) if fam == "logistica" else fit_lgbm(Xg, yg, Xd, params=params)
        print(f"  segmento {g}: predicción final con modelo PROPIO ({fam}) en {int(md.sum()):,} filas")
    return p


def dos_partes(D, p_conv, params=None):
    """E[monto] = P(convierte) × E[monto | convierte].
    Parte 2: LightGBM sobre log1p(monto) SOLO en quienes convirtieron (OOF).
    Al volver de log se multiplica por el factor de Duan (smearing): exp(log) subestima la media.
    Se compara con una regresión directa sobre todos (Tweedie, que tolera muchos ceros)."""
    tr = D["train"]
    if "target_monto" not in tr:
        return None, None
    vs, y, m = D["vars"], tr["target"].astype(int), tr["target_monto"].astype(float)
    pos = (m > 0).values
    Xp = tr.loc[pos, vs].reset_index(drop=True)
    lp = np.log1p(m[pos].reset_index(drop=True))
    folds = list(pliegues((lp > lp.median()).astype(int)))
    pred_log = np.zeros(pos.sum())
    for a, b in folds:
        pred_log[b] = fit_lgbm(Xp.iloc[a], lp.iloc[a], Xp.iloc[b], params=params, monto=True)
    duan = float(np.mean(np.exp(lp - pred_log)))
    cond = np.full(len(tr), np.nan)
    cond[pos] = np.expm1(pred_log) * duan
    # para TODOS (incluidos no convertidos) se necesita E[monto|convierte]: modelo final sobre positivos
    _, mod = fit_lgbm(Xp, lp, tr[vs].iloc[:5], params=params, monto=True, devolver=True)
    cond_todos = np.expm1(mod.predict(tr[vs])) * duan
    cond_todos[pos] = cond[pos]          # para positivos usar la OOF (honesta)
    esperado = p_conv * cond_todos

    params_tw = {**(params or {}), "objective": "tweedie", "tweedie_variance_power": 1.5}
    directo = oof(fit_lgbm, tr[vs], m, pliegues(y), params=params_tw, monto=True)
    from scipy.stats import spearmanr
    r = dict(r2_dos_partes=M.r2(m, esperado), r2_directo_tweedie=M.r2(m, directo),
             spearman_dos_partes=float(spearmanr(m, esperado).statistic),
             spearman_directo=float(spearmanr(m, directo).statistic),
             r2_condicional_log=M.r2(lp, pred_log), factor_duan=duan,
             monto_real_total=float(m.sum()), monto_esperado_total=float(esperado.sum()))
    # R² en soles sobre TODOS: es lo que pediría un "R²" oficial. Spearman: ¿ordena bien los montos?
    # R² condicional (log, solo convertidos): ¿hay señal en el TAMAÑO? Si ~0, el monto solo aporta su promedio.
    r["gana"] = "dos_partes" if r["r2_dos_partes"] >= r["r2_directo_tweedie"] else "directo_tweedie"
    print(f"  monto: R² soles dos partes {r['r2_dos_partes']:.3f} vs directo {r['r2_directo_tweedie']:.3f} · "
          f"Spearman {r['spearman_dos_partes']:.3f} vs {r['spearman_directo']:.3f} · "
          f"R² condicional (log, convertidos) {r['r2_condicional_log']:.3f}")
    return r, mod
