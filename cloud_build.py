"""Collect on a scheduled runner and export a static Pages site.

Without --collect this command never requests source APIs or translations.
"""
import argparse
import json
import shutil
import hashlib
import re
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import server

OUTPUT = server.ROOT / 'dist'


# Hours between attempts. Failed tasks also observe this interval.
CADENCE = {
    'aihot:content': 1, 'aihot:facts': 1, 'aihot:daily': 6,
    'github': 3, 'hn': 1, 'ph:today': 1,
    'ph:yesterday': 6, 'ph:7d': 6, 'ph:30d': 6, 'ph:categories': 12,
    **{f'x:{kind}:{window}': 6 if kind == 'creators' else 1
       for kind, windows in server.XRANK_RANGES.items() for window in windows},
}


def is_due(key, hours, now=None):
    now = now or datetime.now(timezone.utc)
    with closing(server.connect()) as conn:
        row = conn.execute('SELECT last_synced_at FROM sync_state WHERE resource=?', (f'cloud:{key}',)).fetchone()
    if not row or not row['last_synced_at']:
        return True
    try:
        previous = datetime.fromisoformat(row['last_synced_at'].replace('Z', '+00:00'))
        elapsed = (now - previous).total_seconds()
        return elapsed < 0 or elapsed >= hours * 3600
    except (ValueError, TypeError):
        return True


def attempt(key, operation):
    if not is_due(key, CADENCE[key]):
        print(f'Skipped (not due): {key}', flush=True)
        return False
    # Persist the start time, including failures, to avoid aggressive retries.
    server.AIHotClient._state(f'cloud:{key}', None, 'running', None)
    try:
        operation()
        status = 'ok'
    except Exception:
        status = 'error'
    # Keep the attempt start timestamp; source snapshots retain success timestamps.
    with closing(server.connect()) as conn, conn:
        conn.execute('UPDATE sync_state SET last_status=? WHERE resource=?', (status, f'cloud:{key}'))
    print(f'Collected: {key} ({status})', flush=True)
    return status == 'ok'


def collect():
    server.NETWORK_ENABLED = False
    client = server.AIHotClient()

    def content():
        for window in ('24h', '7d'):
            payload = client.get('/items', f'items:all:{window}', {'mode': 'all', 'window': window, 'limit': '100'})
            if payload:
                server.upsert_content(payload.get('items') or [])

    def facts():
        payload = client.get('/hot-topics', 'hot-topics')
        if payload:
            server.upsert_facts(payload, client)

    def daily():
        payload = client.get('/dailies/latest', 'daily:latest')
        if payload:
            server.upsert_daily(payload)

    def ph(window):
        server.sync_producthunt((window,))
        server.ensure_producthunt_translations(server.query_producthunt({'range': [window]})['items'])

    def categories():
        try:
            server.sync_producthunt_categories(force=True)
        finally:
            for key, _, _ in server.PRODUCTHUNT_CATEGORIES:
                server.ensure_producthunt_translations(server.query_producthunt({'category': [key]})['items'])

    def hn():
        server.sync_hacker_news()
        for view in [*server.HN_FEEDS, 'shownew']:
            server.ensure_hn_translations(server.query_hacker_news({'view': [view], 'scope': ['all']})['items'])

    attempt('aihot:content', content)
    attempt('aihot:facts', facts)
    attempt('aihot:daily', daily)
    attempt('github', server.sync_github_trending)
    if server.producthunt_token():
        for window in sorted(server.PRODUCTHUNT_RANGES):
            attempt(f'ph:{window}', lambda window=window: ph(window))
    attempt('ph:categories', categories)
    for kind, windows in server.XRANK_RANGES.items():
        for window in sorted(windows):
            attempt(f'x:{kind}:{window}', lambda kind=kind, window=window: server.sync_xrank(kind, window))
    attempt('hn', hn)


def export():
    server.NETWORK_ENABLED = False
    data = {'meta': server.query_meta(), 'facts': server.query_facts(), 'projects': server.query_projects(), 'content': []}
    data['meta'].update(cloud=True, publishedAt=server.utc_now())
    data['meta']['cadenceHours'] = CADENCE
    data['meta']['sync'] = [row for row in data['meta']['sync'] if not row['resource'].startswith('cloud:')]
    data['meta']['autoSync'] = {'enabled': True, 'intervalMinutes': 60}
    # Error messages may contain upstream response bodies. Never publish them.
    data['meta']['sync'] = [{k: row[k] for k in ('resource', 'last_synced_at', 'last_status') if k in row} for row in data['meta']['sync']]
    offset = 0
    while True:
        page = server.query_content({'limit': ['200'], 'offset': [str(offset)]})
        data['content'].extend(page['items'])
        if not page['page']['hasMore']:
            break
        offset += 200
    for key in sorted(server.PRODUCTHUNT_RANGES):
        data[f'launches:{key}'] = server.query_producthunt({'range': [key]})
    for key, _, _ in server.PRODUCTHUNT_CATEGORIES:
        data[f'launches:{key}'] = server.query_producthunt({'category': [key]})
    for kind, ranges in server.XRANK_RANGES.items():
        for key in sorted(ranges):
            data[f'xrank:{kind}:{key}'] = server.query_xrank({'kind': [kind], 'range': [key]})
    for view in [*server.HN_FEEDS, 'shownew']:
        for scope in ('ai', 'all'):
            for sort in ('rank', 'time', 'score', 'comments'):
                data[f'hn:{view}:{scope}:{sort}'] = server.query_hacker_news({'view': [view], 'scope': [scope], 'sort': [sort]})
    seed_path = server.ROOT / 'public_snapshots.json'
    if seed_path.exists():
        seeds = json.loads(seed_path.read_text(encoding='utf-8'))
        for key, snapshot in seeds.items():
            if key in data and not data[key].get('snapshot') and snapshot.get('snapshot'):
                data[key] = {**snapshot, 'fallback': True}
        for key, view in data.items():
            if key.startswith('launches:'):
                for category in view['categories']:
                    category['count'] = len(data[f"launches:{category['key']}"]['items'])
        data['meta']['counts']['productHuntCategories'] = sum(len(data[f'launches:{key}']['items']) for key, _, _ in server.PRODUCTHUNT_CATEGORIES)
    (OUTPUT / 'data').mkdir(parents=True, exist_ok=True)
    (OUTPUT / 'data/site.json').write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    # Copy only the public frontend, never the DB, configuration or credentials.
    for name in ('styles.css', 'cloud-api.js'):
        shutil.copyfile(server.STATIC / name, OUTPUT / name)
    html = (server.STATIC / 'index.html').read_text(encoding='utf-8')
    html = html.replace('href="/styles.css', 'href="./styles.css').replace('src="/app.js', 'src="./app.js')
    for page in ('facts', 'content', 'projects', 'launches', 'xrank', 'hn', 'about'):
        html = html.replace(f'href="/{page}"', f'href="#/{page}"')
    html = html.replace('<script src="./app.js', '<script src="./cloud-api.js"></script>\n  <script src="./app.js')
    html = html.replace('数据每 30 分钟自动同步', '数据由云端定时更新')
    js = (server.STATIC / 'app.js').read_text(encoding='utf-8')
    js = js.replace('location.pathname', "(location.hash.split('?')[0].slice(1) || '/content')")
    js = js.replace('location.search', "(location.hash.includes('?') ? location.hash.slice(location.hash.indexOf('?')) : '')")
    js = js.replace("history.pushState({}, '', `/", "history.pushState({}, '', `#/")
    js = js.replace("history.replaceState({}, '', `/", "history.replaceState({}, '', `#/")
    (OUTPUT / 'app.js').write_text(js, encoding='utf-8')
    # Give changed assets a new URL so browsers cannot reuse an older release.
    for asset in ('app.js', 'cloud-api.js', 'styles.css'):
        digest = hashlib.sha256((OUTPUT / asset).read_bytes()).hexdigest()[:12]
        html = re.sub(r'\./' + re.escape(asset) + r'(?:\?[^"\s]*)?', f'./{asset}?v={digest}', html)
    (OUTPUT / 'index.html').write_text(html, encoding='utf-8')
    (OUTPUT / '.nojekyll').touch()
    print(f'Exported {len(data["content"])} content items to {OUTPUT}', flush=True)


def export_seed():
    """Publish existing public snapshots with their original timestamps."""
    server.NETWORK_ENABLED = False
    snapshots = {f'launches:{key}': server.query_producthunt({'category': [key]}) for key, _, _ in server.PRODUCTHUNT_CATEGORIES}
    snapshots['xrank:tweets:7d'] = server.query_xrank({'kind': ['tweets'], 'range': ['7d']})
    snapshots = {key: value for key, value in snapshots.items() if value.get('snapshot')}
    (server.ROOT / 'public_snapshots.json').write_text(json.dumps(snapshots, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(f'Exported {len(snapshots)} public fallback snapshots')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--collect', action='store_true')
    parser.add_argument('--seed', action='store_true')
    args = parser.parse_args()
    server.init_db()
    if args.seed:
        export_seed()
    if args.collect:
        collect()
    export()
