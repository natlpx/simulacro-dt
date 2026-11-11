"""
PASO 4 · LLAVES Y GRANO: ¿cómo se unen las 4 tablas y qué representa cada fila?

Por qué es un paso propio: el error más caro en un concurso no es un mal modelo, es un
JOIN que multiplica filas (1 empresa x 300 transacciones = 300 veces su monto) o que
pierde el 30% de empresas porque el RUC viene "20123456789" en una tabla y
"20123456789.0" en otra. Aquí se MIDE, no se supone:

  - grano: ¿qué columna(s) identifican una fila única? (COUNT vs COUNT DISTINCT)
  - relaciones: para cada par de llaves en tablas distintas, % de valores que calzan.
    cobertura_a = de los valores de A, cuántos existen en B (y viceversa).
    1:1, 1:N o N:M sale de si la llave es única en cada lado.
"""
import itertools

import pandas as pd

import config as C


def granos(con, tablas, perfil):
    filas = []
    for p in tablas:
        llaves = perfil[(perfil.tabla == p.stem) & (perfil.decision == "LLAVE")].columna.tolist()
        fechas = perfil[(perfil.tabla == p.stem) & (perfil.decision.str.startswith("FECHA"))].columna.tolist()
        n = con.execute(f"SELECT count(*) FROM '{p.as_posix()}'").fetchone()[0]
        for k in llaves:
            nd = con.execute(f'SELECT count(DISTINCT "{k}") FROM \'{p.as_posix()}\'').fetchone()[0]
            nn = con.execute(f'SELECT count(*) - count("{k}") FROM \'{p.as_posix()}\'').fetchone()[0]
            fila = dict(tabla=p.stem, llave=k, filas=n, distintos=nd, nulos=nn, unica=(nd == n and nn == 0),
                        filas_por_llave=round(n / max(nd, 1), 2))
            if nd < n and fechas:  # ¿llave + fecha es único? (grano tipo panel: empresa x mes)
                f = fechas[0]
                nd2 = con.execute(f'SELECT count(*) FROM (SELECT DISTINCT "{k}", "{f}" FROM \'{p.as_posix()}\')').fetchone()[0]
                fila["unica_con_" + "fecha"] = f"{k}+{f}: {nd2 == n}"
            filas.append(fila)
    return pd.DataFrame(filas)


def relaciones(con, tablas, perfil, gr):
    llaves = [(p, k) for p in tablas
              for k in perfil[(perfil.tabla == p.stem) & (perfil.decision == "LLAVE")].columna]
    filas = []
    for (pa, ka), (pb, kb) in itertools.combinations(llaves, 2):
        if pa == pb:
            continue
        r = con.execute(f"""
            WITH a AS (SELECT DISTINCT "{ka}" v FROM '{pa.as_posix()}' WHERE "{ka}" IS NOT NULL),
                 b AS (SELECT DISTINCT "{kb}" v FROM '{pb.as_posix()}' WHERE "{kb}" IS NOT NULL)
            SELECT (SELECT count(*) FROM a), (SELECT count(*) FROM b),
                   (SELECT count(*) FROM a JOIN b USING (v))""").fetchone()
        na, nb, ni = r
        if ni == 0:
            continue
        ua = bool(gr[(gr.tabla == pa.stem) & (gr.llave == ka)].unica.iloc[0])
        ub = bool(gr[(gr.tabla == pb.stem) & (gr.llave == kb)].unica.iloc[0])
        tipo = {(True, True): "1:1", (True, False): "1:N", (False, True): "N:1", (False, False): "N:M"}[(ua, ub)]
        filas.append(dict(tabla_a=pa.stem, llave_a=ka, tabla_b=pb.stem, llave_b=kb, tipo=tipo,
                          cobertura_a=round(ni / na, 4), cobertura_b=round(ni / nb, 4), en_comun=ni,
                          alerta=("N:M -> un JOIN directo MULTIPLICA filas; agregar antes" if tipo == "N:M" else
                                  "baja cobertura: revisar formato de llave" if max(ni / na, ni / nb) < 0.5 else "")))
    return pd.DataFrame(filas).sort_values("en_comun", ascending=False) if filas else pd.DataFrame()


def entidad(gr, rel):
    """La entidad (fila del modelo) = llave única que más calza con otras tablas."""
    if C.ENTIDAD:
        return C.ENTIDAD
    unicas = gr[gr.unica]
    if unicas.empty:
        return None
    mejor, score = None, -1
    for _, u in unicas.iterrows():
        s = 0
        if len(rel):
            m = rel[((rel.tabla_a == u.tabla) & (rel.llave_a == u.llave)) | ((rel.tabla_b == u.tabla) & (rel.llave_b == u.llave))]
            s = m.en_comun.sum() + 1e6 * m.shape[0]
        s += u.filas * 1e-3
        if s > score:
            mejor, score = (u.tabla, u.llave), s
    return mejor


def ejecutar(con, bit, tablas, perfil):
    print("\n== PASO 4 · LLAVES Y GRANO ==")
    gr = granos(con, tablas, perfil)
    rel = relaciones(con, tablas, perfil, gr)
    gr.to_csv(C.OUT_DIR / "granos.csv", index=False, encoding="utf-8-sig")
    rel.to_csv(C.OUT_DIR / "relaciones.csv", index=False, encoding="utf-8-sig")
    ent = entidad(gr, rel)
    for _, r in rel.iterrows():
        print(f"  {r.tabla_a}.{r.llave_a} ~ {r.tabla_b}.{r.llave_b}  [{r.tipo}]  "
              f"cobertura {r.cobertura_a:.0%} / {r.cobertura_b:.0%}  {r.alerta}")
    print(f"  ENTIDAD del modelo: {ent}  (fijarla en config.ENTIDAD si no es la correcta)")
    bit.registrar("llaves", "relaciones", len(rel), len(gr), {"entidad": ent})
    return gr, rel, ent
