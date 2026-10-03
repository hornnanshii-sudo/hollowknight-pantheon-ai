"""Fresh integrated combat: every evaluation is normal-start Boss combat."""
import argparse,json,time
from pathlib import Path
import numpy as np
from stable_baselines3 import PPO
from stable_baselines3.common.monitor import Monitor
from single_boss_train import SingleBossEnv
from single_boss_core import ACTIONS,OBS_SIZE,SCHEMA,allowed,CurriculumPolicy
from integrated_combat_core import CombatReward,RelativeFeatures,REVISION,PHASES
from defense_v3_train import Progress,CONFIG
from dodge_reward import outside_view
from train import ROOT,ensure_game

class IntegratedEnv(SingleBossEnv):
    def __init__(self,phase='basic',training=False):
        self.phase=phase;self.integrated_training=training
        super().__init__('nail' if phase=='basic' else 'full',training=False)
    def observe(self,s,dt=0,reset=False):
        if reset:self.features=RelativeFeatures()
        f=self.features.frame(s,120-(s['time']-self.started),120,self.last_action,dt,self.active_task,self.loss)
        self.history=[f.copy() for _ in range(4)] if reset else (self.history+[f])[-4:]
        return np.concatenate(self.history)
    def reset(self,seed=None,options=None):
        self.task='nail' if self.phase=='basic' else 'full'
        super().reset(seed=seed,options=options)
        if self.integrated_training and self.phase!='basic':
            draw=self.np_random.random()
            if draw<(.3 if self.phase=='mixed' else .1):
                if self.np_random.random()<.5:
                    self.active_task='heal';self.state=self.bridge.request('training resources 6 99')
                else:
                    self.active_task='dive';self.state=self.bridge.request('training resources 9 66')
        self.start_hp=self.state['hp'];self.reward=CombatReward()
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
        survived=bool(elapsed>=120 and not dead and not outside)
        success=(survived and self.reward.qualified_engagement) if self.active_task=='defense' else won and not dead and not outside
        term=bool(dead or outside or won or elapsed>=120);trunc=bool(not term and time.monotonic()-self.wall_start>=600)
        reward=self.reward.score(old,s,min(dt,max(0,120-(old['time']-self.started))),hurt,mask)
        if self.active_task=='defense':success=survived and self.reward.qualified_engagement
        reward+=self.reward.terminal(success,s['hp'],self.loss,term,timed_out=elapsed>=120)
        damage=max(0,s['damage_dealt']-old['damage_dealt'])
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
        skill=0.
        self.reward.breakdown['healing']=skill
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
        info.update(survived_120s=survived,disengaged_seconds=self.reward.disengaged_seconds,
                    corner_seconds=self.reward.corner_seconds,qualified_engagement=self.reward.qualified_engagement)
        info.update(dash_count=self.reward.dash_count,unnecessary_dashes=self.reward.unnecessary_dashes,
                    approach_dashes=self.reward.approach_dashes,threat_dashes=self.reward.threat_dashes,
                    dash_followup_hurts=self.reward.dash_followup_hurts)
        return self.observe(s,dt),reward,term,trunc,info

def main():
    p=argparse.ArgumentParser();p.add_argument('--phase',choices=PHASES,default='basic');p.add_argument('--steps',type=int,default=10000)
    p.add_argument('--checkpoint',type=Path);p.add_argument('--eval',type=int,default=0);p.add_argument('--run-name',required=True);a=p.parse_args()
    if a.steps<=0 or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in a.run_name):p.error('Invalid run arguments')
    ensure_game(Path('D:/steam/steamapps/common/Hollow Knight'))
    out=ROOT/'artifacts'/a.run_name;out.mkdir(parents=True,exist_ok=True)
    env=Monitor(IntegratedEnv(a.phase,training=not a.eval),str(out/'monitor.csv'))
    rollout=max(n for n in range(1,1001) if a.steps%n==0)
    cfg=dict(CONFIG);cfg['n_steps']=rollout
    model=PPO.load(a.checkpoint,env=env,device='cpu',custom_objects={'n_steps':rollout}) if a.checkpoint else PPO(CurriculumPolicy,env,device='cpu',**cfg)
    if a.checkpoint:
        old=out.parent/Path(a.checkpoint).parent.name/'config.json'
        if not old.exists() or json.loads(old.read_text()).get('reward_revision')!=REVISION:raise RuntimeError('Reject legacy or incompatible checkpoint')
    (out/'config.json').write_text(json.dumps(dict(schema=SCHEMA,reward_revision=REVISION,phase=a.phase,config=cfg,from_zero_lineage=True),indent=2),encoding='utf-8')
    try:
        if a.eval:
            results=[]
            for i in range(a.eval):
                obs,_=env.reset(seed=10000+i,options={'offset':i%9});done=False
                while not done:
                    act,_=model.predict(obs,deterministic=True);obs,_,term,trunc,info=env.step(act);done=term or trunc
                record={k:v for k,v in info.items() if k!='terminal_observation'};record.update(episode_index=i+1,phase=a.phase,normal_start=True)
                results.append(record);print(json.dumps(record),flush=True)
                (out/'evaluation.json').write_text(json.dumps({'episodes':results},indent=2),encoding='utf-8')
        else:model.learn(a.steps,callback=Progress(out),reset_num_timesteps=not bool(a.checkpoint))
    finally:
        if not a.eval:model.save(out/'latest')
        env.close()

if __name__=='__main__':main()
