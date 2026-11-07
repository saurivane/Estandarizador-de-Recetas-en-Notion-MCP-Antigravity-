#!/usr/bin/env python3
"""
Helper script for the Weekly Notion Recipes Standardization automation.
Subcommands:
  check [--force]       - Checks if a batch of 10 recipes has already been processed in the current ISO week.
                          If not, fetches the next 10 unprocessed recipes (ordered by Fecha de creación ASC)
                          and prints their Notion page details and YouTube/web metadata as JSON.
  apply <spec.json>     - Applies the standardized recipe updates to Notion from a JSON file and marks
                          the current week as completed in weekly_state.json.
  mark-week             - Records the current ISO week in weekly_state.json.
"""
import datetime
import json
import os
import re
import sys
import urllib.request
import urllib.error

sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, '.env')
STATE_PATH = os.path.join(BASE_DIR, 'weekly_state.json')


def load_config():
    env = {}
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    env[k.strip()] = v.strip()
    token = os.environ.get('NOTION_TOKEN') or env.get('NOTION_TOKEN', '')
    db_id = os.environ.get('NOTION_DATABASE_ID') or env.get('NOTION_DATABASE_ID', '')
    return token, db_id


def current_iso_week():
    today = datetime.date.today()
    iso = today.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def req_notion(path, token, method='GET', data=None):
    headers = {
        'Authorization': f'Bearer {token}',
        'Notion-Version': '2022-06-28',
        'Content-Type': 'application/json'
    }
    req = urllib.request.Request(
        f'https://api.notion.com/v1{path}',
        data=json.dumps(data).encode('utf-8') if data is not None else None,
        headers=headers,
        method=method
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode('utf-8'))


def fetch_youtube_info(url):
    if not url:
        return {}
    m = re.search(r'(?:v=|/shorts/|youtu\.be/)([A-Za-z0-9_-]{11})', url)
    if not m:
        return {'url': url, 'type': 'web'}
    vid = m.group(1)
    yt_url = f'https://www.youtube.com/watch?v={vid}'
    try:
        req = urllib.request.Request(
            yt_url,
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        )
        html = urllib.request.urlopen(req, timeout=10).read().decode('utf-8', errors='ignore')
        m_pr = re.search(r'var ytInitialPlayerResponse = (\{.*?\});', html)
        if m_pr:
            pr = json.loads(m_pr.group(1))
            vd = pr.get('videoDetails', {})
            return {
                'video_id': vid,
                'title': vd.get('title'),
                'author': vd.get('author'),
                'description': vd.get('shortDescription')
            }
    except Exception as e:
        return {'video_id': vid, 'error': str(e)}
    return {'video_id': vid}


def cmd_check(force=False):
    week_key = current_iso_week()
    state = {}
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, 'r', encoding='utf-8') as f:
                state = json.load(f)
        except Exception:
            state = {}

    if not force and state.get('last_completed_week') == week_key:
        print(json.dumps({
            'status': 'ALREADY_DONE_THIS_WEEK',
            'week': week_key,
            'last_run_at': state.get('last_run_at'),
            'message': f'La tanda semanal para {week_key} ya fue procesada.'
        }, ensure_ascii=False, indent=2))
        return

    token, db_id = load_config()
    if not token or not db_id:
        print(json.dumps({
            'status': 'ERROR_MISSING_CONFIG',
            'message': 'No se encontraron NOTION_TOKEN o NOTION_DATABASE_ID en las variables de entorno o archivo .env.'
        }, ensure_ascii=False, indent=2))
        return

    query_body = {
        'filter': {
            'property': 'Procesado',
            'checkbox': {'equals': False}
        },
        'sorts': [
            {
                'property': 'Fecha de creación',
                'direction': 'ascending'
            }
        ],
        'page_size': 10
    }
    data = req_notion(f'/databases/{db_id}/query', token, method='POST', data=query_body)
    results = data.get('results', [])

    if not results:
        print(json.dumps({
            'status': 'NO_PENDING_RECORDS',
            'week': week_key,
            'message': 'No hay registros pendientes por procesar en la base de datos Recetas.'
        }, ensure_ascii=False, indent=2))
        return

    batch = []
    for p in results:
        props = p.get('properties', {})
        title = ''.join(x['plain_text'] for x in props.get('Name', {}).get('title', []))
        link = props.get('Link', {}).get('url', '')
        created = props.get('Fecha de creación', {}).get('created_time', '')
        yt_info = fetch_youtube_info(link)
        batch.append({
            'page_id': p['id'],
            'current_title': title,
            'created_time': created,
            'link': link,
            'source_metadata': yt_info
        })

    print(json.dumps({
        'status': 'PENDING_BATCH',
        'week': week_key,
        'count': len(batch),
        'records': batch
    }, ensure_ascii=False, indent=2))


def build_blocks(rec):
    blocks = [
        {
            'object': 'block',
            'type': 'heading_1',
            'heading_1': {
                'rich_text': [{
                    'type': 'text',
                    'text': {'content': rec.get('h1_title', rec['title'])},
                    'annotations': {'color': 'yellow_background'}
                }]
            }
        },
        {
            'object': 'block',
            'type': 'heading_2',
            'heading_2': {
                'rich_text': [{
                    'type': 'text',
                    'text': {'content': 'Ingredientes'},
                    'annotations': {'color': 'brown_background'}
                }]
            }
        }
    ]
    # Ingredients can be a flat list of strings or a list of {"section": "...", "items": [...]}
    for item in rec.get('ingredient_lines', []):
        if isinstance(item, dict) and 'section' in item:
            blocks.append({
                'object': 'block',
                'type': 'paragraph',
                'paragraph': {
                    'rich_text': [{
                        'type': 'text',
                        'text': {'content': item['section']},
                        'annotations': {'bold': True}
                    }]
                }
            })
            for sub in item.get('items', []):
                blocks.append({
                    'object': 'block',
                    'type': 'bulleted_list_item',
                    'bulleted_list_item': {
                        'rich_text': [{'type': 'text', 'text': {'content': sub}}]
                    }
                })
        else:
            blocks.append({
                'object': 'block',
                'type': 'bulleted_list_item',
                'bulleted_list_item': {
                    'rich_text': [{'type': 'text', 'text': {'content': str(item)}}]
                }
            })

    blocks.append({
        'object': 'block',
        'type': 'heading_2',
        'heading_2': {
            'rich_text': [{
                'type': 'text',
                'text': {'content': 'Instrucciones'},
                'annotations': {'color': 'brown_background'}
            }]
        }
    })

    for step_item in rec.get('steps', []):
        if isinstance(step_item, dict):
            prefix = step_item.get('title', '')
            if prefix and not prefix.endswith(': '):
                prefix = prefix.rstrip(':') + ': '
            text = step_item.get('text', '')
            blocks.append({
                'object': 'block',
                'type': 'numbered_list_item',
                'numbered_list_item': {
                    'rich_text': [
                        {'type': 'text', 'text': {'content': prefix}, 'annotations': {'bold': True}},
                        {'type': 'text', 'text': {'content': text}}
                    ]
                }
            })
        else:
            blocks.append({
                'object': 'block',
                'type': 'numbered_list_item',
                'numbered_list_item': {
                    'rich_text': [{'type': 'text', 'text': {'content': str(step_item)}}]
                }
            })

    blocks.append({
        'object': 'block',
        'type': 'paragraph',
        'paragraph': {'rich_text': []}
    })

    link = rec.get('link', '')
    if link:
        if 'youtube.com' in link or 'youtu.be' in link:
            blocks.append({
                'object': 'block',
                'type': 'video',
                'video': {'type': 'external', 'external': {'url': link}}
            })
        else:
            blocks.append({
                'object': 'block',
                'type': 'embed',
                'embed': {'url': link}
            })
    return blocks


def cmd_apply(spec_file):
    token, _ = load_config()
    if not token:
        print("Error: falta NOTION_TOKEN")
        sys.exit(1)
    with open(spec_file, 'r', encoding='utf-8') as f:
        spec = json.load(f)

    records = spec.get('records', spec if isinstance(spec, list) else [])
    for rec in records:
        page_id = rec['page_id']
        if rec.get('archive') is True:
            req_notion(f'/pages/{page_id}', token, method='PATCH', data={'archived': True})
            print(f"Archived non-recipe page: {page_id}")
            continue

        page_update = {
            'icon': {'type': 'emoji', 'emoji': rec.get('emoji', '🍽️')},
            'properties': {
                'Name': {'title': [{'type': 'text', 'text': {'content': rec['title']}}]},
                'Categorías': {'multi_select': [{'name': c} for c in rec.get('categories', [])]},
                'Ingredientes': {'multi_select': [{'name': i} for i in rec.get('ingredients_tags', [])]},
                'Procesado': {'checkbox': True}
            }
        }
        req_notion(f'/pages/{page_id}', token, method='PATCH', data=page_update)

        existing = req_notion(f'/blocks/{page_id}/children?page_size=100', token, method='GET')
        for b in existing.get('results', []):
            req_notion(f"/blocks/{b['id']}", token, method='DELETE')

        new_blocks = build_blocks(rec)
        req_notion(f'/blocks/{page_id}/children', token, method='PATCH', data={'children': new_blocks})
        print(f"Updated recipe: {rec['title']} ({page_id})")

    cmd_mark_week()


def cmd_mark_week():
    week_key = current_iso_week()
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    state = {
        'last_completed_week': week_key,
        'last_run_at': now_iso
    }
    with open(STATE_PATH, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    print(json.dumps({'status': 'MARKED', 'week': week_key, 'last_run_at': now_iso}, ensure_ascii=False))


if __name__ == '__main__':
    action = sys.argv[1] if len(sys.argv) > 1 else 'check'
    force_flag = '--force' in sys.argv
    if action == 'check':
        cmd_check(force=force_flag)
    elif action == 'apply':
        if len(sys.argv) < 3:
            print("Usage: python notion_weekly_batch.py apply <spec.json>")
            sys.exit(1)
        cmd_apply(sys.argv[2])
    elif action == 'mark-week':
        cmd_mark_week()
    else:
        print(f"Unknown action: {action}")
        sys.exit(1)
