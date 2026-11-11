"""
PASO 5 · VARIABLES: de 4 tablas a UNA tabla con una fila por entidad (empresa).

Principio anti-fuga: TODO evento usado como variable cumple fecha < FECHA_CORTE.
El objetivo se mide en [corte, corte + horizonte). Nada del futuro entra a las variables.

Qué se construye y su frase de negocio:
  Tablas 1:1 con la entidad (maestro, perfil) -> se pegan tal cual; fechas -> "días desde".
  Tablas de EVENTOS (transacciones, operaciones), por entidad:
    n / monto total, promedio, máximo, desviación  -> tamaño y volatilidad del negocio
    n y monto en ventanas 3/6/12 meses              -> actividad reciente vs histórica
    tendencia = monto_3m / (monto_12m / 4)           -> ¿está creciendo? (>1 = acelera)
    recencia_dias, antiguedad_dias, meses_activos    -> ¿sigue vivo?, ¿desde cuándo?
    n rubros/categorías, top_share de categoría      -> diversificación
    n contrapartes, hhi_contraparte                  -> concentración en pocos pagadores
    contagio = % de sus contrapartes cuyos otros     -> efecto red: si los proveedores de
               socios ya hicieron el evento objetivo    mi pagador hacen factoring, yo también
  Tablas N filas sin fecha -> conteos y sumas.
"""
import re

import pandas as pd

import config as C


def _q(c):
    return f'"{c}"'


def _corto(t):
    return re.sub(r"[^a-z0-9]", "", t.lower())[:10]


def _cols(perfil, tabla, decision=None, rol=None):
    d = perfil[perfil.tabla == tabla]
    if decision:
        d = d[d.decision.str.replace("+IND", "", regex=False).isin(decision if isinstance(decision, list) else [decision])]
    if rol:
        d = d[d.rol.isin(rol if isinstance(rol, list) else [rol])]
    return d


def _sql_moneda_a_soles(m, moneda):
    if not moneda:
        return _q(m)
    return (f"CASE WHEN {_q(moneda)} IN ('USD','US$','DOLARES','DOLAR','DOL','2') "
            f"THEN {_q(m)} * {C.TIPO_CAMBIO} ELSE {_q(m)} END")


def fuente_eventos(t, path):
    """Origen de una tabla de eventos; si está en DEDUP_EVENTOS se cuenta cada operación una vez
    (p.ej. la misma operación registrada por el banco y vista también por el SPI)."""
    keys = (C.DEDUP_EVENTOS or {}).get(t)
    if not keys:
        return f"'{path.as_posix()}'"
    k = ", ".join(_q(x) for x in keys)
    return f"(SELECT * FROM '{path.as_posix()}' QUALIFY row_number() OVER (PARTITION BY {k}) = 1)"


PATRON_MES = re.compile(r"^(?P<fam>.+?)_?(?P<per>(?:19|20)\d{2}(?:0[1-9]|1[0-2])|m\d{1,2}|mes_?\d{1,2})$")


def familias_mensuales(columnas):
    """Detecta columnas tipo saldo_202401..saldo_202506 o saldo_m01..saldo_m18 (perfil ANCHO).
    Devuelve {familia: [(periodo_ordenable, columna), ...]} solo si hay >= 3 meses."""
    fam = {}
    for c in columnas:
        m = PATRON_MES.match(c)
        if m:
            per = m.group("per")
            clave = int(per) if per.isdigit() else int(re.sub(r"\D", "", per))
            fam.setdefault(m.group("fam"), []).append((clave, c))
    return {f: sorted(v) for f, v in fam.items() if len(v) >= 3}


def es_posterior_al_corte(col):
    """saldo_202509 con corte 2025-07 -> True. Columna con periodo en el nombre = fecha implícita."""
    m = PATRON_MES.match(col)
    if not m or not m.group("per").isdigit():
        return False
    return int(m.group("per")) >= int(C.FECHA_CORTE[:4] + C.FECHA_CORTE[5:7])


def sql_familias(fams, p, t):
    """Por familia mensual: nivel reciente, tendencia, volatilidad y meses con dato.
    Si el periodo es AAAAMM, solo usa meses ANTERIORES al corte (anti-fuga)."""
    sel, dic, usadas = [], [], set()
    corte_per = int(C.FECHA_CORTE[:4] + C.FECHA_CORTE[5:7])
    for f, cols in fams.items():
        usadas |= {c for _, c in cols}            # todas (incluidas las futuras) salen del "tal cual"
        if all(k > 190000 for k, _ in cols):
            cols = [(k, c) for k, c in cols if k < corte_per]
        if len(cols) < 3:
            continue
        orden = [_q(c) for _, c in cols]
        ult3, prev = orden[-3:], orden[-6:-3] or orden[:-3]
        usadas |= {c for _, c in cols}
        sel += [f"list_avg([{', '.join(ult3)}]) AS {p}__{f}_nivel3",
                f"list_avg([{', '.join(ult3)}]) - list_avg([{', '.join(prev)}]) AS {p}__{f}_tend",
                f"list_stddev_samp([{', '.join(orden)}]) AS {p}__{f}_vol",
                f"list_count([{', '.join(orden)}]) AS {p}__{f}_meses",
                f"{orden[-1]} AS {p}__{f}_ultimo"]
        dic += [(f"{p}__{f}_nivel3", t, f"{f}: promedio de los 3 últimos meses antes del corte"),
                (f"{p}__{f}_tend", t, f"{f}: últimos 3 meses menos los 3 anteriores (crece > 0)"),
                (f"{p}__{f}_vol", t, f"{f}: volatilidad mensual"),
                (f"{p}__{f}_meses", t, f"{f}: meses con dato"), (f"{p}__{f}_ultimo", t, f"{f}: último mes")]
    return sel, dic, usadas


def pivotar(con, perfil):
    """Tabla LARGA (id, periodo, variable, valor) -> una columna por variable x mes. Así entra
    al flujo normal como perfil ANCHO. Las variables raras (<1%) se descartan para no crear miles."""
    for t, s in (C.PIVOTAR or {}).items():
        src = (C.WORK_DIR / "silver" / f"{t}.parquet").as_posix()
        dst = (C.WORK_DIR / "silver" / f"{t}__pivot.parquet").as_posix()
        con.execute(f"""COPY (
            PIVOT (SELECT {_q(s['id'])} AS {_q(s['id'])},
                          {_q(s['variable'])} || '_' || strftime({_q(s['fecha'])}, '%Y%m') AS clave,
                          {_q(s['valor'])} AS valor
                   FROM '{src}'
                   WHERE {_q(s['variable'])} IN (SELECT {_q(s['variable'])} FROM '{src}' GROUP BY 1
                                                 HAVING count(*) >= 0.01 * (SELECT count(*) FROM '{src}')))
            ON clave USING sum(valor) GROUP BY {_q(s['id'])}) TO '{dst}' (FORMAT parquet)""")
        print(f"  · {t}: pivoteada a {dst}")


def detectar_eventos(perfil, rel, ent, gr):
    """Para cada tabla != entidad: con qué columna se une, y si es atributo o evento."""
    te, ke = ent
    specs = {}
    for t in perfil.tabla.unique():
        if C.EVENTOS and t in C.EVENTOS:
            specs[t] = dict(tipo="eventos", **C.EVENTOS[t])
            continue
        if t == te:
            continue
        cand = rel[((rel.tabla_a == te) & (rel.llave_a == ke) & (rel.tabla_b == t)) |
                   ((rel.tabla_b == te) & (rel.llave_b == ke) & (rel.tabla_a == t))] if len(rel) else rel
        if cand.empty:
            print(f"  · {t}: no se une con la entidad -> se omite (revisar relaciones.csv)")
            continue
        cand = cand.assign(col=[r.llave_b if r.tabla_b == t else r.llave_a for _, r in cand.iterrows()])
        roles = perfil[(perfil.tabla == t)].set_index("columna").rol
        cand = cand.assign(es_id=[roles.get(c) == "id" for c in cand.col]).sort_values(["es_id", "en_comun"], ascending=False)
        link = cand.col.iloc[0]
        otras = [c for c in cand.col.iloc[1:]]  # otras llaves que también apuntan a la entidad = contrapartes
        unica = bool(gr[(gr.tabla == t) & (gr.llave == link)].unica.iloc[0])
        fechas = _cols(perfil, t, "FECHA").sort_values("pct_nulo")
        prefer = fechas[fechas.columna.str.contains("emision|operacion|transac|fecha_|^fec", regex=True)]
        fecha = (prefer if len(prefer) else fechas).columna.iloc[0] if len(fechas) else None
        if unica:
            specs[t] = dict(tipo="atributos", id=link)
        elif fecha:
            cps = otras or _cols(perfil, t, "LLAVE", "contraparte").columna.tolist()
            otras_f = [c for c in fechas.columna if c != fecha]
            specs[t] = dict(tipo="eventos", id=link, fecha=fecha, fecha2=otras_f[0] if otras_f else None,
                            montos=(_cols(perfil, t, "NUMERO", "monto").columna.tolist()
                                    or _cols(perfil, t, "NUMERO").sort_values("pct_nulo").columna.tolist())[:3],
                            cat=next(iter(_cols(perfil, t, "CATEGORIA", "rubro").columna), None),
                            cp=cps[0] if cps else None,
                            moneda=next(iter(_cols(perfil, t, "CATEGORIA", "moneda").columna), None))
            # otros números del evento que NO son montos (p.ej. dias_plazo): antes se perdían
            ya = set(specs[t]["montos"])
            specs[t]["otros"] = [c for c in _cols(perfil, t, "NUMERO").columna if c not in ya][:5]
        else:
            specs[t] = dict(tipo="agregado", id=link)
    return specs


def sql_atributos(t, spec, perfil, path):
    """Tabla 1 fila por entidad: números y categorías tal cual; fechas -> días hasta el corte."""
    p = _corto(t)
    fams = familias_mensuales(_cols(perfil, t, "NUMERO").columna.tolist())
    sel, dic, usadas = sql_familias(fams, p, t)
    for _, r in _cols(perfil, t, ["NUMERO", "CATEGORIA", "FECHA"]).iterrows():
        c, d = r.columna, r.decision.replace("+IND", "")
        if c == spec["id"] or c in usadas or es_posterior_al_corte(c):
            continue
        nombre = f"{p}__{c}"
        if d == "FECHA":
            sel.append(f"CASE WHEN {_q(c)} < DATE '{C.FECHA_CORTE}' THEN date_diff('day', {_q(c)}, DATE '{C.FECHA_CORTE}') END AS {_q(nombre)}")
            dic.append((nombre, t, f"días desde {c} hasta el corte (fechas posteriores = NULL, posible fuga)"))
        else:
            sel.append(f"{_q(c)} AS {_q(nombre)}")
            dic.append((nombre, t, f"{c} tal cual ({d.lower()})"))
        if r.decision.endswith("+IND") and d == "FECHA":
            # una fecha POSTERIOR al corte no existía el día de decidir: el indicador solo cuenta las anteriores
            sel.append(f"CAST(coalesce({_q(c)} < DATE '{C.FECHA_CORTE}', false) AS TINYINT) AS \"{p}__tiene_{c}\"")
            dic.append((f"{p}__tiene_{c}", t, f"1 si {c} tiene dato ANTES del corte"))
        elif r.decision.endswith("+IND"):
            sel.append(f'"tiene_{c}" AS "{p}__tiene_{c}"')
            dic.append((f"{p}__tiene_{c}", t, f"1 si {c} tiene dato"))
    sql = f"SELECT {_q(spec['id'])} AS id, {', '.join(sel)} FROM '{path.as_posix()}' QUALIFY row_number() OVER (PARTITION BY {_q(spec['id'])}) = 1"
    return sql, dic


def sql_eventos(t, spec, path, specs_target=None):
    p, corte = _corto(t), f"DATE '{C.FECHA_CORTE}'"
    i, f = _q(spec["id"]), _q(spec["fecha"])
    vmax = max(C.VENTANAS_MESES)
    montos = spec.get("montos") or []
    m_exprs = {m: _sql_moneda_a_soles(m, spec.get("moneda")) for m in montos}
    sel, dic = [f"count(*) AS {p}__n_total"], [(f"{p}__n_total", t, "n° de eventos antes del corte")]
    for m, e in m_exprs.items():
        sel += [f"sum({e}) AS {p}__{m}_total", f"avg({e}) AS {p}__{m}_prom",
                f"max({e}) AS {p}__{m}_max", f"stddev_samp({e}) AS {p}__{m}_std"]
        dic += [(f"{p}__{m}_total", t, f"suma de {m} (S/)"), (f"{p}__{m}_prom", t, f"ticket promedio de {m}"),
                (f"{p}__{m}_max", t, f"mayor {m}"), (f"{p}__{m}_std", t, f"volatilidad de {m}")]
    for v in C.VENTANAS_MESES:
        w = f"{f} >= {corte} - INTERVAL {v} MONTH"
        sel.append(f"count(*) FILTER (WHERE {w}) AS {p}__n_{v}m")
        dic.append((f"{p}__n_{v}m", t, f"n° de eventos en los últimos {v} meses"))
        for m, e in m_exprs.items():
            sel.append(f"coalesce(sum({e}) FILTER (WHERE {w}), 0) AS {p}__{m}_{v}m")
            dic.append((f"{p}__{m}_{v}m", t, f"{m} en los últimos {v} meses"))
    if montos and 3 in C.VENTANAS_MESES and 12 in C.VENTANAS_MESES:
        m0 = montos[0]
        sel.append(f"{p}__{m0}_3m / nullif({p}__{m0}_12m / 4.0, 0) AS {p}__tendencia")
        dic.append((f"{p}__tendencia", t, f"{m0} últimos 3m vs promedio trimestral del año (>1 crece)"))
    sel += [f"date_diff('day', max({f}), {corte}) AS {p}__recencia_dias",
            f"date_diff('day', min({f}), {corte}) AS {p}__antiguedad_dias",
            f"count(DISTINCT date_trunc('month', {f})) AS {p}__meses_activos"]
    dic += [(f"{p}__recencia_dias", t, "días desde el último evento"),
            (f"{p}__antiguedad_dias", t, "días desde el primer evento"),
            (f"{p}__meses_activos", t, "meses con al menos un evento")]
    for o in spec.get("otros") or []:  # números que no son montos: sin conversión de moneda
        sel += [f"avg({_q(o)}) AS {p}__{o}_prom", f"max({_q(o)}) AS {p}__{o}_max"]
        dic += [(f"{p}__{o}_prom", t, f"promedio de {o}"), (f"{p}__{o}_max", t, f"máximo de {o}")]
    if spec.get("fecha2"):  # dos fechas por evento (emisión/vencimiento/pago) -> plazo en días
        # solo si la segunda fecha ya ocurrió el día del corte (un pago futuro no se conocía)
        d2 = f"CASE WHEN {_q(spec['fecha2'])} < {corte} THEN date_diff('day', {f}, {_q(spec['fecha2'])}) END"
        sel += [f"avg(abs({d2})) AS {p}__plazo_prom", f"max(abs({d2})) AS {p}__plazo_max"]
        dic += [(f"{p}__plazo_prom", t, f"días promedio entre {spec['fecha']} y {spec['fecha2']} (plazo de cobro)"),
                (f"{p}__plazo_max", t, f"plazo máximo entre {spec['fecha']} y {spec['fecha2']}")]
    if spec.get("cat"):
        sel.append(f"count(DISTINCT {_q(spec['cat'])}) AS {p}__n_{spec['cat']}")
        dic.append((f"{p}__n_{spec['cat']}", t, f"n° de {spec['cat']} distintos (diversificación)"))
    if spec.get("cp"):
        sel.append(f"count(DISTINCT {_q(spec['cp'])}) AS {p}__n_contrapartes")
        dic.append((f"{p}__n_contrapartes", t, f"n° de {spec['cp']} distintos"))

    base = f"""SELECT * FROM {fuente_eventos(t, path)}
               WHERE {f} < {corte} AND {f} >= {corte} - INTERVAL {vmax * 2} MONTH AND {i} IS NOT NULL"""
    sql = f"WITH e AS ({base}) SELECT {i} AS id, {', '.join(sel)} FROM e GROUP BY {i}"

    # concentración: HHI por contraparte (1 = un solo pagador, ~0 = muy diversificado)
    extras = []
    if spec.get("cp") and montos:
        cp, m0 = _q(spec["cp"]), m_exprs[montos[0]]
        extras.append((f"""WITH e AS ({base}), s AS (SELECT {i} id, {cp} cp, sum(abs({m0})) v FROM e GROUP BY 1, 2)
            SELECT id, sum(power(v / nullif(tot, 0), 2)) AS {p}__hhi_contraparte,
                   max(v / nullif(tot, 0)) AS {p}__top_contraparte_share
            FROM (SELECT *, sum(v) OVER (PARTITION BY id) tot FROM s) GROUP BY id""",
            [(f"{p}__hhi_contraparte", t, "concentración en contrapartes (HHI, 1 = uno solo)"),
             (f"{p}__top_contraparte_share", t, "peso de la contraparte principal")]))
    if spec.get("cat") and montos:
        c, m0 = _q(spec["cat"]), m_exprs[montos[0]]
        extras.append((f"""WITH e AS ({base}), s AS (SELECT {i} id, {c} c, sum(abs({m0})) v FROM e GROUP BY 1, 2)
            SELECT id, max(v / nullif(tot, 0)) AS {p}__top_{spec['cat']}_share,
                   arg_max(c, v) AS {p}__{spec['cat']}_principal
            FROM (SELECT *, sum(v) OVER (PARTITION BY id) tot FROM s) GROUP BY id""",
            [(f"{p}__top_{spec['cat']}_share", t, f"peso del {spec['cat']} principal"),
             (f"{p}__{spec['cat']}_principal", t, f"{spec['cat']} donde mueve más monto")]))
    # contagio por red: requiere saber quién hizo el evento objetivo ANTES del corte
    if spec.get("cp") and specs_target:
        tt, it, ft, filtro = specs_target
        extras.append((f"""WITH ec AS (SELECT DISTINCT {i} id, {_q(spec['cp'])} cp FROM ({base}) WHERE {_q(spec['cp'])} IS NOT NULL),
                 u AS (SELECT DISTINCT {_q(it)} id, 1 AS u FROM '{tt}' WHERE {_q(ft)} < {corte} {('AND ' + filtro) if filtro else ''}),
                 x AS (SELECT ec.*, coalesce(u.u, 0) u FROM ec LEFT JOIN u USING (id)),
                 g AS (SELECT cp, count(*) n_ent, sum(u) n_u FROM x GROUP BY cp)
            SELECT x.id, avg(g.n_ent) AS {p}__grado_red,
                   sum(g.n_u - x.u) / nullif(sum(g.n_ent - 1), 0) AS {p}__contagio
            FROM x JOIN g USING (cp) GROUP BY x.id""",
            [(f"{p}__grado_red", t, "con cuántas entidades comparte contrapartes (tamaño de su red)"),
             (f"{p}__contagio", t, "% de sus vecinos de red que ya hicieron el evento objetivo antes del corte")]))
    return sql, dic, extras


def sql_agregado(t, spec, perfil, path):
    p = _corto(t)
    sel, dic = ["count(*) AS " + f"{p}__n_filas"], [(f"{p}__n_filas", t, "n° de registros")]
    for c in _cols(perfil, t, "NUMERO").columna:
        sel += [f"sum({_q(c)}) AS {p}__{c}_sum", f"avg({_q(c)}) AS {p}__{c}_avg"]
        dic += [(f"{p}__{c}_sum", t, f"suma de {c}"), (f"{p}__{c}_avg", t, f"promedio de {c}")]
    for c in _cols(perfil, t, "CATEGORIA").columna:
        sel.append(f"count(DISTINCT {_q(c)}) AS {p}__{c}_nd")
        dic.append((f"{p}__{c}_nd", t, f"n° de {c} distintos"))
    return f"SELECT {_q(spec['id'])} AS id, {', '.join(sel)} FROM '{path.as_posix()}' GROUP BY 1", dic


def sql_target():
    T = C.TARGET
    if not T:
        return None
    path = (C.WORK_DIR / "silver" / f"{T['tabla']}.parquet").as_posix()
    if "columna" in T:
        return f"SELECT {_q(T['id'])} AS id, max({_q(T['columna'])}) AS target FROM '{path}' GROUP BY 1"
    corte = f"DATE '{C.FECHA_CORTE}'"
    filtro = f"AND {T['filtro']}" if T.get("filtro") else ""
    monto = f", sum({_q(T['monto'])}) AS target_monto" if T.get("monto") else ""
    src = fuente_eventos(T["tabla"], C.WORK_DIR / "silver" / f"{T['tabla']}.parquet")
    return (f"SELECT {_q(T['id'])} AS id, 1 AS target{monto} FROM {src} "
            f"WHERE {_q(T['fecha'])} >= {corte} AND {_q(T['fecha'])} < {corte} + INTERVAL {C.HORIZONTE_MESES} MONTH "
            f"{filtro} GROUP BY 1")


def ejecutar(con, bit, perfil, rel, gr, ent, sufijo=""):
    print(f"\n== PASO 5 · VARIABLES (corte {C.FECHA_CORTE}) ==")
    silver = C.WORK_DIR / "silver"
    te, ke = ent
    if C.PIVOTAR:
        pivotar(con, perfil)
    specs = detectar_eventos(perfil, rel, ent, gr)
    T = C.TARGET
    spec_t = None
    if T and "fecha" in T:
        spec_t = ((silver / f"{T['tabla']}.parquet").as_posix(), T["id"], T["fecha"], T.get("filtro"))

    # base: una fila por entidad
    sql_base, dic = sql_atributos(te, dict(id=ke), perfil, silver / f"{te}.parquet")
    con.execute(f"CREATE OR REPLACE TABLE modelo AS {sql_base}")
    bit.registrar("features", f"base:{te}", con.execute("SELECT count(*) FROM modelo").fetchone()[0],
                  len(con.execute("DESCRIBE modelo").fetchall()))

    def pegar(sql, nombre, presencia=False):
        con.execute(f"CREATE OR REPLACE TEMP TABLE _f AS {sql}")
        dup = con.execute("SELECT count(*) - count(DISTINCT id) FROM _f").fetchone()[0]
        assert dup == 0, f"{nombre}: la tabla de variables tiene ids repetidos -> el JOIN multiplicaría filas"
        n0 = con.execute("SELECT count(*) FROM modelo").fetchone()[0]
        pres = (f", CAST(_f.id IS NOT NULL AS TINYINT) AS \"{_corto(nombre)}__presente\"" if presencia else "")
        con.execute(f"CREATE OR REPLACE TABLE modelo AS SELECT m.*, _f.* EXCLUDE (id){pres} "
                    f"FROM modelo m LEFT JOIN _f ON m.id = _f.id")
        if presencia:  # "aparece en esta tabla" (p.ej. cliente = aparece en perfiles de productos)
            dic.append((f"{_corto(nombre)}__presente", nombre, f"1 si la entidad aparece en {nombre}"))
        n1 = con.execute("SELECT count(*) FROM modelo").fetchone()[0]
        assert n0 == n1, f"{nombre}: el JOIN cambió el número de filas ({n0} -> {n1})"
        cob = con.execute("SELECT count(*) FROM modelo WHERE id IN (SELECT id FROM _f)").fetchone()[0]
        bit.registrar("features", nombre, n1, len(con.execute("DESCRIBE modelo").fetchall()),
                      {"cobertura_entidades": round(cob / max(n1, 1), 4)})

    for t in (C.PIVOTAR or {}):  # la tabla larga entra pivoteada, como perfil ancho
        specs.pop(t, None)
        specs[f"{t}__pivot"] = dict(tipo="pivot", id=C.PIVOTAR[t]["id"])
    for t, s in specs.items():
        path = silver / f"{t}.parquet"
        print(f"  · {t}: {s}")
        if s["tipo"] == "pivot":
            cols = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM '{path.as_posix()}'").fetchall()]
            sel, d, _ = sql_familias(familias_mensuales(cols), _corto(t), t)
            dic += d
            pegar(f"SELECT {_q(s['id'])} AS id, {', '.join(sel)} FROM '{path.as_posix()}'", t, presencia=True)
            continue
        if s["tipo"] == "atributos":
            q, d = sql_atributos(t, s, perfil, path); dic += d; pegar(q, t, presencia=True)
        elif s["tipo"] == "eventos":
            q, d, extras = sql_eventos(t, s, path, spec_t); dic += d; pegar(q, t, presencia=True)
            for k, (qx, dx) in enumerate(extras):
                dic += dx; pegar(qx, f"{t}:extra{k + 1}")
        else:
            q, d = sql_agregado(t, s, perfil, path); dic += d; pegar(q, t, presencia=True)

    # rellenos con significado: sin eventos = 0 eventos (no "desconocido")
    cols_n = [r[0] for r in con.execute("DESCRIBE modelo").fetchall()
              if re.search(r"__(n_|.*_(3|6|12)m$|meses_activos|n_contrapartes)", r[0])]
    if cols_n:
        con.execute("CREATE OR REPLACE TABLE modelo AS SELECT * REPLACE (" +
                    ", ".join(f"coalesce({_q(c)}, 0) AS {_q(c)}" for c in cols_n) + ") FROM modelo")

    qt = sql_target()
    if qt:
        extra = ", coalesce(t.target_monto, 0) AS target_monto" if C.TARGET.get("monto") else ""
        con.execute(f"CREATE OR REPLACE TABLE modelo AS SELECT m.*, coalesce(t.target, 0) AS target{extra} "
                    f"FROM modelo m LEFT JOIN ({qt}) t USING (id)")
        tasa = con.execute("SELECT avg(target) FROM modelo").fetchone()[0]
        print(f"  OBJETIVO: tasa de positivos = {tasa:.2%}")
    con.execute(f"CREATE OR REPLACE TABLE modelo AS SELECT *, DATE '{C.FECHA_CORTE}' AS fecha_corte FROM modelo")
    destino = C.OUT_DIR / f"tabla_modelo{sufijo}.parquet"
    # ORDER BY id: DuckDB procesa en paralelo y devuelve las filas en orden distinto en cada corrida.
    # Como la selección (70/30) y los pliegues del modelo se arman por POSICIÓN, sin esto dos corridas
    # con los mismos datos daban Gini y variables distintas. Ordenado = reproducible.
    # round(round(x, 9), 6): DuckDB suma en paralelo y el orden de la suma cambia el último decimal (~1e-15) entre
    # corridas; a LightGBM eso le basta para cortar distinto (Gini ±0.0025). El paso a 9 decimales absorbe ese
    # ruido antes de redondear a 6 (si no, los promedios que caen justo en ...5 se redondean a veces arriba y a
    # veces abajo). 6 decimales sobran para modelar.
    tipos = con.execute("DESCRIBE modelo").fetchall()
    sel = ", ".join(f'round(round("{c}", 9), 6) AS "{c}"' if t in ("DOUBLE", "FLOAT", "REAL") else f'"{c}"' for c, t, *_ in tipos)
    con.execute(f"COPY (SELECT {sel} FROM modelo ORDER BY id) TO '{destino.as_posix()}' (FORMAT parquet)")
    pd.DataFrame(dic, columns=["variable", "tabla_origen", "significado"]).to_csv(
        C.OUT_DIR / "diccionario_variables.csv", index=False, encoding="utf-8-sig")
    n, k = con.execute("SELECT count(*) FROM modelo").fetchone()[0], len(con.execute("DESCRIBE modelo").fetchall())
    bit.registrar("features", f"tabla_modelo{sufijo}", n, k, {"con_target": bool(qt), "corte": C.FECHA_CORTE})
    return destino, specs
