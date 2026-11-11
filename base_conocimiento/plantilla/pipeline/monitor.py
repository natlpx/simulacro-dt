"""
PASO 8 · MONITOR VISUAL: un solo HTML (funciona sin internet) para VER cómo se mueven los datos.

Qué responde cada sección (y qué buscar):
  1. KPIs              -> ¿cuánto entró, cuánto quedó, cuánto se eliminó?
  2. Embudo de columnas -> por tabla: columnas crudas -> limpias -> variables -> seleccionadas
  3. Decisiones        -> por qué se fue cada columna (vacía, constante, duplicada...)
  4. Conciliación      -> suma de montos antes vs después: si cambia, algo se perdió
  5. Valores anulados  -> columnas donde el parseo falló (formato raro no contemplado)
  6. Línea de tiempo   -> eventos y monto por mes + línea del CORTE: meses faltantes,
                          saltos, o datos después del corte (= lo que NO se puede usar)
  7. Rubros            -> dónde está la plata (Pareto): para la historia de negocio
  8. Distribución      -> forma del monto (log): colas, ceros, negativos
  9. Llaves            -> cómo se unen las tablas, coberturas y alertas N:M
 10. Selección         -> Gini/PSI por variable y decisión del embudo
"""
import html
import json

import pandas as pd

import config as C

# paleta de referencia validada (categórica en orden fijo + estados reservados)
AZUL, NARANJA, AQUA, AMARILLO, VIOLETA = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#6250d6"
GRIS, CRITICO = "#9a9890", "#d03b3b"
COLOR_DECISION = {"NUMERO": AZUL, "CATEGORIA": AQUA, "FECHA": VIOLETA, "LLAVE": AMARILLO,
                  "TARGET": NARANJA, "DROP": GRIS}

CSS = """
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#fcfcfb;color:#0b0b0b;margin:0}
main{max-width:1180px;margin:0 auto;padding:28px 24px 60px}
h1{font-size:26px;margin:0 0 4px} h2{font-size:18px;margin:36px 0 4px;border-top:1px solid #e4e3df;padding-top:22px}
.sub{color:#52514e;font-size:14px;margin:0 0 14px;max-width:820px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin:18px 0}
.kpi{background:#fff;border:1px solid #e4e3df;border-radius:10px;padding:14px}
.kpi b{display:block;font-size:24px;font-variant-numeric:tabular-nums}.kpi span{color:#52514e;font-size:12.5px}
table{border-collapse:collapse;font-size:12.5px;width:100%;background:#fff}
th,td{border-bottom:1px solid #eeede9;padding:5px 8px;text-align:left;vertical-align:top}
th{background:#f4f3f0;position:sticky;top:0} td.n{text-align:right;font-variant-numeric:tabular-nums}
.tabla{max-height:420px;overflow:auto;border:1px solid #e4e3df;border-radius:8px}
.alerta{color:#a32a2a;font-weight:600}.ok{color:#11734f}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media(max-width:900px){.grid2{grid-template-columns:1fr}}
input.f{padding:6px 10px;border:1px solid #d6d5d0;border-radius:6px;margin:4px 0 8px;width:280px}
"""


def _fig_html(fig, primero=False):
    fig.update_layout(template="simple_white", font=dict(family="system-ui, sans-serif", size=12, color="#0b0b0b"),
                      margin=dict(l=10, r=10, t=40, b=10), paper_bgcolor="#fcfcfb", plot_bgcolor="#fcfcfb",
                      hoverlabel=dict(bgcolor="white"), legend=dict(orientation="h", y=1.08, x=0))
    fig.update_xaxes(gridcolor="#eeede9", linecolor="#d6d5d0")
    fig.update_yaxes(gridcolor="#eeede9", linecolor="#d6d5d0")
    return fig.to_html(full_html=False, include_plotlyjs=True if primero else False,
                       config={"displaylogo": False, "responsive": True})


def _corte(f):
    f.add_shape(type="line", x0=C.FECHA_CORTE, x1=C.FECHA_CORTE, yref="paper", y0=0, y1=1,
                line=dict(color=NARANJA, width=2, dash="dash"))
    f.add_annotation(x=C.FECHA_CORTE, yref="paper", y=1.02, text="corte", showarrow=False,
                     font=dict(color="#52514e", size=11))


def _tabla(df, id_=None, max_filas=400):
    if df is None or len(df) == 0:
        return "<p class='sub'>(sin datos)</p>"
    df = df.head(max_filas)
    cab = "".join(f"<th>{html.escape(str(c))}</th>" for c in df.columns)
    filas = []
    for _, r in df.iterrows():
        celdas = []
        for v in r.values:
            if isinstance(v, float):
                txt, cls = (f"{v:,.4f}" if abs(v) < 10 else f"{v:,.0f}") if pd.notna(v) else "", "n"
            elif isinstance(v, (int,)) and not isinstance(v, bool):
                txt, cls = f"{v:,}", "n"
            else:
                txt, cls = html.escape(str(v)) if v is not None and str(v) != "nan" else "", ""
                if any(k in txt for k in ("⚠", "FUGA", "N:M", "baja cobertura", "REVISAR")):
                    cls = "alerta"
            celdas.append(f"<td class='{cls}'>{txt}</td>")
        filas.append("<tr>" + "".join(celdas) + "</tr>")
    filtro = (f"<input class='f' placeholder='filtrar…' oninput=\"filtrar('{id_}',this.value)\">" if id_ else "")
    return f"{filtro}<div class='tabla'><table id='{id_ or ''}'><thead><tr>{cab}</tr></thead><tbody>{''.join(filas)}</tbody></table></div>"


def generar(con, bit, perfil, gr=None, rel=None, specs=None, sel=None):
    import plotly.graph_objects as go
    print("\n== PASO 8 · MONITOR ==")
    b = bit.leer()
    partes, primero = [], True

    def fig(f):
        nonlocal primero
        h = _fig_html(f, primero); primero = False
        return h

    # ---------------------------------------------------------------- 1. KPIs
    ing = b[b.paso == "ingesta"].drop_duplicates("tabla", keep="last") if len(b) else pd.DataFrame()
    lim = b[b.paso == "limpieza"].drop_duplicates("tabla", keep="last") if len(b) else pd.DataFrame()
    modelo = b[(b.paso == "features") & (b.tabla == "tabla_modelo")]
    k = [("tablas", f"{perfil.tabla.nunique()}"),
         ("filas crudas", f"{int(ing.filas.sum()):,}" if len(ing) else "-"),
         ("columnas crudas", f"{len(perfil):,}"),
         ("columnas eliminadas", f"{(perfil.decision == 'DROP').sum():,} ({(perfil.decision == 'DROP').mean():.0%})"),
         ("duplicados quitados", f"{int(lim.get('duplicados_quitados', pd.Series([0])).fillna(0).sum()):,}" if len(lim) else "-"),
         ("filas del modelo", f"{int(modelo.filas.iloc[-1]):,}" if len(modelo) else "-"),
         ("variables creadas", f"{int(modelo.columnas.iloc[-1]):,}" if len(modelo) else "-")]
    if sel is not None:
        k.append(("variables finales", f"{(sel.decision == 'QUEDA').sum()}"))
    partes.append("<div class='kpis'>" + "".join(f"<div class='kpi'><b>{v}</b><span>{t}</span></div>" for t, v in k) + "</div>")

    # ---------------------------------------------------------------- 2. embudo de columnas por tabla
    partes.append("<h2>Embudo de columnas por tabla</h2><p class='sub'>Cuántas columnas entran crudas y cuántas sobreviven a la limpieza. Una tabla que pierde casi todo puede estar mal leída (encabezado corrido, separador equivocado).</p>")
    tb = perfil.groupby("tabla").agg(crudas=("columna", "size"), utiles=("decision", lambda s: (s != "DROP").sum())).reset_index()
    f = go.Figure()
    f.add_bar(x=tb.tabla, y=tb.crudas, name="columnas crudas", marker_color=GRIS, hovertemplate="%{x}<br>crudas: %{y}<extra></extra>")
    f.add_bar(x=tb.tabla, y=tb.utiles, name="columnas útiles", marker_color=AZUL, hovertemplate="%{x}<br>útiles: %{y}<extra></extra>")
    f.update_layout(barmode="group", bargap=0.35, bargroupgap=0.08, height=330, yaxis_title="columnas")
    partes.append(fig(f))

    # ---------------------------------------------------------------- 3. decisiones del perfil
    partes.append("<h2>Qué se decidió con cada columna</h2><p class='sub'>Gris = eliminada. Revisen la tabla completa: la forma se mide sola, el SIGNIFICADO lo valida una persona (correcciones en <code>decisiones_manual.csv</code>).</p>")
    d = perfil.assign(dec=perfil.decision.str.replace("+IND", "", regex=False)).groupby(["tabla", "dec"]).size().unstack(fill_value=0)
    f = go.Figure()
    for dec in [x for x in COLOR_DECISION if x in d.columns]:
        f.add_bar(y=d.index, x=d[dec], name=dec, orientation="h", marker_color=COLOR_DECISION[dec],
                  marker_line=dict(color="#fcfcfb", width=2), hovertemplate=f"%{{y}}<br>{dec}: %{{x}}<extra></extra>")
    f.update_layout(barmode="stack", height=90 + 45 * len(d), xaxis_title="columnas")
    partes.append(fig(f))
    motivos = perfil[perfil.decision == "DROP"].assign(m=lambda x: x.forma).groupby("m").size().sort_values()
    partes.append("<div class='grid2'><div>")
    f = go.Figure(go.Bar(y=motivos.index, x=motivos.values, orientation="h", marker_color=GRIS,
                         hovertemplate="%{y}: %{x} columnas<extra></extra>"))
    f.update_layout(height=260, title="Motivo de eliminación", xaxis_title="columnas")
    partes.append(fig(f) + "</div><div>")
    roles = perfil[perfil.decision != "DROP"].rol.value_counts().sort_values()
    f = go.Figure(go.Bar(y=roles.index, x=roles.values, orientation="h", marker_color=AZUL,
                         hovertemplate="%{y}: %{x} columnas<extra></extra>"))
    f.update_layout(height=260, title="Papel detectado (columnas útiles)", xaxis_title="columnas")
    partes.append(fig(f) + "</div></div>")
    pv = perfil.copy()
    def _rango(r):
        if str(r.decision).startswith("FECHA"):
            return f"{r.get('fecha_min', '')} → {r.get('fecha_max', '')}"
        if str(r.decision).startswith("NUMERO"):
            return f"{r['min']:,.2f} · mediana {r['p50']:,.2f} · {r['max']:,.2f}"
        return ""
    pv["rango"] = pv.apply(_rango, axis=1)
    cols_p = ["tabla", "columna", "decision", "forma", "rol", "motivo", "pct_nulo", "nd", "top5", "rango"]
    partes.append(_tabla(pv[cols_p].sort_values(["tabla", "decision"]), "t_perfil", 2000))

    # ---------------------------------------------------------------- 4. conciliación
    partes.append("<h2>Conciliación: filas y montos en cada paso</h2><p class='sub'>Cada paso registra filas, columnas y suma de montos. Si la suma cambia sin que lo hayamos decidido (duplicados quitados), algo se perdió o se multiplicó.</p>")
    if len(b):
        cols_b = [c for c in b.columns if c in ("paso", "tabla", "filas", "columnas", "segundos", "motor", "mb_origen", "mb_parquet",
                                              "duplicados_quitados", "cols_eliminadas", "cobertura_entidades", "filas_rotas_o_multilinea")
                  or c.startswith("suma_")]
        partes.append(_tabla(b[cols_b], "t_bit"))
    det_path = C.OUT_DIR / "limpieza_detalle.csv"
    if det_path.exists():
        det = pd.read_csv(det_path)
        det = det[det.anulados > 0].sort_values("pct_anulado", ascending=False).head(20)
        if len(det):
            partes.append("<h2>Valores que no se pudieron convertir</h2><p class='sub'>Tenían texto pero quedaron vacíos al convertir a número/fecha. Por encima de 5% hay un formato que la limpieza no contempla: abrir el top5 de esa columna en el perfil.</p>")
            f = go.Figure(go.Bar(y=det.tabla + "." + det.columna, x=det.pct_anulado,
                                 marker_color=[CRITICO if v > 0.05 else AMARILLO for v in det.pct_anulado],
                                 orientation="h", hovertemplate="%{y}<br>%{x:.2%} anulados<extra></extra>"))
            f.update_layout(height=120 + 22 * len(det), xaxis_tickformat=".0%", xaxis_title="% de valores anulados",
                            yaxis_autorange="reversed")
            partes.append(fig(f))

    # ---------------------------------------------------------------- 5. tiempo, rubro, distribución
    silver = C.WORK_DIR / "silver"
    for t, s in (specs or {}).items():
        if s.get("tipo") != "eventos":
            continue
        p = (silver / f"{t}.parquet").as_posix()
        fe = f'"{s["fecha"]}"'
        m = s.get("montos") or []
        mexpr = f'sum("{m[0]}")' if m else "NULL"
        serie = con.execute(f"SELECT date_trunc('month', {fe}) mes, count(*) n, {mexpr} monto FROM '{p}' "
                            f"WHERE {fe} IS NOT NULL GROUP BY 1 ORDER BY 1").fetchdf()
        partes.append(f"<h2>Línea de tiempo · {t}</h2><p class='sub'>Línea vertical = corte ({C.FECHA_CORTE}). "
                      f"Lo de la izquierda alimenta variables; lo de la derecha solo sirve para el objetivo. Buscar meses vacíos o saltos (cambio de sistema, carga parcial).</p><div class='grid2'><div>")
        f = go.Figure(go.Scatter(x=serie.mes, y=serie.n, mode="lines+markers", line=dict(color=AZUL, width=2),
                                 marker=dict(size=8), hovertemplate="%{x|%Y-%m}<br>%{y:,} eventos<extra></extra>"))
        _corte(f)
        f.update_layout(height=300, title="Eventos por mes", yaxis_title="eventos")
        partes.append(fig(f) + "</div><div>")
        if m:
            f = go.Figure(go.Scatter(x=serie.mes, y=serie.monto, mode="lines+markers", line=dict(color=AQUA, width=2),
                                     marker=dict(size=8), hovertemplate="%{x|%Y-%m}<br>S/ %{y:,.0f}<extra></extra>"))
            _corte(f)
            f.update_layout(height=300, title=f"Suma de {m[0]} por mes", yaxis_title=m[0])
            partes.append(fig(f))
        partes.append("</div></div>")

        if s.get("cat") and m:
            c = f'"{s["cat"]}"'
            rub = con.execute(f"SELECT coalesce({c}, 'SIN DATO') rubro, count(*) n, sum(\"{m[0]}\") monto, "
                              f"count(DISTINCT \"{s['id']}\") entidades FROM '{p}' GROUP BY 1 ORDER BY monto DESC").fetchdf()
            rub["share"] = rub.monto / rub.monto.sum()
            rub["acumulado"] = rub.share.cumsum()
            top = rub.head(15).iloc[::-1]
            partes.append(f"<h2>¿Dónde está la plata? {s['cat']} en {t}</h2><p class='sub'>Pareto: cuántos rubros explican el 80% del monto. Es la primera lámina de negocio.</p><div class='grid2'><div>")
            f = go.Figure(go.Bar(y=top.rubro, x=top.monto, orientation="h", marker_color=AZUL,
                                 customdata=top[["share", "entidades"]],
                                 hovertemplate="%{y}<br>S/ %{x:,.0f} (%{customdata[0]:.1%})<br>%{customdata[1]:,} entidades<extra></extra>"))
            f.update_layout(height=430, title=f"Top 15 por {m[0]}", xaxis_title=m[0])
            partes.append(fig(f) + "</div><div>")
            f = go.Figure(go.Scatter(x=list(range(1, len(rub) + 1)), y=rub.acumulado, mode="lines+markers",
                                     line=dict(color=AZUL, width=2), marker=dict(size=8), text=rub.rubro,
                                     hovertemplate="%{text}<br>top %{x}: %{y:.1%} del monto<extra></extra>"))
            f.add_hline(y=0.8, line_dash="dot", line_color=GRIS)
            f.update_layout(height=430, title="Monto acumulado (Pareto)", yaxis_tickformat=".0%", xaxis_title="n° de rubros")
            partes.append(fig(f) + "</div></div>")

        if m:
            dist = con.execute(f"""SELECT floor(log10(abs("{m[0]}")) * 4) / 4 AS b, count(*) n FROM '{p}'
                                   WHERE "{m[0]}" > 0 GROUP BY 1 ORDER BY 1""").fetchdf()
            otros = con.execute(f"""SELECT count(*) FILTER (WHERE "{m[0]}" = 0), count(*) FILTER (WHERE "{m[0]}" < 0),
                                    count(*) FILTER (WHERE "{m[0]}" IS NULL) FROM '{p}'""").fetchone()
            partes.append(f"<h2>Forma de {m[0]} ({t})</h2><p class='sub'>Eje en escala log10 (cada unidad = ×10). "
                          f"Ceros: {otros[0]:,} · negativos: {otros[1]:,} · vacíos: {otros[2]:,}. Una cola larga a la derecha es normal en montos; "
                          f"un pico aislado suele ser un valor por defecto.</p>")
            f = go.Figure(go.Bar(x=dist.b + 0.125, y=dist.n, width=0.23, marker_color=AZUL,
                                 customdata=10 ** dist.b, hovertemplate="desde %{customdata:,.0f}<br>%{y:,} registros<extra></extra>"))
            ticks = list(range(int(dist.b.min()), int(dist.b.max()) + 2)) if len(dist) else []
            f.update_xaxes(tickvals=ticks, ticktext=[f"{10 ** t:,.0f}" for t in ticks], title=f"{m[0]} (escala ×10)")
            f.update_layout(height=300, bargap=0.1, yaxis_title="registros")
            partes.append(fig(f))

    # ---------------------------------------------------------------- 8. llaves
    if rel is not None:
        partes.append("<h2>Cómo se unen las tablas</h2><p class='sub'>Cobertura = % de valores de una tabla que existen en la otra. N:M o coberturas bajas = no hacer JOIN directo.</p>")
        partes.append(_tabla(rel, "t_rel"))
        if gr is not None:
            partes.append("<p class='sub' style='margin-top:14px'>Grano de cada tabla (¿qué identifica una fila?)</p>" + _tabla(gr, "t_gr"))

    # ---------------------------------------------------------------- 9. selección
    if sel is not None and len(sel):
        partes.append("<h2>Embudo de selección de variables</h2><p class='sub'>Gini individual de cada variable (train). Rojo = demasiado buena (¿existe el día de decidir?), gris = fuera, azul = queda.</p>")
        top = sel.sort_values("gini", ascending=False).head(30).iloc[::-1]
        col = {"QUEDA": AZUL, "FUERA": GRIS, "REVISAR_FUGA": CRITICO}
        f = go.Figure(go.Bar(y=top.variable, x=top.gini, orientation="h", marker_color=[col.get(x, GRIS) for x in top.decision],
                             customdata=top[["decision", "motivo", "psi", "iv"]],
                             hovertemplate="%{y}<br>Gini %{x:.3f} · IV %{customdata[3]:.3f} · PSI %{customdata[2]:.3f}<br>%{customdata[0]} %{customdata[1]}<extra></extra>"))
        f.add_vline(x=C.U["gini_fuga"], line_dash="dot", line_color=CRITICO)
        f.update_layout(height=140 + 20 * len(top), xaxis_title="Gini individual")
        partes.append(fig(f))
        partes.append(_tabla(sel, "t_sel"))

    script = """<script>function filtrar(id,q){q=q.toLowerCase();document.querySelectorAll('#'+id+' tbody tr').forEach(r=>{r.style.display=r.innerText.toLowerCase().includes(q)?'':'none'})}</script>"""
    doc = (f"<!DOCTYPE html><html lang='es'><head><meta charset='utf-8'><title>Monitor del pipeline</title>"
           f"<style>{CSS}</style></head><body><main><h1>Monitor del pipeline de datos</h1>"
           f"<p class='sub'>Corte {C.FECHA_CORTE} · horizonte {C.HORIZONTE_MESES} meses · generado automáticamente por run_pipeline.py</p>"
           + "".join(partes) + script + "</main></body></html>")
    destino = C.OUT_DIR / "monitor.html"
    destino.write_text(doc, encoding="utf-8")
    print(f"  -> {destino}")
    return destino
