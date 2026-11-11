"""
ALTERNATIVA EN POLARS LAZY para las variables de eventos (mismo resultado que DuckDB).

Cuándo usar Polars en vez de DuckDB:
  - El equipo piensa mejor en "dataframes encadenados" que en SQL.
  - Hay lógica difícil en SQL (bucles por ventana, funciones Python).
Por qué LAZY (scan_parquet, no read_parquet): Polars arma un plan y lo optimiza antes de
leer -> solo lee las columnas usadas (projection pushdown) y empuja el filtro de fecha al
lector de Parquet (predicate pushdown). collect(engine="streaming") procesa por bloques
cuando no entra en RAM.
Regla del equipo: UNA herramienta por paso. Si DuckDB ya hace el paso, Polars es el plan B.

Uso:
  from pipeline.features_polars import rfm_polars
  df = rfm_polars("data/work/silver/transacciones.parquet", id="id_emp", fecha="fec_emision",
                  monto="mto_factura", corte="2025-07-01")
"""
from datetime import date

import polars as pl


def rfm_polars(path, id, fecha, monto, corte, ventanas=(3, 6, 12), prefijo="ev"):
    corte_d = date.fromisoformat(corte)
    vmax = max(ventanas)
    lf = (pl.scan_parquet(path)
          .select([id, fecha, monto])                                   # solo 3 columnas del disco
          .filter((pl.col(fecha) < corte_d) &
                  (pl.col(fecha) >= pl.lit(corte_d).dt.offset_by(f"-{vmax * 2}mo")) &
                  pl.col(id).is_not_null()))
    aggs = [pl.len().alias(f"{prefijo}__n_total"),
            pl.col(monto).sum().alias(f"{prefijo}__{monto}_total"),
            pl.col(monto).mean().alias(f"{prefijo}__{monto}_prom"),
            pl.col(monto).max().alias(f"{prefijo}__{monto}_max"),
            pl.col(monto).std().alias(f"{prefijo}__{monto}_std"),
            (pl.lit(corte_d) - pl.col(fecha).max()).dt.total_days().alias(f"{prefijo}__recencia_dias"),
            (pl.lit(corte_d) - pl.col(fecha).min()).dt.total_days().alias(f"{prefijo}__antiguedad_dias"),
            pl.col(fecha).dt.truncate("1mo").n_unique().alias(f"{prefijo}__meses_activos")]
    for v in ventanas:
        en_v = pl.col(fecha) >= pl.lit(corte_d).dt.offset_by(f"-{v}mo")
        aggs += [en_v.sum().alias(f"{prefijo}__n_{v}m"),
                 pl.col(monto).filter(en_v).sum().alias(f"{prefijo}__{monto}_{v}m")]
    out = lf.group_by(id).agg(aggs)
    if 3 in ventanas and 12 in ventanas:
        out = out.with_columns((pl.col(f"{prefijo}__{monto}_3m") /
                                (pl.col(f"{prefijo}__{monto}_12m") / 4)).alias(f"{prefijo}__tendencia"))
    return out.rename({id: "id"}).collect(engine="streaming")
