// באנר שיתוף לקו: אוטובוס עם המספר על השלט (1200×630) — לוואטסאפ.
// קלט: JSON של מספרי קווים · פלט: PNG לכל קו בשם line-h<hex>.png
import fs from 'fs';
const [,, numsFile, outDir, chromePath] = process.argv;
const { chromium } = await import(process.env.PW_IMPORT || 'playwright-core');
const nums = JSON.parse(fs.readFileSync(numsFile, 'utf8'));
fs.mkdirSync(outDir, { recursive: true });
const b = await chromium.launch({ executablePath: chromePath, args: ['--no-sandbox'] });
const p = await b.newPage({ viewport: { width: 1200, height: 630 } });
for (const n of nums) {
  const fsz = n.length <= 3 ? 96 : n.length <= 4 ? 78 : 62;
  await p.setContent(`<body style="margin:0"><div dir="rtl" style="width:1200px;height:630px;display:flex;align-items:center;gap:70px;padding:0 90px;box-sizing:border-box;background:linear-gradient(140deg,#2e1065 0%,#6d28d9 100%);font-family:'Segoe UI',Arial,sans-serif;position:relative;overflow:hidden">
    <div style="position:absolute;left:-120px;top:-120px;width:460px;height:460px;border-radius:50%;background:rgba(255,255,255,.07)"></div>
    <div style="flex:1">
      <div style="font-size:110px;font-weight:900;color:#fff;line-height:1">קו ${n}</div>
      <div style="font-size:38px;font-weight:600;color:#ddd6fe;margin-top:18px">ההיסטוריה המלאה — הקו בזמן</div>
      <div style="font-size:24px;color:rgba(255,255,255,.55);margin-top:46px;direction:ltr">transit-freak.github.io/kav-bochan/line-history</div>
    </div>
    <svg width="360" height="430" viewBox="0 0 180 215">
      <rect x="10" y="10" width="160" height="185" rx="26" fill="#f8fafc" stroke="#0f172a" stroke-width="5"/>
      <rect x="24" y="26" width="132" height="44" rx="10" fill="#fbbf24" stroke="#78350f" stroke-width="3"/>
      <text x="90" y="${n.length <= 3 ? 62 : 58}" font-size="${n.length <= 3 ? 38 : n.length <= 4 ? 30 : 24}" font-weight="900" fill="#1c1917" text-anchor="middle" font-family="Arial">${n}</text>
      <rect x="24" y="82" width="132" height="62" rx="10" fill="#1e293b"/>
      <circle cx="42" cy="168" r="9" fill="#fde68a"/>
      <circle cx="138" cy="168" r="9" fill="#fde68a"/>
      <rect x="70" y="158" width="40" height="20" rx="5" fill="#e2e8f0" stroke="#475569" stroke-width="2"/>
      <circle cx="48" cy="205" r="10" fill="#0f172a"/>
      <circle cx="132" cy="205" r="10" fill="#0f172a"/>
    </svg>
  </div></body>`);
  await p.screenshot({ path: `${outDir}/line-h${Buffer.from(n, 'utf8').toString('hex')}.png` });
}
await b.close();
console.log('רונדרו', nums.length, 'באנרים');
