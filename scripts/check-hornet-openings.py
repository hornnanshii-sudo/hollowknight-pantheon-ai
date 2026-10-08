import json
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import hornet_core as h

def main():
    out=Path('artifacts/hornet-v2-course');rows=[]
    try:
        if h.request('state')['scene']=='Menu_Title':h.request('load');time.sleep(4)
        for profile in ('native','near-left','near-right'):
            for trial in range(2):
                s=h.reset(profile);b=s['hornet'];dx=b['x']-s['x']
                ok=s['hp']==9 and s['soul']==0 and b['damage']==b['hurt']==0 and b['max_hp']==900
                if profile!='native':ok=ok and abs(abs(dx)-4.5)<.05 and abs(b['y']-s['y'])<1.5 and bool(s['facing_right'])==(dx>0) and min(s['terrain_distances'][:2])>1
                initial=s
                for _ in range(25):
                    new=h.request('tick 0 0 2');h.validate(s,new);s=new
                rows.append(dict(profile=profile,trial=trial,passed=bool(ok),initial=initial,after=s));h.write_json(out/'opening-acceptance.json',dict(passed=False,results=rows));print(profile,trial,ok,dx,flush=True)
        h.write_json(out/'opening-acceptance.json',dict(passed=all(r['passed'] for r in rows),results=rows))
        if not all(r['passed'] for r in rows):raise RuntimeError('Opening validation failed')
    finally:h.request('release');h.disconnect()

if __name__=='__main__':main()
