"""
CONFIGURACIÓN DEL DÍA DEL EVENTO (se copia FUERA de base_conocimiento/ a las 15:30)

Por qué existe: base_conocimiento/ se cierra el viernes a las 14:00 y lo que se cambie ahí
después "no cuenta y el control lo marca como error". Entonces la plantilla NO se edita:
se corre desde la base con esta configuración, que vive en otra carpeta del repo.

    python base_conocimiento/plantilla/run_pipeline.py --config trabajo/config_evento.py
    python base_conocimiento/plantilla/run_modelo.py   --config trabajo/config_evento.py

Qué cambia respecto a config.py de la plantilla:
  - RAW_DIR  -> data/ de la raíz del repo del evento (carpeta bloqueada: nunca se sube).
  - WORK_DIR, TMP_DIR, OUT_DIR -> FUERA del repo (~/datafest_trabajo): parquet y reportes
    pesados no se suben por accidente ni disparan el aviso de "archivos pesados".
  - BASE -> esta carpeta: aquí se crea decisiones_manual.csv si hace falta (no en la base).
Todo lo demás se hereda de la plantilla y solo se sobrescribe lo de la sección 3.
"""
import importlib.util
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
REPO = AQUI.parent                                               # raíz del repo del evento
PLANTILLA = REPO / "base_conocimiento" / "plantilla" / "config.py"
if str(PLANTILLA.parent) not in sys.path:      # para que cualquier script (p.ej. trabajo/exportar_submission.py)
    sys.path.insert(0, str(PLANTILLA.parent))  # encuentre el paquete pipeline/ de la base

_s = importlib.util.spec_from_file_location("config_plantilla", PLANTILLA)
_b = importlib.util.module_from_spec(_s)
_s.loader.exec_module(_b)
globals().update({k: v for k, v in vars(_b).items() if not k.startswith("__")})

# ---------------------------------------------------------------- 1. rutas
BASE = AQUI                                          # decisiones_manual.csv va junto a este archivo
RAW_DIR = REPO / "data"                              # donde la organización indique poner los datos
TRABAJO = Path.home() / "datafest_trabajo"           # fuera del repo: nada de esto se sube
WORK_DIR = TRABAJO / "work"
TMP_DIR = TRABAJO / "tmp_duckdb"
OUT_DIR = TRABAJO / "salidas"

# ---------------------------------------------------------------- 2. máquina
# RAM_GB, MEMORY_LIMIT, THREADS se detectan solos (heredados). Para fijarlos a mano:
# MEMORY_LIMIT, THREADS = "6GB", 4

# ---------------------------------------------------------------- 3. EL CASO (llenar al leer el enunciado)
# La plantilla trae valores de EJEMPLO atados a los datos de prueba (tablas que no existirán).
# Aquí se apagan; el equipo los vuelve a poner con los nombres reales. Con DATAFEST_PRUEBA=1
# (variable de entorno) se conservan, para ensayar con generar_datos_prueba.py.
import os  # noqa: E402

if os.environ.get("DATAFEST_PRUEBA") != "1":
    PIVOTAR = None          # tabla larga empresa x mes x variable -> dict(id=, fecha=, variable=, valor=)
    DEDUP_EVENTOS = None    # misma operación por dos fuentes -> {"tabla": ["id", "fecha", "monto"]}
    SEGMENTO = None         # variable de tabla_modelo para comparar 1 vs varios modelos
    CUPOS_ZONA = None       # {"LIMA": 50, ...} solo si el enunciado da cupos por zona
    COLUMNA_ZONA = None
    EVALUAR = None          # dict(tabla=, id=) si entregan la lista de empresas a puntuar
    UNIR_TABLAS = None

# Lo que SIEMPRE se llena con el enunciado (descomentar y ajustar):
# FECHA_CORTE = "AAAA-MM-DD"        # día de la "foto"; el target mira [corte, corte + horizonte)
# HORIZONTE_MESES = 6
# TARGET = dict(tabla="...", id="...", fecha="...", filtro="...", monto="...")
# CAPACIDAD = 1000                  # fracción (0.025) o número de empresas que la fuerza de venta puede contactar

# Correcciones humanas al perfil automático (reemplaza decisiones_manual.csv: así no se sube un .csv).
# decision: KEEP / DROP ; rol: id, fecha, monto, contraparte, rubro, ... (ver perfil_columnas.csv)
DECISIONES_MANUAL = [
    # dict(tabla="maestro_clientes", columna="fecha_cancelacion_cuenta", decision="DROP", rol=""),
]

if TARGET == _b.TARGET and os.environ.get("DATAFEST_PRUEBA") != "1":
    print("⚠ config_evento: TARGET sigue siendo el EJEMPLO de los datos de prueba. "
          "Defínanlo con las tablas reales en la sección 3 antes de correr.")
