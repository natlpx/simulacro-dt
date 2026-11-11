# Guía paso a paso: correr la plantilla en Windows, macOS o Linux

Cada paso tiene el comando para los tres sistemas. Hagan los pasos 1 a 5 **en casa, con internet**, en las 5 laptops. El día del concurso solo hacen los pasos 6 a 8.

> Probado con Python 3.10 y 3.13, y con la carpeta en una ruta con espacios, tildes y ñ (`.../Sofía Ñandú/plantilla datafest`).

---

## Paso 1. Verificar Git y Python

| | Windows (PowerShell) | macOS (Terminal) | Linux (Terminal) |
|---|---|---|---|
| Git | `git --version` | `git --version` | `git --version` |
| Python | `py --version` | `python3 --version` | `python3 --version` |

- Se necesita **Python 3.10 o superior**; lo ideal es 3.11 o 3.12. Con 3.14, algunas librerías (CatBoost) pueden no instalar todavía.
- **Windows:** si `py` no existe, instalen Python desde python.org y marquen **"Add python.exe to PATH"** en la primera pantalla.
- **macOS:** si no tienen Homebrew, instálenlo desde brew.sh; lo necesitan en el paso 4.

En esta guía, `PY` significa `py` en Windows y `python3` en macOS o Linux. Dentro del entorno virtual (paso 3) los tres usan simplemente `python`.

## Paso 2. Poner el repo en una carpeta que NO se sincronice

OneDrive (Windows) e iCloud (macOS, en "Documentos" y "Escritorio") bloquean archivos mientras se sincronizan. DuckDB escribe muchos archivos y eso da errores raros.

| Windows | macOS / Linux |
|---|---|
| `mkdir C:\datafest` y `cd C:\datafest` | `mkdir -p ~/datafest && cd ~/datafest` |

Luego clonen ahí:
```
git clone <url-del-repo>
cd plantilla_2026
```

## Paso 3. Crear y activar el entorno virtual

El entorno virtual (`.venv`) aísla las librerías de este proyecto. Así no chocan con otras versiones instaladas en la laptop.

| | Windows (PowerShell) | macOS / Linux |
|---|---|---|
| Crear (una sola vez) | `py -m venv .venv` | `python3 -m venv .venv` |
| Activar (cada vez que abran una terminal) | `.venv\Scripts\Activate.ps1` | `source .venv/bin/activate` |
| Saber si está activo | El prompt empieza con `(.venv)` | El prompt empieza con `(.venv)` |

- **Windows:** si sale *"la ejecución de scripts está deshabilitada"*, corran una sola vez `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` y respondan `S`.
- **Windows con CMD** en vez de PowerShell: `.venv\Scripts\activate.bat`.
- **VS Code:** `Ctrl+Shift+P` (`Cmd+Shift+P` en Mac) → *Python: Select Interpreter* → elijan el que dice `.venv`. Así la terminal de VS Code lo activa sola.

## Paso 4. Requisito extra según el sistema

| Sistema | Qué hacer | Por qué |
|---|---|---|
| **macOS** | `brew install libomp` | LightGBM y XGBoost usan OpenMP para paralelizar, y macOS no lo trae |
| **Windows** | Normalmente nada. Si LightGBM no carga, instalen *Microsoft Visual C++ Redistributable (x64)* | Son librerías de C++ que necesitan esas DLL |
| **Linux** | `sudo apt install libgomp1` (Ubuntu/Debian), si LightGBM no carga | Mismo motivo que en macOS |

## Paso 5. Instalar y probar todo con un solo comando

Con el entorno activo:
```
python preparar_offline.py
```

Tarda unos 3–5 minutos e imprime un **resumen**: una línea por librería con OK o FALTA, más el resultado de una prueba completa con datos sintéticos.
- Si algo dice FALTA, el mismo script imprime el arreglo para su sistema.
- Peguen el resumen en el grupo del equipo: así saben qué laptops están listas.

---

## Paso 6. El día del concurso: preparar datos y configuración

1. Copien los archivos del caso en `data/raw/`. Esa carpeta no se sube a git: está en `.gitignore`.
2. Ajusten la configuración. Si la plantilla está en `base_conocimiento/` (que se cierra a las 14:00), **no editen su `config.py`**. Creen un `config_evento.py` fuera de esa carpeta y corran todo con `--config config_evento.py`. Ver `experimentos/config_variante.py` como ejemplo.

## Paso 7. Correr en este orden

```
python run_pipeline.py
python run_pipeline.py --desde features --corte AAAA-MM-DD --sufijo _t1
python run_modelo.py
```

- **Primero** la tabla del corte actual; **después** la del corte anterior (`_t1`). La segunda corrida rehace la selección de variables de forma honesta (`docs/CAMBIOS_REVISION.md`).
- `--rapido` en `run_modelo.py` salta XGBoost, CatBoost, segmentos y permutación. Úsenlo para iterar rápido.
- Al empezar, cada script imprime una línea como `macOS · Python 3.12 · RAM 24 GB · DuckDB memory_limit=14GB threads=9`. **La RAM y los núcleos se detectan solos** en cada laptop.

## Paso 8. Abrir los reportes

| Windows | macOS | Linux |
|---|---|---|
| `start salidas\monitor.html` | `open salidas/monitor.html` | `xdg-open salidas/monitor.html` |
| `start salidas\modelo\reporte_modelo.html` | `open salidas/modelo/reporte_modelo.html` | `xdg-open salidas/modelo/reporte_modelo.html` |

---

## Que la laptop no se duerma durante corridas largas

| Windows | macOS | Linux |
|---|---|---|
| Configuración → Sistema → Energía → "Suspender: nunca" (enchufada), o `powercfg /change standby-timeout-ac 0` | `caffeinate -i python run_modelo.py --optuna 1800` | `systemd-inhibit python run_modelo.py --optuna 1800` |

## Problemas frecuentes

| Mensaje | Sistema | Arreglo |
|---|---|---|
| `'python' no se reconoce` | Windows | Usen `py`, o reinstalen Python marcando "Add to PATH" y reabran la terminal |
| `la ejecución de scripts está deshabilitada` | Windows | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| `UnicodeEncodeError: 'charmap'` | Windows | Ya está corregido en `config.py`. Si aparece en un script propio, agreguen `from pipeline import plataforma; plataforma.consola_utf8()` |
| `PermissionError` / `El proceso no tiene acceso al archivo` | Windows | Cierren Excel si tiene abierto un archivo de `data/raw` y saquen el repo de OneDrive (paso 2) |
| `Library not loaded: libomp.dylib` | macOS | `brew install libomp` |
| `externally-managed-environment` | macOS / Linux | Falta el entorno virtual (paso 3) |
| `No module named pip` | Todos | `python -m ensurepip --upgrade` |
| `No module named 'pipeline'` | Todos | Corran los scripts con la ruta a la raíz del repo: `python run_pipeline.py` desde esa carpeta, o `python ruta/al/repo/run_pipeline.py` |
| `Out of Memory` en DuckDB | Todos | Cierren otros programas o bajen `MEMORY_LIMIT` en la config (por ejemplo `"3GB"`) |
| Muy lento con `.xlsx` grandes | Todos | Corran `preparar_offline.py` con internet para descargar la extensión `excel` de DuckDB |

## Comandos de Git del evento (iguales en los tres sistemas)

```
git checkout -b nombre/tarea          # su rama
git add archivo.py && git commit -m "qué hice"
git push -u origin nombre/tarea       # al menos 1 vez por hora
```
Luego abren un Pull Request en GitHub y avisan a la integradora (al menos cada 2 horas).
