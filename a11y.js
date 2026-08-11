/* כפתור נגישות צף — לכל כלי האתר (בקשת שלמה).
   הסמל: הסמל הבינלאומי לנגישות (ISA) — לבן על עיגול כחול, כפי שנהוג
   בתקן הישראלי. קובץ אחד עצמאי: מזריק את הכפתור, התפריט וה-CSS שלו,
   ושומר את ההעדפות ב-localStorage כך שהן חלות על כל ביקור ובכל כלי.
   ההחלה דרך מחלקות על <html>; ההגדלה ב-zoom על #root כדי לא לשבור
   מיקום קבוע של הכפתור עצמו. */
(function () {
  "use strict";
  var LS = "kb-a11y";
  var FLAGS = ["font1", "font2", "contrast", "links", "nomotion"];

  function load() {
    try { return JSON.parse(localStorage.getItem(LS) || "{}") || {}; } catch (e) { return {}; }
  }
  function save(p) {
    try { localStorage.setItem(LS, JSON.stringify(p)); } catch (e) { /* מצב פרטי */ }
  }
  function apply(p) {
    var h = document.documentElement;
    FLAGS.forEach(function (f) { h.classList.toggle("a11y-" + f, !!p[f]); });
  }

  var css = [
    /* הגדלת תצוגה — על התוכן, לא על הכפתור הצף */
    "html.a11y-font1 #root, html.a11y-font1 body > .wrap { zoom: 1.12; }",
    "html.a11y-font2 #root, html.a11y-font2 body > .wrap { zoom: 1.25; }",
    /* ניגודיות מוגברת */
    "html.a11y-contrast #root, html.a11y-contrast body > .wrap { filter: contrast(1.25); }",
    /* הדגשת קישורים וכפתורים */
    "html.a11y-links a, html.a11y-links button { text-decoration: underline !important; }",
    /* ביטול אנימציות ומעברים */
    "html.a11y-nomotion *, html.a11y-nomotion *::before, html.a11y-nomotion *::after { transition: none !important; animation: none !important; scroll-behavior: auto !important; }",
    /* הכפתור והתפריט */
    "#kb-a11y-btn { position: fixed; bottom: 18px; inset-inline-start: 14px; z-index: 99999; width: 46px; height: 46px; border-radius: 50%; border: 2px solid #fff; background: #0055aa; box-shadow: 0 2px 10px rgba(0,0,0,.35); cursor: pointer; display: flex; align-items: center; justify-content: center; padding: 0; }",
    "#kb-a11y-btn:hover { background: #0066cc; }",
    "#kb-a11y-btn svg { width: 28px; height: 28px; display: block; }",
    "#kb-a11y-panel { position: fixed; bottom: 72px; inset-inline-start: 14px; z-index: 99999; background: #fff; color: #0f172a; border: 1px solid #cbd5e1; border-radius: 14px; box-shadow: 0 8px 30px rgba(0,0,0,.25); padding: 12px; width: 230px; font-family: inherit; font-size: 14px; direction: rtl; text-align: right; }",
    "#kb-a11y-panel h2 { margin: 0 0 8px; font-size: 15px; font-weight: 800; }",
    "#kb-a11y-panel button.a11y-opt { display: block; width: 100%; text-align: right; margin: 4px 0; padding: 8px 10px; border-radius: 9px; border: 1.5px solid #e2e8f0; background: #f8fafc; color: #0f172a; font-size: 13.5px; font-weight: 700; cursor: pointer; font-family: inherit; }",
    "#kb-a11y-panel button.a11y-opt[aria-pressed='true'] { border-color: #0055aa; background: #e6f0fa; color: #003d7a; }",
    "#kb-a11y-panel a { display: block; margin-top: 8px; font-size: 12.5px; color: #0055aa; font-weight: 700; }",
  ].join("\n");

  var ICON = '<svg viewBox="0 0 26 26" aria-hidden="true"><circle cx="13" cy="4.4" r="2.2" fill="#fff"/><path d="M13 7.2 v6.2 h5.6 M13 10.4 h4.6" stroke="#fff" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/><path d="M10.9 11.2 a5.6 5.6 0 1 0 7.1 7.4 M18.6 13.6 l1.6 5.6 h1.6" stroke="#fff" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>';

  function build() {
    var style = document.createElement("style");
    style.textContent = css;
    document.head.appendChild(style);

    var prefs = load();
    apply(prefs);

    var btn = document.createElement("button");
    btn.id = "kb-a11y-btn";
    btn.setAttribute("aria-label", "תפריט נגישות");
    btn.setAttribute("aria-expanded", "false");
    btn.title = "נגישות";
    btn.innerHTML = ICON;
    document.body.appendChild(btn);

    var panel = null;
    var OPTS = [
      ["font1", "הגדלת טקסט"],
      ["font2", "הגדלת טקסט מוגברת"],
      ["contrast", "ניגודיות מוגברת"],
      ["links", "הדגשת קישורים וכפתורים"],
      ["nomotion", "ביטול אנימציות"],
    ];

    function close() {
      if (panel) { panel.remove(); panel = null; btn.setAttribute("aria-expanded", "false"); }
    }
    function open() {
      panel = document.createElement("div");
      panel.id = "kb-a11y-panel";
      panel.setAttribute("role", "dialog");
      panel.setAttribute("aria-label", "אפשרויות נגישות");
      var h = document.createElement("h2");
      h.textContent = "נגישות";
      panel.appendChild(h);
      // רענון מצב הלחצנים לפי data-opt — כפתור האיפוס אינו אופציה ואסור
      // שייספר כאחת (הבאג הראשון של הווידג'ט: אינדקס מחוץ לרשימה)
      function refresh() {
        panel.querySelectorAll(".a11y-opt[data-opt]").forEach(function (x) {
          x.setAttribute("aria-pressed", prefs[x.getAttribute("data-opt")] ? "true" : "false");
        });
      }
      OPTS.forEach(function (o) {
        var b = document.createElement("button");
        b.className = "a11y-opt";
        b.setAttribute("data-opt", o[0]);
        b.textContent = o[1];
        b.setAttribute("aria-pressed", prefs[o[0]] ? "true" : "false");
        b.onclick = function () {
          prefs[o[0]] = !prefs[o[0]];
          // שתי דרגות ההגדלה סותרות זו את זו
          if (o[0] === "font1" && prefs.font1) prefs.font2 = false;
          if (o[0] === "font2" && prefs.font2) prefs.font1 = false;
          save(prefs); apply(prefs); refresh();
        };
        panel.appendChild(b);
      });
      var reset = document.createElement("button");
      reset.className = "a11y-opt";
      reset.textContent = "↺ איפוס הכול";
      reset.onclick = function () {
        prefs = {}; save(prefs); apply(prefs); refresh();
      };
      panel.appendChild(reset);
      var a = document.createElement("a");
      // ההצהרה יושבת בשורש האתר — הנתיב מחושב לפי מיקום הסקריפט עצמו
      var me = document.querySelector('script[src*="a11y.js"]');
      var base = me ? me.getAttribute("src").replace(/a11y\.js.*$/, "") : "";
      a.href = base + "accessibility.html";
      a.textContent = "הצהרת נגישות ←";
      panel.appendChild(a);
      document.body.appendChild(panel);
      btn.setAttribute("aria-expanded", "true");
    }
    btn.onclick = function () { panel ? close() : open(); };
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") close(); });
    document.addEventListener("click", function (e) {
      if (panel && !panel.contains(e.target) && e.target !== btn && !btn.contains(e.target)) close();
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", build);
  else build();
})();
