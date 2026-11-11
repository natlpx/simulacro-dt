"""
PASO 3 · LIMPIEZA: bronze (texto) -> silver (tipado y limpio). Una regla por CLASE de
columna, no por columna: el SQL se genera solo a partir de perfil_columnas.csv.

REGLA DE ORO: la limpieza solo hace transformaciones FILA A FILA que no aprenden nada
de los datos (parsear, recortar, anular centinelas). Todo lo que aprende de los datos
(medianas, percentiles para recortar extremos, categorías raras, target encoding) va en
regularizar.py y se ajusta SOLO con train. Si no, se filtra información del futuro.

  decisión      | transformación SQL
  --------------|-----------------------------------------------------------
  DROP          | no se selecciona (vacía, constante, duplicada, texto libre)
  LLAVE         | idn(): mayúsculas, sin espacios, sin ".0" de Excel
  FECHA         | fecha(): 12 formatos + AAAAMM + serial Excel; 1900-01-01 -> NULL
  NUMERO        | num(): 'S/ 1,234.50' -> 1234.5 ; centinelas (-1, 9999...) -> NULL
  CATEGORIA     | txt(): 'Comercio ' / 'COMERCIO' / 'comércio' -> 'COMERCIO'
  TARGET        | 1/0 desde 1/0, S/N, SI/NO, TRUE/FALSE
  ...+IND       | además tiene_<col> = 1 si hay dato (la ausencia también informa)
"""
import time

import pandas as pd

import config as C
from pipeline.perfil import _rol_por_nombre


def expr_columna(r):
    q = f'"{r.columna}"'
    d = r.decision.replace("+IND", "")
    if d == "LLAVE":
        e = f"idn({q})"
    elif d == "FECHA":
        serial = "true" if _rol_por_nombre(r.columna) == "fecha" else "false"
        e = f"fecha({q}, {serial})"
    elif d == "NUMERO":
        s = str(r.sentinelas or "").strip()
        e = f"CASE WHEN num({q}) IN ({s}) THEN NULL ELSE num({q}) END" if s and s != "nan" else f"num({q})"
    elif d == "TARGET":
        e = (f"CASE WHEN txt({q}) IN ('1','1.0','S','SI','Y','YES','TRUE','VERDADERO') THEN 1 "
             f"WHEN txt({q}) IN ('0','0.0','N','NO','FALSE','FALSO') THEN 0 END")
    elif d == "CATEGORIA":
        e = f"txt({q})"
    else:
        return []
    out = [f"{e} AS {q}"]
    if r.decision.endswith("+IND"):
        out.append(f'CAST({q} IS NOT NULL AS TINYINT) AS "tiene_{r.columna}"')
    return out


def limpiar_tabla(con, bit, path_bronze, perfil_t):
    silver = C.WORK_DIR / "silver"
    silver.mkdir(parents=True, exist_ok=True)
    destino = silver / f"{path_bronze.stem}.parquet"
    src = path_bronze.as_posix()
    t0 = time.time()

    sel = [x for _, r in perfil_t.iterrows() for x in expr_columna(r)]
    distinct = "DISTINCT" if C.QUITAR_DUPLICADOS_EXACTOS else ""
    con.execute(f"COPY (SELECT {distinct} {', '.join(sel)} FROM '{src}') TO '{destino.as_posix()}' "
                f"(FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 200000)")

    # ---------- conciliación: ¿qué se perdió al convertir? (por columna)
    convertidas = perfil_t[perfil_t.decision.str.replace("+IND", "", regex=False).isin(["NUMERO", "FECHA", "LLAVE", "TARGET"])]
    detalle = []
    if len(convertidas):
        exprs = []
        for _, r in convertidas.iterrows():
            q = f'"{r.columna}"'
            exprs.append(f"count(txt({q})) AS a_{len(exprs)}")
        antes = con.execute(f"SELECT {', '.join(exprs)} FROM '{src}'").fetchone()
        # se mide sobre las MISMAS filas crudas (sin DISTINCT) para no confundir duplicados con fallos
        exprs_d = [f"count({expr_columna(r)[0].rsplit(' AS ', 1)[0]})" for _, r in convertidas.iterrows()]
        despues = con.execute(f"SELECT {', '.join(exprs_d)} FROM '{src}'").fetchone()
        for (_, r), a, b in zip(convertidas.iterrows(), antes, despues):
            detalle.append(dict(tabla=path_bronze.stem, columna=r.columna, decision=r.decision,
                                con_dato_antes=a, con_dato_despues=b, anulados=a - b,
                                pct_anulado=round((a - b) / a, 4) if a else 0))

    # ---------- bitácora: filas, columnas, duplicados y suma de montos antes/después
    n_antes = con.execute(f"SELECT count(*) FROM '{src}'").fetchone()[0]
    n_desp = con.execute(f"SELECT count(*) FROM '{destino.as_posix()}'").fetchone()[0]
    ncol = len(con.execute(f"DESCRIBE SELECT * FROM '{destino.as_posix()}'").fetchall())
    extra = {"duplicados_quitados": n_antes - n_desp,
             "cols_eliminadas": int((perfil_t.decision == "DROP").sum())}
    montos = perfil_t[(perfil_t.rol == "monto") & (perfil_t.decision.str.startswith("NUMERO"))].columna.tolist()[:3]
    for m in montos:
        s_raw = con.execute(f'SELECT sum(num("{m}")) FROM \'{src}\'').fetchone()[0] or 0
        s_cln = con.execute(f'SELECT sum("{m}") FROM \'{destino.as_posix()}\'').fetchone()[0] or 0
        extra[f"suma_{m}_antes"] = round(s_raw, 2)
        extra[f"suma_{m}_despues"] = round(s_cln, 2)
    bit.registrar("limpieza", path_bronze.stem, n_desp, ncol, extra, time.time() - t0)
    return destino, detalle


def ejecutar(con, bit, tablas_bronze, perfil):
    print("\n== PASO 3 · LIMPIEZA ==")
    salidas, detalle = [], []
    for p in tablas_bronze:
        d, det = limpiar_tabla(con, bit, p, perfil[perfil.tabla == p.stem])
        salidas.append(d)
        detalle += det
    det = pd.DataFrame(detalle)
    det.to_csv(C.OUT_DIR / "limpieza_detalle.csv", index=False, encoding="utf-8-sig")
    malos = det[det.pct_anulado > 0.05] if len(det) else det
    for _, r in malos.iterrows():
        print(f"  ⚠ {r.tabla}.{r.columna}: {r.pct_anulado:.1%} de valores no se pudieron convertir -> revisar formato")
    return salidas
