#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""עזר לבדיקת דאטאבוס (probe-databus-bulk.yml): מסכם תשובת siri_ride_stops מה-stdin."""
import json
import sys

d = json.load(sys.stdin)
print(len(d), 'שורות ב-2 דקות של התחלות')
m = [x for x in d if x.get('nearest_siri_vehicle_location_id')]
g = [x for x in d if x.get('gtfs_ride_stop__arrival_time')]
print('עם מיקום קרוב:', len(m), '· עם לו"ז GTFS:', len(g))
x = (g or m or d)[:1]
print(json.dumps(x, ensure_ascii=False, indent=1)[:3500])
