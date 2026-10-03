"""Penalize persistent disengagement, not ordinary jumps or emergency retreats."""
from defense_v3_core import Reward,collision_time
from dodge_reward import safe_gap

class EngagedReward(Reward):
    def __init__(self):
        super().__init__()
        self.disengaged_run=0.;self.corner_run=0.;self.corner_seconds=0.
        self.last_threat=-100.;self.disengaged_seconds=0.
    def score(self,old,s,dt,hurt,action_mask=0):
        previous_avoidances=self.avoidances
        reward=super().score(old,s,dt,hurt,action_mask)
        threat=any(collision_time(s,h,.5) is not None for h in s['hazards'])
        if threat:self.last_threat=s['time']
        gap=safe_gap(s)
        retreat_grace=s['time']-self.last_threat<1.
        far=gap>6 and not retreat_grace
        self.disengaged_run=self.disengaged_run+dt if far else 0.
        self.disengaged_seconds+=dt if gap>6 else 0.
        terrain=s['terrain_distances'];hits=s['terrain_hits']
        wall=any(hits[i] and terrain[i]<1.2 for i in (0,1))
        high=hits[2] and terrain[2]>3
        ceiling=hits[3] and terrain[3]<1.2
        corner=(wall and high or ceiling) and gap>5 and not retreat_grace
        self.corner_run=self.corner_run+dt if corner else 0.
        self.corner_seconds+=dt if corner else 0.
        far_cost=-min(.12,.04*(self.disengaged_run-2))*dt if self.disengaged_run>2 else 0.
        corner_cost=-.08*dt if self.corner_run>2 else 0.
        self.breakdown['disengagement']=far_cost
        self.breakdown['corner_camping']=corner_cost
        # No paid dodge when its verified endpoint is persistent disengagement.
        removed=self.breakdown['avoidance'] if gap>6 else 0.
        if removed:
            self.breakdown['avoidance']=0.;self.avoidances=previous_avoidances
        lost_survival=self.breakdown['survival'] if self.disengaged_run>2 or self.corner_run>2 else 0.
        self.breakdown['survival']-=lost_survival
        return reward+far_cost+corner_cost-removed-lost_survival
    @property
    def qualified_engagement(self):
        return self.near_fraction>=.35 and self.disengaged_seconds/max(self.elapsed,1e-6)<=.2 and self.corner_seconds/max(self.elapsed,1e-6)<=.05
