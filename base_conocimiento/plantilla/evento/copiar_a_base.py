"""
Arma base_conocimiento/ en el repo del EVENTO (Datafest-BCP) siguiendo el paso 7 del PDF.

    python evento/copiar_a_base.py --repo-evento RUTA/AL/REPO/DEL/EVENTO --revisado-por "usuario1, usuario2"

Qué hace (y por qué):
  1. Copia SOLO los archivos versionados de la plantilla (git ls-files): nunca salidas/, data/
     ni el historial de git (que tiene correos personales/institucionales).
  2. Excluye datos de cualquier tipo (.csv, .parquet, .xlsx, .pkl, .zip, .json...): el PDF los prohíbe.
     decisiones_manual.csv también queda fuera: el día del evento se crea junto a config_evento.py.
  3. Verifica el límite de 20 MB (recomienda < 18 MB de margen).
  4. Genera base_conocimiento/INVENTARIO.md con una fila por archivo: qué es, quién lo escribió
     y para qué sirve ("lo que no figure genera un aviso"). Si el repo ya trae un INVENTARIO.md
     oficial, NO lo pisa: escribe INVENTARIO_propuesto.md para que copien las filas a su formato.
  5. NO hace commits ni push: imprime los comandos para que los haga cada una con su cuenta.
Funciona igual en Windows, macOS y Linux.
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

PLANTILLA = Path(__file__).resolve().parent.parent
PROHIBIDAS = {".csv", ".tsv", ".parquet", ".xlsx", ".xls", ".xlsm", ".pkl", ".pickle", ".joblib",
              ".zip", ".gz", ".7z", ".rar", ".json", ".jsonl", ".ndjson", ".feather", ".db", ".duckdb",
              ".model", ".txt_model", ".cbm", ".ubj"}
LIMITE_MB, MARGEN_MB = 20, 18

AUTORIA_DEFECTO = ("Preparado antes del evento con asistencia de Claude (Anthropic); revisado y probado por "
                   "el equipo ({revisado}). Ver nota al inicio.")

DESCRIPCION = {
    ".gitattributes": ("Config. git", "Mismo final de línea en Windows/macOS/Linux"),
    ".gitignore": ("Config. git", "Impide subir data/, salidas/ y parquet"),
    "README.md": ("Documentación", "Mapa de la plantilla y cómo usarla"),
    "config.py": ("Configuración", "Parámetros del caso (corte, target, capacidad); en el evento NO se edita: se usa config_evento.py"),
    "docs/CAMBIOS_REVISION.md": ("Notas", "Huecos encontrados en la revisión y cómo se corrigieron, con efecto medido"),
    "docs/ESCENARIOS.md": ("Notas", "Qué hacer si los datos vienen distintos (formatos, faltantes, restricciones)"),
    "docs/GUIA_EJECUCION.md": ("Notas", "Instalación y ejecución paso a paso en Windows, macOS y Linux"),
    "docs/MODELADO.md": ("Notas", "Qué modelo usar según la data, métricas, desbalance, hiperparámetros"),
    "docs/PASOS_EVENTO.md": ("Notas", "Checklist del jueves al sábado según el PDF de participación"),
    "evento/config_evento.py": ("Plantilla de configuración", "Se copia a trabajo/ a las 15:30 para correr la base sin editarla"),
    "evento/copiar_a_base.py": ("Utilidad", "Este script: arma base_conocimiento/ e INVENTARIO.md"),
    "evento/exportar_submission.py": ("Utilidad", "predicciones.csv -> entregas/submission.csv (formato a ajustar con entregas/README.md)"),
    "evento/presentacion_index.html": ("Plantilla", "Estructura vacía de presentacion/index.html (negocio + anexo técnico)"),
    "evento/BITACORA_FUENTES_inicial.md": ("Notas", "Fuentes que influyeron en la plantilla, para copiar a docs/BITACORA_FUENTES.md"),
    "evento/USO_DE_IA_ejemplo.md": ("Notas", "Formato para registrar el uso de Copilot en docs/USO_DE_IA.md"),
    "experimentos/config_variante.py": ("Experimento", "Ejemplo de configuración alternativa sin tocar config.py"),
    "experimentos/escenarios_modelado.py": ("Experimento", "Datos sintéticos: cuándo conviene logística, LightGBM o un modelo por segmento"),
    "experimentos/generar_variante.py": ("Experimento", "Genera datos de prueba con otro formato para probar robustez"),
    "experimentos/resultados.txt": ("Notas", "Resultados medidos de los experimentos"),
    "generar_datos_prueba.py": ("Utilidad", "Genera datos SINTÉTICOS de prueba (no son datos del reto)"),
    "pipeline/__init__.py": ("Código", "Marca el paquete"),
    "pipeline/bitacora.py": ("Código", "Registro de filas/columnas por tabla y paso (trazabilidad)"),
    "pipeline/db.py": ("Código", "Conexión DuckDB y macros SQL de limpieza (números, fechas, IDs)"),
    "pipeline/features.py": ("Código", "Variables por empresa con datos anteriores al corte + target"),
    "pipeline/features_polars.py": ("Código", "Alternativa en Polars de las variables de eventos"),
    "pipeline/ingesta.py": ("Código", "Lectura de CSV/Excel/JSON/Parquet a Parquet (todo como texto)"),
    "pipeline/limpieza.py": ("Código", "Tipado y limpieza por clase de columna"),
    "pipeline/llaves.py": ("Código", "Grano de cada tabla y cómo se unen"),
    "pipeline/modelado/__init__.py": ("Código", "Marca el paquete"),
    "pipeline/modelado/afinamiento.py": ("Código", "Búsqueda de hiperparámetros con Optuna y su importancia"),
    "pipeline/modelado/candidatos.py": ("Código", "Modelos candidatos con la misma validación (regla, logística, LightGBM, XGBoost, CatBoost)"),
    "pipeline/modelado/datos.py": ("Código", "Qué filas entrenan, cuáles se puntúan y cómo se valida"),
    "pipeline/modelado/diagnostico.py": ("Código", "Mide la tabla y recomienda qué probar"),
    "pipeline/modelado/importancia.py": ("Código", "Importancia de variables: gain, permutación, SHAP"),
    "pipeline/modelado/metricas.py": ("Código", "Gini, AUC-PR, lift, captura, calibración"),
    "pipeline/modelado/priorizar.py": ("Código", "Lista según capacidad: voraz vs PuLP/HiGHS"),
    "pipeline/modelado/reporte_modelo.py": ("Código", "Reporte HTML del modelado"),
    "pipeline/modelado/segmentos_monto.py": ("Código", "Uno vs varios modelos por segmento; modelo de monto"),
    "pipeline/monitor.py": ("Código", "Reporte HTML de los datos"),
    "pipeline/perfil.py": ("Código", "Ficha y decisión por columna"),
    "pipeline/plataforma.py": ("Código", "Diferencias Windows/macOS/Linux (consola, RAM, archivos)"),
    "pipeline/regularizar.py": ("Código", "Transformaciones aprendidas solo con train"),
    "pipeline/seleccion.py": ("Código", "Embudo de selección y detección de fugas"),
    "preparar_offline.py": ("Utilidad", "Instala y prueba todo; resumen OK/FALTA"),
    "requirements.txt": ("Configuración", "Librerías de Python"),
    "run_modelo.py": ("Código", "Orquestador del modelado"),
    "run_pipeline.py": ("Código", "Orquestador del pipeline de datos"),
}


def archivos_plantilla():
    try:
        r = subprocess.run(["git", "ls-files", "-z"], cwd=PLANTILLA, capture_output=True, check=True)
        lista = [p for p in r.stdout.decode("utf-8").split("\0") if p]
    except Exception:
        print("  (git no disponible: se recorre la carpeta excluyendo data/, salidas/, .git/)")
        lista = [str(p.relative_to(PLANTILLA)).replace("\\", "/") for p in PLANTILLA.rglob("*")
                 if p.is_file() and not any(x in p.parts for x in (".git", "data", "salidas", "__pycache__", ".venv"))]
    # archivos de evento/ aún no commiteados también entran
    lista += [str(p.relative_to(PLANTILLA)).replace("\\", "/") for p in (PLANTILLA / "evento").glob("*") if p.is_file()]
    return sorted(set(lista))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-evento", required=True, help="carpeta raíz del repo Datafest-BCP (la que tiene REGLAS.md)")
    ap.add_argument("--revisado-por", default="[usuarios de GitHub]", help="quiénes revisaron la plantilla")
    ap.add_argument("--autoria", default=None, help="texto de autoría (por defecto declara la asistencia de IA)")
    ap.add_argument("--reemplazar", action="store_true", help="si base_conocimiento/plantilla ya existe, rehacerla")
    a = ap.parse_args()

    repo = Path(a.repo_evento).expanduser().resolve()
    if not (repo / "REGLAS.md").exists():
        print(f"AVISO: {repo} no tiene REGLAS.md. ¿Es la raíz del repo del evento? (sigo igual)")
    base = repo / "base_conocimiento"
    destino = base / "plantilla"
    if destino.exists():
        if not a.reemplazar:
            sys.exit(f"{destino} ya existe. Usen --reemplazar para rehacerla.")
        shutil.rmtree(destino)

    copiados, excluidos = [], []
    for rel in archivos_plantilla():
        src = PLANTILLA / rel
        if not src.is_file():
            continue
        if src.suffix.lower() in PROHIBIDAS:
            excluidos.append(rel)
            continue
        if rel.startswith("data/") or "__pycache__" in rel or src.suffix.lower() in (".pyc", ".pyo"):
            continue      # ninguna carpeta data/ ni binarios dentro de la base (el control busca datos)
        dst = destino / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copiados.append(rel)

    total_mb = sum(p.stat().st_size for p in base.rglob("*") if p.is_file()) / 1e6
    print(f"Copiados {len(copiados)} archivos a {destino}")
    if excluidos:
        print("Excluidos por ser datos (prohibidos en la base): " + ", ".join(excluidos))
    estado = "OK" if total_mb < MARGEN_MB else ("JUSTO" if total_mb < LIMITE_MB else "EXCEDE")
    print(f"Tamaño de base_conocimiento/: {total_mb:.2f} MB (límite {LIMITE_MB} MB) -> {estado}")
    if estado == "EXCEDE":
        sys.exit("Excede el límite: saquen archivos antes de subir.")

    autoria = a.autoria or AUTORIA_DEFECTO.format(revisado=a.revisado_por)
    filas = []
    for p in sorted(base.rglob("*")):
        if not p.is_file() or p.name in ("INVENTARIO.md", "INVENTARIO_propuesto.md"):
            continue
        rel_base = p.relative_to(base).as_posix()
        rel_pl = p.relative_to(destino).as_posix() if destino in p.parents else None
        tipo, para = DESCRIPCION.get(rel_pl, ("[COMPLETAR]", "[COMPLETAR]"))
        quien = autoria if rel_pl else "[COMPLETAR: usuario(s) de GitHub de quien lo escribió]"
        filas.append(f"| `{rel_base}` | {tipo} | {quien} | {para} |")

    texto = f"""# Inventario de la base de conocimiento

> Nota sobre autoría: el código y los documentos de `plantilla/` se prepararon ANTES del evento con
> asistencia de una IA distinta del Copilot del evento (Claude, de Anthropic). El equipo los revisó,
> los probó con datos sintéticos generados por nosotros y puede explicar cada parte.
> [Si la organización respondió la consulta, indicar aquí la fecha y la respuesta.]
> No contiene datos del reto, datos reales ni modelos entrenados.

| Archivo | Qué es | Quién lo escribió | Para qué sirve |
|---|---|---|---|
""" + "\n".join(filas) + "\n"
    inv = base / "INVENTARIO.md"
    if inv.exists() and "plantilla/" not in inv.read_text(encoding="utf-8"):
        inv = base / "INVENTARIO_propuesto.md"
        print("Ya existe un INVENTARIO.md oficial: escribí INVENTARIO_propuesto.md. Copien sus filas al formato "
              "oficial y borren el propuesto antes del commit.")
    inv.write_text(texto, encoding="utf-8")
    print(f"Inventario: {inv}  ({len(filas)} archivos; completen los [COMPLETAR])")

    print(f"""
Siguientes pasos (cada una con SU cuenta y el correo anónimo configurado):
  cd "{repo}"
  git checkout -b <usuario>/base
  git add base_conocimiento
  git status                      # revisen: nada de data/ ni .csv
  git commit -m "base: plantilla e inventario"
  git push -u origin <usuario>/base
  -> Pull Request en GitHub; la integradora lo fusiona ANTES de las 13:30 del viernes (cierre 14:00).
  -> Comprueben en github.com/Datafest-BCP/<equipo>/tree/main/base_conocimiento""")


if __name__ == "__main__":
    main()
