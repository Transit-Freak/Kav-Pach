-- פרופיל אוטובוס לישראל — הפרופיל הרשמי של OSRM לרכב (car.lua) עם שלושה שינויים:
--
-- 1. נת"צ: כביש המסומן access=no + bus=yes (או psv=yes) סגור לרכב פרטי ופתוח
--    לאוטובוס. בפרופיל הרכב הרשמי OSRM לא ייכנס לשם, והמסלול "יעקוף" את הנת"צ
--    בכביש המקביל. כאן תגי bus/psv נבדקים לפני תגי הרכב הכלליים.
-- 2. highway=busway — דרך ייעודית לאוטובוסים (מטרונית, נתיבי BRT). לא מופיעה
--    בטבלת המהירויות של הרכב כלל, ולכן לא ניתנת לניתוב בלעדיה.
-- 3. הגבלות פנייה: הגבלה עם except=bus/psv לא חלה על אוטובוס.
--
-- מה לא מטופל כאן: oneway:bus=no (נת"צ נגד הכיוון) — דורש טיפול במטפל הכיווניות.
--
-- שימוש: osrm-extract -p /data/bus-il.lua  (הקובץ הרשמי נשאר ב-/opt)

package.path = '/opt/?.lua;' .. package.path
local base = require('car')
local base_setup = base.setup

function base.setup()
  local p = base_setup()
  -- 1. תגי גישה של אוטובוס לפני תגי הרכב
  p.access_tags_hierarchy = Sequence { 'bus', 'psv', 'motorcar', 'motor_vehicle', 'vehicle', 'access' }
  -- 2. דרך אוטובוסים ייעודית
  if p.speeds and p.speeds.highway then
    p.speeds.highway.busway = 40
  end
  -- 3. הגבלות פנייה שחלות על אוטובוס
  p.restrictions = Sequence { 'bus', 'psv', 'motorcar', 'motor_vehicle', 'vehicle' }
  return p
end
setup = base.setup

return base
