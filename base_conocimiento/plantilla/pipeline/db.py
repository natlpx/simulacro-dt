"""
Conexión DuckDB + MACROS SQL de limpieza.

Por qué DuckDB: es SQL embebido (no hay servidor), lee Parquet/CSV directo del disco,
procesa por bloques y, si falta RAM, usa disco (spill). Con 8 GB de datos en una laptop
de 8-16 GB es lo que evita el "MemoryError" de pandas.

Por qué macros: la limpieza se escribe UNA vez como función SQL y se aplica a 200 columnas
generando el SQL automáticamente. Nadie limpia columna por columna a mano.
"""
import duckdb
import config as C


def _lista_sql(valores):
    return "[" + ", ".join("'" + v.replace("'", "''") + "'" for v in valores) + "]"


def conectar(path_db=None):
    C.TMP_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path_db) if path_db else ":memory:")
    con.execute(f"SET memory_limit='{C.MEMORY_LIMIT}'")
    con.execute(f"SET threads={C.THREADS}")
    con.execute(f"SET temp_directory='{C.TMP_DIR.as_posix()}'")
    con.execute("SET preserve_insertion_order=false")  # menos RAM en COPY grandes
    registrar_macros(con)
    return con


def registrar_macros(con):
    sent = _lista_sql(C.SENTINELAS_TXT)
    fsent = _lista_sql(C.FECHAS_CENTINELA)

    # 1) Texto: quita espacios dobles, tildes, mayúsculas; centinelas -> NULL
    con.execute(f"""
    CREATE OR REPLACE MACRO txt(s) AS (
        CASE WHEN s IS NULL OR list_contains({sent}, upper(trim(CAST(s AS VARCHAR)))) THEN NULL
             ELSE upper(strip_accents(trim(regexp_replace(CAST(s AS VARCHAR), '\\s+', ' ', 'g'))))
        END)""")

    # 2) Identificador: texto limpio + quita el ".0" que Excel pega a los números
    #    (RUC 20123456789 leído como float = "20123456789.0" -> rompe los JOIN)
    con.execute("""
    CREATE OR REPLACE MACRO idn(s) AS (
        regexp_replace(regexp_replace(txt(s), '\\.0+$', ''), '[^A-Z0-9\\-]', '', 'g'))""")

    # 3) Número escrito como texto: 'S/ 1,234.50', '1.234,50', '(500)', '12%', 'US$ 3,000'
    con.execute("""
    CREATE OR REPLACE MACRO _num_parse(c) AS TRY_CAST(
        CASE
          WHEN regexp_full_match(c, '-?\\d{1,3}(\\.\\d{3})+(,\\d+)?') THEN replace(replace(c, '.', ''), ',', '.')  -- 1.234.567,89
          WHEN regexp_full_match(c, '-?\\d{1,3}(,\\d{3})+(\\.\\d+)?') THEN replace(c, ',', '')                       -- 1,234,567.89
          WHEN regexp_full_match(c, '-?\\d+,\\d+')                    THEN replace(c, ',', '.')                       -- 1234,5
          ELSE c END AS DOUBLE)""")
    con.execute(f"""
    CREATE OR REPLACE MACRO _num_fin(b) AS (
        CASE WHEN b IS NULL OR b = '' OR list_contains({sent}, b) THEN NULL
             ELSE (CASE WHEN b LIKE '(%)' THEN -1 ELSE 1 END)
                  * _num_parse(replace(replace(b, '(', ''), ')', ''))
        END)""")
    con.execute("""
    CREATE OR REPLACE MACRO num(s) AS _num_fin(
        regexp_replace(upper(trim(CAST(s AS VARCHAR))), '(S/\\.?|US\\$|USD|PEN|SOLES|\\$|%|\\s)', '', 'g'))""")

    # 4) Fecha: prueba varios formatos, 'AAAAMM' (periodo) y número serial de Excel.
    #    serial=true solo para columnas cuyo NOMBRE dice fecha (si no, el monto 45000
    #    se convertiría en el 15/03/2023).
    # Enrutador de fechas: una regex barata decide el formato ANTES de parsear.
    # (try_strptime con 12 formatos a ciegas es ~25x más lento en columnas que no son fecha)
    con.execute("""
    CREATE OR REPLACE MACRO _fecha_s(s) AS (
        CASE
          WHEN s IS NULL OR s = '' THEN NULL
          WHEN regexp_full_match(s, '\\d{4}-\\d{1,2}-\\d{1,2}([ T].*)?')
               THEN CAST(try_strptime(split_part(replace(s, 'T', ' '), ' ', 1), '%Y-%m-%d') AS DATE)
          WHEN regexp_full_match(s, '\\d{1,2}/\\d{1,2}/\\d{4}( .*)?')
               THEN CAST(try_strptime(split_part(s, ' ', 1), '%d/%m/%Y') AS DATE)
          WHEN regexp_full_match(s, '(19|20)\\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\\d|3[01])')
               THEN CAST(try_strptime(s, '%Y%m%d') AS DATE)
          WHEN regexp_full_match(s, '(19|20)\\d{2}(0[1-9]|1[0-2])')
               THEN CAST(try_strptime(s || '01', '%Y%m%d') AS DATE)
          WHEN regexp_full_match(s, '\\d{1,2}-\\d{1,2}-\\d{4}')   THEN CAST(try_strptime(s, '%d-%m-%Y') AS DATE)
          WHEN regexp_full_match(s, '\\d{4}/\\d{1,2}/\\d{1,2}( .*)?') THEN CAST(try_strptime(split_part(s, ' ', 1), '%Y/%m/%d') AS DATE)
          WHEN regexp_full_match(s, '\\d{1,2}\\.\\d{1,2}\\.\\d{4}') THEN CAST(try_strptime(s, '%d.%m.%Y') AS DATE)
          WHEN regexp_full_match(s, '\\d{1,2}/\\d{1,2}/\\d{2}')   THEN CAST(try_strptime(s, '%d/%m/%y') AS DATE)
        END)""")
    con.execute("CREATE OR REPLACE MACRO _fecha_txt(s) AS _fecha_s(trim(CAST(s AS VARCHAR)))")
    con.execute(f"""
    CREATE OR REPLACE MACRO fecha(s, serial) AS (
        CASE WHEN list_contains({fsent}, CAST(_fecha_txt(s) AS VARCHAR)) THEN NULL
             WHEN _fecha_txt(s) IS NOT NULL THEN _fecha_txt(s)
             WHEN serial AND regexp_full_match(trim(CAST(s AS VARCHAR)), '\\d{{5}}(\\.\\d+)?')
                  AND TRY_CAST(s AS DOUBLE) BETWEEN 20000 AND 60000
                  THEN DATE '1899-12-30' + CAST(floor(TRY_CAST(s AS DOUBLE)) AS INTEGER)
             ELSE NULL END)""")
