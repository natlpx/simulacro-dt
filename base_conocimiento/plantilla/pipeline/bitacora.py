"""
BITÁCORA (data lineage): registra qué le pasó a cada tabla en cada paso.

Por qué: con 8 GB nadie puede "mirar" los datos. Lo que sí se puede es medir en cada paso
filas, columnas, nulos y la SUMA de montos. Si la suma de montos cambia entre 'ingesta' y
'limpieza' sin que lo hayamos decidido, perdimos o duplicamos plata en un JOIN.
Es la conciliación que hace cualquier equipo de datos en un banco.
"""
import json
import time
from datetime import datetime

import config as C


class Bitacora:
    def __init__(self, nombre="bitacora"):
        C.OUT_DIR.mkdir(parents=True, exist_ok=True)
        self.path = C.OUT_DIR / f"{nombre}.jsonl"
        self._t0 = time.time()

    def registrar(self, paso, tabla, filas, columnas, extra=None, segundos=None):
        fila = dict(ts=datetime.now().isoformat(timespec="seconds"), paso=paso, tabla=tabla,
                    filas=int(filas), columnas=int(columnas),
                    segundos=round(segundos if segundos is not None else time.time() - self._t0, 2),
                    **(extra or {}))
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(fila, ensure_ascii=False, default=str) + "\n")
        extra_txt = " ".join(f"{k}={v}" for k, v in (extra or {}).items() if not isinstance(v, (dict, list)))
        print(f"  [{paso:<10}] {tabla:<28} filas={filas:>12,}  cols={columnas:>4}  {extra_txt}")
        self._t0 = time.time()

    def leer(self):
        import pandas as pd
        if not self.path.exists():
            return pd.DataFrame()
        return pd.read_json(self.path, lines=True)

    def reiniciar(self):
        if self.path.exists():
            self.path.unlink()
