"""Bounded native combat baselines. Does not instantiate or update an RL model."""
import argparse
import json
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import hornet_core as h

def choose(s,kind,step):
    b=s['hornet'];dx=b['x']-s['x'];dy=b['y']-s['y'];m=h.action_mask(s)
    move=0
    if kind in ('approach','counter') and abs(dx)>1.6:move=2 if dx>0 else 1
    if kind=='retreat':move=1 if dx>0 else 2
    if move and s['terrain_distances'][move-1]<.6:move=0
    nail=1 if kind!='wait' and kind!='retreat' and m[6] and (kind=='stationary' or abs(dx)<3.5 and abs(dy)<3) else 0
    # This is an explicit heuristic probe, never a policy demonstration dataset.
    jump=int(kind=='counter' and m[4] and ('Dash' in b['phase'] or 'Throw' in b['phase']) and abs(dx)<9)
    return [move,jump,nail,0]

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,default=Path('artifacts/hornet-v1'));p.add_argument('--episodes',type=int,default=2);a=p.parse_args()
    a.out.mkdir(parents=True,exist_ok=True);rows=[];phases=set();errors=[]
    try:
        for kind in ('wait','stationary','approach','counter','retreat'):
            for ep in range(a.episodes):
                s=h.reset();start=s['time'];initial=s;steps=0
                file=a.out/f'audit-{kind}-{ep}.jsonl'
                with file.open('w',encoding='utf8') as f:
                    f.write(json.dumps({'initial':s})+'\n')
                    for step in range(3000):
                        action=choose(s,kind,step);mask,pulse=h.buttons(action,s)
                        new=h.request(f'tick {mask} {pulse} 2');h.validate(s,new);steps+=1
                        f.write(json.dumps({'action':action,'state':new})+'\n');s=new
                        phases.update(e['kind'][4:] for e in s['hornet']['events'] if e['kind'].startswith('fsm:'))
                        if step%250==0:print(kind,ep,step,'hp',s['hp'],'boss',s['hornet']['hp'],flush=True)
                        if s['hp']<=0 or h.won(s):break
                b=s['hornet'];row=dict(kind=kind,episode=ep,steps=steps,start_hp=initial['hp'],hp=s['hp'],hurt=b['hurt'],damage=b['damage'],hits=b['hits'],attacks=b['attacks'],seconds=s['time']-start,win=h.won(s),native_death=b['native_death'],bosses_dead=b['bosses_dead'],complete=b['complete'])
                rows.append(row);h.write_json(a.out/'baseline-progress.json',rows);print(row,flush=True)
    except Exception as e:
        errors.append(repr(e));raise
    finally:
        try:h.request('release')
        finally:
            # Full native victory is required before trusting the terminal target.
            passed=not errors and any(r['win'] for r in rows) and any(r['hurt'] for r in rows) and any(r['hits'] for r in rows)
            h.write_json(a.out/'acceptance.json',dict(passed=passed,training=False,model_updates=0,rows=rows,phases=sorted(phases),errors=errors,missing=[] if passed else ['Native complete victory and/or event coverage not yet demonstrated'],scope='Event-counter/physics reconciliation; independent frame annotations remain a separate review'))

if __name__=='__main__':main()
