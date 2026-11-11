"""Reporte HTML del modelado (offline). Cada sección dice qué mirar."""
import html

import pandas as pd

from pipeline.monitor import AMARILLO, AQUA, AZUL, CRITICO, CSS, GRIS, NARANJA, _fig_html, _tabla


def generar(R, destino):
    import plotly.graph_objects as go
    P, primero = [], [True]

    def fig(f):
        h = _fig_html(f, primero[0]); primero[0] = False
        return h

    def sec(t, sub):
        P.append(f"<h2>{t}</h2><p class='sub'>{sub}</p>")

    # ---------------- diagnóstico
    d = R["diagnostico"]
    m = d["medidas"]
    k = [("filas de entrenamiento", f"{m.get('filas_train', 0):,}"), ("variables", f"{d['n_vars']}"),
         ("tasa de positivos", f"{m.get('tasa_positivos', 0):.2%}"), ("desbalance", m.get("desbalance", "-")),
         ("positivos por variable", f"{m.get('epv', '-')}"), ("modelo elegido", R["elegido"])]
    if "examen" in R:
        k.append(("Gini en el examen", f"{R['examen']['gini']:.3f}"))
    P.append("<div class='kpis'>" + "".join(f"<div class='kpi'><b>{v}</b><span>{t}</span></div>" for t, v in k) + "</div>")
    sec("Diagnóstico: qué dice la data", f"Modo de validación: {html.escape(d['modo'])}. Cada recomendación sale de una medida; el resto del reporte la confirma o la descarta.")
    P.append("<div class='tabla'><table><thead><tr><th>medida</th><th>recomendación y por qué</th></tr></thead><tbody>" +
             "".join(f"<tr><td><b>{html.escape(t)}</b></td><td>{html.escape(x)}</td></tr>" for t, x in d["recomendaciones"]) +
             "</tbody></table></div>")

    # ---------------- comparación
    t = R["comparacion"].copy()
    sec("Comparación de modelos (misma validación OOF)",
        "Las reglas son 'sin modelo' (línea base). Si un modelo más simple queda a menos de 0.005 de Gini del mejor, se elige el simple.")
    t = t.sort_values("gini")
    col = [NARANJA if mm == R["elegido"] else (GRIS if mm.startswith("regla") else AZUL) for mm in t.modelo]
    f = go.Figure(go.Bar(y=t.modelo, x=t.gini, orientation="h", marker_color=col,
                         customdata=t[["auc_pr", "lift_d1"]],
                         hovertemplate="%{y}<br>Gini %{x:.4f}<br>AUC-PR %{customdata[0]:.4f} · lift D1 %{customdata[1]:.2f}x<extra></extra>"))
    f.update_layout(height=120 + 34 * len(t), xaxis_title="Gini (OOF)", title="Naranja = elegido · gris = sin modelo")
    P.append(fig(f))
    P.append(_tabla(t.sort_values("gini", ascending=False).round(4)))

    # ---------------- desbalance y calibración
    tg = R["comparacion"].set_index("modelo")
    dif = {k: tg.gini.get(k, float("nan")) - tg.gini.get("lgbm", float("nan")) for k in ("lgbm_pesos", "lgbm_submuestra")}
    pm = {k: tg.prob_media.get(k, float("nan")) for k in ("lgbm", "lgbm_pesos", "lgbm_submuestra")}
    sec("Desbalance: ¿reponderar o no? (medido, no supuesto)",
        f"Gini contra lgbm sin tratamiento: con pesos {dif['lgbm_pesos']:+.4f}, con submuestreo {dif['lgbm_submuestra']:+.4f}. "
        f"Probabilidad media: sin tratamiento {pm['lgbm']:.3f}, con pesos {pm['lgbm_pesos']:.3f}, submuestreo corregido {pm['lgbm_submuestra']:.3f} "
        f"(real {tg.tasa_real.iloc[0]:.3f}). En teoría reponderar no cambia el orden; en la práctica puede bajarlo (el árbol "
        "se concentra en los positivos y el early stopping se desajusta). Por eso se mide. Puntos sobre la diagonal = probabilidad honesta.")
    f = go.Figure()
    for (nombre, c), color in zip(R["calibracion"].items(), [AZUL, AQUA, NARANJA, AMARILLO]):
        f.add_scatter(x=c.prob_media, y=c.tasa_real, mode="lines+markers", name=nombre, line=dict(color=color, width=2),
                      marker=dict(size=8), hovertemplate=nombre + "<br>predicha %{x:.3f}<br>real %{y:.3f}<extra></extra>")
    mx = max(max(c.prob_media.max(), c.tasa_real.max()) for c in R["calibracion"].values())
    f.add_scatter(x=[0, mx], y=[0, mx], mode="lines", name="perfecta", line=dict(color=GRIS, dash="dot", width=1))
    f.update_layout(height=380, xaxis_title="probabilidad predicha (decil)", yaxis_title="tasa real")
    P.append(fig(f))

    # ---------------- deciles
    sec("Lift por decil (modelo elegido)", "La frase para el jurado: 'el 10% de arriba convierte X veces más que el promedio'.")
    dd = R.get("examen_deciles", R["deciles"])
    f = go.Figure(go.Bar(x=dd.decil, y=dd.lift, marker_color=AZUL, customdata=dd[["tasa", "captura_acum"]],
                         hovertemplate="decil %{x}<br>lift %{y:.2f}x<br>tasa %{customdata[0]:.1%}<br>captura acum. %{customdata[1]:.0%}<extra></extra>"))
    f.add_hline(y=1, line_dash="dot", line_color=GRIS)
    f.update_layout(height=320, xaxis_title="decil (1 = más probable)", yaxis_title="lift", xaxis=dict(dtick=1))
    P.append(fig(f))

    # ---------------- hiperparámetros
    if "hiper" in R:
        H = R["hiper"]
        sec("Hiperparámetros: cuáles importaron",
            f"Default {H['default']:.4f} → mejor {H['mejor']:.4f} (+{H['mejor'] - H['default']:.4f}). "
            "La importancia (fANOVA) dice qué perilla explicó la variación del Gini entre pruebas: la próxima vez solo se mueven esas.")
        P.append("<div class='grid2'><div>")
        imp = pd.Series(H["importancia"]).sort_values()
        f = go.Figure(go.Bar(y=imp.index, x=imp.values, orientation="h", marker_color=AZUL,
                             hovertemplate="%{y}: %{x:.0%}<extra></extra>"))
        f.update_layout(height=300, xaxis_tickformat=".0%", title="Importancia de cada hiperparámetro")
        P.append(fig(f) + "</div><div>")
        pr = R["hiper_pruebas"]
        f = go.Figure(go.Scatter(x=pr.number, y=pr.gini_cv, mode="markers", marker=dict(size=8, color=AZUL), name="prueba",
                                 hovertemplate="prueba %{x}<br>Gini %{y:.4f}<extra></extra>"))
        f.add_scatter(x=pr.number, y=pr.gini_cv.cummax(), mode="lines", line=dict(color=NARANJA, width=2), name="mejor hasta ahí")
        f.update_layout(height=300, title="Gini por prueba", xaxis_title="prueba")
        P.append(fig(f) + "</div></div>")
        P.append(_tabla(pd.DataFrame([H["mejores"]]).round(4)))

    # ---------------- segmentos
    if "segmentos" in R:
        s = R["segmentos"]
        sec("¿Uno o varios modelos?",
            f"Se entrena global y uno por segmento con la familia del modelo elegido ({html.escape(str(s.familia.iloc[0]))}); "
            f"la otra familia aparece en la tabla como referencia. Gana el que mide más EN CADA segmento y, si gana "
            f"'separado', la predicción final de ese segmento usa su modelo propio. Recomendación: "
            f"{int(s.n_modelos_recomendado.iloc[0])} modelo(s) de probabilidad.")
        f = go.Figure()
        f.add_bar(x=s.segmento, y=s.gini_global, name="global", marker_color=AZUL)
        f.add_bar(x=s.segmento, y=s.gini_separado, name="separado", marker_color=AQUA)
        f.update_layout(barmode="group", height=300, yaxis_title="Gini dentro del segmento", bargap=0.4, bargroupgap=0.08)
        P.append(fig(f))
        P.append(_tabla(s.round(4)))

    # ---------------- importancia
    imp = R["importancia"].head(20).iloc[::-1]
    sec("Qué variables importan (y si se puede confiar)",
        f"Medido en: {R['importancia_donde']}, con LightGBM"
        f"{'' if R['elegido'].startswith('lgbm') else ' como modelo de referencia (el elegido es ' + R['elegido'] + ')'}. SHAP = aporte promedio; permutación = cuánto cae el Gini si la variable se desordena. "
        "Gain alto con permutación ~0 = el modelo la usa pero no generaliza.")
    P.append("<div class='grid2'><div>")
    f = go.Figure(go.Bar(y=imp.variable, x=imp.shap_medio, orientation="h", marker_color=AZUL,
                         customdata=imp[["sentido"]], hovertemplate="%{y}<br>SHAP medio %{x:.4f}<br>%{customdata[0]}<extra></extra>"))
    f.update_layout(height=560, title="SHAP medio (|aporte|)")
    P.append(fig(f) + "</div><div>")
    f = go.Figure(go.Bar(y=imp.variable, x=imp.permutacion_gini, orientation="h", marker_color=AQUA,
                         hovertemplate="%{y}<br>caída de Gini %{x:.4f}<extra></extra>"))
    f.update_layout(height=560, title="Permutación (caída de Gini)")
    P.append(fig(f) + "</div></div>")
    P.append(_tabla(R["importancia"].round(4), "t_imp"))
    if "coef_logistica" in R:
        cf = R["coef_logistica"].head(20).iloc[::-1]
        sec("Modelo elegido (logística): coeficientes estandarizados",
            "Esto es lo que se explica al jurado, porque es el modelo entregado. Coeficiente = cuánto suben los log-odds si la "
            "variable sube 1 desviación estándar. Odds ratio = exp(coef): 1.5 multiplica las chances por 1.5; 0.7 las baja 30%. "
            "Las gráficas de arriba (SHAP, permutación) son de LightGBM como referencia del patrón.")
        f = go.Figure(go.Bar(y=cf.variable, x=cf.coef, orientation="h",
                             marker_color=[AZUL if v > 0 else CRITICO for v in cf.coef], customdata=cf[["odds_ratio"]],
                             hovertemplate="%{y}<br>coef %{x:.3f}<br>odds ratio %{customdata[0]:.2f}<extra></extra>"))
        f.update_layout(height=560, xaxis_title="coeficiente (variable estandarizada)")
        P.append(fig(f))
        P.append(_tabla(R["coef_logistica"].round(4), "t_coef"))
    if "caso" in R:
        sec("Explicar un caso: la empresa mejor puntuada",
            f"Modelo usado: {html.escape(R.get('caso_modelo', 'LightGBM'))}. Aporte de cada variable a SU predicción (log-odds) "
            "frente a la empresa promedio. Positivo = la empuja hacia arriba.")
        c = R["caso"].iloc[::-1]
        f = go.Figure(go.Bar(y=c.variable + " = " + c.valor.str.slice(0, 14), x=c.aporte, orientation="h",
                             marker_color=[AZUL if v > 0 else CRITICO for v in c.aporte],
                             hovertemplate="%{y}<br>aporte %{x:.3f}<extra></extra>"))
        f.update_layout(height=380)
        P.append(fig(f))

    # ---------------- monto y priorización
    if R.get("monto"):
        mo = R["monto"]
        sec("Monto: dos partes vs directo", f"Gana: <b>{mo['gana']}</b>. R² en soles = lo que pediría una métrica oficial (lo dominan pocas empresas grandes). Spearman = ¿ordena bien los montos? R² condicional = ¿hay señal en el TAMAÑO de quienes convierten?")
        P.append(_tabla(pd.DataFrame([mo]).round(4)))
    if "prior" in R:
        pr = R["prior"]
        txt = f"{pr['n']:,} empresas priorizadas. Voraz {pr['voraz']:,.0f} vs PuLP {pr['entero']:,.0f} ({pr['estado']})."
        if "conversion_priorizados" in pr:
            txt += (f" Convierten {pr['conversion_priorizados']:.1%} contra {pr['conversion_base']:.1%} de la base "
                    f"({pr['conversion_priorizados'] / max(pr['conversion_base'], 1e-9):.1f}x).")
        sec("Priorización con capacidad", txt)
        if "prior_zona" in R:
            P.append(_tabla(R["prior_zona"].round(4)))

    doc = (f"<!DOCTYPE html><html lang='es'><head><meta charset='utf-8'><title>Reporte de modelado</title>"
           f"<style>{CSS}</style></head><body><main><h1>Reporte de modelado</h1>"
           f"<p class='sub'>Generado por run_modelo.py</p>{''.join(P)}"
           "<script>function filtrar(id,q){q=q.toLowerCase();document.querySelectorAll('#'+id+' tbody tr').forEach(r=>{r.style.display=r.innerText.toLowerCase().includes(q)?'':'none'})}</script>"
           "</main></body></html>")
    destino.write_text(doc, encoding="utf-8")
    print(f"  -> {destino}")
