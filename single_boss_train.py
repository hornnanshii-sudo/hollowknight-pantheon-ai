"""Train all curriculum tasks using one masked policy and real game inputs."""
import argparse,json,time
from pathlib import Path
import numpy as np
import torch as th
from stable_baselines3 import PPO
from stable_baselines3.common.monitor import Monitor
from defense_v3_train import DefenseEnv, Progress, CONFIG
from defense_v3_core import Reward
from single_boss_core import ACTIONS,OBS_SIZE,FRAME_SIZE,SCHEMA,TASKS,allowed,CurriculumFeatures,CurriculumPolicy
from dodge_reward import outside_view
from train import ROOT,ensure_game

class SingleBossEnv(DefenseEnv):
    def __init__(self,task='defense',training=False):
        self.task=task;self.active_task=task;self.training=training
        super().__init__(120)
        import gymnasium as gym
        self.action_space=gym.spaces.Discrete(len(ACTIONS))
        self.observation_space=gym.spaces.Box(-np.inf,np.inf,(OBS_SIZE,),np.float32)
    def observe(self,s,dt=0,reset=False):
        if reset:self.features=CurriculumFeatures()
        f=self.features.frame(s,120-(s['time']-self.started),120,self.last_action,dt,self.active_task,self.loss)
        self.history=[f.copy() for _ in range(4)] if reset else (self.history+[f])[-4:]
        return np.concatenate(self.history)
    def reset(self,seed=None,options=None):
        # Parent establishes legitimate full-health, zero-soul defense entry.
        self.active_task='defense';self.bridge.request('mode dodge')
        super().reset(seed=seed,options=options)
        self.active_task=self.task
        if self.training and self.task!='defense' and self.np_random.random()<.2:
            self.active_task=TASKS[int(self.np_random.integers(0,TASKS.index(self.task)))]
        if self.active_task!='defense':self.bridge.request('mode combat')
        if self.active_task=='heal':
            self.state=self.bridge.request('training resources 6 99')
        self.start_hp=self.state['hp'];self.loss=0
        self.hits_start=self.state['effective_hits'];self.damage_start=self.state['damage_dealt']
        self.focus_attempts=0;self.unsafe_focus=0;self.heals=0
        self.dive_attempts=0;self.dive_effective=0;self.pending_focus=None;self.pending_dive=None
        self.skill_rewards=0.;self.previous_mask=0
        return self.observe(self.state,reset=True),{}
    def step(self,action):
        action=int(action)
        if not allowed(self.active_task)[action]:raise RuntimeError('Masked action escaped policy')
        mask,pulse=ACTIONS[action];old=self.state;before=time.monotonic()
        s=self.bridge.request(f'tick {mask} {pulse}');latency=time.monotonic()-before
        if s['scene']!='GG_Gruz_Mother':raise RuntimeError('Wrong boss arena')
        ticks=s['physics_ticks']-old['physics_ticks'];dt=s['time']-old['time']
        if not s['sync_paused'] or ticks!=4 or not 0<dt<.16:raise RuntimeError(f'Invalid sync tick {ticks}/{dt}')
        if self.active_task=='defense' and s['damage_dealt']!=self.damage_start:raise RuntimeError('Offense in defense task')
        self.steps+=1;self.dt_sum+=dt;self.dt_min=min(self.dt_min,dt);self.dt_max=max(self.dt_max,dt)
        hurt=max(0,old['hp']-s['hp']);healed=max(0,s['hp']-old['hp']);self.loss+=hurt;self.heals+=healed
        elapsed=s['time']-self.started;outside=outside_view(s);dead=s['hp']<=0
        won=bool(s['won'])
        success=(elapsed>=120 and not dead and not outside) if self.active_task=='defense' else won and not dead and not outside
        term=bool(dead or outside or won or elapsed>=120);trunc=bool(not term and time.monotonic()-self.wall_start>=600)
        reward=self.reward.score(old,s,min(dt,max(0,120-(old['time']-self.started))),hurt,mask)
        reward+=self.reward.terminal(success,s['hp'],self.loss,term)
        damage=max(0,s['damage_dealt']-old['damage_dealt'])
        self.reward.breakdown['boss_damage']=.02*damage if self.active_task!='defense' else 0.
        if mask&256 and not self.previous_mask&256:
            self.focus_attempts+=1;self.pending_focus=s['time']+1.5
        if hurt and self.pending_focus is not None:
            self.unsafe_focus+=1;self.pending_focus=None
        if healed or (self.pending_focus is not None and s['time']>self.pending_focus):self.pending_focus=None
        if not old['spellQuake'] and s['spellQuake']:
            self.dive_attempts+=1;self.pending_dive=[s['time']+1.,False,False]
        if self.pending_dive:
            self.pending_dive[1]|=bool(damage);self.pending_dive[2]|=bool(hurt)
            if s['time']>=self.pending_dive[0] or term:
                if self.pending_dive[1] and not self.pending_dive[2]:self.dive_effective+=1
                self.pending_dive=None
        # Reward successful healing only once per restored mask, with a cap.
        # Large hurt costs prevent heal/hurt cycles becoming profitable.
        skill=min(.2*healed,max(0,2-self.skill_rewards));self.skill_rewards+=skill
        self.reward.breakdown['healing']=skill
        reward+=self.reward.breakdown['boss_damage']+skill
        for key,val in self.reward.breakdown.items():self.reward_totals[key]=self.reward_totals.get(key,0)+val
        self.previous_mask=mask;self.last_action=action;self.state=s
        info=dict(is_success=success,task=self.active_task,target_seconds=120,fight_seconds=min(elapsed,120),
                  start_hp=self.start_hp,hp=s['hp'],hp_lost=self.loss,
                  effective_hits=s['effective_hits']-self.hits_start,damage_dealt=s['damage_dealt']-self.damage_start,
                  out_of_view=outside,watchdog_timeout=trunc,estimated_avoidances=self.reward.avoidances,
                  flawless_success=bool(success and self.loss==0),first_hurt_seconds=self.reward.first_hurt if self.reward.first_hurt is not None else min(elapsed,120),
                  risky_dash_hurts=self.reward.dash_hurts,near_fraction=self.reward.near_fraction,far_seconds=self.reward.far_seconds,
                  reward_parts=self.reward_totals.copy(),dt_mean=self.dt_sum/self.steps,dt_min=self.dt_min,dt_max=self.dt_max,
                  request_seconds=latency,initial_offset=self.offset,healing_completed=self.heals,
                  focus_attempts=self.focus_attempts,unsafe_focus=self.unsafe_focus,dive_attempts=self.dive_attempts,dive_effective=self.dive_effective)
        return self.observe(s,dt),reward,term,trunc,info

def migrate(source,env):
    old=PPO.load(source,device='cpu');model=PPO(CurriculumPolicy,env,device='cpu',**CONFIG)
    src=old.policy.state_dict();dst=model.policy.state_dict()
    for key,target in dst.items():
        if key not in src:continue
        value=src[key]
        if value.shape==target.shape:target.copy_(value)
        elif key in ('mlp_extractor.policy_net.0.weight','mlp_extractor.value_net.0.weight'):
            target.zero_()
            for frame in range(4):target[:,frame*FRAME_SIZE:frame*FRAME_SIZE+176].copy_(value[:,frame*176:(frame+1)*176])
        elif key=='action_net.weight':target[:18].copy_(value)
        elif key=='action_net.bias':target[:18].copy_(value)
    model.policy.load_state_dict(dst);model.num_timesteps=old.num_timesteps
    return model

def main():
    p=argparse.ArgumentParser();p.add_argument('--task',choices=TASKS,default='defense');p.add_argument('--steps',type=int,default=10000)
    p.add_argument('--checkpoint',type=Path);p.add_argument('--migrate-v3',type=Path);p.add_argument('--eval',type=int,default=0);p.add_argument('--run-name',required=True)
    p.add_argument('--convert-only',action='store_true');a=p.parse_args()
    if a.checkpoint and a.migrate_v3:p.error('Choose one checkpoint source')
    if any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in a.run_name) or a.steps<=0:p.error('Invalid run arguments')
    ensure_game(Path('D:/steam/steamapps/common/Hollow Knight'))
    out=ROOT/'artifacts'/a.run_name;out.mkdir(parents=True,exist_ok=True)
    env=Monitor(SingleBossEnv(a.task,training=not a.eval),str(out/'monitor.csv'))
    rollout=max(n for n in range(1,1001) if a.steps%n==0)
    model=PPO.load(a.checkpoint,env=env,device='cpu',custom_objects={'n_steps':rollout}) if a.checkpoint else migrate(a.migrate_v3,env) if a.migrate_v3 else PPO(CurriculumPolicy,env,device='cpu',**CONFIG)
    (out/'config.json').write_text(json.dumps(dict(schema=SCHEMA,task=a.task,obs_size=OBS_SIZE,actions=ACTIONS,config=CONFIG),indent=2),encoding='utf-8')
    try:
        if a.convert_only:
            if not a.migrate_v3:raise RuntimeError('Conversion requires v3 checkpoint')
            model.save(out/'latest')
        elif a.eval:
            results=[]
            for i in range(a.eval):
                obs,_=env.reset(options={'offset':i%9});done=False
                while not done:
                    act,_=model.predict(obs,deterministic=True);obs,_,term,trunc,info=env.step(act);done=term or trunc
                record={k:v for k,v in info.items() if k!='terminal_observation'};record['episode_index']=i+1
                results.append(record);print(json.dumps(record),flush=True)
                (out/'evaluation.json').write_text(json.dumps({'episodes':results},indent=2),encoding='utf-8')
        else:model.learn(a.steps,callback=Progress(out),reset_num_timesteps=False)
    finally:
        if not a.eval:model.save(out/'latest')
        env.close()

if __name__=='__main__':main()
