"""
De predicciones.csv (salida de run_modelo.py) a entregas/submission.csv (entregable oficial).

El formato exacto lo dice entregas/README.md del repo del evento y NO lo conocemos aún. Por eso
todo lo que depende del formato está en FORMATO (abajo): se ajusta en 2 minutos al leerlo.
Después SIEMPRE:   python -m datafest.validar

Uso (desde la raíz del repo del evento, después de copiar este archivo a trabajo/):
    python trabajo/exportar_submission.py --config trabajo/config_evento.py
"""
import argparse
import importlib.util
import sys

sys.dont_write_bytecode = True   # sin __pycache__: no ensucia base_conocimiento/ ni trabajo/
from pathlib import Path

import pandas as pd

# ------------------------------------------------------------------ AJUSTAR CON entregas/README.md
FORMATO = dict(
    columnas={            # columna_en_submission: columna_en_predicciones.csv
        "id_empresa": "id",
        "probabilidad": "prob",
        # "valor_esperado": "valor_esperado",
        # "priorizado": "priorizado",
    },
    orden=None,           # p.ej. "probabilidad" para ordenar descendente; None = como venga
    decimales=6,          # redondeo de columnas numéricas
    separador=",",
)
# ---------------------------------------------------------------------------------------------


def cargar_config(ruta):
    s = importlib.util.spec_from_file_location("config", ruta)
    m = importlib.util.module_from_spec(s)
    sys.modules["config"] = m
    s.loader.exec_module(m)
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--salida", default="entregas/submission.csv")
    a = ap.parse_args()
    C = cargar_config(a.config)

    pred = Path(C.OUT_DIR) / "modelo" / "predicciones.csv"
    if not pred.exists():
        sys.exit(f"No existe {pred}. Corran primero run_modelo.py con la misma --config.")
    df = pd.read_csv(pred, dtype={"id": str})

    faltan = [c for c in FORMATO["columnas"].values() if c not in df]
    if faltan:
        sys.exit(f"predicciones.csv no tiene {faltan}. Columnas disponibles: {list(df.columns)}")
    sub = df[list(FORMATO["columnas"].values())].copy()
    sub.columns = list(FORMATO["columnas"].keys())

    # controles que el validador oficial seguramente también hará
    id_col = sub.columns[0]
    dup = sub[id_col].duplicated().sum()
    if dup:
        sys.exit(f"{dup} ids duplicados en la entrega: revisen el grano de la tabla de modelo.")
    nulos = sub.isna().sum()
    if nulos.any():
        sys.exit(f"Hay nulos en la entrega:\n{nulos[nulos > 0]}")

    if FORMATO["orden"]:
        sub = sub.sort_values(FORMATO["orden"], ascending=False)
    num = sub.select_dtypes("number").columns
    sub[num] = sub[num].round(FORMATO["decimales"])

    destino = Path(a.salida)
    destino.parent.mkdir(parents=True, exist_ok=True)
    sub.to_csv(destino, index=False, sep=FORMATO["separador"], encoding="utf-8")
    print(f"OK: {len(sub):,} filas -> {destino}")
    print("Siguiente paso obligatorio:  python -m datafest.validar")


if __name__ == "__main__":
    main()
