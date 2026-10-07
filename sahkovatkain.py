#!/usr/bin/env python3
import json, urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

SOURCE="https://raw.githubusercontent.com/vividfog/nordpool-predict-fi/main/deploy/prediction.json"
TZ=ZoneInfo("Europe/Helsinki")
HOURS=8
DAYS=5

def transfer(dt):
    winter=dt.month in (11,12,1,2,3)
    return 3.20 if winter and dt.weekday()!=6 and 7<=dt.hour<22 else 1.90

req=urllib.request.Request(SOURCE,headers={"User-Agent":"sahkovatkain/0.1"})
with urllib.request.urlopen(req,timeout=30) as r:
    data=json.load(r)

now=datetime.now(TZ)
rows=[]
for n in range(DAYS):
    day=now.date()+timedelta(days=n)
    p=[]
    for ts,price in data:
        dt=datetime.fromtimestamp(ts/1000,TZ)
        if dt.date()==day:
            p.append(float(price)+transfer(dt))
    p.sort()
    if len(p)>=HOURS:
        rows.append(f"{day:%Y%m%d},{sum(p[:HOURS])/HOURS:.2f}")

Path("deploy").mkdir(exist_ok=True)
out="# sahkovatkain v0.1\n# updated="+now.isoformat(timespec="seconds")+"\n"+"\n".join(rows)+"\n"
Path("deploy/sahkovatkain.txt").write_text(out,encoding="utf-8")
print(out)
