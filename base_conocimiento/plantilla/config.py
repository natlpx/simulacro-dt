"""
CONFIGURACIÓN ÚNICA DEL PIPELINE
================================
Todo lo que cambia entre un caso y otro vive aquí. El código de /pipeline no se toca
el día del concurso: solo se ajusta este archivo y, si hace falta, decisiones_manual.csv.

Por qué así: con 8 GB y 5 personas, el error más caro es que cada uno "arregle" el código
a su manera. Un solo archivo de configuración = una sola verdad.
"""
from pathlib import Path

from pipeline import plataforma

plataforma.consola_utf8()   # Windows: sin esto, el primer "⚠" detiene el pipeline (UnicodeEncodeError)

# ----------------------------------------------------------------------------
# 1. RUTAS
# ----------------------------------------------------------------------------
BASE = Path(__file__).resolve().parent
RAW_DIR = BASE / "data" / "raw"          # aquí se copian los 4 Excel/CSV del USB (NO se modifican)
WORK_DIR = BASE / "data" / "work"        # parquet crudo (bronze) y limpio (silver)
OUT_DIR = BASE / "salidas"               # perfiles, bitácora, reporte HTML, features
TMP_DIR = BASE / "data" / "tmp_duckdb"   # DuckDB usa disco cuando falta RAM (spill)

# ----------------------------------------------------------------------------
# 2. RECURSOS DE LA MÁQUINA
#    Se calculan solos en cada laptop (Windows, macOS o Linux): memory_limit = 60% de la RAM
#    física y threads = núcleos - 1. Con 8 GB -> "4GB"; con 16 GB -> "9GB"; con 24 GB -> "14GB".
#    Para fijarlos a mano, reemplacen la línea por p.ej. MEMORY_LIMIT, THREADS = "5GB", 4
# ----------------------------------------------------------------------------
RAM_GB, MEMORY_LIMIT, THREADS = plataforma.recursos()
MUESTRA_PERFIL = 1_000_000   # filas para perfilar la FORMA de cada columna (conteo total sí es exacto)

# ----------------------------------------------------------------------------
# 3. FECHAS DEL CASO (se llenan cuando lean el enunciado)
#    corte = el "día de decidir". Todo lo que se usa como variable debe ser < corte.
# ----------------------------------------------------------------------------
FECHA_CORTE = "2025-07-01"
HORIZONTE_MESES = 6            # ventana del objetivo: [corte, corte + horizonte)
VENTANAS_MESES = [3, 6, 12]    # ventanas de comportamiento (RFM)
TIPO_CAMBIO = 3.75             # USD -> PEN si aparece una columna de moneda

# ----------------------------------------------------------------------------
# 4. VALORES BASURA ("centinelas") que en realidad significan "no hay dato"
# ----------------------------------------------------------------------------
SENTINELAS_TXT = [
    "", "NA", "N/A", "N.A.", "NULL", "NONE", "NAN", "NAT", "-", "--", "---", "?", ".",
    "SIN DATO", "SIN INFORMACION", "S/D", "SD", "NO DEFINIDO", "NO APLICA", "DESCONOCIDO",
    "#N/A", "#VALUE!", "#REF!", "#DIV/0!", "#NAME?", "0000-00-00", "00/00/0000",
]
# Números que suelen ser códigos de "sin dato". Solo se anulan si además son el mínimo
# o el máximo de la columna y aparecen con frecuencia anormal (>= 0.5%): así no borramos
# un -1 legítimo en una variación porcentual.
SENTINELAS_NUM = [-1, -9, -99, -999, -9999, -99999, 999, 9999, 99999, 999999,
                  9999999, 99999999, 999999999]
FECHAS_CENTINELA = ["1900-01-01", "1899-12-30", "1970-01-01", "2099-12-31", "9999-12-31", "3000-01-01"]

# Formatos que reconoce el enrutador de fechas de pipeline/db.py (macro _fecha_s).
# Ambigüedad 05/03/2024: se asume DÍA/MES (Perú). Si el caso viene en formato EE.UU., cambiar allí.
FORMATOS_FECHA = [
    "%Y-%m-%d", "%d/%m/%Y", "%Y%m%d", "%d-%m-%Y", "%Y/%m/%d", "%d.%m.%Y",
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M",
    "%Y-%m-%d %H:%M:%S.%f", "%d/%m/%y",
]

# ----------------------------------------------------------------------------
# 5. ROLES SEMÁNTICOS: cómo reconocer una columna por su NOMBRE cuando no sabemos
#    los campos exactos. El perfil combina nombre + contenido; el nombre solo no basta.
#    (los nombres se normalizan antes: minúsculas, sin tildes, '_' en vez de espacios)
# ----------------------------------------------------------------------------
PATRONES_ROL = {   # el ORDEN importa: gana el primer patrón que calza
    "target":      r"(^|_)(target|label|objetivo|y)($|_)|flag_(compra|adq|conv|venta|default|fuga)|convirt|adquiri",
    "id":          r"^(id|cod|codigo|key|llave|ruc|dni|cuc)(_|$)|_(id|cod|codigo|key|ruc|dni|cuc)$",
    "fecha":       r"(^|_)(fec|fch|fecha|date|dt|periodo|period|mes|anio|year|month|dia|day)($|_)|fecha|_at$",
    "moneda":      r"(^|_)(moneda|currency|divisa|mon)($|_)",
    "monto":       r"(^|_)(mto|monto|imp|importe|amount|saldo|valor|venta|ventas|ingreso|ingresos|pago|deuda|linea|limite|precio|costo|total|facturacion|desembolso|capital)($|_)",
    "rubro":       r"rubro|sector|ciiu|actividad|giro|industria|segmento|categoria|tipo_emp|subsector",
    "zona":        r"zona|region|depart|provincia|distrito|ubigeo|ciudad|agencia|territ|sucursal",
    "estado":      r"estado|status|situacion|anulad|vigente",
    "contraparte": r"pagador|proveedor|deudor|aceptante|contraparte|receptor|emisor|comprador|girador",
}

# ----------------------------------------------------------------------------
# 6. UMBRALES DE DECISIÓN (cada uno tiene su porqué en el README)
# ----------------------------------------------------------------------------
# Entidad = la "fila" del modelo (empresa, cliente). None = se detecta sola: es la llave
# única de la tabla maestra que más se repite en las otras tablas. Para fijarla:
# ENTIDAD = ("maestro_empresas", "id_empresa")
ENTIDAD = None

# Tablas de EVENTOS (transacciones, operaciones). None = autodetección (tablas con
# llave de la entidad + fecha). Para fijar o corregir una:
# EVENTOS = {"transacciones": dict(id="ruc_emisor", fecha="fec_emision", montos=["mto_factura"],
#                                  cat="rubro", cp="ruc_pagador", moneda="moneda")}
EVENTOS = None

# OBJETIVO: lo define el ENUNCIADO, nunca la autodetección.
# TARGET = dict(tabla="factoring_operaciones", id="id_empresa", fecha="fecha_operacion",
#               filtro="estado <> 'ANULADA'")   # 1 si hubo evento en [corte, corte+horizonte)
# o una columna ya existente:  TARGET = dict(tabla="maestro", id="id_empresa", columna="flag_compra")
TARGET = dict(tabla="operaciones_factoring", id="ruc", fecha="fecha_operacion",   # <- EJEMPLO con
              filtro="estado <> 'ANULADA' AND banco = 'BCP'",                     #    datos de prueba
              monto="monto_financiado")
# Si el enunciado da el MONTO a predecir, agregar monto="columna" al TARGET (se suma en la ventana):
# TARGET = dict(..., monto="monto_financiado")
QUITAR_DUPLICADOS_EXACTOS = True

# Misma operación vista por dos fuentes (registro interno + SPI): se cuenta UNA vez.
# Llaves que definen "la misma operación". None = no deduplicar.
# DEDUP_EVENTOS = {"operaciones_factoring": ["ruc", "fecha_operacion", "monto_financiado"]}
DEDUP_EVENTOS = None

# Tabla LARGA (empresa x mes x variable x valor) -> se pivotea a una columna por variable.
# PIVOTAR = {"perfil_largo": dict(id="id_empresa", fecha="periodo", variable="producto", valor="saldo")}
PIVOTAR = {"saldos_productos_largo": dict(id="cod_cliente", fecha="periodo",   # <- EJEMPLO con
                                          variable="producto", valor="saldo_prom")}  #    datos de prueba

# Segmento para modelos separados o métricas por grupo (nombre de variable en tabla_modelo).
# Ej. forma A (con lead) vs forma B (sin lead). None = sin segmentos.
SEGMENTO = "maestrocli__flag_lead_factoring"    # <- EJEMPLO con datos de prueba

# Lista de evaluación: si el banco entrega un archivo con las empresas a puntuar (sin target).
# EVALUAR = dict(tabla="empresas_test", id="id_empresa")
# Si train y test vienen como DOS archivos de la misma tabla, únanlos (UNIR_TABLAS) e indiquen
# de qué archivo salen las empresas a puntuar:
# UNIR_TABLAS = {"empresas": ["train_empresas", "test_empresas"]}
# EVALUAR = dict(tabla="empresas", id="id_empresa", archivo="test_empresas.csv")
EVALUAR = None
UNIR_TABLAS = None

# Capacidad comercial para priorizar (fracción de la base o número) y cupos por zona (%).
CAPACIDAD = 0.025
CUPOS_ZONA = {"LIMA": 50, "NORTE": 18, "SUR": 17, "CENTRO": 10, "ORIENTE": 5}
COLUMNA_ZONA = "maestrocli__zona"

U = dict(
    nulos_drop=0.98,        # >98% vacía -> no aporta, se elimina
    nulos_indicador=0.70,   # 70-98% vacía -> se guarda como "tiene_x" (la AUSENCIA informa)
    top_constante=0.995,    # un valor ocupa >99.5% -> casi constante, se elimina
    parse_ok=0.95,          # >=95% se convierte a número/fecha -> esa columna ES número/fecha
    id_ratio=0.90,          # >=90% valores distintos -> parece identificador
    card_alta=50,           # >50 categorías -> frequency encoding, no one-hot
    texto_largo=40,         # largo promedio > 40 y muy distinta -> texto libre, fuera del modelo
    sentinela_min_share=0.005,
    psi_alerta=0.10, psi_drop=0.25,     # estabilidad entre periodos
    gini_fuga=0.50,                     # una sola variable con Gini > 0.5 = sospecha de fuga
    gini_min=0.02,                      # Gini < 0.02 = no separa nada
    spearman_max=0.90,                  # dos variables casi iguales: me quedo con la de más Gini
    iv_fuga=0.50,
)
