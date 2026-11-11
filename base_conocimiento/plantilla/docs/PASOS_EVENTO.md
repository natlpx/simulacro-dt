# Pasos del jueves al sábado, según el PDF de participación

Todo lo de este archivo sale de "Información de participación – Datafest 2026". Donde el PDF no dice algo, se marca como **supuesto**.

## Estructura final del repo del evento

```
<repo Datafest-BCP del equipo>/
├── REGLAS.md, .github/, scripts/ ...   ← de la organización: NO TOCAR
├── base_conocimiento/                  ← cierra vie 14:00 (fusionada en main)
│   ├── INVENTARIO.md                   ← una fila por archivo: qué es, quién, para qué
│   ├── notas/                          ← notas propias del equipo (.md)
│   └── plantilla/                      ← esta plantilla, sin datos ni historial
├── trabajo/                            ← se crea vie 15:30 (código nuevo del evento)
│   ├── config_evento.py                ← copia de base_conocimiento/plantilla/evento/ (incluye DECISIONES_MANUAL)
│   └── exportar_submission.py          ← copia de base_conocimiento/plantilla/evento/
├── data/                               ← datos del reto (bloqueada: nunca se suben)
├── entregas/submission.csv             ← entregable 1 (validar con python -m datafest.validar)
├── presentacion/index.html             ← entregable 2
└── docs/BITACORA_FUENTES.md, docs/USO_DE_IA.md
```

Las salidas pesadas (parquet, reportes HTML, predicciones) van a `~/datafest_trabajo/`, **fuera del repo**.

**Supuesto:** que los datos se ponen en `data/` de la raíz. Si la organización indica otra carpeta, cambien `RAW_DIR` en `config_evento.py`.

## Miércoles 11 y jueves 12 (antes de armar la base)

1. **Consultar a la organización** (respondiendo su correo) si se admite en `base_conocimiento/` código propio preparado antes del evento con asistencia de una IA. El PDF solo dice "código que escribió alguien de su equipo"; sin respuesta escrita, llevarlo es un riesgo.
2. **Poner en privado** los repos de práctica del equipo en GitHub (Settings → Danger Zone → Change visibility). El PDF prohíbe "código copiado de repositorios públicos": si la plantilla sigue pública, otro equipo puede copiarla y el control no sabrá quién copió a quién.
3. `python preparar_offline.py` en las 5 laptops: debe terminar sin ningún FALTA.
4. Simulacro completo con datos de prueba (ver "Simulacro" al final).

## Jueves 12 (noche)

1. Las 5 aceptan la invitación de GitHub antes del viernes a las 12:00.
2. Cada una clona el repo del evento y sigue `docs/GUIA_INICIO.md` del repo oficial.
3. Configurar el correo anónimo en ese repo: `git config user.email "<id>+<usuario>@users.noreply.github.com"`.
4. **Si la organización aprobó subir la plantilla**, una persona arma la base desde esta plantilla:
   ```
   python evento/copiar_a_base.py --repo-evento RUTA/AL/REPO_EVENTO --revisado-por "usuario1, usuario2, ..."
   ```
   - Revisen `base_conocimiento/INVENTARIO.md` y completen los `[COMPLETAR]`.
   - Agreguen sus notas propias en `base_conocimiento/notas/` y su fila en el inventario.
5. **Si no la aprobó:** solo `notas/` con lo escrito por ustedes, más su propio pipeline mínimo.

## Viernes 13

| Hora | Qué | Quién |
|---|---|---|
| hasta 13:30 | Rama `<usuario>/base` → PR → la integradora fusiona. Comprobar en GitHub que se ve `base_conocimiento/` en `main` | Quien armó la base + integradora |
| 14:00 | **Cierre de la base.** Desde aquí no se toca `base_conocimiento/` | — |
| 14:30 | Caso y dudas. Anotar: target, corte, métrica, formato de entrega, capacidad comercial | Todas (rol asignado) |
| 15:30 | **Inicio.** Crear `trabajo/` con las copias de `config_evento.py` y `exportar_submission.py` | Integradora o DS |
| 15:30–16:00 | Planificación de 30 min (recomendación de la organización) | Todas |
| 16:00 | Copiar datos a `data/`. Llenar la sección 3 de `trabajo/config_evento.py` | DE + DS |
| 16:15 | `python base_conocimiento/plantilla/run_pipeline.py --config trabajo/config_evento.py` | DE |
| ~18:00 | Segunda tabla: `... run_pipeline.py --config trabajo/config_evento.py --desde features --corte <corte anterior> --sufijo _t1` | DE |
| ~18:30 | `python base_conocimiento/plantilla/run_modelo.py --config trabajo/config_evento.py --rapido` | DS |
| ~22:00 | **Primer submission válido en `main`**: `python trabajo/exportar_submission.py --config trabajo/config_evento.py` → `python -m datafest.validar` → PR | DS + integradora |
| cada hora | `git push` de cada rama | Todas |
| cada 2 h | PR a `main` y aviso a la integradora | Todas |

## Sábado 14

| Hora | Qué |
|---|---|
| 09:00 | **Congelar el modelo.** Solo submission final, presentación y bitácoras |
| 09:00–10:00 | `presentacion/index.html` (partir de `base_conocimiento/plantilla/evento/presentacion_index.html`) |
| 10:00 | Todo fusionado en `main` (30 min de margen) |
| **10:30** | **Cierre: solo cuenta lo que está en `main`** |
| 11:30 | Evaluación técnica (30 min, preguntan a cualquiera) |
| 15:30 | Defensa de finalistas (10 min) |

## Comandos del evento (desde la raíz del repo)

| | Windows | macOS / Linux |
|---|---|---|
| Copiar config | `mkdir trabajo` y `copy base_conocimiento\plantilla\evento\config_evento.py trabajo\` | `mkdir -p trabajo && cp base_conocimiento/plantilla/evento/config_evento.py trabajo/` |
| Copiar exportador | `copy base_conocimiento\plantilla\evento\exportar_submission.py trabajo\` | `cp base_conocimiento/plantilla/evento/exportar_submission.py trabajo/` |
| Copiar presentación | `mkdir presentacion` y `copy base_conocimiento\plantilla\evento\presentacion_index.html presentacion\index.html` | `mkdir -p presentacion && cp base_conocimiento/plantilla/evento/presentacion_index.html presentacion/index.html` |

Lo copiado fuera de la base **cuenta como código nuevo** (PDF). Son ~3 archivos chicos; súbanlos en commits separados y temprano, para no disparar el aviso de "bloques grandes subidos de golpe".

## Lo que NO se hace

- Editar `base_conocimiento/` después de las 14:00 del viernes.
- Tocar `.github/`, `scripts/verificar_checkpoint.sh`, `scripts/validar_papers.py` o `REGLAS.md`.
- `git push --force`.
- Subir cualquier dato a cualquier carpeta.
- Usar otra IA que no sea el Copilot del evento, pegar datos o el enunciado en otros servicios, o pedir ayuda fuera del equipo.
- Mencionar la universidad (nombre del equipo, repo, presentación, defensa).

## Simulacro (con datos sintéticos, fuera del repo del evento)

Reproduce el flujo del viernes en una carpeta de mentira. macOS / Linux:

```
python generar_datos_prueba.py
mkdir -p ~/sim_evento/data && cd ~/sim_evento && git init && echo reglas > REGLAS.md
python RUTA/plantilla_2026/evento/copiar_a_base.py --repo-evento ~/sim_evento --revisado-por "usuarios"
cp RUTA/plantilla_2026/data/raw/*.* data/
mkdir -p trabajo && cp base_conocimiento/plantilla/evento/config_evento.py base_conocimiento/plantilla/evento/exportar_submission.py trabajo/
export DATAFEST_PRUEBA=1        # Windows PowerShell:  $env:DATAFEST_PRUEBA = "1"
python base_conocimiento/plantilla/run_pipeline.py --config trabajo/config_evento.py
python base_conocimiento/plantilla/run_pipeline.py --config trabajo/config_evento.py --desde features --corte 2025-01-01 --sufijo _t1
python base_conocimiento/plantilla/run_modelo.py --config trabajo/config_evento.py --rapido
python trabajo/exportar_submission.py --config trabajo/config_evento.py
git status     # solo deben aparecer base_conocimiento/, trabajo/ y entregas/submission.csv
```

Tiempos medidos el 11/11 con 20 000 empresas: pipeline ~70 s, corte anterior ~6 s, modelo rápido ~25 s.
Al terminar, borren `~/sim_evento` y `~/datafest_trabajo`. `DATAFEST_PRUEBA` no se usa el día del evento.
