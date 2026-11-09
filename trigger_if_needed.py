#!/usr/bin/env python3
"""
Gatekeeper script for the Weekly Notion Recipes Standardization sidecar.
Runs in 0.05s locally with ZERO AI tokens and ZERO chat conversations if the current ISO week
has already been processed in weekly_state.json.
Only when a new week starts (and has not been processed yet) does it invoke `agentapi.bat new-conversation`.
"""
import datetime
import json
import os
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(BASE_DIR, 'weekly_state.json')

PROMPT = (
    'Llama a la herramienta MCP `check_weekly_batch` del servidor `notion-recetas` (con `force: false`). '
    'Si el resultado tiene `"status": "ALREADY_DONE_THIS_WEEK"` o `"status": "NO_PENDING_RECORDS"`, '
    'detente inmediatamente y responde únicamente con una línea indicando que la tanda semanal ya está al día. '
    'Si el resultado es `"status": "PENDING_BATCH"`, analiza los 10 registros devueltos (si algún vídeo de YouTube '
    'tiene descripción vacía o le faltan ingredientes/pasos, usa `search_web` buscando el `video_id` o el título '
    'del vídeo para obtener la receta completa), prepara para cada uno su versión estandarizada en español '
    '(`title` limpio para la tabla, `h1_title` para la cabecera, `emoji` representativo, `categories` como '
    '`salado`/`dulce`/`comida italiana`/`comida china`, `ingredients_tags` en minúsculas en español, '
    '`ingredient_lines` con cantidades, `steps` detallados con `title` y `text`, y `link`; si algún registro no es '
    'una receta sino una reseña de tienda/restaurante, pon `"archive": true`), y finalmente llama a la herramienta '
    'MCP `apply_weekly_batch` del servidor `notion-recetas` pasando el array `records` y `mark_week_done: true`. '
    'No ejecutes ningún comando de terminal (`run_command`).'
)


def current_iso_week():
    today = datetime.date.today()
    iso = today.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def main():
    week_key = current_iso_week()
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, 'r', encoding='utf-8') as f:
                state = json.load(f)
            if state.get('last_completed_week') == week_key:
                # Already done this week! Exit silently without opening a conversation.
                return 0
        except Exception:
            pass

    # Not done this week yet: trigger the agent conversation!
    res = subprocess.run([r'C:/Users/sauri/.gemini/antigravity/bin\agentapi.BAT', shell=True, 'new-conversation', '--', PROMPT])
    return res.returncode


if __name__ == '__main__':
    sys.exit(main())
