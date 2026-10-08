"""Versioned full-step telemetry, independent of reward shaping."""
import gzip
import json
import time
from pathlib import Path
import numpy as np
import hornet_core as h
from hornet_train import Policy
from hornet_pilot import PilotEnv

class TracePolicy(Policy):
    def capture(self,dist):
        self.last_decision={'probabilities':[d.probs.detach().cpu().numpy().tolist() for d in dist.distribution],
                            'entropy':[d.entropy().detach().cpu().numpy().tolist() for d in dist.distribution]}
    def forward(self,obs,*a,**kw):
        result=super().forward(obs,*a,**kw);self.capture(self.action_dist);return result
    def get_distribution(self,obs,*a,**kw):
        dist,state=super().get_distribution(obs,*a,**kw);self.capture(dist);return dist,state

class TelemetryEnv(PilotEnv):
    def __init__(self,*a,**kw):
        super().__init__(*a,**kw);self.policy=None;self.trace=None;self.episode=0;self.mode='training' if self.training else 'evaluation';self.start_profile='native';self.opening=None
    def emit(self,row):
        self.trace.write(json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n')
        self.trace.flush()
    def reset(self,seed=None,options=None):
        if self.trace:self.trace.close()
        self.reset_profile=self.opening() if self.opening else 'native'
        obs,info=super().reset(seed=seed,options=options)
        self.start_profile=self.reset_profile
        self.episode+=1;self.wall_seconds=0.;self.wall_no_hit=0.;self.since_hit=0.;self.max_no_hit=0.
        self.action_counts=[np.zeros(n,dtype=int) for n in h.HEADS];self.entropy_sum=np.zeros(4);self.prob_steps=0
        self.xmin=self.xmax=self.s['x'];self.distance_sum=0.;self.dt_min=1.;self.dt_max=0.;self.latencies=[]
        folder=self.out/'traces';folder.mkdir(parents=True,exist_ok=True)
        self.trace=gzip.open(folder/f'{self.mode}-{time.time_ns()}.jsonl.gz','wt',encoding='utf8',compresslevel=3)
        self.emit(dict(schema='hornet-trace-v2',type='reset',episode=self.episode,mode=self.mode,opening=self.start_profile,actual=self.ledger.data['actual'],state=self.s))
        return obs,info
    def step(self,action):
        old=self.s;decision=getattr(self.policy,'last_decision',None);started=time.perf_counter()
        try:result=super().step(action)
        except BaseException as e:
            self.emit(dict(type='invalid',error=repr(e),action=np.asarray(action).tolist(),decision=decision,previous=old,state=getattr(self,'last_raw',None),actual=self.ledger.data['actual']))
            raise
        new=self.s;dt=new['time']-old['time'];latency=time.perf_counter()-started
        delta_damage=new['hornet']['damage']-old['hornet']['damage'];delta_hurt=new['hornet']['hurt']-old['hornet']['hurt']
        near_wall=bool(new['terrain_hits'][0] and new['terrain_distances'][0]<1 or new['terrain_hits'][1] and new['terrain_distances'][1]<1)
        self.wall_seconds+=dt*near_wall;self.wall_no_hit+=dt*(near_wall and delta_damage==0)
        self.since_hit=0 if delta_damage else self.since_hit+dt;self.max_no_hit=max(self.max_no_hit,self.since_hit)
        self.xmin=min(self.xmin,new['x']);self.xmax=max(self.xmax,new['x']);self.distance_sum+=abs(new['hornet']['x']-new['x'])
        self.dt_min=min(self.dt_min,dt);self.dt_max=max(self.dt_max,dt);self.latencies.append(latency)
        for c,x in zip(self.action_counts,action):c[int(x)]+=1
        if decision:
            self.entropy_sum+=np.array([v[0] for v in decision['entropy']]);self.prob_steps+=1
        self.emit(dict(type='step',episode_step=self.steps,actual=self.ledger.data['actual'],action=np.asarray(action).tolist(),decision=decision,command=self.last_command,dt=dt,roundtrip_seconds=latency,damage_delta=delta_damage,hurt_delta=delta_hurt,reward_parts=dict(damage=delta_damage/9,hurt=-self.coeff['hurt']*delta_hurt),state=new))
        if result[2] or result[3]:
            row=dict(result[4]['episode_result'],mode=self.mode,opening=self.start_profile,actual=self.ledger.data['actual'],wall_seconds_estimate=self.wall_seconds,wall_no_damage_seconds_estimate=self.wall_no_hit,max_seconds_without_hit=self.max_no_hit,x_min=self.xmin,x_max=self.xmax,mean_abs_boss_dx=self.distance_sum/self.steps,action_counts=[v.tolist() for v in self.action_counts],mean_head_entropy=(self.entropy_sum/max(1,self.prob_steps)).tolist(),dt_min=self.dt_min,dt_max=self.dt_max,roundtrip_p95=float(np.quantile(self.latencies,.95)))
            with (self.out/'diagnostics.jsonl').open('a',encoding='utf8') as f:f.write(json.dumps(row)+'\n')
            self.emit(dict(type='episode_summary',**row))
        return result
    def close(self):
        if self.trace:self.trace.close();self.trace=None
        super().close()
