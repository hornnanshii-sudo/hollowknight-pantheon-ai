"""Terrain rays plus six nearest active DamageHero AABBs, and checkpoint migration."""
import numpy as np
from stable_baselines3 import PPO

def geometry_observation(s):
    if not s.get('terrain_valid'):raise RuntimeError('Terrain physics layer unavailable')
    distances=s['terrain_distances'];hits=s['terrain_hits']
    if len(distances)!=8 or len(hits)!=8:raise RuntimeError('Invalid terrain rays')
    x,y=s['hero_cx'],s['hero_cy']
    result=[v/20 for v in distances]+list(hits)+[(x-s['view_left'])/20,(s['view_right']-x)/20,(y-s['view_bottom'])/20,(s['view_top']-y)/20]
    for i in range(6):
        hs=s['hazards']
        if i>=len(hs):result.extend([0]*9);continue
        h=hs[i];result.extend([1,(h['cx']-x)/30,(h['cy']-y)/20,h['ex']/5,h['ey']/5,h['vx']/30,h['vy']/30,h['damage']/2,h['shadow_hazard']])
    return np.asarray(result,dtype=np.float32)

def load_or_migrate(path,env):
    old=PPO.load(path,device='cpu')
    if old.observation_space.shape==(496,):return PPO.load(path,env=env,device='cpu')
    if old.observation_space.shape!=(200,) or old.action_space.n!=12:raise RuntimeError('Unsupported checkpoint migration')
    model=PPO('MlpPolicy',env,device='cpu',n_steps=1000,batch_size=125,n_epochs=4,gamma=.995,ent_coef=.02,learning_rate=3e-4,policy_kwargs={'net_arch':dict(pi=[128,128],vf=[128,128])},seed=42,verbose=1)
    state=old.policy.state_dict();target=model.policy.state_dict()
    for key,value in state.items():
        if target[key].shape==value.shape:target[key]=value
        elif key in ('mlp_extractor.policy_net.0.weight','mlp_extractor.value_net.0.weight'):
            target[key].zero_()
            for frame in range(4):target[key][:,frame*124:frame*124+50]=value[:,frame*50:frame*50+50]
        else:raise RuntimeError(f'Unexpected migration tensor {key}')
    model.policy.load_state_dict(target);model.num_timesteps=old.num_timesteps
    print(f'Migrated 200 -> 496 observations at {old.num_timesteps} steps; new feature weights start at zero',flush=True)
    return model
