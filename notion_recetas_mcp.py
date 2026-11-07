#!/usr/bin/env python3
"""
Local stdio MCP Server for Notion Recetas Weekly Standardization.
Runs outside the terminal sandbox via Antigravity's MCP host so scheduled automations
can query and update Notion + YouTube metadata without needing BypassSandbox prompts.
"""
import datetime
import json
import os
import re
import sys
import urllib.request
import urllib.error

sys.stdin.reconfigure(encoding='utf-8')
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
    with urllib.request.urlopen(req, timeout=20) as resp:
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
        html = urllib.request.urlopen(req, timeout=15).read().decode('utf-8', errors='ignore')
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


def check_weekly_batch(force=False):
    week_key = current_iso_week()
    state = {}
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, 'r', encoding='utf-8') as f:
                state = json.load(f)
        except Exception:
            state = {}

    if not force and state.get('last_completed_week') == week_key:
        return {
            'status': 'ALREADY_DONE_THIS_WEEK',
            'week': week_key,
            'last_run_at': state.get('last_run_at'),
            'message': f'La tanda semanal para {week_key} ya fue procesada.'
        }

    token, db_id = load_config()
    if not token or not db_id:
        return {
            'status': 'ERROR_MISSING_CONFIG',
            'message': 'No se encontraron NOTION_TOKEN o NOTION_DATABASE_ID en las variables de entorno o archivo .env.'
        }

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
        return {
            'status': 'NO_PENDING_RECORDS',
            'week': week_key,
            'message': 'No hay registros pendientes por procesar en la base de datos Recetas.'
        }

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

    return {
        'status': 'PENDING_BATCH',
        'week': week_key,
        'count': len(batch),
        'records': batch
    }


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


def apply_weekly_batch(records, mark_week_done=True):
    token, _ = load_config()
    if not token:
        return {'status': 'ERROR_MISSING_TOKEN', 'message': 'Falta NOTION_TOKEN'}
    updated = []
    for rec in records:
        page_id = rec['page_id']
        if rec.get('archive') is True:
            req_notion(f'/pages/{page_id}', token, method='PATCH', data={'archived': True})
            updated.append({'page_id': page_id, 'action': 'archived'})
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
        updated.append({'page_id': page_id, 'title': rec['title'], 'action': 'standardized'})

    week_key = current_iso_week()
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if mark_week_done:
        state = {
            'last_completed_week': week_key,
            'last_run_at': now_iso
        }
        with open(STATE_PATH, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

    return {
        'status': 'SUCCESS',
        'week_marked': week_key if mark_week_done else None,
        'updated_records': updated
    }


TOOLS = [
    {
        'name': 'check_weekly_batch',
        'description': 'Checks if the weekly batch of 10 Notion recipes has already been processed this ISO week. If not, returns the next 10 unprocessed recipes from Notion along with their YouTube video metadata.',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'force': {
                    'type': 'boolean',
                    'description': 'If true, ignores whether the current week was already marked completed and fetches the next 10 unprocessed recipes anyway. Default false.'
                }
            }
        }
    },
    {
        'name': 'apply_weekly_batch',
        'description': 'Standardizes a list of Notion recipe records (updates icon, title, categories, ingredient tags, page blocks with H1/H2/ingredients/instructions/video, sets Procesado=true) and marks the current ISO week as completed.',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'records': {
                    'type': 'array',
                    'description': 'List of standardized recipe objects to apply in Notion.',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'page_id': {'type': 'string', 'description': 'Notion page UUID'},
                            'archive': {'type': 'boolean', 'description': 'Set true ONLY if the video is not a recipe (e.g. a restaurant/shop review) and should be deleted/archived'},
                            'title': {'type': 'string', 'description': 'Clean Spanish recipe name for the database Name property'},
                            'h1_title': {'type': 'string', 'description': 'Heading 1 title inside the page (yellow_background)'},
                            'emoji': {'type': 'string', 'description': 'Single emoji icon for the page'},
                            'categories': {
                                'type': 'array',
                                'items': {'type': 'string'},
                                'description': 'Categories multi-select (e.g., "salado", "dulce", "comida italiana", "comida china")'
                            },
                            'ingredients_tags': {
                                'type': 'array',
                                'items': {'type': 'string'},
                                'description': 'Normalized lowercase Spanish ingredient names for the Ingredientes multi-select property'
                            },
                            'ingredient_lines': {
                                'type': 'array',
                                'description': 'Either strings (bullet points) or objects {"section": "Para la masa:", "items": ["500 g de harina", ...]}',
                                'items': {}
                            },
                            'steps': {
                                'type': 'array',
                                'description': 'Instruction steps as objects {"title": "Preparar la masa", "text": "En un bol..."}',
                                'items': {
                                    'type': 'object',
                                    'properties': {
                                        'title': {'type': 'string'},
                                        'text': {'type': 'string'}
                                    },
                                    'required': ['title', 'text']
                                }
                            },
                            'link': {'type': 'string', 'description': 'Original video/recipe URL to embed at the bottom'}
                        },
                        'required': ['page_id']
                    }
                },
                'mark_week_done': {
                    'type': 'boolean',
                    'description': 'Whether to mark the current ISO week as completed in weekly_state.json. Default true.'
                }
            },
            'required': ['records']
        }
    }
]


def send_response(msg_id, result=None, error=None):
    resp = {'jsonrpc': '2.0', 'id': msg_id}
    if error is not None:
        resp['error'] = error
    else:
        resp['result'] = result
    sys.stdout.write(json.dumps(resp, ensure_ascii=False) + '\n')
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue

        method = msg.get('method')
        msg_id = msg.get('id')
        params = msg.get('params') or {}

        if method == 'initialize':
            send_response(msg_id, {
                'protocolVersion': params.get('protocolVersion', '2024-11-05'),
                'capabilities': {'tools': {}},
                'serverInfo': {'name': 'notion-recetas', 'version': '1.0.0'}
            })
        elif method == 'notifications/initialized':
            continue
        elif method == 'ping':
            send_response(msg_id, {})
        elif method == 'tools/list':
            send_response(msg_id, {'tools': TOOLS})
        elif method == 'tools/call':
            tool_name = params.get('name')
            args = params.get('arguments') or {}
            try:
                if tool_name == 'check_weekly_batch':
                    res = check_weekly_batch(force=bool(args.get('force', False)))
                elif tool_name == 'apply_weekly_batch':
                    res = apply_weekly_batch(
                        records=args.get('records', []),
                        mark_week_done=bool(args.get('mark_week_done', True))
                    )
                else:
                    send_response(msg_id, error={'code': -32601, 'message': f'Unknown tool: {tool_name}'})
                    continue

                send_response(msg_id, {
                    'content': [{'type': 'text', 'text': json.dumps(res, ensure_ascii=False, indent=2)}],
                    'isError': False
                })
            except Exception as e:
                send_response(msg_id, {
                    'content': [{'type': 'text', 'text': f'Error: {e}'}],
                    'isError': True
                })
        elif msg_id is not None:
            send_response(msg_id, error={'code': -32601, 'message': f'Method not found: {method}'})


if __name__ == '__main__':
    main()
