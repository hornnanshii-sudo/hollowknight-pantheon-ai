"""Version 2: explicit jump hold/release, stable phase/hazard slots, bounded rewards."""
import math
import numpy as np
from dodge_reward import safe_gap,outside_view

ACTIONS=[(move|jump|dash,jpulse|dash) for move in (0,1,2) for jump,jpulse in ((0,0),(4,0),(4,4)) for dash in (0,16)]
FRAME_SIZE=176
OBS_SIZE=FRAME_SIZE*4
SCHEMA='defense-v2-176x4-actions18'

def collision_time(s,h,window=1.):
    dx=h['cx']-s['hero_cx'];dy=h['cy']-s['hero_cy']
    vx=h['vx']-s['vx'];vy=h['vy']-s['vy']
    ex=h['ex']+s['hero_ex']+.1;ey=h['ey']+s['hero_ey']+.1
    if dx*vx+dy*vy>=0:return None
    enter,leave=0.,window
    for d,v,e in ((dx,vx,ex),(dy,vy,ey)):
        if abs(v)<1e-7:
            if abs(d)>e:return None
        else:
            t1,t2=sorted(((-e-d)/v,(e-d)/v));enter=max(enter,t1);leave=min(leave,t2)
    return enter if enter<=leave and leave>=0 else None

class Features:
    def __init__(self):self.slots=[None]*6;self.names=None
    def frame(self,s,remaining,horizon,last_action,dt):
        names=s['boss_phase_names']
        if len(names)>31:raise RuntimeError('Boss needs expanded exact phase schema')
        if self.names is None:self.names=list(names)
        if self.names!=names:raise RuntimeError('Phase schema changed within episode')
        phase=np.zeros(32);phase[names.index(s['boss_phase'])+1 if s['boss_phase'] in names else 0]=1
        base=[s['x']/40,s['y']/20,s['vx']/30,s['vy']/30,(s['bx']-s['x'])/30,(s['by']-s['y'])/20,s['bvx']/30,s['bvy']/30,s['hp']/9,s['grounded'],s['hero_ex']/5,s['hero_ey']/5]
        movement=[s[k] for k in ('facing_right','doubleJumped','touchingWallL','touchingWallR','wallSliding','dashing','jumping','doubleJumping','invulnerable','shadowDashing')]+[s['shadowDashTimer']/1.5,s['dashCooldownTimer'],s['attack_cooldown']]
        clock=[max(0,remaining)/horizon,horizon/120,s['boss_phase_age']/5,dt/.08]
        action=np.zeros(18)
        if last_action is not None:action[last_action]=1
        if not s['terrain_valid']:raise RuntimeError('Missing Terrain layer')
        x,y=s['hero_cx'],s['hero_cy']
        terrain=[v/20 for v in s['terrain_distances']]+s['terrain_hits']+[(x-s['view_left'])/20,(s['view_right']-x)/20,(y-s['view_bottom'])/20,(s['view_top']-y)/20]+[v/20 for v in s['floor_distances']]
        # Stable identities across frames; do not feed arbitrary numeric instance IDs to the network.
        hazards={h['id']:h for h in s['hazards']}
        self.slots=[key if key in hazards else None for key in self.slots]
        for key in hazards:
            if key not in self.slots and None in self.slots:self.slots[self.slots.index(None)]=key
        entities=[]
        for key in self.slots:
            if key is None:entities.extend([0]*12);continue
            h=hazards[key];ttc=collision_time(s,h)
            entities.extend([1,(h['cx']-x)/30,(h['cy']-y)/20,h['ex']/5,h['ey']/5,h['vx']/30,h['vy']/30,h['damage']/2,h['shadow_hazard'],h['kind']/2,h['velocity_valid'],1 if ttc is None else ttc])
        # Counts expose overflow rather than silently treating six slots as complete.
        result=np.asarray(base+movement+clock+list(phase)+list(action)+terrain+entities+[min(s['hazard_count'],30)/30,float(s['hazard_count']>6)],np.float32)
        if result.shape!=(FRAME_SIZE,) or not np.isfinite(result).all():raise RuntimeError(f'Bad frame {result.shape}')
        return np.clip(result,-5,5)

class Reward:
    def __init__(self):
        self.pending={};self.paid=set();self.avoidances=0;self.aux_paid=0.;self.elapsed=0.;self.near_seconds=0.;self.far_seconds=0.;self.breakdown={}
    def score(self,old,s,dt,hurt):
        parts={'survival':.04*dt,'damage':-5*hurt,'avoidance':0.,'engagement':0.,'outside':-5. if outside_view(s) else 0.,'success':0.}
        self.elapsed+=dt;gap=safe_gap(s);self.near_seconds+=dt if .5<=gap<=5 else 0;self.far_seconds+=dt if gap>8 else 0
        hs={h['id']:h for h in s['hazards']}
        if hurt:self.pending.clear()
        else:
            for key,(deadline,x,y) in list(self.pending.items()):
                if s['time']<deadline:continue
                h=hs.get(key[0]);moved=math.hypot(s['hero_cx']-x,s['hero_cy']-y)>.3
                if h is not None and collision_time(s,h,.35) is None and moved and not s['invulnerable'] and key not in self.paid and self.aux_paid<1:
                    value=min(.1,1-self.aux_paid);parts['avoidance']+=value;self.aux_paid+=value;self.avoidances+=1;self.paid.add(key)
                del self.pending[key]
            if not old['invulnerable']:
                for h in old['hazards']:
                    key=(h['id'],old['boss_phase_event']);ttc=collision_time(old,h,.35)
                    if ttc is not None and key not in self.paid and key not in self.pending:
                        self.pending[key]=(old['time']+.35,old['hero_cx'],old['hero_cy'])
        # Potential difference gives no repeated bonus merely for occupying a location.
        def potential(state):return -.03*min(max(safe_gap(state)-5,0),5)
        if not hurt:parts['engagement']=potential(s)-potential(old)
        self.breakdown=parts
        return sum(parts.values())
    def terminal(self,success):
        bonus=5. if success else 0.;self.breakdown['success']=bonus;return bonus
    @property
    def near_fraction(self):return self.near_seconds/max(self.elapsed,1e-6)

def ending(hurt,dead,outside,reached,watchdog):
    failed=bool(hurt or dead or outside);success=bool(reached and not failed)
    return bool(failed or success),bool(watchdog and not (failed or success)),success
