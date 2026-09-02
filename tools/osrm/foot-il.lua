-- פרופיל הליכה לאזורי תעשייה בישראל — הפרופיל הרשמי של OSRM (foot.lua)
-- עם שני שינויים, שניהם בעקבות ממצא שלמה 02.09 (פארק תעסוקה יואב):
--
-- 1. כבישים פנימיים המסומנים access=private. באזורי תעשייה זה הכלל, לא
--    החריג: כביש השירות שמוביל מהשער למפעלים מסומן פרטי, והפרופיל הרשמי
--    מסרב לעבור בו. התוצאה: תחנה 65 מ׳ מהגבול "מרוחקת" 14–18 דק׳ מהמרכז,
--    כי הניתוב מקיף את כל האזור מבחוץ. העובד הולך בכביש הזה כל יום.
--
-- 2. כבישים ראשיים (trunk) והרמפות שלהם (trunk_link, motorway_link). תחנות
--    "צומת" ו"מסעף" יושבות בדיוק שם, והפרופיל הרשמי לא מכיר אותם כדרכי
--    הליכה כלל — אז הוא מצמיד את התחנה לדרך המוכרת הקרובה ומנתב משם, לפעמים
--    קילומטרים (מסעף נחף: 82 מ׳ מהאזור, 11.7 ק״מ "הליכה"). מי שיורד בתחנה כזו
--    הולך בשולי הרמפה אל האזור. כביש מהיר עצמו (motorway) נשאר אסור.
--
-- כל שאר הכללים (גדרות, שערים, מדרגות, מהירות 5 קמ״ש) נשארים של הפרופיל
-- הרשמי. השומר הגאומטרי ב-tools/parks.py נשאר כרשת ביטחון למקרים אחרים,
-- ובדיקת קבע 15 מדווחת כמה פעמים הוא עדיין נדרש.
--
-- שימוש: osrm-extract -p /data/foot-il.lua  (הקובץ הרשמי נשאר ב-/opt)

package.path = '/opt/?.lua;' .. package.path
local base = require('foot')
local base_setup = base.setup

function base.setup()
  local p = base_setup()
  -- 1. כבישים פרטיים מותרים להליכה
  if p.access_tag_blacklist then
    p.access_tag_blacklist['private'] = nil
  end
  -- 2. כבישים ראשיים ורמפות במהירות הליכה רגילה
  local ws = p.default_speed or 5
  if p.speeds and p.speeds.highway then
    p.speeds.highway.trunk         = ws
    p.speeds.highway.trunk_link    = ws
    p.speeds.highway.motorway_link = ws
  end
  return p
end
-- הפרופיל הרשמי מגדיר גם setup גלובלי; מיישרים את שניהם, כדי שהשינוי
-- יחול לא משנה מאיזה מהם osrm-extract קורא.
setup = base.setup

return base
