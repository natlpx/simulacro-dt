"""Arma un USB 'distinto' a partir de los datos de prueba:
 - facturas partidas en 2 archivos por año (facturas_2024.csv, facturas_2025.csv) + fecha de pago
 - maestro partido en train/test y guardado en latin-1
 - operaciones con 10% duplicadas como si vinieran también del SPI (otra fuente)
"""
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

src = Path(__file__).resolve().parents[1] / "data" / "raw"
dst = Path(__file__).resolve().parent / "variante" / "raw"
shutil.rmtree(dst.parent, ignore_errors=True); dst.mkdir(parents=True)
rng = np.random.default_rng(1)

f = pd.read_csv(src / "facturas_electronicas.csv", dtype=str)
fe = pd.to_datetime(f.fec_emision, format="mixed", dayfirst=True)
f["fec_pago"] = (fe + pd.to_timedelta(f.dias_plazo.astype(int) + rng.integers(-5, 20, len(f)), "D")).dt.strftime("%d/%m/%Y")
f[fe.dt.year == 2024].to_csv(dst / "facturas_2024.csv", index=False)
f[fe.dt.year == 2025].to_csv(dst / "facturas_2025.csv", index=False)

m = pd.read_csv(src / "maestro_clientes.csv", dtype=str)
m["Rubro Económico"] = m["Rubro Económico"].str.replace("CONSTRUCCION", "CONSTRUCCIÓN")
test = rng.random(len(m)) < 0.3
m[~test].to_csv(dst / "train_empresas.csv", index=False, encoding="latin-1")
m[test].to_csv(dst / "test_empresas.csv", index=False, encoding="latin-1")

op = pd.read_excel(src / "operaciones_factoring.xlsx", sheet_name=None, dtype=str)
op = pd.concat(op.values())
spi = op.sample(frac=0.10, random_state=2)
pd.concat([op.assign(Fuente="INTERNO"), spi.assign(Fuente="SPI")]).to_csv(dst / "operaciones_factoring.csv", index=False)
shutil.copy(src / "perfil_cliente.xlsx", dst / "perfil_cliente.xlsx")
for p in sorted(dst.iterdir()):
    print(f"  {p.name:<30} {p.stat().st_size/1e6:6.1f} MB")
