"""Public-only daily fact archives. Git branch persistence is driven by Pages workflow."""
import argparse
import json
import re
from contextlib import closing
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

import server


def restore(directory):
    # Validate everything before writing: a corrupt archive must fail the build, not be overwritten.
    records = []
    for path in sorted(Path(directory).glob('????-??-??.json')):
        day = path.stem
        date.fromisoformat(day)
        body = json.loads(path.read_text(encoding='utf-8'))
        if body.get('version') != 1 or body.get('date') != day:
            raise ValueError(f'Invalid archive: {path.name}')
        for record in body['items']:
            item = record['item']
            observed = record['observed_at']
            if not item.get('aihot_story_id') or not item.get('title') or not observed:
                raise ValueError(f'Incomplete archive: {path.name}')
            instant = datetime.fromisoformat(observed.replace('Z', '+00:00'))
            if instant.tzinfo is None or instant.astimezone(timezone(timedelta(hours=8))).date().isoformat() != day:
                raise ValueError(f'Observation date mismatch: {path.name}')
            observed = instant.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')
            allowed = {key: item.get(key) for key in server.FACT_PUBLIC_FIELDS}
            allowed['recovered'] = bool(item.get('recovered'))
            records.append((day, allowed['aihot_story_id'], observed, json.dumps(allowed, ensure_ascii=False)))
    with closing(server.connect()) as conn, conn:
        conn.executemany('''INSERT INTO fact_history VALUES(?,?,?,?)
            ON CONFLICT(archive_date,aihot_story_id) DO UPDATE SET
            observed_at=excluded.observed_at,item_json=excluded.item_json
            WHERE excluded.observed_at > fact_history.observed_at''', records)
    return len(records)


def save(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'archive.json').write_text('{"version":1,"kind":"public-facts-daily"}\n', encoding='utf-8')
    server.recover_fact_history()
    with closing(server.connect()) as conn:
        rows = conn.execute('SELECT * FROM fact_history ORDER BY archive_date,aihot_story_id').fetchall()
    days = {}
    for row in rows:
        day = row['archive_date']
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day):
            raise ValueError('Invalid archive date')
        item = json.loads(row['item_json'])
        public = {key: item.get(key) for key in server.FACT_PUBLIC_FIELDS}
        public['recovered'] = bool(item.get('recovered'))
        days.setdefault(day, []).append({'observed_at': row['observed_at'], 'item': public})
    for day, items in days.items():
        path = directory / f'{day}.json'
        body = json.dumps({'version': 1, 'date': day, 'items': items}, ensure_ascii=False, sort_keys=True, indent=2) + '\n'
        temp = path.with_suffix('.json.tmp')
        temp.write_text(body, encoding='utf-8')
        temp.replace(path)
    return len(rows)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['restore', 'save'])
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    server.init_db()
    print(f'{args.action}: {globals()[args.action](args.directory)} facts')
