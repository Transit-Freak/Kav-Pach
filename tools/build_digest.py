# -*- coding: utf-8 -*-
"""הקו בזמן — קובץ הסיכום להתראות (digest.json).

השינויים המהותיים (בלי לו"ז/תדירות) של 14 הימים האחרונים, עם ערי הקצה
של כל קו — עמוד הסיכום באתר (#digest=עיר@ימים) מסנן ומקבץ ממנו.
רץ יומית ב-workflow של ההתראות, לפני השליחה.
"""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from send_push import SKIP_KINDS, dest_cities  # noqa: E402

OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
OUT = f'{OUTDIR}/digest.json'
DAYS = int(os.environ.get('DAYS', '14'))


def main():
    since = (datetime.date.today() - datetime.timedelta(days=DAYS)).isoformat()
    try:
        cat = {x['rd']: x for x in json.load(open(f'{OUTDIR}/lines.json'))['lines']}
    except Exception:
        cat = {}
    items = []
    for f in os.listdir(f'{OUTDIR}/lines'):
        try:
            d = json.load(open(f'{OUTDIR}/lines/{f}', encoding='utf-8'))
        except Exception:
            continue
        rd = d.get('rd') or f.rsplit('.', 1)[0]
        for v in d.get('versions') or []:
            dd = str(v.get('d', ''))[:10]
            if dd < since or v.get('k') in SKIP_KINDS or v.get('k') in ('baseline', 'snapshot'):
                continue
            dest = d.get('dest') or (cat.get(rd) or {}).get('dest', '')
            items.append({'d': dd, 'rd': rd, 'mk': rd.split('-')[0],
                          'line': d.get('line') or (cat.get(rd) or {}).get('line', ''),
                          'k': v.get('k'), 'ct': dest_cities(dest)})
    items.sort(key=lambda x: x['d'], reverse=True)
    json.dump({'gen': datetime.date.today().isoformat(), 'days': DAYS, 'items': items},
              open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print(f'digest: {len(items)} שינויים מ-{since}')


if __name__ == '__main__':
    main()
