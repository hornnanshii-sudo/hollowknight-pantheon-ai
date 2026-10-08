"""User-authorized long continuation of verified damage/hurt learning only.

The 200k ceiling includes the pilot and rejected samples. This does not assert
terminal acceptance or silently enable uncalibrated victory rewards/curricula.
"""
import argparse
import json
import msvcrt
import os
import random
import traceback
from pathlib import Path
import numpy as np
import torch
from sb3_contrib import RecurrentPPO
from sb3_contrib.common.recurrent.buffers import RecurrentRolloutBuffer
import hornet_core as h
from hornet_train import evaluate
from hornet_pilot import PilotEnv, COEFF

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'artifacts/hornet-long-200k'
TOTAL=ROOT/'artifacts/hornet-v1/ledger.json'

class LongLedger(h.Ledger):
    def reserve(self,training):
        d=self.data
        if d['pending'] is not None:raise RuntimeError('Pending action needs reconciliation')
        if training and d['actual']>=h.LIMIT:raise RuntimeError('Cumulative 200000 budget exhausted')
        # No fictitious promotion: all samples remain explicitly damage-learning.
        d['pending']='training' if training else 'evaluation';h.write_json(self.path,d)

def configure_rollout(model,env,size):
    model.n_steps=size;model.batch_size=100 if size%100==0 else size
    model.normalize_advantage=size>1
    shape=(size,model.policy.lstm_actor.num_layers,model.n_envs,model.policy.lstm_actor.hidden_size)
    model.rollout_buffer=RecurrentRolloutBuffer(size,env.observation_space,env.action_space,shape,device=model.device,gamma=model.gamma,gae_lambda=model.gae_lambda,n_envs=model.n_envs)

def checkpoint(model,ledger):
    name=f'checkpoint-{ledger.data["actual"]}-{ledger.data["effective"]}'
    folder=OUT/name;folder.mkdir()
    model.save(folder/'model.zip')
    torch.save(dict(torch=torch.get_rng_state(),numpy=np.random.get_state(),python=random.getstate()),folder/'rng.pt')
    h.write_json(folder/'state.json',dict(**ledger.data,reward_version='hornet-pilot-damage1-hurt1-v1'))
    h.write_json(OUT/'checkpoint.json',dict(directory=name,actual=ledger.data['actual'],effective=ledger.data['effective']))

def summarize(rows):
    return dict(episodes=len(rows),episodes_with_hits=sum(r['hits']>0 for r in rows),mean_damage=float(np.mean([r['damage'] for r in rows])),mean_hits=float(np.mean([r['hits'] for r in rows])),mean_hurt=float(np.mean([r['hurt'] for r in rows])),mean_seconds=float(np.mean([r['seconds'] for r in rows])),terminal_acceptance_passed=False)

def main():
    p=argparse.ArgumentParser();p.add_argument('--resume',action='store_true');args=p.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    lock=(OUT/'run.lock').open('a+b');lock.seek(0);lock.write(b'1');lock.flush();lock.seek(0)
    msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    ledger=None;env=None
    try:
        ledger=LongLedger(TOTAL)
        if args.resume:
            source=OUT/json.loads((OUT/'checkpoint.json').read_text(encoding='utf8'))['directory']
        else:
            if (OUT/'manifest.json').exists() or ledger.data['actual']!=5000:raise RuntimeError('Fresh continuation requires the original 5000-step boundary')
            source=ROOT/'artifacts/hornet-pilot-5k/checkpoint-5000'
        saved=json.loads((source/'state.json').read_text(encoding='utf8'))
        if saved['actual']>ledger.data['actual'] or saved['reward_version']!='hornet-pilot-damage1-hurt1-v1':raise RuntimeError('Checkpoint and ledger/version mismatch')
        ledger.data['effective']=saved['effective'];h.write_json(ledger.path,ledger.data)
        phases=json.loads((ROOT/'artifacts/hornet-v1/initial-state.json').read_text(encoding='utf8'))['hornet']['phase_names']
        env=PilotEnv(OUT,phases,COEFF,ledger);ev=PilotEnv(OUT,phases,COEFF,ledger,training=False)
        model=RecurrentPPO.load(source/'model.zip',env=env,device='cpu')
        rng=torch.load(source/'rng.pt',weights_only=False)
        torch.set_rng_state(rng['torch']);np.random.set_state(rng['numpy']);random.setstate(rng['python'])
        if not args.resume:
            h.write_json(OUT/'manifest.json',dict(authorization='User explicitly requested long training after the pilot',source=str(source),start_actual=5000,start_effective=4017,total_budget=200000,remaining_budget=195000,training_stage='native damage learning; no automatic no-hit curriculum',evaluation_every=5000,evaluation_episodes=20,coefficients=COEFF,reward_version=saved['reward_version'],full_acceptance_passed=False,terminal_rewards_enabled=False,stop_on_suspected_completion=True))
            checkpoint(model,ledger)
        print('RESTORED',source,'actual',ledger.data['actual'],'effective',ledger.data['effective'],'optimizer_states',len(model.policy.optimizer.state),flush=True)
        while ledger.data['actual']<h.LIMIT:
            if (OUT/'STOP').exists():
                h.write_json(OUT/'status.json',dict(phase='stopped',reason='STOP file',**ledger.data));return
            boundary=min(h.LIMIT,(ledger.data['actual']//5000+1)*5000)
            size=min(1000,boundary-ledger.data['actual'])
            configure_rollout(model,env,size)
            h.write_json(OUT/'status.json',dict(phase='training',pid=os.getpid(),budget=h.LIMIT,next_evaluation=boundary,**ledger.data))
            model.learn(size,reset_num_timesteps=False)
            if not all(torch.isfinite(v).all() for v in model.policy.parameters()):raise RuntimeError('Nonfinite parameters')
            ledger.data['effective']+=size;h.write_json(ledger.path,ledger.data);checkpoint(model,ledger)
            metrics={k:float(v) for k,v in model.logger.name_to_value.items() if isinstance(v,(int,float,np.number))}
            with (OUT/'ppo-metrics.jsonl').open('a',encoding='utf8') as f:f.write(json.dumps(dict(actual=ledger.data['actual'],effective=ledger.data['effective'],metrics=metrics))+'\n')
            print('COMPLETED_UPDATE',ledger.data['actual'],'effective',ledger.data['effective'],flush=True)
            if ledger.data['actual']==boundary:
                rows=evaluate(model,ev,20)
                h.write_json(OUT/f'report-{boundary}.json',dict(actual=boundary,results=rows,summary=summarize(rows)))
                model._last_obs=None # Real game reset by evaluation; next rollout resets LSTM via episode_start.
        h.write_json(OUT/'status.json',dict(phase='complete_budget',**ledger.data))
    except BaseException as e:
        h.write_json(OUT/'status.json',dict(phase='needs_attention',error=repr(e),**(ledger.data if ledger else {})))
        traceback.print_exc();raise
    finally:
        try:h.request('release')
        except Exception:pass
        h.disconnect();lock.close()

if __name__=='__main__':main()
