# -*- coding: utf-8 -*-
"""פאנל התקלות של הקו בזמן — כל מחלקות הבעיות שנתגלו, במקום אחד.

דרישת שלמה ("תעשה פאנל שיבדוק את כל התקלות המעצבנות האלו"): סריקה של
כל קובצי הקווים אחר כל מחלקת תקלה שנתפסה אי-פעם, עם מונה ודוגמאות.
רץ בסוף כל סריקה יומית; הפלט: data/qa.json + דף data/qa.html.

המטרה: כשמונה יורד לאפס — המחלקה מטופלת; כשהוא עולה — משהו נשבר.
"""
import datetime
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compact_lines import materialize  # noqa: E402

OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
ARC0, ARC1 = '2022-01-16', '2026-07-24'

CHECKS = {
    'shp_missing': 'שרטוט חסר — הגרסה מוצגת כקו מקורב מקווקו (מושלם אוטומטית מהארכיון)',
    'codes_missing': 'תחנת ➕/➖ בלי מק"ט מקובע (מושלם אוטומטית ככל שהפערים נסגרים)',
    'bare_rem': 'רשומת ➖ שהיא מספר חשוף בלי שם',
    'noop_events': 'אירוע שרצף התחנות שלו זהה לקודם (מועמד לניקוי תנודות)',
    'undated_gaps': 'שינוי בין גרסאות בלי תאריך מדויק (בתור למנועי התיארוך)',
    'empty_geo': 'אירוע מסלול בלי תחנות ובלי שרטוט',
    'dup_versions': 'שתי גרסאות באותו קו, תאריך וסוג',
    'thinned_shp': 'שרטוט קצר חשוד ביחס למספר התחנות (ייתכן דילול ישן)',
    'noop_redraw': 'אירוע "תיקון שרטוט" שהשרטוט בו זהה לגרסה הקודמת (מועמד לניקוי)',
}


def run():
    out = {k: {'label': v, 'count': 0, 'sample': []} for k, v in CHECKS.items()}

    def hit(check, desc):
        c = out[check]
        c['count'] += 1
        if len(c['sample']) < 5:
            c['sample'].append(desc)

    for p in sorted(glob.glob(f'{OUTDIR}/lines/*.json')):
        lf = materialize(json.load(open(p, encoding='utf-8')))
        rd = lf.get('rd') or p.rsplit('/', 1)[-1]
        vs = sorted(lf.get('versions') or [], key=lambda v: v['d'])
        seen_dk = set()
        prev_codes = None
        prev_shp = None
        for v in vs:
            d, k = v.get('d', ''), v.get('k', '')
            stops = v.get('stops') or []
            codes = [str(s[0]) for s in stops] if stops else None
            if stops and not v.get('shp') and ARC0 <= d <= ARC1:
                hit('shp_missing', f'{rd} · {d}')
            if (v.get('add') or v.get('rem')):
                ac, rc = v.get('ac') or [], v.get('rc') or []
                miss = (len(v.get('add') or []) - sum(1 for c in ac if c is not None)) + \
                       (len(v.get('rem') or []) - sum(1 for c in rc if c is not None))
                if miss > 0:
                    hit('codes_missing', f'{rd} · {d} ({miss})')
                for n in v.get('rem') or []:
                    if str(n).isdigit():
                        hit('bare_rem', f'{rd} · {d} · {n}')
                        break
                if codes is not None and prev_codes is not None and codes == prev_codes:
                    hit('noop_events', f'{rd} · {d} · {k}')
            elif codes is not None and prev_codes is not None and codes != prev_codes \
                    and k not in ('new', 'baseline', 'snapshot', 'times', 'removed'):
                hit('undated_gaps', f'{rd} · {d}')
            if k in ('route', 'redraw', 'extend', 'shorten', 'terminal', 'stops',
                     'stops-add', 'stops-del') and not stops and not v.get('shp'):
                hit('empty_geo', f'{rd} · {d} · {k}')
            if (d, k) in seen_dk:
                hit('dup_versions', f'{rd} · {d} · {k}')
            seen_dk.add((d, k))
            if stops and v.get('shp') and len(stops) >= 8 and len(v['shp']) < len(stops) * 6:
                hit('thinned_shp', f'{rd} · {d}')
            # "תיקון שרטוט" בלי שינוי בשרטוט — נתגלה בקו 26 שדרות: אירוע
            # שמציג מפה ריקה מהדגשות כי אין באמת מה להדגיש
            if k == 'redraw' and v.get('shp') and prev_shp and v['shp'] == prev_shp:
                hit('noop_redraw', f'{rd} · {d}')
            if v.get('shp'):
                prev_shp = v['shp']
            if codes is not None:
                prev_codes = codes
    return out


def main():
    res = run()
    # ממצאי הצייד (סיור הדפדפן היומי באתר החי) — שורות נוספות בפאנל
    try:
        hunt = json.load(open(f'{OUTDIR}/ui-hunt.json', encoding='utf-8'))
        lbl = {'page_load': 'עמוד קו שלא נטען (סיור חי)',
               'js_error': 'שגיאת קוד בדפדפן (סיור חי)',
               'empty_map': 'מפה שלא מציירת כלום (סיור חי)',
               'no_code': 'רשומת ➕/➖ בלי מק"ט בתצוגה (סיור חי)',
               'compare_broken': '"השווה" לא נפתח (סיור חי)',
               'js_error_compare': 'שגיאת קוד בהשוואה (סיור חי)',
               'crash': 'קריסת עמוד בסיור החי'}
        agg = {}
        for i in hunt.get('issues') or []:
            k = 'hunt_' + i.get('type', 'x')
            e = agg.setdefault(k, {'label': lbl.get(i.get('type'), i.get('type')), 'count': 0, 'sample': []})
            e['count'] += 1
            if len(e['sample']) < 5:
                e['sample'].append(f"{i.get('rd')} · {i.get('detail', '')[:60]}")
        for k in lbl:
            res.setdefault('hunt_' + k, {'label': lbl[k] + f" — מדגם {hunt.get('checked', 0)} עמודים",
                                          'count': 0, 'sample': []})
        res.update({k: v for k, v in agg.items()})
    except Exception:
        pass
    gen = datetime.datetime.now().strftime('%d.%m.%Y %H:%M')
    json.dump({'generated': gen, 'checks': res},
              open(f'{OUTDIR}/qa.json', 'w', encoding='utf-8'), ensure_ascii=False)
    rows = ''
    for cid, c in res.items():
        ok = c['count'] == 0
        color = '#16a34a' if ok else '#d97706'
        samp = ' · '.join(c['sample'])
        rows += f'''<div style="display:flex;gap:14px;align-items:baseline;padding:12px 16px;border-bottom:1px solid #eef2fb">
<div style="min-width:76px;font-size:26px;font-weight:900;color:{color};font-variant-numeric:tabular-nums;text-align:center">{c['count']:,}</div>
<div><div style="font-weight:700;color:#1e2440">{c['label']}</div>
<div style="font-size:12.5px;color:#5a6280;direction:ltr;text-align:right">{samp}</div></div></div>'''
    html = f'''<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>פאנל התקלות — הקו בזמן</title></head>
<body style="margin:0;font-family:system-ui,sans-serif;background:#f6f7fb;color:#1e2440">
<div style="max-width:860px;margin:0 auto;padding:22px 14px">
<h1 style="font-size:24px;margin:0 0 4px">🔍 פאנל התקלות — הקו בזמן</h1>
<div style="color:#5a6280;font-size:14px;margin-bottom:16px">כל מחלקות התקלות שנתגלו, נבדקות מחדש בכל סריקה יומית · עדכון: {gen} · אפס = המחלקה נקייה</div>
<div style="background:#fff;border:1px solid #c7d2f0;border-radius:14px;overflow:hidden">{rows}</div>
<div style="color:#5a6280;font-size:13px;margin-top:12px">המונים של "שרטוט חסר" ו"מק"ט חסר" יורדים אוטומטית ככל שמנועי ההשלמה מהארכיון מתקדמים.</div>
</div></body></html>'''
    open(f'{OUTDIR}/qa.html', 'w', encoding='utf-8').write(html)
    print('פאנל התקלות:', ' · '.join(f"{k}:{v['count']}" for k, v in res.items()))


if __name__ == '__main__':
    main()
