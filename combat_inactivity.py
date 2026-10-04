"""Bounded inactivity costs; movement and button spam cannot earn rewards."""
from collections import deque
from defense_v3_core import collision_time

class Inactivity:
    def __init__(self):
        self.positions=deque();self.elapsed=0.;self.last_progress=0.;self.exempt_time=0.
        self.idle_seconds=0.;self.no_progress_seconds=0.
    def score(self,old,s,dt):
        self.elapsed+=dt
        self.positions.append((self.elapsed,s['hero_cx'],s['hero_cy']))
        while self.positions and self.positions[0][0]<self.elapsed-2:self.positions.popleft()
        progress=s['damage_dealt']>old['damage_dealt'] or s['hero_healed']>old['hero_healed']
        if progress:self.last_progress=self.elapsed
        charging=s['hero_nailCharging'] and s['nailChargeTimer']<=s['nailChargeTime']+1.
        preparing=s['hero_focusing'] or charging or s['hero_casting'] or s['hero_castRecoiling'] or s['hero_nailArt_active']
        imminent=any(collision_time(s,h,.3) is not None for h in s['hazards'])
        # Exemptions have a cumulative cap until genuine progress, so toggling
        # focus/charge indefinitely cannot bypass the inactivity cost.
        if progress:self.exempt_time=0.
        exempt=bool((preparing or imminent or s['hero_recoiling']) and self.exempt_time<3.)
        if exempt:self.exempt_time+=dt
        x=[p[1] for p in self.positions];y=[p[2] for p in self.positions]
        stationary=self.elapsed>=2 and max(x)-min(x)<.35 and max(y)-min(y)<.35
        idle=stationary and self.elapsed-self.last_progress>=2.5 and not exempt
        no_progress=self.elapsed-self.last_progress>=8 and not exempt
        self.idle_seconds+=dt if idle else 0.;self.no_progress_seconds+=dt if no_progress else 0.
        return dict(inactive=-.04*dt if idle else 0.,no_progress=-.02*dt if no_progress else 0.)
