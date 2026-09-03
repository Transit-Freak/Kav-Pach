#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""עמוד נחיתה לדו"ח (בקשת שלמה 03.09: קישור במקום קובץ לחילוץ).

כותב parks/report/index.html עם חותמת הבנייה, מספר העמודים וקישורים
לקובצי PDF ו-Word בשמות לועזיים קבועים (report.pdf, report.docx), שמועתקים
כאן מהקבצים בשם העברי. רץ בסוף כל בנייה של הדו"ח.
"""
import json
import os
import shutil

D = 'parks/report'
SRC = 'נגישות-אזורי-תעשייה'
data = json.load(open(f'{D}/data.json', encoding='utf-8')) if os.path.exists(f'{D}/data.json') else {}
gen = data.get('generated', '')
n = (data.get('national') or {}).get('n', '')
pages = ''
try:
    import fitz  # PyMuPDF
    pages = fitz.open(f'{D}/{SRC}.pdf').page_count
except Exception:
    try:
        pages = len([f for f in os.listdir(f'{D}/preview') if f.endswith('.png')])
    except Exception:
        pages = ''
for ext in ('pdf', 'docx'):
    if os.path.exists(f'{D}/{SRC}.{ext}'):
        shutil.copyfile(f'{D}/{SRC}.{ext}', f'{D}/report.{ext}')
# הגרסה הערוכה של איריס (03.09): קובץ שמסודר ידנית ומתפרסם כאן בקישור קבוע,
# לצד הדו"ח האוטומטי. מוצג רק כשהקובץ קיים; הבנייה האוטומטית אינה נוגעת בו.
iris = os.path.exists(f'{D}/report-iris.docx')
iris_html = ('<h2 style="font-size:18px;margin:30px 0 4px">הגרסה הערוכה (איריס דור-און)</h2>'
             '<p class="m">הדו"ח האוטומטי עם ההקדמה, העריכה והתוספות של איריס. Word, A4 לאורך.</p>'
             '<a class="b w" href="report-iris.docx">📝 הגרסה הערוכה — Word</a>'
             + ('<a class="b" href="report-iris.pdf">📄 הגרסה הערוכה — PDF</a>' if os.path.exists(f'{D}/report-iris.pdf') else '')) if iris else ''
html = f'''<!DOCTYPE html>
<html lang="he" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow"><meta name="color-scheme" content="light only"><title>נגישות אזורי תעשייה — הדו"ח</title>
<style>html,body{{background:#fff}} body{{font-family:Assistant,Heebo,Arial,sans-serif;max-width:640px;margin:40px auto;padding:0 18px;color:#0f172a;line-height:1.6}}
h1{{font-size:24px;margin:0 0 6px}} .m{{color:#475569;margin:0 0 22px}} a.b{{display:block;padding:14px 18px;margin:10px 0;border-radius:12px;background:#312e81;color:#fff;text-decoration:none;font-weight:700;font-size:18px}}
a.b.w{{background:#0d6bb4}} .s{{font-size:13px;color:#64748b;margin-top:26px}}</style></head><body>
<h1>נגישות אזורי תעשייה — הדו"ח</h1>
<p class="m">נבנה {gen} (שעון ישראל) · {n} אזורים · {pages} עמודים · Word, A4 לאורך</p>
<a class="b" href="report.pdf">📄 פתיחה כ-PDF</a>
<a class="b w" href="report.docx">📝 הורדה כ-Word</a>
{iris_html}
<p class="s">הכתובת קבועה: כל בנייה חדשה מחליפה את הקבצים כאן. הקובץ בשם העברי נשמר גם הוא בתיקייה זו. חזרה ל<a href="../">אתר</a>.</p>
</body></html>'''
open(f'{D}/index.html', 'w', encoding='utf-8').write(html)
print(f'עמוד הדו"ח: {gen} · {pages} עמודים · report.pdf / report.docx')
