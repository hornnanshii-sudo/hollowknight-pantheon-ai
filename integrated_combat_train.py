"""Fresh integrated combat: every evaluation is normal-start Boss combat."""
import argparse,json,time,os
from pathlib import Path
import numpy as np
from stable_baselines3 import PPO
from stable_baselines3.common.monitor import Monitor
from single_boss_train import SingleBossEnv
from single_boss_core import ACTIONS,allowed
from integrated_observation import HISTORY,OBS_SIZE,SCHEMA,CombatFeatures,CombatPolicy,transfer_four_frames
from integrated_combat_core import CombatReward,RelativeFeatures,REVISION,PHASES
from defense_v3_train import Progress,CONFIG
from dodge_reward import outside_view
from train import ROOT,ensure_game
from combat_start_profiles import profile,TRAIN

class IntegratedEnv(SingleBossEnv):
    def __init__(self,phase='basic',training=False,assessment=None):
        self.phase=phase;self.integrated_training=training;self.assessment=assessment
        super().__init__('nail' if phase=='basic' else 'full',training=False)
        import gymnasium as gym
        self.observation_space=gym.spaces.Box(-np.inf,np.inf,(OBS_SIZE,),np.float32)
    def observe(self,s,dt=0,reset=False):
        if reset:self.features=CombatFeatures()
        if not s.get('boss_valid',1) and s.get('won') and self.features.names is not None:
            s=dict(s,boss_phase_names=self.features.names,boss_phase='')
        f=self.features.frame(s,120-(s['time']-self.started),120,self.last_action,dt,self.active_task,self.loss)
        self.history=[f.copy() for _ in range(HISTORY)] if reset else (self.history+[f])[-HISTORY:]
        return np.concatenate(self.history)
    def reset(self,seed=None,options=None):
        self.task='nail' if self.phase=='basic' else 'full'
        options=options or {}
        bank=options.get('bank','train' if self.integrated_training else 'validation')
        index=options.get('profile_index')
        for attempt in range(4):
            super().reset(seed=seed if attempt==0 else None,options={'offset':0})
            if index is None:index=int(self.np_random.integers(len(TRAIN)))
            direction,walk,wait=profile(bank,index)
            for _ in range(walk):self.state=self.bridge.request(f'tick {direction} 0')
            for _ in range(wait):self.state=self.bridge.request('tick 0 0')
            if self.state['hp']==9 and self.state['boss_valid'] and not self.state['won']:break
        else:raise RuntimeError(f'Cannot establish profile {bank}/{index}')
        self.started=self.state['time'];self.wall_start=time.monotonic()
        self.start_bank=bank;self.start_profile=index
        if self.integrated_training and self.phase!='basic':
            draw=self.np_random.random()
            if draw<(.3 if self.phase=='mixed' else .1):
                if self.np_random.random()<.5:
                    self.active_task='heal';self.state=self.bridge.request('training resources 6 99')
                else:
                    self.active_task='dive';self.state=self.bridge.request('training resources 9 66')
        if self.assessment:
            self.active_task=self.assessment
            self.state=self.bridge.request('training resources 6 99' if self.assessment=='heal' else 'training resources 9 66')
        self.start_hp=self.state['hp'];self.start_soul=self.state['soul'];self.reward=CombatReward()
        self.counter_start={k:self.state[k] for k in ('nail_damage','spell_damage','quake_damage','quake_hits','focus_heals')}
        self.pending_focus=False;self.last_focus_heal_at=-100.;self.focus_post_hurt=0;self.dive_hurt_count=0
        self.damage_start=self.state['damage_dealt'];self.hits_start=self.state['effective_hits']
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
        hurt=max(0,s['hero_damage_taken']-old['hero_damage_taken']);healed=max(0,s['hero_healed']-old['hero_healed']);self.loss+=hurt;self.heals+=healed
        elapsed=s['time']-self.started;outside=outside_view(s);dead=s['hp']<=0
        won=bool(s['won'])
        survived=bool(elapsed>=120 and not dead and not outside)
        success=(survived and self.reward.qualified_engagement) if self.active_task=='defense' else won and not dead and not outside
        term=bool(dead or outside or won or elapsed>=120);trunc=bool(not term and time.monotonic()-self.wall_start>=600)
        reward=self.reward.score(old,s,min(dt,max(0,120-(old['time']-self.started))),hurt,mask)
        if self.active_task=='defense':success=survived and self.reward.qualified_engagement
        reward+=self.reward.terminal(success,s['hp'],self.loss,term,timed_out=elapsed>=120)
        damage=max(0,s['damage_dealt']-old['damage_dealt'])
        focus_started=s['focus_starts']>old['focus_starts']
        if focus_started:
            self.focus_attempts+=s['focus_starts']-old['focus_starts'];self.pending_focus=True
        if hurt and self.pending_focus:
            self.unsafe_focus+=1;self.pending_focus=False
        if s['focus_heals']>old['focus_heals']:self.last_focus_heal_at=s['time']
        if hurt and s['time']-self.last_focus_heal_at<=.5:self.focus_post_hurt+=1
        if s['focus_heals']>old['focus_heals'] or not s['hero_focusing']:self.pending_focus=False
        if s['quake_casts']>old['quake_casts']:
            self.dive_attempts+=s['quake_casts']-old['quake_casts'];self.pending_dive=[False,False]
        if self.pending_dive:
            self.pending_dive[0]|=s['quake_damage']>old['quake_damage']
            self.pending_dive[1]|=bool(hurt)
            if (old['spellQuake'] and not s['spellQuake']) or term:
                if self.pending_dive[0] and not self.pending_dive[1]:self.dive_effective+=1
                if self.pending_dive[1]:self.dive_hurt_count+=1
                self.pending_dive=None
        # Healing is measured, but receives no button/event bonus.
        skill=0.
        self.reward.breakdown['healing']=skill
        for key,val in self.reward.breakdown.items():self.reward_totals[key]=self.reward_totals.get(key,0)+val
        self.previous_mask=mask;self.last_action=action;self.state=s
        info=dict(is_success=success,task=self.active_task,target_seconds=120,fight_seconds=min(elapsed,120),
                  start_hp=self.start_hp,start_soul=self.start_soul,hp=s['hp'],hp_lost=self.loss,
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
        info.update({k:s[k]-self.counter_start[k] for k in self.counter_start})
        info.update(start_bank=self.start_bank,start_profile=self.start_profile,focus_post_hurt=self.focus_post_hurt)
        if self.assessment:
            info['assessment']=self.assessment
            info['assessment_success']=bool(info['focus_heals']>=1 and self.unsafe_focus==0 and self.focus_post_hurt==0) if self.assessment=='heal' else bool(info['quake_damage']>0 and self.dive_effective>=1 and self.dive_hurt_count==0)
            if elapsed>=20 and not term:trunc=True
        return self.observe(s,dt),reward,term,trunc,info

def atomic_model_save(model,path):
    path=Path(path);temporary=path.with_name(path.name+'.tmp.zip')
    model.save(temporary);os.replace(temporary,path.with_suffix('.zip'))

class AtomicProgress(Progress):
    def _on_rollout_start(self):
        if self.num_timesteps:atomic_model_save(self.model,self.out/'latest')


def main():
    p=argparse.ArgumentParser();p.add_argument('--phase',choices=PHASES,default='basic');p.add_argument('--steps',type=int,default=10000)
    p.add_argument('--migrate-four-frame',type=Path);p.add_argument('--migration-only',action='store_true');p.add_argument('--assessment',choices=('heal','dive'));p.add_argument('--eval-bank',choices=('validation','confirmation'),default='validation');p.add_argument('--checkpoint',type=Path);p.add_argument('--eval',type=int,default=0);p.add_argument('--run-name',required=True);a=p.parse_args()
    if a.steps<=0 or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in a.run_name):p.error('Invalid run arguments')
    ensure_game(Path('D:/steam/steamapps/common/Hollow Knight'))
    out=ROOT/'artifacts'/a.run_name;out.mkdir(parents=True,exist_ok=True)
    env=Monitor(IntegratedEnv(a.phase,training=not a.eval,assessment=a.assessment),str(out/'monitor.csv'))
    rollout=max(n for n in range(1,1001) if a.steps%n==0)
    cfg=dict(CONFIG);cfg['n_steps']=rollout
    model=PPO.load(a.checkpoint,env=env,device='cpu',custom_objects={'n_steps':rollout}) if a.checkpoint else PPO(CombatPolicy,env,device='cpu',**cfg)
    if a.migrate_four_frame:
        if a.checkpoint or not a.migration_only:raise RuntimeError('Explicit offline migration required')
        old_cfg=json.loads(a.migrate_four_frame.with_name('config.json').read_text())
        if old_cfg.get('schema')!='single-boss-v1-209x4-actions25' or old_cfg.get('reward_revision')!='integrated-combat-v1':raise RuntimeError('Unexpected migration source')
        old_model=PPO.load(a.migrate_four_frame,device='cpu')
        state=model.policy.state_dict();transfer_four_frames(old_model.policy.state_dict(),state)
        model.policy.load_state_dict(state);model.num_timesteps=old_model.num_timesteps
    if a.checkpoint:
        old=Path(a.checkpoint).with_name('config.json')
        if not old.exists() or json.loads(old.read_text()).get('reward_revision')!=REVISION or json.loads(old.read_text()).get('schema')!=SCHEMA:raise RuntimeError('Reject legacy or incompatible checkpoint')
    (out/'config.json').write_text(json.dumps(dict(schema=SCHEMA,reward_revision=REVISION,phase=a.phase,config=cfg,from_zero_lineage=True,frames=HISTORY,obs_size=OBS_SIZE,migration_source=str(a.migrate_four_frame) if a.migrate_four_frame else None,
        counters='actual_health_and_damage_events_v2',optimizer_reset=bool(a.migrate_four_frame),
        deterministic_resume=False,eval_bank=a.eval_bank,assessment=a.assessment),indent=2),encoding='utf-8')
    try:
        if a.migration_only:
            if not a.migrate_four_frame:raise RuntimeError('Missing migration source')
            atomic_model_save(model,out/'latest')
        elif a.eval:
            results=[]
            for i in range(a.eval):
                obs,_=env.reset(seed=10000+i,options={'bank':a.eval_bank,'profile_index':i});done=False
                while not done:
                    act,_=model.predict(obs,deterministic=True);obs,_,term,trunc,info=env.step(act);done=term or trunc
                record={k:v for k,v in info.items() if k!='terminal_observation'};record.update(episode_index=i+1,phase=a.phase,normal_start=not bool(a.assessment))
                results.append(record);print(json.dumps(record),flush=True)
                (out/'evaluation.json').write_text(json.dumps({'episodes':results},indent=2),encoding='utf-8')
        else:
            model.learn(a.steps,callback=AtomicProgress(out),reset_num_timesteps=not bool(a.checkpoint))
            atomic_model_save(model,out/'latest')
    finally:
        # On failure keep the last completed optimizer boundary. A partially
        # sampled rollout must not count as learned steps or replace its model.
        env.close()

if __name__=='__main__':main()
