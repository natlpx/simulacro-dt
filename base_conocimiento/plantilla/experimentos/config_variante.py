"""Configuración de PRUEBA para escenarios de datos distintos (no es la del concurso).
Hereda todo de config.py y cambia solo lo necesario."""
import importlib.util
from pathlib import Path

# hereda config.py (se carga por ruta: el nombre "config" ya lo ocupa este archivo)
_spec = importlib.util.spec_from_file_location("config_base", Path(__file__).resolve().parents[1] / "config.py")
_base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_base)
globals().update({k: v for k, v in vars(_base).items() if not k.startswith("__")})

BASE_V = Path(__file__).resolve().parent / "variante"
RAW_DIR = BASE_V / "raw"
WORK_DIR = BASE_V / "work"
OUT_DIR = BASE_V / "salidas"
TMP_DIR = BASE_V / "tmp"
PIVOTAR = None
UNIR_TABLAS = {"empresas": ["train_empresas", "test_empresas"]}
EVALUAR = dict(tabla="empresas", id="ruc_cliente", archivo="test_empresas.csv")
TARGET = dict(tabla="operaciones_factoring", id="ruc", fecha="fecha_operacion",
              filtro="estado <> 'ANULADA' AND banco = 'BCP'", monto="monto_financiado")
DEDUP_EVENTOS = {"operaciones_factoring": ["ruc", "fecha_operacion", "monto_financiado"]}
