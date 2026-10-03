"""Result-first rewards for integrated single-boss combat."""
import math
from defense_v3_core import collision_time
from dodge_reward import safe_gap,outside_view
from single_boss_core import CurriculumFeatures

REVISION='integrated-combat-v1'
PHASES=('basic','mixed','full')
TOTAL_STEPS=300000
PHASE_CAPS={'basic':100000,'mixed':100000,'full':300000}

class RelativeFeatures(CurriculumFeatures):
    def frame(self,s,*args):
        f=super().frame(s,*args)
        # Replace absolute world positions with arena-relative coordinates.
        width=max(s['view_right']-s['view_left'],1.)
        height=max(s['view_top']-s['view_bottom'],1.)
        f[0]=(s['hero_cx']-(s['view_left']+s['view_right'])/2)/width
        f[1]=(s['hero_cy']-s['view_bottom'])/height
        return f

class CombatReward:
    def __init__(self):
        self.elapsed=0.;self.near_seconds=0.;self.far_seconds=0.;self.first_hurt=None
        self.avoidances=0;self.dash_hurts=0;self.disengaged_seconds=0.;self.corner_seconds=0.
        self.dash_count=0;self.unnecessary_dashes=0;self.approach_dashes=0;self.threat_dashes=0
        self.dash_followup_hurts=0;self.followup=None;self.breakdown={}
    @property
    def near_fraction(self):return self.near_seconds/max(self.elapsed,1e-6)
    @property
    def qualified_engagement(self):return self.near_fraction>=.35
    def score(self,old,s,dt,hurt,action_mask=0):
        self.elapsed+=dt;gap=safe_gap(s)
        self.near_seconds+=dt if .5<=gap<=5 else 0
        self.far_seconds+=dt if gap>8 else 0
        self.disengaged_seconds+=dt if gap>6 else 0
        distances=s['terrain_distances'];hits=s['terrain_hits']
        wall=any(hits[i] and distances[i]<1.2 for i in (0,1))
        high=bool(hits[2] and distances[2]>3)
        ceiling=bool(hits[3] and distances[3]<1.2)
        self.corner_seconds+=dt if gap>5 and (wall and high or ceiling) else 0.
        if hurt and self.first_hurt is None:self.first_hurt=self.elapsed
        started=bool(action_mask&16 and not(old['dashing'] or old['shadowDashing']) and (s['dashing'] or s['shadowDashing']))
        cost=0.
        if started:
            self.dash_count+=1;self.followup=old['time']+.5
            threat=any(collision_time(old,h,.4) is not None or
                       (abs(h['cx']-old['hero_cx'])<h['ex']+old['hero_ex'] and abs(h['cy']-old['hero_cy'])<h['ey']+old['hero_ey']) for h in old['hazards'])
            approach=safe_gap(old)>5 and gap<safe_gap(old)-.2
            if threat:self.threat_dashes+=1
            elif approach:self.approach_dashes+=1
            else:
                self.unnecessary_dashes+=1;cost=-.005 if s['shadowDashing'] else -.003
        if self.followup is not None:
            if s['time']>self.followup:self.followup=None
            elif hurt:self.dash_followup_hurts+=1;self.followup=None
        # Reward true net Boss health depletion, clipped to prevent overkill
        # and missing/dead Boss telemetry from generating fabricated damage.
        depletion=max(0,old['boss_hp']-max(0,s['boss_hp'])) if old['boss_hp']>0 else 0
        observed=max(0,s['damage_dealt']-old['damage_dealt'])
        actual=min(depletion,observed)
        damage=10.*actual/max(old['boss_max_hp'],1)
        self.breakdown=dict(boss_damage=damage,damage=-float(hurt),time=-.01*dt,
                            unnecessary_dash=cost,outside=-12. if outside_view(s) else 0.,
                            success=0.,death=0.,timeout=0.)
        return sum(self.breakdown.values())
    def terminal(self,success,hp,hp_lost,terminated,timed_out=False):
        self.breakdown['success']=(10.+5.*max(0,hp)/9.+(5. if hp_lost==0 else 0.)) if success else 0.
        self.breakdown['death']=-3. if terminated and hp<=0 else 0.
        self.breakdown['timeout']=-2. if timed_out and not success and hp>0 else 0.
        return self.breakdown['success']+self.breakdown['death']+self.breakdown['timeout']

def transition(phase,spent,result,streak):
    passed=result['episodes']>=30 and result['out_of_view']==0 and result['watchdog_timeout']==0 and result['success_rate']>=.9 and result['winning_hp_lost']<=2
    streak=streak+1 if passed else 0
    advance=phase!='full' and (streak>=2 or spent>=PHASE_CAPS[phase])
    return advance,('mastery' if advance and streak>=2 else 'budget_unmastered' if advance else 'continue'),streak
