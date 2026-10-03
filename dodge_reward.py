"""Estimated collision avoidance, safe engagement, and bounded anti-camping shaping."""
import math

def collision_threat(s,window=.35):
    dx=s["boss_cx"]-s["hero_cx"];dy=s["boss_cy"]-s["hero_cy"]
    vx=s["bvx"]-s["vx"];vy=s["bvy"]-s["vy"]
    ex=s["boss_ex"]+s["hero_ex"]+.15;ey=s["boss_ey"]+s["hero_ey"]+.15
    if vx*vx+vy*vy<.25:return False
    if dx*vx+dy*vy>=0:return False
    enter,leave=0.,window
    for d,v,e in ((dx,vx,ex),(dy,vy,ey)):
        if abs(v)<1e-6:
            if abs(d)>e:return False
        else:
            t1,t2=sorted(((-e-d)/v,(e-d)/v));enter=max(enter,t1);leave=min(leave,t2)
    return enter<=leave and leave>=0

def safe_gap(s):
    dx=max(0,abs(s["boss_cx"]-s["hero_cx"])-s["boss_ex"]-s["hero_ex"])
    dy=max(0,abs(s["boss_cy"]-s["hero_cy"])-s["boss_ey"]-s["hero_ey"])
    return math.hypot(dx,dy)

def outside_view(s):
    return (s["hero_cx"]+s["hero_ex"]<s["view_left"] or
            s["hero_cx"]-s["hero_ex"]>s["view_right"] or
            s["hero_cy"]+s["hero_ey"]<s["view_bottom"] or
            s["hero_cy"]-s["hero_ey"]>s["view_top"])

class DodgeReward:
    def __init__(self):
        self.pending=None;self.cooldown=-1;self.idle_seconds=0
        self.avoidances=0;self.near_seconds=0;self.far_seconds=0;self.total_seconds=0
    def score(self,old,s,dt,hurt):
        gap=safe_gap(s);threat=collision_threat(s)
        near=.5<=gap<=5
        self.total_seconds+=dt
        self.near_seconds+=dt if near else 0
        self.far_seconds+=dt if gap>8 else 0
        reward=.01*dt-5*hurt
        if near and not hurt:reward+=.04*dt
        if gap>8:reward-=.06*dt
        if s["grounded"] and abs(s["vx"])+abs(s["vy"])<.2 and not threat and gap>5:
            self.idle_seconds+=dt
        else:self.idle_seconds=0
        if self.idle_seconds>2:reward-=.08*dt
        if hurt:self.pending=None
        elif self.pending and s["time"]>=self.pending[0]:
            _,x,y=self.pending
            moved=math.hypot(s["hero_cx"]-x,s["hero_cy"]-y)>.3
            if not threat and moved:
                reward+=.3;self.avoidances+=1
            self.pending=None;self.cooldown=s["time"]+.8
        if not hurt and not self.pending and old["time"]>=self.cooldown and collision_threat(old):
            self.pending=(old["time"]+.35,old["hero_cx"],old["hero_cy"])
        return reward
    @property
    def near_fraction(self):return self.near_seconds/max(self.total_seconds,1e-6)
