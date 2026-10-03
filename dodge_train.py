"""Fresh no-attack curriculum; evaluation target is 120 seconds without damage."""
import argparse,hashlib,json,time
from pathlib import Path
import numpy as np
import gymnasium as gym
from stable_baselines3 import PPO
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.callbacks import BaseCallback
from train import GruzEnv,ensure_game,observation,ROOT
from dodge_reward import DodgeReward,outside_view
from skill_actions import skill_observation

from terrain_observation import geometry_observation,load_or_migrate

DODGE_ACTIONS=[(move|keys,keys) for move in (0,1,2) for keys in (0,4,16,20)]

def danger_observation(s):
    phase=np.zeros(16,dtype=np.float32)
    if s["boss_phase"]:
        phase[hashlib.sha256(s["boss_phase"].encode()).digest()[0]%16]=1
    extra=[(s["boss_cx"]-s["hero_cx"])/30,(s["boss_cy"]-s["hero_cy"])/20,
           s["hero_ex"]/5,s["hero_ey"]/5,s["boss_ex"]/5,s["boss_ey"]/5,
           s["facing_right"],float(bool(s["boss_phase"]))]
    return np.concatenate([skill_observation(s,observation(s)),np.asarray(extra,dtype=np.float32),phase,geometry_observation(s)])

class DodgeEnv(GruzEnv):
    def __init__(self,horizon):
        super().__init__(skills=True)
        self.horizon=horizon
        self.action_space=gym.spaces.Discrete(len(DODGE_ACTIONS))
        self.observation_space=gym.spaces.Box(-np.inf,np.inf,(496,),np.float32)
        self.bridge.request("mode dodge")
    def observe(self,s,reset=False):
        frame=danger_observation(s)
        self.history=[frame.copy() for _ in range(4)] if reset else (self.history+[frame])[-4:]
        return np.concatenate(self.history)
    def reset(self,**kwargs):
        obs,info=super().reset(**kwargs)
        self.wall_started=time.monotonic()
        self.shaping=DodgeReward()
        for charm in (35,12,10,22,40):
            if self.state.get(f"equippedCharm_{charm}"):
                raise RuntimeError(f"Passive offense charm {charm} must be disabled for pure dodge")
        if self.state["boss_ex"]<=0 or self.state["hero_ex"]<=0:
            raise RuntimeError("Missing collider bounds; danger observation invalid")
        if not all(k in self.state for k in ("view_left","view_right","view_bottom","view_top")):
            raise RuntimeError("Camera bounds unavailable; cannot validate out-of-view escape")
        return obs,info
    def step(self,action):
        mask,pulse=DODGE_ACTIONS[int(action)]
        s=self.bridge.request(f"pulse {mask} {pulse}")
        if s["scene"]!="GG_Gruz_Mother":raise RuntimeError("Unexpected scene")
        if s["damage_dealt"]!=self.damage_start:raise RuntimeError("Boss damage in pure dodge mode")
        hurt=max(0,self.state["hp"]-s["hp"]);self.hp_lost+=hurt
        elapsed=s["time"]-self.started
        dt=max(0,min(s["time"]-self.state["time"],self.horizon-(self.state["time"]-self.started)))
        out_of_view=outside_view(s)
        failed=bool(hurt or s["hp"]<=0 or out_of_view)
        reached=elapsed>=self.horizon
        watchdog=time.monotonic()-self.wall_started>=150
        reward=self.shaping.score(self.state,s,dt,hurt)
        if out_of_view:reward-=5
        success=bool(reached and not failed and self.hp_lost==0)
        if success:reward+=5*self.horizon/120*self.shaping.near_fraction
        self.state=s
        info=dict(is_success=success,no_damage_win=False,no_damage_survival=success,
                  target_seconds=self.horizon,fight_seconds=min(elapsed,120),start_hp=self.start_hp,
                  hp=s["hp"],hp_lost=self.hp_lost,effective_hits=0,damage_dealt=0,end_soul=s["soul"],
                  hero_x=s["x"],hero_y=s["y"],boss_x=s["bx"],boss_y=s["by"],view_bounds=[s["view_left"],s["view_right"],s["view_bottom"],s["view_top"]],watchdog_timeout=watchdog,out_of_view=out_of_view,estimated_avoidances=self.shaping.avoidances,near_fraction=self.shaping.near_fraction,far_seconds=self.shaping.far_seconds,combo=0,boss_hp=s["boss_hp"])
        return self.observe(s),reward,failed,reached or watchdog,info

class Progress(BaseCallback):
    def __init__(self,out):super().__init__();self.out=out
    def _on_step(self):
        for info in self.locals["infos"]:
            if "episode" in info:
                record={k:v for k,v in info.items() if k!="terminal_observation"}
                record["steps"]=self.num_timesteps
                with (self.out/"episodes.jsonl").open("a",encoding="utf-8") as f:f.write(json.dumps(record)+"\n")
                print(json.dumps(record),flush=True)
        if self.n_calls%1000==0:self.model.save(self.out/"latest")
        return True

def main():
    p=argparse.ArgumentParser();p.add_argument("--steps",type=int,default=20000)
    p.add_argument("--horizon",type=float,default=10);p.add_argument("--eval",type=int,default=0)
    p.add_argument("--checkpoint",type=Path);p.add_argument("--run-name",required=True)
    a=p.parse_args()
    if not 0<a.horizon<=120:p.error("Horizon must be 0..120")
    if any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in a.run_name):p.error("Invalid name")
    out=ROOT/"artifacts"/a.run_name;out.mkdir(parents=True,exist_ok=True)
    ensure_game(Path("D:/steam/steamapps/common/Hollow Knight"))
    env=Monitor(DodgeEnv(120 if a.eval else a.horizon),str(out/"monitor.csv"))
    model=load_or_migrate(a.checkpoint,env) if a.checkpoint else PPO("MlpPolicy",env,device="cpu",n_steps=1000,batch_size=125,n_epochs=4,gamma=.995,ent_coef=.02,learning_rate=3e-4,policy_kwargs={"net_arch":dict(pi=[128,128],vf=[128,128])},seed=42,verbose=1)
    try:
        if a.eval:
            results=[]
            for i in range(a.eval):
                obs,_=env.reset();done=False
                while not done:
                    act,_=model.predict(obs,deterministic=True)
                    obs,_,term,trunc,info=env.step(act);done=term or trunc
                record={k:v for k,v in info.items() if k!="terminal_observation"};record["episode_index"]=i+1
                results.append(record);print(json.dumps(record),flush=True)
            (out/"evaluation.json").write_text(json.dumps(dict(episodes=results),indent=2),encoding="utf-8")
        else:model.learn(a.steps,callback=Progress(out),reset_num_timesteps=not bool(a.checkpoint))
    finally:
        if not a.eval:model.save(out/"latest")
        env.close()
if __name__=="__main__":main()
