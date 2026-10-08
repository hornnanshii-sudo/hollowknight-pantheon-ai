"""Native input probes and paired policy-mode diagnostics; no model updates."""
import json
import sys
from pathlib import Path
import numpy as np
from sb3_contrib import RecurrentPPO
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import hornet_core as h
from hornet_logging import TracePolicy,TelemetryEnv
from hornet_pilot import COEFF

OUT=Path('artifacts/hornet-action-audit-v2')
def main():
    OUT.mkdir(parents=True,exist_ok=True);probes=[]
    try:
        for name,action in [('left',[1,0,0,0]),('right',[2,0,0,0]),('left_jump',[1,1,0,0]),('right_jump',[2,1,0,0]),('left_attack',[1,0,1,0]),('right_attack',[2,0,1,0]),('up_attack',[0,0,2,0]),('down_attack',[0,1,3,0]),('left_dash',[1,0,0,1]),('right_dash',[2,0,0,1])]:
            s=h.reset();initial=s;trace=[]
            for i in range(8):
                a=list(action)
                if i and a[3]:a[3]=0
                if a[2] and not s['can_attack']:a[2]=0
                if a[1] and not h.action_mask(s)[4]:a[1]=0
                mask,pulse=h.buttons(a,s);new=h.request(f'tick {mask} {pulse} 2');h.validate(s,new);trace.append(dict(action=a,command=mask,state=new));s=new
            dx=s['x']-initial['x'];dy=max(x['state']['y'] for x in trace)-initial['y']
            passed=(dx<-.1 if action[0]==1 else dx>.1 if action[0]==2 else True) and (dy>.1 if action[1] else True) and (s['hornet']['attacks']>0 if action[2] else True)
            probes.append(dict(name=name,passed=passed,dx=dx,max_dy=dy,attacks=s['hornet']['attacks'],trace=trace));print(name,passed,dx,dy,flush=True)
            h.write_json(OUT/'input-probes.json',dict(passed=False,results=probes))
        h.write_json(OUT/'input-probes.json',dict(passed=all(r['passed'] for r in probes),results=probes))
        if not all(r['passed'] for r in probes):raise RuntimeError('Input probe failed')
        phases=json.loads(Path('artifacts/hornet-v1/initial-state.json').read_text(encoding='utf8'))['hornet']['phase_names']
        env=TelemetryEnv(OUT,phases,COEFF,h.Ledger(OUT/'ledger.json'),training=False)
        model=RecurrentPPO.load('artifacts/hornet-long-200k/checkpoint-10000-9017/model.zip',device='cpu')
        model.policy.__class__=TracePolicy;env.policy=model.policy
        for deterministic in (True,False):
            env.mode='deterministic' if deterministic else 'stochastic'
            for ep in range(2):
                obs,_=env.reset();hidden=None;starts=np.array([True])
                for _ in range(3001):
                    a,hidden=model.predict(obs,state=hidden,episode_start=starts,deterministic=deterministic)
                    obs,_,term,trunc,info=env.step(a);starts[:]=False
                    if term or trunc:print(env.mode,ep,info['episode_result'],flush=True);break
        env.close();h.write_json(OUT/'status.json',dict(phase='complete',training_steps=0))
    finally:h.request('release');h.disconnect()

if __name__=='__main__':main()
