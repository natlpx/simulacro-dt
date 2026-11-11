"""
Detalles del sistema operativo (Windows, macOS, Linux) en un solo lugar.

Por qué existe: el mismo código corre en 5 laptops distintas. Lo que cambia entre ellas
no es la lógica sino tres cosas del entorno:
  1. La consola de Windows puede no aceptar UTF-8 (⚠, ✂, tildes) y el print se cae
     con UnicodeEncodeError, sobre todo si la salida va a un archivo (python x.py > log.txt).
  2. La RAM y los núcleos: un memory_limit fijo ("5GB") se queda corto en una Mac de 24 GB
     y revienta una laptop de 8 GB con otras cosas abiertas.
  3. Detalles de archivos (renombrar sobre un archivo existente falla en Windows).
No importa config.py: config.py importa este módulo.
"""
import os
import platform
import sys
from pathlib import Path

SISTEMA = platform.system()  # "Windows", "Darwin" (macOS) o "Linux"
NOMBRE_SISTEMA = {"Darwin": "macOS"}.get(SISTEMA, SISTEMA)


def consola_utf8():
    """Fuerza UTF-8 en la salida. errors='replace': si aun así un símbolo no se puede mostrar,
    se imprime '?' en vez de detener el pipeline."""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def ram_total_gb():
    """RAM física en GB sin librerías extra (psutil no viene instalado por defecto)."""
    try:
        if SISTEMA == "Windows":
            import ctypes

            class _Mem(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = _Mem()
            m.dwLength = ctypes.sizeof(_Mem)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.ullTotalPhys / 1024 ** 3
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024 ** 3  # Linux y macOS
    except Exception:
        return 8.0  # valor prudente si no se puede medir


def recursos():
    """memory_limit = 60% de la RAM (el resto queda para el sistema, VS Code y el navegador).
    threads = núcleos - 1 (uno libre para que la laptop siga respondiendo)."""
    ram = ram_total_gb()
    nucleos = os.cpu_count() or 2
    return ram, f"{max(1, int(ram * 0.6))}GB", max(1, nucleos - 1)


def reemplazar(origen: Path, destino: Path):
    """Renombra pisando el destino si existe. Path.rename falla en Windows si el destino
    existe; Path.replace funciona igual en los tres sistemas."""
    Path(origen).replace(destino)


def resumen():
    ram, mem, hilos = recursos()
    return (f"{NOMBRE_SISTEMA} · Python {platform.python_version()} · RAM {ram:.0f} GB "
            f"-> DuckDB memory_limit={mem}, threads={hilos}")
