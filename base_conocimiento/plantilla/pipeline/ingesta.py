"""
PASO 1 · INGESTA: Excel / CSV  ->  Parquet "bronze" (todo como TEXTO).

Por qué TODO como texto en este paso:
  Si dejamos que la herramienta "adivine" los tipos con las primeras 1000 filas, un RUC se
  vuelve número (pierde ceros), una fecha 05/03 se lee como 3 de mayo, y la fila 2.000.001
  con "S/D" en una columna numérica hace caer la carga después de 20 minutos.
  Leer todo como texto NUNCA falla. Los tipos se deciden después, con el perfil, midiendo.

Por qué Parquet: columnar + comprimido + con tipos. Se lee solo la columna que se necesita.
  Excel se lee UNA vez en la vida; desde aquí en adelante nadie vuelve a abrir el Excel.

Motores para Excel (en orden de preferencia, se elige solo):
  1. DuckDB read_xlsx  -> streaming, poca RAM. Requiere la extensión 'excel' instalada
     ANTES del concurso (con internet): python -c "import duckdb; duckdb.sql('INSTALL excel')"
  2. fastexcel/calamine (Rust) -> muy rápido, pero carga la hoja entera en RAM.
     Si la hoja es muy grande lee por BLOQUES DE COLUMNAS para no reventar la memoria.
  3. openpyxl read_only -> lento pero memoria constante (último recurso).
"""
import re
import time
import unicodedata
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

import config as C
from pipeline import plataforma

EXT_EXCEL = {".xlsx", ".xlsm", ".xlsb", ".xls"}
EXT_CSV = {".csv", ".txt", ".tsv"}
EXT_OTROS = {".parquet", ".json", ".jsonl", ".ndjson"}


def _expandir_zips(raw_dir):
    """Un .zip se descomprime una vez en una carpeta hermana (no se toca el original)."""
    import zipfile
    for z in list(Path(raw_dir).rglob("*.zip")):
        dest = z.with_suffix("")
        if not dest.exists():
            with zipfile.ZipFile(z) as f:
                f.extractall(dest)
            print(f"  · descomprimido {z.name} -> {dest.name}/")


# ---------------------------------------------------------------- nombres de columnas
def normalizar_nombre(n, i):
    """'Fecha de Emisión ' -> 'fecha_de_emision'. Nombres vacíos -> col_<i>."""
    n = "" if n is None else str(n)
    n = unicodedata.normalize("NFKD", n).encode("ascii", "ignore").decode()
    n = re.sub(r"[^0-9a-zA-Z]+", "_", n.strip().lower()).strip("_")
    if not n or n.startswith("unnamed") or n.startswith("__unnamed"):
        n = f"col_{i}"
    if n[0].isdigit():
        n = "c_" + n
    return n


def nombres_unicos(nombres):
    vistos, out = {}, []
    for i, n in enumerate(nombres):
        b = normalizar_nombre(n, i)
        if b in vistos:
            vistos[b] += 1
            b = f"{b}_{vistos[b]}"
        else:
            vistos[b] = 0
        out.append(b)
    return out


def nombre_tabla(path, hoja=None):
    base = normalizar_nombre(Path(path).stem, 0)
    return base if hoja is None else f"{base}__{normalizar_nombre(hoja, 0)}"


# ---------------------------------------------------------------- escritura común
def _escribir_tabla_texto(tabla: pa.Table, destino: Path, archivo, hoja, writer=None):
    """Castea todo a string, normaliza nombres y agrega columnas de linaje."""
    cols = nombres_unicos(tabla.column_names)
    arrays = [tabla.column(i).cast(pa.string()) if tabla.column(i).type != pa.string() else tabla.column(i)
              for i in range(tabla.num_columns)]
    t = pa.table(arrays, names=cols)
    t = t.append_column("_archivo", pa.array([Path(archivo).name] * t.num_rows, pa.string()))
    t = t.append_column("_hoja", pa.array([str(hoja or "")] * t.num_rows, pa.string()))
    if writer is None:
        writer = pq.ParquetWriter(destino, t.schema, compression="zstd")
    writer.write_table(t, row_group_size=200_000)
    return writer


# ---------------------------------------------------------------- CSV
def detectar_encoding(path, muestra=8_000_000):
    """Lee los primeros MB como bytes: si no decodifican como utf-8, es latin-1 (típico de Excel
    en Windows). Se detecta ANTES de leer porque con ignore_errors=true un encoding equivocado
    no da error: descarta filas en silencio (puede dejar la tabla en 0 filas)."""
    with open(path, "rb") as f:
        b = f.read(muestra)
    try:
        b[: len(b) - 4 if len(b) == muestra else len(b)].decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        return "latin-1"



def ingestar_csv(con, path: Path, destino: Path):
    """DuckDB detecta separador/encabezado; all_varchar evita fallos de tipo;
    ignore_errors + null_padding toleran filas rotas (se cuentan en la bitácora)."""
    src = path.as_posix()
    n_lineas = None
    enc = detectar_encoding(path)
    if enc != "utf-8":
        print(f"     · {path.name}: codificación {enc} (no utf-8)")
    con.execute(f"""
        CREATE OR REPLACE TEMP VIEW _csv AS
        SELECT * FROM read_csv('{src}', all_varchar=true, header=true, sample_size=-1,
                               ignore_errors=true, null_padding=true, strict_mode=false,
                               encoding='{enc}')""")
    cols = [r[0] for r in con.execute("DESCRIBE _csv").fetchall()]
    nuevos = nombres_unicos(cols)
    sel = ", ".join(f'"{a}" AS "{b}"' for a, b in zip(cols, nuevos))
    con.execute(f"""COPY (SELECT {sel}, '{path.name}' AS _archivo, '' AS _hoja FROM _csv)
                    TO '{destino.as_posix()}' (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 200000)""")
    try:  # filas físicas vs filas cargadas: si difieren, hubo filas rotas
        with open(path, "rb") as f:
            n_lineas = sum(1 for _ in f) - 1
    except Exception:
        pass
    return n_lineas


# ---------------------------------------------------------------- Excel
def _hojas_excel(path):
    try:
        import fastexcel
        return fastexcel.read_excel(str(path)).sheet_names
    except Exception:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True)
        return wb.sheetnames


def _excel_duckdb(con, path, hoja, destino):
    con.execute("LOAD excel")
    con.execute(f"""CREATE OR REPLACE TEMP VIEW _xl AS
        SELECT * FROM read_xlsx('{path.as_posix()}', sheet='{hoja}', all_varchar=true,
                                ignore_errors=true, empty_as_varchar=true)""")
    cols = [r[0] for r in con.execute("DESCRIBE _xl").fetchall()]
    sel = ", ".join(f'"{a}" AS "{b}"' for a, b in zip(cols, nombres_unicos(cols)))
    con.execute(f"""COPY (SELECT {sel}, '{path.name}' AS _archivo, '{hoja}' AS _hoja FROM _xl)
                    TO '{destino.as_posix()}' (FORMAT parquet, COMPRESSION zstd)""")


def _excel_fastexcel(path, hoja, destino, bloque_cols=None):
    """calamine es ~10x más rápido que openpyxl. Si el archivo es grande se lee en bloques
    de columnas (use_columns) y se pega horizontalmente: el pico de RAM baja proporcionalmente."""
    import fastexcel
    rd = fastexcel.read_excel(str(path))
    head = rd.load_sheet(hoja, n_rows=1, dtypes="string")
    todas = [c.name for c in head.available_columns()] if hasattr(head, "available_columns") else head.to_arrow().column_names
    if not bloque_cols or bloque_cols >= len(todas):
        t = rd.load_sheet(hoja, dtypes="string").to_arrow()
    else:
        partes = []
        for i in range(0, len(todas), bloque_cols):
            idx = list(range(i, min(i + bloque_cols, len(todas))))
            partes.append(rd.load_sheet(hoja, use_columns=idx, dtypes="string").to_arrow())
        arrays, names = [], []
        for p in partes:
            arrays += [p.column(j) for j in range(p.num_columns)]
            names += p.column_names
        t = pa.table(arrays, names=names)
    w = _escribir_tabla_texto(t, destino, path, hoja)
    w.close()


def _excel_openpyxl(path, hoja, destino, lote=100_000):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[hoja]
    filas = ws.iter_rows(values_only=True)
    header = next(filas)
    writer, buf = None, []
    def volcar(buf, writer):
        cols = list(zip(*buf)) if buf else [[] for _ in header]
        t = pa.table([pa.array([None if v is None else str(v) for v in c], pa.string()) for c in cols],
                     names=[str(h) for h in header])
        return _escribir_tabla_texto(t, destino, path, hoja, writer)
    for r in filas:
        buf.append(r[:len(header)] + (None,) * (len(header) - len(r)))
        if len(buf) >= lote:
            writer = volcar(buf, writer); buf = []
    if buf or writer is None:
        writer = volcar(buf, writer)
    writer.close()


def ingestar_excel(con, path: Path, out_dir: Path, ram_gb=8):
    """Una tabla por hoja. Si varias hojas tienen las mismas columnas (Excel partido por el
    límite de 1.048.576 filas) se unen en una sola tabla con UNION ALL BY NAME."""
    salidas = []
    tam_gb = path.stat().st_size / 1e9
    for hoja in _hojas_excel(path):
        destino = out_dir / f"{nombre_tabla(path, hoja)}.parquet"
        t0 = time.time()
        motor = None
        for intento in ("duckdb", "fastexcel", "openpyxl"):
            try:
                if intento == "duckdb":
                    _excel_duckdb(con, path, hoja, destino)
                elif intento == "fastexcel":
                    # xlsx comprime ~5-10x: un archivo de 1 GB puede ocupar 8+ GB en RAM
                    bloque = 25 if tam_gb * 8 > ram_gb * 0.5 else None
                    _excel_fastexcel(path, hoja, destino, bloque_cols=bloque)
                else:
                    _excel_openpyxl(path, hoja, destino)
                motor = intento
                break
            except Exception as e:
                print(f"     · motor {intento} no disponible para {path.name}/{hoja}: {str(e)[:90]}")
        if motor is None:
            raise RuntimeError(f"No se pudo leer {path}/{hoja}")
        salidas.append((destino, hoja, motor, time.time() - t0))
    return salidas


# ---------------------------------------------------------------- orquestador del paso
def ejecutar(con, bit, raw_dir=None, ram_gb=None):
    raw_dir = Path(raw_dir or C.RAW_DIR)
    ram_gb = ram_gb or getattr(C, "RAM_GB", 8)
    bronze = C.WORK_DIR / "bronze"
    bronze.mkdir(parents=True, exist_ok=True)
    for f in bronze.glob("*.parquet"):
        f.unlink()
    _expandir_zips(raw_dir)
    archivos = sorted(p for p in raw_dir.rglob("*") if p.is_file() and not p.name.startswith(".")
                      and p.suffix.lower() in EXT_EXCEL | EXT_CSV | EXT_OTROS)
    if not archivos:
        raise FileNotFoundError(f"No hay archivos en {raw_dir}")
    print(f"\n== PASO 1 · INGESTA ({len(archivos)} archivos) ==")
    for p in archivos:
        ext = p.suffix.lower()
        if ext in EXT_CSV:
            destino = bronze / f"{nombre_tabla(p)}.parquet"
            t0 = time.time()
            n_lineas = ingestar_csv(con, p, destino)
            _registrar(con, bit, destino, p, "csv", time.time() - t0, n_lineas)
        elif ext in (".json", ".jsonl", ".ndjson"):
            destino = bronze / f"{nombre_tabla(p)}.parquet"
            con.execute(f"CREATE OR REPLACE TEMP VIEW _pq AS SELECT * FROM read_json_auto('{p.as_posix()}', sample_size=-1)")
            cols = [r[0] for r in con.execute("DESCRIBE _pq").fetchall()]
            sel = ", ".join(f'CAST("{a}" AS VARCHAR) AS "{b}"' for a, b in zip(cols, nombres_unicos(cols)))
            con.execute(f"COPY (SELECT {sel}, '{p.name}' AS _archivo, '' AS _hoja FROM _pq) "
                        f"TO '{destino.as_posix()}' (FORMAT parquet, COMPRESSION zstd)")
            _registrar(con, bit, destino, p, "json", 0)
        elif ext == ".parquet":
            destino = bronze / f"{nombre_tabla(p)}.parquet"
            con.execute(f"CREATE OR REPLACE TEMP VIEW _pq AS SELECT * FROM '{p.as_posix()}'")
            cols = [r[0] for r in con.execute("DESCRIBE _pq").fetchall()]
            sel = ", ".join(f'CAST("{a}" AS VARCHAR) AS "{b}"' for a, b in zip(cols, nombres_unicos(cols)))
            con.execute(f"COPY (SELECT {sel}, '{p.name}' AS _archivo, '' AS _hoja FROM _pq) "
                        f"TO '{destino.as_posix()}' (FORMAT parquet, COMPRESSION zstd)")
            _registrar(con, bit, destino, p, "parquet", 0)
        else:
            for destino, hoja, motor, seg in ingestar_excel(con, p, bronze, ram_gb):
                _registrar(con, bit, destino, p, f"excel:{motor}", seg)
    _unir_hojas_gemelas(con, bronze, bit)
    _unir_partidos(con, bronze, bit)
    return sorted(bronze.glob("*.parquet"))


def _cols(con, p):
    return tuple(sorted(r[0] for r in con.execute(f"DESCRIBE SELECT * FROM '{p.as_posix()}'").fetchall()))


def _unir(con, bronze, bit, destino_nombre, partes, motivo):
    destino = bronze / f"{destino_nombre}.parquet"
    tmp = bronze / f"_{destino_nombre}.tmp.parquet"
    lista = ", ".join(f"'{p.as_posix()}'" for p in partes)
    con.execute(f"COPY (SELECT * FROM read_parquet([{lista}], union_by_name=true)) "
                f"TO '{tmp.as_posix()}' (FORMAT parquet, COMPRESSION zstd)")
    for p in partes:
        p.unlink()
    plataforma.reemplazar(tmp, destino)   # rename falla en Windows si el destino existe
    n = con.execute(f"SELECT count(*) FROM '{destino.as_posix()}'").fetchone()[0]
    bit.registrar("ingesta", destino_nombre, n, len(_cols(con, destino)) - 2, {motivo: len(partes)}, 0)


def _unir_partidos(con, bronze, bit):
    """1) archivos de la MISMA tabla partidos por periodo (transacciones_202401, _202402...):
          mismo nombre sin los dígitos + mismas columnas -> una tabla (la columna _archivo
          guarda de dónde vino cada fila).
       2) config.UNIR_TABLAS: uniones explícitas (p.ej. train + test de la misma tabla)."""
    grupos = {}
    for p in bronze.glob("*.parquet"):
        base = re.sub(r"_+$", "", re.sub(r"[_\-]?(19|20)\d{2}[_\-]?\d{0,4}|[_\-]?(parte|part|p)?[_\-]?\d{1,3}$", "", p.stem))
        if base and base != p.stem:
            grupos.setdefault((base, _cols(con, p)), []).append(p)
    for (base, _), partes in grupos.items():
        if len(partes) >= 2:
            _unir(con, bronze, bit, base, partes, "archivos_partidos_unidos")
    for destino, nombres in (C.UNIR_TABLAS or {}).items():
        partes = [bronze / f"{normalizar_nombre(n, 0)}.parquet" for n in nombres]
        partes = [p for p in partes if p.exists()]
        if len(partes) >= 2:
            _unir(con, bronze, bit, normalizar_nombre(destino, 0), partes, "tablas_unidas_config")


def _registrar(con, bit, destino, origen, motor, seg, n_lineas=None):
    n = con.execute(f"SELECT count(*) FROM '{destino.as_posix()}'").fetchone()[0]
    ncol = len(con.execute(f"DESCRIBE SELECT * FROM '{destino.as_posix()}'").fetchall()) - 2
    extra = dict(origen=origen.name, motor=motor, mb_origen=round(origen.stat().st_size / 1e6, 1),
                 mb_parquet=round(destino.stat().st_size / 1e6, 1))
    if n_lineas is not None and n_lineas != n:
        extra["filas_rotas_o_multilinea"] = n_lineas - n
    bit.registrar("ingesta", destino.stem, n, ncol, extra, seg)
    if n == 0:
        raise RuntimeError(f"ALARMA: {origen.name} quedó con 0 filas. Revisar separador/encoding/encabezado "
                           f"antes de seguir (abrir las primeras líneas con un editor de texto).")
    if n_lineas and (n_lineas - n) / max(n_lineas, 1) > 0.01:
        print(f"  ⚠ ALARMA: {origen.name} perdió {(n_lineas - n) / n_lineas:.1%} de filas al leer "
              f"(saltos de línea dentro de celdas o separador irregular). Revisar antes de seguir.")


def _unir_hojas_gemelas(con, bronze, bit):
    grupos = {}
    for p in bronze.glob("*__*.parquet"):
        cols = tuple(sorted(r[0] for r in con.execute(f"DESCRIBE SELECT * FROM '{p.as_posix()}'").fetchall()))
        grupos.setdefault((p.stem.split("__")[0], cols), []).append(p)
    for (base, _), partes in grupos.items():
        if len(partes) < 2:
            if len(partes) == 1 and len(list(bronze.glob(f"{base}__*.parquet"))) == 1:
                plataforma.reemplazar(partes[0], bronze / f"{base}.parquet")  # una sola hoja: nombre limpio
            continue
        destino = bronze / f"{base}.parquet"
        lista = ", ".join(f"'{p.as_posix()}'" for p in partes)
        con.execute(f"COPY (SELECT * FROM read_parquet([{lista}], union_by_name=true)) "
                    f"TO '{destino.as_posix()}' (FORMAT parquet, COMPRESSION zstd)")
        for p in partes:
            p.unlink()
        n = con.execute(f"SELECT count(*) FROM '{destino.as_posix()}'").fetchone()[0]
        bit.registrar("ingesta", base, n, len(_) - 2, {"hojas_unidas": len(partes)}, 0)
