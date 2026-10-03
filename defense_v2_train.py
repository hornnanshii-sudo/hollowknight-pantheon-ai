"""Fresh, synchronous defense PPO. Separate schema from all previous models."""
import argparse,json,time
from pathlib import Path
import numpy as np
import gymnasium as gym
from stable_baselines3 import PPO
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.callbacks import BaseCallback
from train import Bridge,ensure_game,ROOT
from defense_v2_core import ACTIONS,OBS_SIZE,SCHEMA,Features,Reward,ending
from dodge_reward import outside_view

class DefenseEnv(gym.Env):
    def __init__(self,horizon=10):
        self.horizon=horizon;self.bridge=Bridge();self.bridge.request('mode dodge')
        self.action_space=gym.spaces.Discrete(len(ACTIONS));self.observation_space=gym.spaces.Box(-np.inf,np.inf,(OBS_SIZE,),np.float32)
    def observe(self,s,dt=0,reset=False):
        f=self.features.frame(s,self.horizon-(s['time']-self.started),self.horizon,self.last_action,dt)
        self.history=[f.copy() for _ in range(4)] if reset else (self.history+[f])[-4:]
        return np.concatenate(self.history)
    def reset(self,seed=None,options=None):
        super().reset(seed=seed);offset=(options or {}).get('offset',int(self.np_random.integers(0,9)))
        for attempt in range(3):
            self.bridge.request('reset');deadline=time.monotonic()+45
            while time.monotonic()<deadline:
                s=self.bridge.request('state')
                if s['ready']:break
                time.sleep(.1)
            else:raise TimeoutError('Arena not ready')
            s=self.bridge.request('sync on')
            for _ in range((offset//3)*2):s=self.bridge.request(f'tick {offset%3} 0')
            if s['hp']==9:break
        else:raise RuntimeError('Cannot establish a valid full-health episode start')
        if any(s.get(f'equippedCharm_{c}') for c in (35,12,10,22,40)):raise RuntimeError('Passive damage charm enabled')
        self.state=s;self.started=s['time'];self.start_hp=s['hp'];self.damage_start=s['damage_dealt'];self.wall_start=time.monotonic();self.features=Features();self.reward=Reward();self.last_action=None;self.loss=0;self.steps=0;self.dt_sum=0;self.dt_min=1e9;self.dt_max=0;self.offset=offset;self.reward_totals={}
        return self.observe(s,reset=True),{}
    def step(self,action):
        mask,pulse=ACTIONS[int(action)];before=time.monotonic();s=self.bridge.request(f'tick {mask} {pulse}');latency=time.monotonic()-before
        if s['scene']!='GG_Gruz_Mother' or s['damage_dealt']!=self.damage_start:raise RuntimeError('Invalid pure-defense state')
        ticks=s['physics_ticks']-self.state['physics_ticks'];dt=s['time']-self.state['time']
        if not s['sync_paused'] or ticks!=4:raise RuntimeError(f'Synchronous tick violation: {ticks}')
        if not 0<dt<.16:raise RuntimeError(f'Unexpected game dt {dt}')
        self.steps+=1;self.dt_sum+=dt;self.dt_min=min(self.dt_min,dt);self.dt_max=max(self.dt_max,dt)
        hurt=max(0,self.state['hp']-s['hp']);self.loss+=hurt;elapsed=s['time']-self.started
        term,trunc,success=ending(hurt,s['hp']<=0,outside_view(s),elapsed>=self.horizon,time.monotonic()-self.wall_start>=600)
        reward=self.reward.score(self.state,s,min(dt,max(0,self.horizon-(self.state['time']-self.started))),hurt)+self.reward.terminal(success)
        for key,val in self.reward.breakdown.items():self.reward_totals[key]=self.reward_totals.get(key,0)+val
        self.last_action=int(action);self.state=s
        info=dict(is_success=success,target_seconds=self.horizon,fight_seconds=min(elapsed,self.horizon),start_hp=self.start_hp,hp=s['hp'],hp_lost=self.loss,effective_hits=0,damage_dealt=0,out_of_view=outside_view(s),watchdog_timeout=trunc,estimated_avoidances=self.reward.avoidances,near_fraction=self.reward.near_fraction,far_seconds=self.reward.far_seconds,reward_parts=self.reward_totals.copy(),dt_mean=self.dt_sum/self.steps,dt_min=self.dt_min,dt_max=self.dt_max,request_seconds=latency,initial_offset=self.offset)
        return self.observe(s,dt),reward,term,trunc,info
    def close(self):self.bridge.close()

class Progress(BaseCallback):
    def __init__(self,out):super().__init__();self.out=out
    def _on_step(self):
        for info in self.locals['infos']:
            if 'episode' in info:
                record={k:v for k,v in info.items() if k!='terminal_observation'};record['steps']=self.num_timesteps
                with (self.out/'episodes.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(record)+'\n')
                print(json.dumps(record),flush=True)
        return True
    def _on_rollout_end(self):
        # Save after the optimizer update at the next rollout start, avoiding pre-update checkpoints.
        pass
    def _on_rollout_start(self):
        if self.num_timesteps:self.model.save(self.out/'latest')

CONFIG=dict(n_steps=1000,batch_size=125,n_epochs=4,gamma=.999,gae_lambda=.98,ent_coef=.015,learning_rate=3e-4,target_kl=.03,policy_kwargs={'net_arch':dict(pi=[128,128],vf=[128,128])},seed=42,verbose=1)
def main():
    p=argparse.ArgumentParser();p.add_argument('--steps',type=int,default=20000);p.add_argument('--horizon',type=float,default=10);p.add_argument('--eval',type=int,default=0);p.add_argument('--checkpoint',type=Path);p.add_argument('--run-name',required=True);a=p.parse_args()
    if not 0<a.horizon<=120 or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in a.run_name):p.error('Invalid arguments')
    out=ROOT/'artifacts'/a.run_name;out.mkdir(parents=True,exist_ok=True)
    ensure_game(Path('D:/steam/steamapps/common/Hollow Knight'));env=Monitor(DefenseEnv(a.horizon),str(out/'monitor.csv'))
    (out/'config.json').write_text(json.dumps(dict(schema=SCHEMA,obs_size=OBS_SIZE,actions=ACTIONS,horizon=a.horizon,config=CONFIG),indent=2))
    model=PPO.load(a.checkpoint,env=env,device='cpu') if a.checkpoint else PPO('MlpPolicy',env,device='cpu',**CONFIG)
    try:
        if a.eval:
            results=[]
            for i in range(a.eval):
                obs,_=env.reset(options={'offset':i%9});done=False
                while not done:
                    act,_=model.predict(obs,deterministic=True);obs,_,term,trunc,info=env.step(act);done=term or trunc
                record={k:v for k,v in info.items() if k!='terminal_observation'};record['episode_index']=i+1;results.append(record);print(json.dumps(record),flush=True)
                (out/'evaluation.json').write_text(json.dumps({'episodes':results},indent=2))
        else:model.learn(a.steps,callback=Progress(out),reset_num_timesteps=not bool(a.checkpoint))
    finally:
        if not a.eval:model.save(out/'latest')
        env.close()
if __name__=='__main__':main()
