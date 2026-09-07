"""Collect on a scheduled runner and export a static Pages site.

Without --collect this command never requests source APIs or translations.
"""
import argparse
import json
import shutil
from pathlib import Path

import server

OUTPUT = server.ROOT / 'dist'


def collect():
    # Keep collection out of HTTP/page reads. The workflow serializes runs.
    print('Starting source refresh', flush=True)
    result = server.sync_all()
    print(json.dumps({'ok': result['ok'], 'durationMs': result.get('durationMs')}), flush=True)
    for kind, ranges in server.XRANK_RANGES.items():
        for range_key in sorted(ranges):
            if range_key == server.XRANK_DEFAULTS[kind]:
                continue
            try:
                server.sync_xrank(kind, range_key)
            except Exception:
                print(f'Keeping previous snapshot: {kind}/{range_key}', flush=True)
    # Translation is performed only in the collector, with existing cache reuse.
    for range_key in sorted(server.PRODUCTHUNT_RANGES):
        server.ensure_producthunt_translations(server.query_producthunt({'range': [range_key]})['items'])
    for key, _, _ in server.PRODUCTHUNT_CATEGORIES:
        server.ensure_producthunt_translations(server.query_producthunt({'category': [key]})['items'])
    for view in [*server.HN_FEEDS, 'shownew']:
        server.ensure_hn_translations(server.query_hacker_news({'view': [view], 'scope': ['all']})['items'])


def export():
    server.NETWORK_ENABLED = False
    data = {'meta': server.query_meta(), 'facts': server.query_facts(), 'projects': server.query_projects(), 'content': []}
    data['meta'].update(cloud=True, publishedAt=server.utc_now())
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
    (OUTPUT / 'index.html').write_text(html, encoding='utf-8')
    js = (server.STATIC / 'app.js').read_text(encoding='utf-8')
    js = js.replace('location.pathname', "(location.hash.split('?')[0].slice(1) || '/facts')")
    js = js.replace('location.search', "(location.hash.includes('?') ? location.hash.slice(location.hash.indexOf('?')) : '')")
    js = js.replace("history.pushState({}, '', `/", "history.pushState({}, '', `#/")
    js = js.replace("history.replaceState({}, '', `/", "history.replaceState({}, '', `#/")
    (OUTPUT / 'app.js').write_text(js, encoding='utf-8')
    (OUTPUT / '.nojekyll').touch()
    print(f'Exported {len(data["content"])} content items to {OUTPUT}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--collect', action='store_true')
    args = parser.parse_args()
    server.init_db()
    if args.collect:
        collect()
    export()
