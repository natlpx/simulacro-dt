"""
PASO 2 · PERFIL: una ficha por columna + una DECISIÓN con su MOTIVO.

Pregunta que responde: "¿qué FORMA tiene esta columna y qué PAPEL juega?"
  - Forma (se mide, es infalible): vacía, constante, duplicada, identificador, fecha,
    número, binaria, categoría baja/alta, texto libre.
  - Papel (se infiere del nombre + contenido, NO es infalible): id, contraparte, fecha,
    monto, rubro, zona, moneda, estado, target, atributo.
    Por eso todo queda en un CSV que un humano revisa y corrige en decisiones_manual.csv.

Por qué con muestra: las decisiones son sobre la FORMA de la columna; 1 millón de filas
al azar (reservoir) da la misma forma que 50 millones, en segundos. Los conteos totales
de filas sí son exactos.
"""
import re

import pandas as pd

import config as C

# nombres que suelen describir algo que pasó DESPUÉS de la decisión -> posibles fugas
PATRON_POSTERIOR = r"(^|_)(cancel|resultado|final|cierre|baja|castig|recuper|anula|post|desembols|aprob|rechaz|mora_futura)"


def _rol_por_nombre(nombre):
    for rol, patron in C.PATRONES_ROL.items():
        if re.search(patron, nombre):
            return rol
    return None


def perfilar_tabla(con, path):
    """Devuelve DataFrame con una fila por columna."""
    src = path.as_posix()
    n_total = con.execute(f"SELECT count(*) FROM '{src}'").fetchone()[0]
    cols = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM '{src}'").fetchall()]
    meta = [c for c in cols if c.startswith("_")]
    cols = [c for c in cols if not c.startswith("_")]

    con.execute(f"""CREATE OR REPLACE TEMP TABLE _m AS
        SELECT row_number() OVER () AS _rid, * FROM '{src}'
        USING SAMPLE reservoir({C.MUESTRA_PERFIL} ROWS) REPEATABLE (42)""")
    n_m = con.execute("SELECT count(*) FROM _m").fetchone()[0]

    # --- una sola pasada: cada conversión (txt/num/fecha) se calcula UNA vez por celda
    #     en una tabla intermedia y luego se agregan todas las medidas (en lotes de 40 columnas)
    filas = []
    sent_sql = ", ".join(str(x) for x in C.SENTINELAS_NUM)
    for i in range(0, len(cols), 40):
        lote = cols[i:i + 40]
        conv = ["_rid"]
        for j, c in enumerate(lote):
            q = f'"{c}"'
            conv += [f"txt({q}) AS t{j}", f"num({q}) AS n{j}", f"_fecha_txt({q}) AS f{j}",
                     f"CASE WHEN _fecha_txt({q}) IS NULL THEN fecha({q}, true) END AS fs{j}"]
        con.execute(f"CREATE OR REPLACE TEMP TABLE _c AS SELECT {', '.join(conv)} FROM _m")
        exprs = []
        for j in range(len(lote)):
            t, n, fe = f"t{j}", f"n{j}", f"f{j}"
            exprs += [
                f"count({t}) AS nn_{j}", f"approx_count_distinct({t}) AS nd_{j}",
                f"count({n}) AS nnum_{j}", f"count({fe}) AS nfec_{j}",
                f"count({fe}) + count(fs{j}) AS nfecs_{j}",
                f"avg(length({t})) AS len_{j}", f"stddev_pop(length({t})) AS lensd_{j}",
                f"min({n}) AS min_{j}", f"max({n}) AS max_{j}",
                f"approx_quantile({n}, 0.01) AS p01_{j}", f"approx_quantile({n}, 0.50) AS p50_{j}",
                f"approx_quantile({n}, 0.99) AS p99_{j}",
                f"avg({n}) AS mean_{j}", f"stddev_samp({n}) AS std_{j}",
                f"avg(CASE WHEN {n} < 0 THEN 1.0 WHEN {n} IS NOT NULL THEN 0.0 END) AS neg_{j}",
                f"avg(CASE WHEN {n} = 0 THEN 1.0 WHEN {n} IS NOT NULL THEN 0.0 END) AS cero_{j}",
                f"avg(CASE WHEN {n} = round({n}) THEN 1.0 WHEN {n} IS NOT NULL THEN 0.0 END) AS ent_{j}",
                f"bit_xor(hash(CAST(_rid AS VARCHAR) || '|' || coalesce({t}, '<NULL>'))) AS hash_{j}",
                f"min({fe}) AS fmin_{j}", f"max({fe}) AS fmax_{j}",
                f"histogram({n}) FILTER (WHERE {n} IN ({sent_sql})) AS sent_{j}",
            ]
        r = con.execute(f"SELECT {', '.join(exprs)} FROM _c").fetchdf().iloc[0]
        tops_lote = []
        for j, c in enumerate(lote):
            t = con.execute(f"SELECT t{j} v, count(*) n FROM _c WHERE t{j} IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 5").fetchall()
            tops_lote.append(t)
        for j, c in enumerate(lote):
            g = lambda k: r[f"{k}_{j}"]
            t = tops_lote[j]
            filas.append(dict(columna=c, nn=g("nn"), nd=g("nd"), nnum=g("nnum"), nfec=g("nfec"),
                              nfecs=g("nfecs"), len_prom=g("len"), len_sd=g("lensd"),
                              min=g("min"), p01=g("p01"), p50=g("p50"), p99=g("p99"), max=g("max"),
                              media=g("mean"), std=g("std"), pct_neg=g("neg"), pct_cero=g("cero"),
                              pct_entero=g("ent"), hash=g("hash"), fecha_min=g("fmin"), fecha_max=g("fmax"),
                              sent_hist=g("sent"), top_valor=t[0][0] if t else None, top_n=t[0][1] if t else 0,
                              top5=" | ".join(f"{v} ({n})" for v, n in t)))
    con.execute("DROP TABLE IF EXISTS _c")
    df = pd.DataFrame(filas)

    df.insert(0, "tabla", path.stem)
    df["n_total"] = n_total
    df["n_muestra"] = n_m
    df["pct_nulo"] = 1 - df.nn / max(n_m, 1)
    nn = df.nn.clip(lower=1)
    df["pct_num"] = df.nnum / nn
    df["pct_fecha"] = df.nfec / nn
    df["pct_fecha_serial"] = df.nfecs / nn
    df["ratio_distintos"] = (df.nd / nn).clip(upper=1)
    df["top_share"] = df.top_n / nn

    df = _detectar_sentinelas(con, df)
    df = clasificar(df)
    con.execute("DROP TABLE IF EXISTS _m")
    return df


def _detectar_sentinelas(con, df):
    """Un número 'raro' (-1, 9999, 999999...) que pesa >=0.5% es código de vacío si:
    es el mín/máx de la columna, o la columna es continua (>1000 valores distintos):
    en un monto continuo, que el valor exacto 999999 se repita miles de veces no es natural.
    (los conteos ya vienen de la pasada única: sent_hist = {valor: n})"""
    sent = []
    for _, r in df.iterrows():
        encontrados = []
        h = r.get("sent_hist")
        if r.pct_num >= C.U["parse_ok"] and r.nn > 0 and isinstance(h, dict) and h:
            for s_val, n in h.items():
                s_val = float(s_val)
                if (s_val in (r["min"], r["max"]) or r.nd > 1000) and n / r.nn >= C.U["sentinela_min_share"]:
                    encontrados.append(int(s_val))
        sent.append(",".join(str(x) for x in sorted(encontrados)))
    df["sentinelas"] = sent
    return df.drop(columns=["sent_hist"])


def clasificar(df):
    U = C.U
    hash_visto = {}
    forma, rol, decision, motivo = [], [], [], []
    for _, r in df.iterrows():
        nom = r.columna
        rn = _rol_por_nombre(nom)
        es_num = r.pct_num >= U["parse_ok"]
        es_fecha_txt = r.pct_fecha >= U["parse_ok"] and (rn == "fecha" or r.pct_num < 0.5)
        es_fecha_serial = rn == "fecha" and r.pct_fecha_serial >= U["parse_ok"]
        f, ro, d, m = None, rn or "atributo", None, ""

        if r.nn == 0 or r.pct_nulo >= U["nulos_drop"]:
            f, d, m = "vacia", "DROP", f"{r.pct_nulo:.1%} vacía"
        elif (r.nd <= 1 or r.top_share >= U["top_constante"]) and r.pct_nulo >= 0.005:
            # un solo valor + vacíos: lo que informa es si HAY dato (p.ej. fecha de cancelación)
            f, d, m = "presencia", ("FECHA+IND" if (es_fecha_txt or es_fecha_serial) else "CATEGORIA+IND"), \
                      f"un solo valor ('{r.top_valor}') y {r.pct_nulo:.0%} vacía -> vale como indicador"
        elif r.nd <= 1 or r.top_share >= U["top_constante"]:
            f, d, m = "constante", "DROP", f"'{r.top_valor}' ocupa {r.top_share:.1%}"
        elif r.hash in hash_visto:
            f, d, m = "duplicada", "DROP", f"copia exacta de {hash_visto[r.hash]}"
        elif rn == "target" and r.nd <= 2:
            f, ro, d, m = "binaria", "target", "TARGET", "nombre de objetivo y 2 valores"
        elif es_fecha_txt or es_fecha_serial:
            f, ro, d, m = "fecha", "fecha", "FECHA", f"{max(r.pct_fecha, r.pct_fecha_serial):.0%} parsea a fecha"
        elif rn in ("id", "contraparte") and not (es_num and r.pct_entero < 0.99):
            f, d, m = "id", "LLAVE", "nombre de llave"
        elif r.ratio_distintos >= U["id_ratio"] and not es_num and (r.len_sd or 0) < 1.5 and r.len_prom < 25:
            f, ro, d, m = "id", "id", "LLAVE", f"{r.ratio_distintos:.0%} distintos y largo fijo"
        elif es_num and r.pct_entero >= 0.999 and r.ratio_distintos >= U["id_ratio"] and (r.len_sd or 0) < 0.5 and r.len_prom >= 6:
            f, ro, d, m = "id", "id", "LLAVE", "entero único de largo fijo (código)"
        elif es_num and r.nd <= 2:
            f, d, m = "binaria", "NUMERO", "0/1"
        elif es_num:
            f, d, m = "numero", "NUMERO", f"{r.pct_num:.0%} parsea a número"
            if rn not in ("monto",) and ro in ("rubro", "zona", "estado") and r.nd <= U["card_alta"]:
                f, d, m = "categoria_baja", "CATEGORIA", "código numérico de categoría"
        elif r.len_prom > U["texto_largo"] and r.nd > U["card_alta"]:
            f, d, m = "texto_libre", "DROP", f"texto libre (largo {r.len_prom:.0f})"
        elif r.nd <= 2:
            f, d, m = "binaria", "CATEGORIA", "2 valores"
        elif r.nd <= U["card_alta"]:
            f, d, m = "categoria_baja", "CATEGORIA", f"{int(r.nd)} categorías"
        else:
            f, d, m = "categoria_alta", "CATEGORIA", f"{int(r.nd)} categorías -> frecuencia/target enc."

        # ajustes de rol por contenido
        if ro == "monto" and f != "numero":
            ro = "atributo"
        if ro in ("rubro", "zona", "moneda", "estado") and f not in ("categoria_baja", "categoria_alta", "binaria"):
            ro = "atributo"
        if ro == "fecha" and f != "fecha":
            ro = "atributo"
        if ro == "atributo" and f == "categoria_baja" and r.top5 and re.search(r"\b(PEN|USD|SOLES|DOLARES)\b", str(r.top5)):
            ro = "moneda"

        # modificadores
        if d not in ("DROP", "TARGET", "LLAVE") and not d.endswith("+IND") and r.pct_nulo >= U["nulos_indicador"]:
            m += f" | {r.pct_nulo:.0%} vacía -> + indicador tiene_"
            d = d + "+IND"
        if d != "DROP" and re.search(PATRON_POSTERIOR, nom):
            m += " | ¿POSTERIOR AL CORTE? revisar fuga"
        if r.sentinelas:
            m += f" | centinelas {r.sentinelas} -> NULL"
        hash_visto.setdefault(r.hash, nom)
        forma.append(f); rol.append(ro); decision.append(d); motivo.append(m)
    df["forma"], df["rol"], df["decision"], df["motivo"] = forma, rol, decision, motivo
    return df


def aplicar_manual(df):
    """decisiones_manual.csv (tabla,columna,decision,rol) pisa lo automático. Aquí entra el humano."""
    # En el evento, las decisiones van DENTRO de config_evento.py (DECISIONES_MANUAL = [dict(...), ...])
    # para no subir un .csv al repo: el control automático avisa si ve archivos de datos.
    if getattr(C, "DECISIONES_MANUAL", None):
        man = pd.DataFrame(C.DECISIONES_MANUAL).astype(str).replace("None", "").fillna("")
    else:
        p = C.BASE / "decisiones_manual.csv"
        if not p.exists():
            return df
        man = pd.read_csv(p, dtype=str).fillna("")
    for _, m in man.iterrows():
        sel = (df.tabla == m.tabla) & (df.columna == m.columna)
        if m.get("decision"):
            df.loc[sel, "decision"] = m.decision
            df.loc[sel, "motivo"] = df.loc[sel, "motivo"] + " | MANUAL"
        if m.get("rol"):
            df.loc[sel, "rol"] = m.rol
    return df


COLS_SALIDA = ["tabla", "columna", "decision", "forma", "rol", "motivo", "pct_nulo", "nd", "ratio_distintos",
               "top_share", "top5", "pct_num", "pct_fecha", "min", "p01", "p50", "p99", "max", "media",
               "pct_neg", "pct_cero", "sentinelas", "fecha_min", "fecha_max", "len_prom", "n_total"]


def ejecutar(con, bit, tablas):
    print("\n== PASO 2 · PERFIL ==")
    todos = []
    for p in tablas:
        df = perfilar_tabla(con, p)
        todos.append(df)
        cuenta = df.decision.str.replace(r"\+IND", "", regex=True).value_counts().to_dict()
        roles = {k: v for k, v in df.rol.value_counts().to_dict().items() if k != "atributo"}
        bit.registrar("perfil", p.stem, int(df.n_total.iloc[0]), len(df), {"decisiones": cuenta, "roles": roles,
                      "drop": int((df.decision == "DROP").sum())})
    perfil = aplicar_manual(pd.concat(todos, ignore_index=True))
    perfil[COLS_SALIDA].to_csv(C.OUT_DIR / "perfil_columnas.csv", index=False, encoding="utf-8-sig")
    print(f"  -> {C.OUT_DIR/'perfil_columnas.csv'}  (revísenlo; correcciones en decisiones_manual.csv)")
    return perfil
