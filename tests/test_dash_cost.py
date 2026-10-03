import unittest
import tests.test_defense_v2 as fixtures
from engaged_defense import EngagedReward

class DashCostTests(unittest.TestCase):
    def state(self):return fixtures.DefenseV2Tests().state()
    def test_ordinary_unnecessary_dash_cost_once(self):
        old=self.state();new=dict(old,time=.08,dashing=1)
        r=EngagedReward();r.score(old,new,.08,0,16)
        self.assertEqual(r.breakdown['unnecessary_dash'],-.03)
        r.score(new,dict(new,time=.16),.08,0,16)
        self.assertEqual(r.breakdown['unnecessary_dash'],0)
        self.assertEqual(r.dash_count,1)
    def test_shadow_cost_and_failed_button_not_costed(self):
        old=self.state();r=EngagedReward()
        r.score(old,dict(old,time=.08,dashing=1,shadowDashing=1),.08,0,16)
        self.assertEqual(r.breakdown['unnecessary_dash'],-.05)
        r=EngagedReward();r.score(old,dict(old,time=.08),.08,0,16)
        self.assertEqual(r.dash_count,0)
    def test_far_approach_not_penalized(self):
        old=self.state();old['boss_cx']=12
        new=dict(old,time=.08,hero_cx=1,dashing=1)
        r=EngagedReward();r.score(old,new,.08,0,18)
        self.assertEqual(r.breakdown['unnecessary_dash'],0)
        self.assertEqual(r.approach_dashes,1)
    def test_threat_escape_not_penalized(self):
        old=self.state();old['hazards']=[fixtures.DefenseV2Tests().hazard(1)]
        new=dict(old,time=.08,dashing=1,hero_cx=-1)
        r=EngagedReward();r.score(old,new,.08,0,17)
        self.assertEqual(r.breakdown['unnecessary_dash'],0)
        self.assertEqual(r.threat_dashes,1)
    def test_followup_hurt_counted_once(self):
        old=self.state();new=dict(old,time=.08,dashing=1)
        r=EngagedReward();r.score(old,new,.08,0,16)
        r.score(new,dict(new,time=.16,hp=8),.08,1,0)
        r.score(new,dict(new,time=.24,hp=7),.08,1,0)
        self.assertEqual(r.dash_followup_hurts,1)

if __name__=='__main__':unittest.main()
