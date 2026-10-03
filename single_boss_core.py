"""Fixed observation/action interface for a single-boss curriculum."""
import numpy as np
import torch as th
from stable_baselines3.common.policies import ActorCriticPolicy
from defense_v3_core import ACTIONS as DEFENSE_ACTIONS, Features

TASKS=('defense','nail','dive','heal','full')
ACTIONS=list(DEFENSE_ACTIONS)+[(m|8,8) for m in (0,1,2)]+[(m|96,64) for m in (0,1,2)]+[(256,0)]
FRAME_SIZE=176+3+len(TASKS)+len(ACTIONS)
OBS_SIZE=FRAME_SIZE*4
SCHEMA='single-boss-v1-209x4-actions25'

def allowed(task):
    level=TASKS.index(task)
    return np.array([i<18 or (i<21 and level>=1) or (i<24 and level>=2) or level>=3 for i in range(len(ACTIONS))])

class CurriculumFeatures(Features):
    def frame(self,s,remaining,horizon,last_action,dt,task,loss):
        base=super().frame(s,remaining,horizon,last_action if last_action is not None and last_action<18 else None,dt)
        stage=np.zeros(5);stage[TASKS.index(task)]=1
        action=np.zeros(len(ACTIONS))
        if last_action is not None:action[last_action]=1
        return np.concatenate([base,np.array([s['soul']/99,s['spellQuake'],min(loss/9,5)]),stage,action]).astype(np.float32)

class CurriculumPolicy(ActorCriticPolicy):
    def _latents(self,obs):
        features=self.extract_features(obs)
        return self.mlp_extractor(features)
    def _distribution(self,obs,latent):
        stages=obs[:,3*FRAME_SIZE+179:3*FRAME_SIZE+184].argmax(dim=1)
        ids=th.arange(len(ACTIONS),device=obs.device)[None,:]
        mask=(ids<18)|((ids<21)&(stages[:,None]>=1))|((ids<24)&(stages[:,None]>=2))|(stages[:,None]>=3)
        return self.action_dist.proba_distribution(action_logits=self.action_net(latent).masked_fill(~mask,-1e9))
    def forward(self,obs,deterministic=False):
        pi,vf=self._latents(obs);dist=self._distribution(obs,pi)
        actions=dist.get_actions(deterministic=deterministic)
        return actions,self.value_net(vf),dist.log_prob(actions)
    def get_distribution(self,obs):
        pi,_=self._latents(obs);return self._distribution(obs,pi)
    def evaluate_actions(self,obs,actions):
        pi,vf=self._latents(obs);dist=self._distribution(obs,pi)
        return self.value_net(vf),dist.log_prob(actions),dist.entropy()

def gate(task,r):
    if r['episodes']<30 or r['out_of_view'] or r['watchdog_timeout']:return False
    if task=='defense':return r['success_rate']>=.9 and r['hp_lost_per_minute']<=1 and r['near_fraction']>=.25
    if task=='nail':return r['success_rate']>=.9 and r['winning_hp_lost']<=2
    if task=='dive':return r['success_rate']>=.9 and r['winning_hp_lost']<=2 and r['dive_effective_fraction']>=.8
    if task=='heal':return r['success_rate']>=.9 and r['healing_completed']>=1 and r['unsafe_focus_fraction']<=.1
    return r['success_rate']>=.95 and r['winning_hp_lost']<=1
