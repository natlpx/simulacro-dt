"""
ORQUESTADOR: corre todo o solo algunos pasos.

  python run_pipeline.py                         # todo, con data/raw
  python run_pipeline.py --raw /media/usb/datos  # leer directo del USB
  python run_pipeline.py --desde perfil          # re-correr sin re-leer los Excel
  python run_pipeline.py --solo monitor

Pasos: ingesta -> perfil -> limpieza -> llaves -> features -> seleccion -> monitor
Cada paso deja su salida en disco, así que si algo falla se retoma desde ese paso.
"""
import argparse
import sys

sys.dont_write_bytecode = True   # sin __pycache__: no ensucia base_conocimiento/ ni trabajo/
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
# --config otra_config.py : usar otra configuración (otro target, otro corte, otro caso) sin editar config.py
if "--config" in sys.argv:
    import importlib.util
    _ruta = sys.argv[sys.argv.index("--config") + 1]
    _spec = importlib.util.spec_from_file_location("config", _ruta)
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules["config"] = _mod
    _spec.loader.exec_module(_mod)
import config as C  # noqa: E402
from pipeline import features, ingesta, limpieza, llaves, monitor, perfil, seleccion  # noqa: E402
from pipeline.bitacora import Bitacora  # noqa: E402
from pipeline.db import conectar  # noqa: E402

PASOS = ["ingesta", "perfil", "limpieza", "llaves", "features", "seleccion", "monitor"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=None)
    ap.add_argument("--desde", default="ingesta", choices=PASOS)
    ap.add_argument("--solo", default=None, choices=PASOS)
    ap.add_argument("--ram_gb", type=float, default=None, help="RAM a asumir (por defecto, la detectada)")
    ap.add_argument("--corte", default=None, help="otra fecha de corte (backtest fuera de tiempo)")
    ap.add_argument("--sufijo", default="", help="sufijo de tabla_modelo, p.ej. _oot")
    ap.add_argument("--config", default=None)
    a = ap.parse_args()
    if a.corte:
        C.FECHA_CORTE = a.corte
    pasos = [a.solo] if a.solo else PASOS[PASOS.index(a.desde):]

    from pipeline import plataforma
    print(f"{plataforma.NOMBRE_SISTEMA} · Python {sys.version.split()[0]} · RAM {getattr(C, 'RAM_GB', 0):.0f} GB · DuckDB memory_limit={C.MEMORY_LIMIT} threads={C.THREADS}")
    C.OUT_DIR.mkdir(parents=True, exist_ok=True)
    con = conectar()
    bit = Bitacora()
    if "ingesta" in pasos:
        bit.reiniciar()
    t0 = time.time()

    bronze_dir, silver_dir = C.WORK_DIR / "bronze", C.WORK_DIR / "silver"
    tablas_b = ingesta.ejecutar(con, bit, a.raw, a.ram_gb) if "ingesta" in pasos else sorted(bronze_dir.glob("*.parquet"))

    if "perfil" in pasos:
        perf = perfil.ejecutar(con, bit, tablas_b)
    else:
        perf = perfil.aplicar_manual(pd.read_csv(C.OUT_DIR / "perfil_columnas.csv"))
    perf["decision"] = perf.decision.astype(str)

    tablas_s = limpieza.ejecutar(con, bit, tablas_b, perf) if "limpieza" in pasos else sorted(silver_dir.glob("*.parquet"))

    if "llaves" in pasos:
        gr, rel, ent = llaves.ejecutar(con, bit, tablas_s, perf)
    else:
        gr, rel = pd.read_csv(C.OUT_DIR / "granos.csv"), pd.read_csv(C.OUT_DIR / "relaciones.csv")
        ent = llaves.entidad(gr, rel)

    specs, path_modelo = None, C.OUT_DIR / "tabla_modelo.parquet"
    if ent and ("features" in pasos or "monitor" in pasos):
        if "features" in pasos:
            path_modelo, specs = features.ejecutar(con, bit, perf, rel, gr, ent, a.sufijo)
        else:
            specs = features.detectar_eventos(perf, rel, ent, gr)

    sel = None
    if a.sufijo:  # tabla de backtest: no re-hace el monitor
        print(f"\nTabla {path_modelo.name} lista (corte {C.FECHA_CORTE}).")
        # La selección se REHACE con la tabla del corte anterior como train (ver seleccion.embudo_fuera_de_tiempo):
        # antes se decidía con la tabla del corte actual, que es el examen.
        actual = C.OUT_DIR / "tabla_modelo.parquet"
        if a.sufijo == "_t1" and actual.exists():
            seleccion.ejecutar(bit, actual)
        return
    if "seleccion" in pasos and path_modelo.exists():
        sel = seleccion.ejecutar(bit, path_modelo)
    elif (C.OUT_DIR / "seleccion_variables.csv").exists():
        sel = pd.read_csv(C.OUT_DIR / "seleccion_variables.csv")

    if "monitor" in pasos:
        monitor.generar(con, bit, perf, gr, rel, specs, sel)
    print(f"\nListo en {time.time() - t0:,.1f} s. Salidas en {C.OUT_DIR}")


if __name__ == "__main__":
    main()
