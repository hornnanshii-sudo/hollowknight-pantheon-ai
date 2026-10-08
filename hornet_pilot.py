"""Explicitly authorized 5k pilot. Does not waive full-training acceptance."""
import json
import os
import random
import traceback
from pathlib import Path
import numpy as np
import torch
from sb3_contrib import RecurrentPPO
import hornet_core as h
from hornet_train import Env, Policy

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'artifacts/hornet-pilot-5k'
TOTAL_LEDGER=ROOT/'artifacts/hornet-v1/ledger.json'
COEFF=dict(hurt=1.0,win=0.,flawless=0.,death=0.,timeout=0.)

class PilotLedger(h.Ledger):
    def __init__(self,path):
        super().__init__(path)
        self.start=self.data['actual']
    def reserve(self,training):
        if training and self.data['actual']-self.start>=5000:raise RuntimeError('Pilot 5000 sample limit')
        super().reserve(training)

def suspected_completion(s):
    b=s.get('hornet',{})
    return (s.get('scene')!='GG_Hornet_1' or not b.get('valid') or b.get('hp',0)<=0 or
            b.get('native_death') or b.get('bosses_dead') or b.get('complete'))

class PilotEnv(Env):
    def step(self,action):
        # Intercept the validated state before it enters PPO's rollout buffer.
        previous=self.s
        obs,reward,term,trunc,info=super().step(action)
        if suspected_completion(self.s):
            h.write_json(self.out/'suspected-completion.json',dict(previous=previous,state=self.s))
            raise RuntimeError('Suspected victory: batch rejected pending terminal audit')
        return obs,reward,term,trunc,info

def save(model,ledger,label):
    folder=OUT/label;folder.mkdir()
    model.save(folder/'model.zip')
    torch.save(dict(torch=torch.get_rng_state(),numpy=np.random.get_state(),python=random.getstate()),folder/'rng.pt')
    h.write_json(folder/'state.json',dict(**ledger.data,reward_version='hornet-pilot-damage1-hurt1-v1'))
    # Only complete generations become visible through the checkpoint pointer.
    h.write_json(OUT/'checkpoint.json',dict(directory=label,actual=ledger.data['actual'],effective=ledger.data['effective']))

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    # Durable one-shot claim; even a crashed pilot cannot silently start a second 5k.
    with (OUT/'run-claim.json').open('x',encoding='utf8') as f:json.dump(dict(pid=os.getpid(),limit=5000),f)
    ledger=PilotLedger(TOTAL_LEDGER);env=None;model=None
    try:
        if ledger.start!=0:raise RuntimeError('Pilot requires the existing Hornet total ledger to be unused')
        phase_names=json.loads((ROOT/'artifacts/hornet-v1/initial-state.json').read_text())['hornet']['phase_names']
        h.write_json(OUT/'manifest.json',dict(training='limited learnability pilot, not accepted full training',reward_version='hornet-pilot-damage1-hurt1-v1',coefficients=COEFF,damage_reward_per_hp=1/9,limit=5000,counts_toward_total=200000,baseline=None,terminal_rewards_enabled=False,full_acceptance_passed=False))
        env=PilotEnv(OUT,phase_names,COEFF,ledger)
        model=RecurrentPPO(Policy,env,n_steps=1000,batch_size=100,n_epochs=4,learning_rate=1e-4,gamma=.9975,gae_lambda=.95,ent_coef=.01,target_kl=.015,device='cpu',seed=42,verbose=1,policy_kwargs=dict(lstm_hidden_size=128,net_arch=dict(pi=[128],vf=[128])))
        save(model,ledger,'checkpoint-0')
        for batch in range(5):
            h.write_json(OUT/'status.json',dict(phase='training',pilot_limit=5000,**ledger.data))
            model.learn(total_timesteps=1000,reset_num_timesteps=False)
            if not all(torch.isfinite(p).all() for p in model.policy.parameters()):raise RuntimeError('Nonfinite model parameters')
            ledger.data['effective']+=1000;h.write_json(ledger.path,ledger.data)
            save(model,ledger,f'checkpoint-{ledger.data["actual"]}')
            metrics={k:float(v) for k,v in model.logger.name_to_value.items() if isinstance(v,(int,float,np.number))}
            with (OUT/'ppo-metrics.jsonl').open('a') as f:f.write(json.dumps(dict(actual=ledger.data['actual'],metrics=metrics))+'\n')
            print('COMPLETED_UPDATE',ledger.data['actual'],flush=True)
        rows=env.rows
        def stats(r):
            return dict(episodes=len(r),mean_damage=float(np.mean([x['damage'] for x in r])) if r else None,mean_hits=float(np.mean([x['hits'] for x in r])) if r else None,mean_hurt=float(np.mean([x['hurt'] for x in r])) if r else None,mean_seconds=float(np.mean([x['seconds'] for x in r])) if r else None)
        h.write_json(OUT/'report.json',dict(**ledger.data,all=stats(rows),early=stats(rows[:len(rows)//2]),late=stats(rows[len(rows)//2:]),limitations='Training-policy episodes only, no held-out evaluation; temporal differences do not establish improvement. Final partial episode excluded.',full_acceptance_passed=False))
        h.write_json(OUT/'status.json',dict(phase='pilot_complete',pilot_limit=5000,**ledger.data))
    except BaseException as e:
        h.write_json(OUT/'status.json',dict(phase='needs_attention',error=repr(e),**ledger.data))
        traceback.print_exc();raise
    finally:
        try:h.request('release')
        except Exception:pass

if __name__=='__main__':main()
