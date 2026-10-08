"""Gated Recurrent PPO. No automatic bypass of calibration or acceptance."""
import argparse
import hashlib
import json
from pathlib import Path
import gymnasium as gym
import numpy as np
import torch
from sb3_contrib import RecurrentPPO
from sb3_contrib.common.recurrent.policies import RecurrentActorCriticPolicy
import hornet_core as h

class Policy(RecurrentActorCriticPolicy):
    def set_mask(self,obs):
        self.mask=obs[:,-sum(h.HEADS):]>.5
        # PPO recurrent padding is excluded from the loss, but must have finite logits.
        for i in (0,3,5,9):self.mask[:,i]=True
    def forward(self,obs,*a,**kw):self.set_mask(obs);return super().forward(obs,*a,**kw)
    def get_distribution(self,obs,*a,**kw):self.set_mask(obs);return super().get_distribution(obs,*a,**kw)
    def evaluate_actions(self,obs,*a,**kw):self.set_mask(obs);return super().evaluate_actions(obs,*a,**kw)
    def _get_action_dist_from_latent(self,latent_pi):
        return self.action_dist.proba_distribution(self.action_net(latent_pi).masked_fill(~self.mask,-1e9))

class Env(gym.Env):
    def __init__(self,out,phases,coeff,ledger,training=True,cap=9):
        self.out=Path(out);self.phases=phases;self.coeff=coeff;self.ledger=ledger;self.training=training;self.cap=cap
        self.action_space=gym.spaces.MultiDiscrete(h.HEADS)
        # 11 scalar, 9 flags, 9 buttons, 11 rays, 8 ray-valid, hazards, FSM + masks.
        size=48+8*h.HAZARDS+len(phases)+1+sum(h.HEADS)
        self.observation_space=gym.spaces.Box(-5,5,(size,),dtype=np.float32)
        self.rows=[]
    def reset(self,seed=None,options=None):
        super().reset(seed=seed);self.s=h.reset(getattr(self,'reset_profile','native'));self.start=self.s['time'];self.parts={};self.steps=0;self.first_hit=None
        return h.observation(self.s,self.phases,0,self.cap),{}
    def step(self,action):
        mask,pulse=h.buttons(action,self.s)
        self.last_command=dict(mask=mask,pulse=pulse,ticks=2)
        self.ledger.reserve(self.training)
        new=h.request(f'tick {mask} {pulse} 2')
        self.last_raw=new
        # Executed samples count even when validation subsequently rejects this batch.
        self.ledger.settle();h.validate(self.s,new)
        self.steps+=1;elapsed=new['time']-self.start
        terminal=h.won(new) or new['hp']<=0 or (self.training and new['hornet']['hurt']>=self.cap)
        timeout=elapsed>=120
        parts=h.reward(self.s,new,self.coeff,terminal or timeout,timeout)
        for k,v in parts.items():self.parts[k]=self.parts.get(k,0)+v
        if self.first_hit is None and new['hornet']['hits']:self.first_hit=elapsed
        self.s=new;info={}
        if terminal or timeout:
            b=new['hornet'];row=dict(win=h.won(new),flawless=h.won(new) and b['hurt']==0,hp=new['hp'],hurt=b['hurt'],damage=b['damage'],hits=b['hits'],attacks=b['attacks'],seconds=elapsed,first_hit=self.first_hit,reward_parts=self.parts,cap=self.cap,steps=self.steps)
            self.rows.append(row);info['episode_result']=row
            with (self.out/('episodes.jsonl' if self.training else 'evaluation.jsonl')).open('a',encoding='utf8') as f:f.write(json.dumps(row)+'\n')
        if self.steps%100==0:h.write_json(self.out/'status.json',dict(phase='training' if self.training else 'evaluation',**self.ledger.data,episode_steps=self.steps))
        return h.observation(new,self.phases,elapsed,self.cap),sum(parts.values()),bool(terminal),bool(timeout and not terminal),info
    def close(self):h.request('release')

def evaluate(model,env,n=20):
    rows=[]
    for i in range(n):
        obs,_=env.reset();hidden=None;starts=np.array([True])
        for _ in range(3001):
            action,hidden=model.predict(obs,state=hidden,episode_start=starts,deterministic=True)
            obs,_,term,trunc,info=env.step(action);starts[:]=False
            if term or trunc:rows.append(info['episode_result']);break
        else:raise RuntimeError('Evaluation step cap violated')
        h.write_json(env.out/'eval-progress.json',dict(completed=len(rows),total=n,results=rows))
    return rows

def gate(stage,rows):
    if len(rows)!=20:return False
    if stage==0:return sum(r['hits']>0 for r in rows)>=16
    wins=[r for r in rows if r['win']]
    return len(wins)>=16 and np.mean([r['hurt'] for r in wins])<=2

def preflight(out):
    """Report missing evidence without constructing a model or taking game control."""
    evidence={};reasons=[]
    for name in ('acceptance','calibration','initial-state'):
        path=out/(name+'.json')
        try:evidence[name]=json.loads(path.read_text(encoding='utf8'))
        except (OSError,ValueError) as e:reasons.append(f'{name}: {type(e).__name__}')
    a=evidence.get('acceptance',{});c=evidence.get('calibration',{})
    if not a.get('passed'):reasons.append('Native event acceptance has not passed')
    if not a.get('independent_event_review_passed'):reasons.append('Independent event review has not passed')
    if not c.get('passed'):reasons.append('Reward calibration has not passed')
    if reasons:
        h.write_json(out/'startup-check.json',dict(passed=False,reasons=reasons,model_created=False))
        raise RuntimeError('; '.join(reasons))
    h.write_json(out/'startup-check.json',dict(passed=True))
    return evidence

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,default=Path('artifacts/hornet-v1'));a=p.parse_args();out=a.run
    evidence=preflight(out);calibration=evidence['calibration']
    phases=evidence['initial-state']['hornet']['phase_names']
    coeff=calibration['coefficients'];ledger=h.Ledger(out/'ledger.json')
    if ledger.data['actual'] or (out/'checkpoint.zip').exists():raise RuntimeError('Fresh-run entry refuses to overwrite/resume an existing run')
    env=Env(out,phases,coeff,ledger);ev=Env(out,phases,coeff,ledger,False)
    model=RecurrentPPO(Policy,env,n_steps=1000,batch_size=100,n_epochs=4,learning_rate=1e-4,gamma=.9975,gae_lambda=.95,ent_coef=.01,target_kl=.015,device='cpu',seed=42,policy_kwargs=dict(lstm_hidden_size=128,net_arch=dict(pi=[128],vf=[128])))
    h.write_json(out/'manifest.json',dict(schema=h.SCHEMA,phases=phases,coefficients=coeff,training_budget=h.LIMIT,stage_limits=h.STAGE_LIMITS,control_seconds=.04,rollout=1000))
    try:
        baseline=evaluate(model,ev);h.write_json(out/'untrained-evaluation.json',baseline)
        streak=0
        for stage,budget in enumerate(h.STAGE_LIMITS):
            ledger.data['stage']=stage;streak=0
            while ledger.data['stage_actual'][stage]<budget:
                # Fixed 1k chunks divide every authorized checkpoint and phase budget.
                model.learn(total_timesteps=1000,reset_num_timesteps=False)
                ledger.data['effective']+=1000;h.write_json(ledger.path,ledger.data)
                model.save(out/'checkpoint.zip')
                h.write_json(out/'checkpoint-state.json',ledger.data)
                if ledger.data['stage_actual'][stage]%5000:continue
                rows=evaluate(model,ev);h.write_json(out/f'report-{ledger.data["actual"]}.json',dict(stage=stage,results=rows,passed=gate(stage,rows)))
                # VecEnv may hold an observation from before evaluation reset the real game.
                model._last_obs=None
                if stage==0:
                    improved=np.mean([r['damage'] for r in rows])>np.mean([r['damage'] for r in baseline]) and sum(r['hits']>0 for r in rows)>sum(r['hits']>0 for r in baseline)
                    if ledger.data['stage_actual'][0]==5000 and not improved:raise RuntimeError('5k learnability check failed; further training prohibited')
                    passed=gate(stage,rows) and improved
                elif stage==1:passed=gate(stage,rows)
                else:
                    # A separate two-checkpoint transition to first-hit termination.
                    passed=sum(r['flawless'] for r in rows)>=10
                    if env.cap==2:
                        streak=streak+1 if passed else 0
                        if streak>=2:env.cap=1;streak=0
                        continue
                    if sum(r['flawless'] for r in rows)>=18:
                        final=evaluate(model,ev,100)
                        passed_final=sum(r['flawless'] for r in final)>=90
                        h.write_json(out/'final-confirmation.json',dict(results=final,passed=passed_final))
                        h.write_json(out/'status.json',dict(phase='complete' if passed_final else 'confirmation_failed',**ledger.data))
                        return
                streak=streak+1 if passed else 0
                if stage<2 and streak>=2:
                    if stage==1:env.cap=2
                    break
            else:raise RuntimeError('Stage budget exhausted without mastery; no automatic promotion')
    except Exception as e:
        h.write_json(out/'status.json',dict(phase='needs_attention',error=repr(e),**ledger.data));raise
    finally:env.close()

if __name__=='__main__':main()
