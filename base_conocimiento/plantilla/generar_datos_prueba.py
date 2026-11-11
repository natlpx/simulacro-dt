"""
Genera 4 archivos SUCIOS tipo factoring para probar el pipeline sin el USB real.
A propósito usa nombres de columnas distintos a los del simulacro (ruc_cliente,
fec_emision, imp_factura...) para demostrar que el pipeline no depende de nombres exactos.

Trampas incluidas: montos como texto ('S/ 1,234.50', '1.234,50'), fechas en 3 formatos
y seriales de Excel, RUC con '.0', centinelas (-1, 999999, 'S/D', 1900-01-01), rubros
mal escritos ('Comercio ', 'COMÉRCIO'), columnas vacías/constantes/duplicadas/texto libre,
filas duplicadas, moneda USD/PEN, una variable FUGA (posterior al corte) y Excel con
2 hojas que deben unirse.

  python generar_datos_prueba.py --empresas 20000 --facturas 400000
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

RUBROS = ["COMERCIO", "MANUFACTURA", "CONSTRUCCION", "AGRO", "MINERIA", "SERVICIOS", "TRANSPORTE",
          "TEXTIL", "PESCA", "TECNOLOGIA", "SALUD", "EDUCACION"]
ZONAS = ["LIMA", "NORTE", "SUR", "CENTRO", "ORIENTE"]


def ensuciar_rubro(r, rng):
    x = rng.random()
    if x < 0.08: return r.title() + " "
    if x < 0.12: return r.lower()
    if x < 0.14: return r.replace("O", "Ó", 1)
    if x < 0.16: return "S/D"
    return r


def main(n_emp=20000, n_fac=400000, out="data/raw", semilla=7):
    rng = np.random.default_rng(semilla)
    out = Path(out); out.mkdir(parents=True, exist_ok=True)

    # ---------------- maestro de clientes (CSV)
    ruc = 20100000000 + rng.choice(9_000_000, n_emp, replace=False)
    rubro = rng.choice(RUBROS, n_emp, p=np.array([20, 14, 10, 8, 4, 15, 7, 6, 3, 5, 4, 4]) / 100)
    zona = rng.choice(ZONAS, n_emp, p=[.5, .18, .17, .1, .05])
    ventas = np.round(np.exp(rng.normal(13, 1.4, n_emp)), 2)
    propension = 1 / (1 + np.exp(-(-3.2 + 0.5 * (rubro == "MANUFACTURA") + 0.6 * (rubro == "COMERCIO")
                                   + 0.35 * (np.log(ventas) - 13) + rng.normal(0, 0.6, n_emp))))
    m = pd.DataFrame({
        "RUC Cliente": [f"{r}.0" if rng.random() < 0.3 else str(r) for r in ruc],
        "Razón Social": [f"EMPRESA {i} SAC" for i in range(n_emp)],
        "Rubro Económico": [ensuciar_rubro(r, rng) for r in rubro],
        "Zona": zona,
        "Fec. Alta": pd.to_datetime("2010-01-01") + pd.to_timedelta(rng.integers(0, 5000, n_emp), "D"),
        "Ventas Anuales": [f"S/ {v:,.2f}" if rng.random() < 0.5 else (f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if rng.random() < 0.3 else str(v)) for v in ventas],
        "Num Trabajadores": np.where(rng.random(n_emp) < 0.05, -1, rng.integers(1, 500, n_emp)),
        "Segmento": rng.choice(["PYME", "PYME", "PYME", "EMPRESA", "CORPORATIVO"], n_emp),
        "pais": "PERU",                                       # constante
        "campo_libre_1": np.nan,                              # vacía
        "Observaciones": [f"cliente contactado por ejecutivo {rng.integers(1, 99)} el día {rng.integers(1, 28)} sin novedad relevante" for _ in range(n_emp)],
        "flag_lead_factoring": (rng.random(n_emp) < 0.10 + 0.4 * propension).astype(int),
        "Fecha Cancelacion Cuenta": np.where(rng.random(n_emp) < 0.97, "", "2025-11-30"),
    })
    m["ventas_copia"] = m["Ventas Anuales"]               # duplicada
    m.to_csv(out / "maestro_clientes.csv", index=False)

    # ---------------- facturas / transacciones (CSV grande)
    emi = rng.choice(n_emp, n_fac, p=ventas / ventas.sum() * 0.5 + 0.5 / n_emp)
    pag = rng.choice(n_emp, n_fac)
    dias = rng.integers(0, 730, n_fac)
    fecha = pd.to_datetime("2024-01-01") + pd.to_timedelta(dias, "D")
    monto = np.round(np.exp(rng.normal(8.5, 1.2, n_fac)), 2)
    usd = rng.random(n_fac) < 0.15
    fmt = rng.random(n_fac)
    f_txt = np.where(fmt < 0.6, fecha.strftime("%Y-%m-%d"), np.where(fmt < 0.9, fecha.strftime("%d/%m/%Y"), fecha.strftime("%Y%m%d")))
    t = pd.DataFrame({
        "nro_factura": [f"F{i:09d}" for i in range(n_fac)],
        "ruc_emisor": ruc[emi].astype(str),
        "ruc_pagador": ruc[pag].astype(str),
        "fec_emision": f_txt,
        "dias_plazo": rng.choice([30, 45, 60, 90, 120], n_fac),
        "imp_factura": np.where(usd, np.round(monto / 3.75, 2), monto).astype(str),
        "moneda": np.where(usd, "USD", "PEN"),
        "rubro_pagador": [ensuciar_rubro(r, rng) for r in rubro[pag]],
        "canal": rng.choice(["SUNAT", "SUNAT", "OSE"], n_fac),
        "sistema_origen": "SIS01",
    })
    t.loc[rng.random(n_fac) < 0.01, "imp_factura"] = "999999"     # centinela
    t = pd.concat([t, t.sample(frac=0.02, random_state=1)])       # 2% duplicados exactos
    t.to_csv(out / "facturas_electronicas.csv", index=False)

    # ---------------- operaciones de factoring (Excel, 2 hojas con mismas columnas)
    n_op = int(n_emp * 1.5)
    quien = rng.choice(n_emp, n_op, p=propension / propension.sum())
    f_op = pd.to_datetime("2024-01-01") + pd.to_timedelta(rng.integers(0, 730, n_op), "D")
    op = pd.DataFrame({
        "ID Operacion": [f"OP{i:07d}" for i in range(n_op)],
        "RUC": ruc[quien].astype(str),
        "Fecha Operación": [(d - pd.Timestamp("1899-12-30")).days if rng.random() < 0.3 else d.strftime("%d/%m/%Y") for d in f_op],
        # el monto depende del tamaño de la empresa (señal real para el modelo de monto)
        "Monto Financiado": np.round(np.exp(rng.normal(10, 0.7, n_op)) * (ventas[quien] / np.median(ventas)) ** 0.5, 2),
        "Tasa Mensual %": [f"{x:.2f}%" for x in rng.uniform(0.8, 2.5, n_op)],
        "Estado": rng.choice(["VIGENTE", "CANCELADA", "ANULADA"], n_op, p=[.5, .42, .08]),
        "Banco": rng.choice(["BCP", "BCP", "OTRO BANCO"], n_op),
    })
    mitad = len(op) // 2
    with pd.ExcelWriter(out / "operaciones_factoring.xlsx", engine="xlsxwriter") as w:
        op.iloc[:mitad].to_excel(w, sheet_name="Hoja1", index=False)
        op.iloc[mitad:].to_excel(w, sheet_name="Hoja2", index=False)

    # ---------------- perfil ancho (Excel, 60 columnas, muchas inútiles)
    p = pd.DataFrame({"cod_cliente": ruc.astype(str)})
    for k in range(40):
        x = rng.normal(0, 1, n_emp) + (0.3 * np.log(ventas) if k % 7 == 0 else 0)
        p[f"var_buro_{k:02d}"] = np.where(rng.random(n_emp) < (0.99 if k % 10 == 9 else 0.1), np.nan, np.round(x, 3))
    for k in range(10):
        p[f"ind_producto_{k}"] = rng.choice(["S", "N"], n_emp, p=[.02 if k > 6 else .3, .98 if k > 6 else .7])
    p["score_riesgo"] = np.where(rng.random(n_emp) < 0.03, 9999, rng.integers(200, 900, n_emp))
    p["fecha_ultimo_contacto"] = np.where(rng.random(n_emp) < 0.02, "1900-01-01",
                                          (pd.to_datetime("2023-01-01") + pd.to_timedelta(rng.integers(0, 900, n_emp), "D")).strftime("%Y-%m-%d"))
    p["constante_x"] = 1
    # FUGA: cuenta operaciones de TODO el periodo, incluido el posterior al corte
    cnt = pd.Series(ruc[quien]).astype(str).value_counts()
    p["total_operaciones_hist"] = p.cod_cliente.map(cnt).fillna(0).astype(int)
    fut = pd.Series(ruc[quien][f_op >= "2025-07-01"]).astype(str).value_counts()
    p["ops_ultimo_semestre"] = p.cod_cliente.map(fut).fillna(0).astype(int)
    # perfil ANCHO por mes: saldo_202401 ... saldo_202512 (los meses >= corte NO deben usarse)
    base_saldo = np.exp(rng.normal(9, 1, n_emp)) * (1 + 0.8 * propension)
    for k, per in enumerate(pd.period_range("2024-01", "2025-12", freq="M")):
        crec = 1 + 0.02 * k * (propension > np.median(propension))
        p[f"saldo_{per.strftime('%Y%m')}"] = np.round(base_saldo * crec * rng.lognormal(0, 0.15, n_emp), 2)
    p.to_excel(out / "perfil_cliente.xlsx", index=False, engine="xlsxwriter")

    # 5º archivo, formato LARGO: empresa x mes x producto x saldo (se pivotea)
    meses = pd.period_range("2024-07", "2025-06", freq="M").strftime("%Y-%m-01")
    sub = rng.choice(n_emp, n_emp // 2, replace=False)
    filas = []
    for prod, peso in [("CUENTA_CORRIENTE", 1.0), ("CREDITO_CAPITAL_TRABAJO", 0.6), ("LEASING", 0.3)]:
        tiene = sub[rng.random(len(sub)) < peso]
        for mes in meses:
            filas.append(pd.DataFrame({"cod_cliente": ruc[tiene].astype(str), "periodo": mes, "producto": prod,
                                       "saldo_prom": np.round(np.exp(rng.normal(8, 1, len(tiene))) * (1 + propension[tiene]), 2)}))
    pd.concat(filas).to_csv(out / "saldos_productos_largo.csv", index=False)
    print("archivos en", out.resolve())
    for f in sorted(out.iterdir()):
        print(f"  {f.name:<32} {f.stat().st_size/1e6:8.1f} MB")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--empresas", type=int, default=20000)
    ap.add_argument("--facturas", type=int, default=400000)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "data" / "raw"))
    a = ap.parse_args()
    main(a.empresas, a.facturas, a.out)
