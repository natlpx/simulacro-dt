"""
CORRER ESTO EN CASA, CON INTERNET, ANTES DEL CONCURSO (en las 5 laptops: Windows, macOS o Linux).

    Windows:        py preparar_offline.py        (o python preparar_offline.py)
    macOS / Linux:  python3 preparar_offline.py

Qué hace:
  1. revisa la versión de Python y la carpeta donde está el repo,
  2. instala las librerías de requirements.txt,
  3. comprueba que cada librería importa y, si falla, dice el arreglo para TU sistema,
  4. descarga la extensión 'excel' de DuckDB (lectura de .xlsx con poca RAM),
  5. corre todo con datos de prueba.
Al final imprime un resumen OK / FALTA que pueden pegar en el grupo del equipo.
"""
import os
import platform
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
SISTEMA = platform.system()  # Windows / Darwin / Linux
PY = sys.executable
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}

# librería -> nombre para importar
LIBS = {"duckdb": "duckdb", "polars": "polars", "pyarrow": "pyarrow", "pandas": "pandas", "numpy": "numpy",
        "scipy": "scipy", "plotly": "plotly", "fastexcel": "fastexcel", "openpyxl": "openpyxl",
        "xlsxwriter": "xlsxwriter", "scikit-learn": "sklearn", "lightgbm": "lightgbm", "optuna": "optuna",
        "pulp": "pulp", "highspy": "highspy", "xgboost": "xgboost", "catboost": "catboost"}

ARREGLOS = {
    "Darwin": {
        "lightgbm": "macOS necesita OpenMP:  brew install libomp   (si no tienes Homebrew: https://brew.sh)",
        "xgboost": "macOS necesita OpenMP:  brew install libomp",
    },
    "Windows": {
        "lightgbm": "Instala 'Microsoft Visual C++ Redistributable' (x64) desde la web de Microsoft y reinicia la terminal",
        "xgboost": "Instala 'Microsoft Visual C++ Redistributable' (x64) y reinicia la terminal",
        "catboost": "Revisa que Python sea de 64 bits:  py -c \"import struct; print(struct.calcsize('P')*8)\"  debe decir 64",
    },
    "Linux": {
        "lightgbm": "Instala OpenMP:  sudo apt install libgomp1   (Ubuntu/Debian)",
    },
}


def paso(n, texto):
    print(f"\n[{n}/5] {texto}")


def main():
    estado = {}
    paso(1, "revisando Python y la carpeta")
    v = sys.version_info
    print(f"   {SISTEMA} · Python {platform.python_version()} ({platform.architecture()[0]}) · {PY}")
    if v < (3, 10):
        print("   FALTA: el concurso pide Python 3.10 o superior. Instala 3.11 o 3.12 desde python.org")
        sys.exit(1)
    if v >= (3, 14):
        print("   AVISO: Python 3.14 es muy nuevo; algunas librerías (catboost) pueden no tener versión aún. "
              "Si algo falla al instalar, usen 3.12.")
    ruta = str(RAIZ)
    if "OneDrive" in ruta or "iCloud" in ruta or "Mobile Documents" in ruta:
        print("   AVISO: el repo está en una carpeta sincronizada (OneDrive/iCloud). La sincronización bloquea "
              "archivos mientras DuckDB escribe y causa errores raros. Muevan el repo a otra carpeta, "
              "por ejemplo C:\\datafest (Windows) o ~/datafest (macOS/Linux).")
    estado["python"] = "OK"

    paso(2, "instalando librerías de requirements.txt")
    r = subprocess.run([PY, "-m", "pip", "install", "-q", "-r", str(RAIZ / "requirements.txt")], env=ENV)
    if r.returncode != 0:
        print("   Hubo errores en pip. Lean el mensaje de arriba:\n"
              "     - 'No module named pip'  -> python -m ensurepip --upgrade  y vuelvan a correr\n"
              "     - 'externally-managed-environment' (macOS/Linux) -> usen un entorno virtual (docs/GUIA_EJECUCION.md, paso 3)")

    paso(3, "comprobando que cada librería carga")
    for lib, modulo in LIBS.items():
        r = subprocess.run([PY, "-c", f"import {modulo}"], capture_output=True, text=True, env=ENV)
        if r.returncode == 0:
            estado[lib] = "OK"
        else:
            estado[lib] = "FALTA"
            ultima = (r.stderr.strip().splitlines() or ["?"])[-1][:160]
            print(f"   FALTA {lib}: {ultima}")
            arreglo = ARREGLOS.get(SISTEMA, {}).get(lib)
            if arreglo:
                print(f"      arreglo: {arreglo}")
    obligatorias = [k for k in LIBS if k not in ("xgboost", "catboost")]
    if any(estado[k] != "OK" for k in obligatorias):
        print("\n   Arreglen lo que dice FALTA y vuelvan a correr este script.")
        sys.exit(1)

    paso(4, "descargando extensión excel de DuckDB")
    try:
        import duckdb
        duckdb.sql("INSTALL excel; LOAD excel;")
        estado["duckdb_excel"] = "OK"
    except Exception as e:
        estado["duckdb_excel"] = "FALTA (se usará fastexcel, más RAM)"
        print("   no se pudo:", str(e)[:120])

    paso(5, "prueba completa con datos sintéticos (2-3 minutos)")
    pasos = [["generar_datos_prueba.py"], ["run_pipeline.py"],
             ["run_pipeline.py", "--desde", "features", "--corte", "2025-01-01", "--sufijo", "_t1"],
             ["run_modelo.py", "--rapido"]]
    for args in pasos:
        r = subprocess.run([PY, str(RAIZ / args[0]), *args[1:]], cwd=RAIZ, env=ENV)
        if r.returncode != 0:
            estado["prueba"] = f"FALLA en {' '.join(args)}"
            break
    else:
        estado["prueba"] = "OK"

    print("\n================ RESUMEN (péguenlo en el grupo) ================")
    print(f"{SISTEMA} · Python {platform.python_version()}")
    for k, val in estado.items():
        print(f"  {k:<14} {val}")
    if estado.get("prueba") == "OK":
        print(f"\nTodo listo. Abrir {RAIZ / 'salidas' / 'monitor.html'}")


if __name__ == "__main__":
    main()
