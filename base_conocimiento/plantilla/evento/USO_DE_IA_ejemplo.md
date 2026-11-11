# Cómo llenar docs/USO_DE_IA.md durante el evento

El PDF pide **una línea por tarea** cada vez que usen Copilot. Usen el formato que traiga el archivo del repo; si no trae ninguno, este funciona:

| Hora | Quién tecleaba | Tarea | Qué se le pidió a Copilot | Qué hicimos con la respuesta |
|---|---|---|---|---|
| 16:10 | [usuario] | Exportar submission | Ajustar `FORMATO` de `exportar_submission.py` a `entregas/README.md` | Aceptado tras revisarlo; `datafest.validar` OK |
| 17:30 | [usuario] | Error de DuckDB | Explicar `Conversion Error` en la columna de fechas | Se corrigió a mano en `config_evento.py` (`FORMATOS_FECHA`) |
| 21:00 | [usuario] | Presentación | Proponer texto para la diapositiva del hallazgo | Reescrito por el equipo |

Reglas del PDF que conviene recordar:
- Un chat nuevo por tarea.
- Copilot no ve los datos del reto. No le peguen datos.
- Si cita una web, anoten la dirección en `docs/BITACORA_FUENTES.md` y escriban su propia implementación.
- Rotar quién teclea cada 30–40 minutos; quien teclea hace el commit con su cuenta.
- Uso de IA **antes** del evento: declarado en `base_conocimiento/INVENTARIO.md`.
