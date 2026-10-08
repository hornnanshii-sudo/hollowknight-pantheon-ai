"""Logged opening-course A/B experiment, followed by a fresh selected run."""
import gzip
import hashlib
import json
import msvcrt
import os
import random
import traceback
from pathlib import Path
import numpy as np
import torch
from sb3_contrib import RecurrentPPO
import hornet_core as h
from hornet_logging import TracePolicy,TelemetryEnv
from hornet_long import LongLedger,configure_rollout
from hornet_pilot import COEFF

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'artifacts/hornet-v2-course'

def course_profile(steps,rng):
    fraction=.75 if steps<5000 else .5 if steps<20000 else .25 if steps<40000 else 0
    return rng.choice(('near-left','near-right')) if rng.random()<fraction else 'native'

def summary(rows):
    return dict(episodes=len(rows),mean_damage=float(np.mean([r['damage'] for r in rows])),mean_hurt=float(np.mean([r['hurt'] for r in rows])),mean_hits=float(np.mean([r['hits'] for r in rows])),hit_episodes=sum(r['hits']>0 for r in rows))

def select_course(control,course):
    # Operational screen only, not a significance or generalization claim.
    return course['mean_damage']>control['mean_damage'] and course['mean_hurt']<=control['mean_hurt'] and course['hit_episodes']>=control['hit_episodes']

def paired_eval(model,env,count=3):
    all_rows=[]
    torch_rng=torch.get_rng_state();numpy_rng=np.random.get_state();python_rng=random.getstate()
    try:
        for deterministic in (True,False):
            env.mode='eval-deterministic' if deterministic else 'eval-stochastic'
            torch.manual_seed(2048);np.random.seed(2048)
            for _ in range(count):
                obs,_=env.reset();hidden=None;starts=np.array([True])
                for _ in range(3001):
                    action,hidden=model.predict(obs,state=hidden,episode_start=starts,deterministic=deterministic)
                    obs,_,term,trunc,info=env.step(action);starts[:]=False
                    if term or trunc:
                        all_rows.append(dict(info['episode_result'],mode=env.mode));break
                else:raise RuntimeError('Evaluation exceeded 120s step bound')
                h.write_json(env.out/'eval-progress.json',dict(completed=len(all_rows),total=count*2,results=all_rows))
    finally:
        torch.set_rng_state(torch_rng);np.random.set_state(numpy_rng);random.setstate(python_rng)
        model._last_obs=None
    return all_rows

def run(name,budget,curriculum,ledger):
    out=OUT/name;out.mkdir();base=ledger.data['actual'];rng=random.Random(42)
    phases=json.loads((ROOT/'artifacts/hornet-v1/initial-state.json').read_text(encoding='utf8'))['hornet']['phase_names']
    env=TelemetryEnv(out,phases,COEFF,ledger);ev=TelemetryEnv(out,phases,COEFF,ledger,training=False)
    if curriculum:env.opening=lambda:course_profile(ledger.data['actual']-base,rng)
    model=RecurrentPPO(TracePolicy,env,n_steps=1000,batch_size=100,n_epochs=4,learning_rate=1e-4,gamma=.9975,gae_lambda=.95,ent_coef=.01,target_kl=.015,device='cpu',seed=42,verbose=1,policy_kwargs=dict(lstm_hidden_size=128,net_arch=dict(pi=[128],vf=[128])))
    env.policy=ev.policy=model.policy
    digest=hashlib.sha256(b''.join(v.detach().cpu().numpy().tobytes() for v in model.policy.parameters())).hexdigest()
    model.save(out/'initial-model.zip')
    h.write_json(out/'manifest.json',dict(start_from_zero=True,initial_weight_sha256=digest,initial_optimizer_states=len(model.policy.optimizer.state),start_global_actual=base,budget=budget,curriculum=curriculum,seed=42,reward_version='hornet-pilot-damage1-hurt1-v1',coefficients=COEFF,full_acceptance_passed=False,window_reward_enabled=False,terrain_penalty_enabled=False))
    def save(label):
        folder=out/label;folder.mkdir();model.save(folder/'model.zip')
        torch.save(dict(torch=torch.get_rng_state(),numpy=np.random.get_state(),python=random.getstate(),opening=rng.getstate()),folder/'rng.pt')
        h.write_json(folder/'state.json',dict(global_actual=ledger.data['actual'],model_sampled=ledger.data['actual']-base,model_updated=model.num_timesteps,reward_version='hornet-pilot-damage1-hurt1-v1'))
        h.write_json(out/'checkpoint.json',dict(directory=label,global_actual=ledger.data['actual'],model_sampled=ledger.data['actual']-base))
    save('checkpoint-0')
    try:
        while ledger.data['actual']-base<budget:
            done=ledger.data['actual']-base
            if (OUT/'STOP').exists():raise RuntimeError('User STOP requested')
            next_eval=min(budget,(done//5000+1)*5000);size=min(1000,next_eval-done)
            configure_rollout(model,env,size)
            h.write_json(OUT/'status.json',dict(phase='training',run=name,new_model_steps=done,run_budget=budget,global_actual=ledger.data['actual'],global_limit=200000,next_evaluation=next_eval,pid=os.getpid()))
            model.learn(size,reset_num_timesteps=False)
            if not all(torch.isfinite(v).all() for v in model.policy.parameters()):raise RuntimeError('Nonfinite policy')
            ledger.data['effective']+=size;h.write_json(ledger.path,ledger.data)
            done=ledger.data['actual']-base;save(f'checkpoint-{done}')
            metrics={k:float(v) for k,v in model.logger.name_to_value.items() if isinstance(v,(int,float,np.number))}
            with (out/'ppo-metrics.jsonl').open('a',encoding='utf8') as f:f.write(json.dumps(dict(model_steps=done,global_actual=ledger.data['actual'],metrics=metrics))+'\n')
            print(name,'UPDATED',done,'global',ledger.data['actual'],flush=True)
            if done==next_eval:
                h.write_json(OUT/'status.json',dict(phase='evaluation',run=name,new_model_steps=done,global_actual=ledger.data['actual']))
                rows=paired_eval(model,ev,3 if name.startswith('ab-') else 10)
                h.write_json(out/f'report-{done}.json',dict(results=rows,summary=summary(rows),deterministic=summary([r for r in rows if r['mode']=='eval-deterministic']),stochastic=summary([r for r in rows if r['mode']=='eval-stochastic']),limitations='Game RNG not controlled; small screening sample, not proof of improvement. Evaluation always native opening.'))
        return summary(rows)
    finally:
        env.close();ev.close();h.disconnect()

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    lock=(OUT/'run.lock').open('a+b');lock.write(b'1');lock.flush();lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    ledger=None
    try:
        with (OUT/'claim.json').open('x',encoding='utf8') as f:json.dump(dict(pid=os.getpid()),f)
        old=json.loads((ROOT/'artifacts/hornet-long-200k/status.json').read_text(encoding='utf8'))
        if old['phase']!='stopped':raise RuntimeError('Old training must be stopped')
        if not json.loads((OUT/'opening-acceptance.json').read_text(encoding='utf8'))['passed']:raise RuntimeError('Opening acceptance required')
        if not json.loads((ROOT/'artifacts/hornet-action-audit-v2/input-probes.json').read_text(encoding='utf8'))['passed']:raise RuntimeError('Input acceptance required')
        ledger=LongLedger(ROOT/'artifacts/hornet-v1/ledger.json')
        control=run('ab-native',5000,False,ledger)
        course=run('ab-course',5000,True,ledger)
        chosen=select_course(control,course)
        h.write_json(OUT/'ab-selection.json',dict(control=control,course=course,use_course=chosen,rule='Higher mean damage, no higher hurt, no fewer hit episodes; operational screen only'))
        # Both experiment weights are discarded. Fresh selected model and optimizer.
        result=run('fresh-selected',200000-ledger.data['actual'],chosen,ledger)
        h.write_json(OUT/'status.json',dict(phase='complete_budget',global_actual=ledger.data['actual'],result=result))
    except BaseException as e:
        h.write_json(OUT/'status.json',dict(phase='needs_attention',error=repr(e),global_actual=ledger.data['actual'] if ledger else None));traceback.print_exc();raise
    finally:
        try:h.request('release')
        except Exception:pass
        h.disconnect();lock.close()

if __name__=='__main__':main()
