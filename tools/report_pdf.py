# -*- coding: utf-8 -*-
"""המרת ה-Word של הדו"ח ל-PDF עם תוכן עניינים מלא.

soffice --convert-to לא מעדכן שדות, ולכן תוכן העניינים (שדה TOC של Word)
יצא ריק ב-PDF. כאן LibreOffice נפתח דרך UNO, מעדכן את האינדקסים אחרי
שהעימוד מוכן, ומייצא. אם החיבור נכשל — המרה רגילה, כדי שלא להישאר בלי PDF.

    python3 tools/report_pdf.py parks/report/נגישות-אזורי-תעשייה.docx
"""
import pathlib
import subprocess
import sys
import time

SRC = pathlib.Path(sys.argv[1])
DST = SRC.with_suffix('.pdf')
PORT = '2002'


def plain():
    subprocess.run(['soffice', '--headless', '--norestore', '--convert-to', 'pdf', '--outdir', str(SRC.parent), str(SRC)],
                   check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def via_uno():
    import uno
    from com.sun.star.beans import PropertyValue

    proc = subprocess.Popen(['soffice', '--headless', '--norestore', '--nologo', '--nodefault',
                             f'--accept=socket,host=127.0.0.1,port={PORT};urp;StarOffice.ComponentContext'],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        local = uno.getComponentContext()
        resolver = local.ServiceManager.createInstanceWithContext('com.sun.star.bridge.UnoUrlResolver', local)
        ctx = None
        for _ in range(90):
            try:
                ctx = resolver.resolve(f'uno:socket,host=127.0.0.1,port={PORT};urp;StarOffice.ComponentContext')
                break
            except Exception:
                time.sleep(1)
        if ctx is None:
            raise RuntimeError('אין חיבור UNO')
        desktop = ctx.ServiceManager.createInstanceWithContext('com.sun.star.frame.Desktop', ctx)

        def pv(name, value):
            p = PropertyValue()
            p.Name = name
            p.Value = value
            return p

        doc = desktop.loadComponentFromURL(uno.systemPathToFileUrl(str(SRC.resolve())), '_blank', 0, (pv('Hidden', True),))
        idx = doc.getDocumentIndexes()
        # פעמיים: העדכון הראשון משנה את מספר העמודים של התוכן עצמו
        for _ in range(2):
            doc.refresh()
            for i in range(idx.getCount()):
                idx.getByIndex(i).update()
        print('אינדקסים שעודכנו:', idx.getCount())
        doc.storeToURL(uno.systemPathToFileUrl(str(DST.resolve())), (pv('FilterName', 'writer_pdf_Export'),))
        doc.close(True)
        try:
            desktop.terminate()
        except Exception:
            pass
    finally:
        try:
            proc.wait(timeout=30)
        except Exception:
            proc.kill()


try:
    via_uno()
    if not DST.exists():
        raise RuntimeError('לא נוצר קובץ')
    print('PDF דרך UNO:', DST.name)
except Exception as e:
    print('UNO נכשל:', e, '→ המרה רגילה בלי תוכן עניינים')
    plain()
