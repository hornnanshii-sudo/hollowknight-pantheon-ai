import unittest
from tests.test_defense_v2 import DefenseV2Tests
from defense_v3_core import Reward, ending

class ContinuousDefenseTests(unittest.TestCase):
    def setUp(self):self.fixture=DefenseV2Tests()
    def test_hurt_does_not_end_but_death_does(self):
        self.assertEqual(ending(1,False,False,False,False),(False,False,False))
        self.assertEqual(ending(1,True,False,False,False),(True,False,False))
    def test_terminal_prefers_flawless_and_death_penalty(self):
        r=Reward();r.score(self.fixture.state(),self.fixture.state(),.08,0)
        self.assertEqual(r.terminal(True,9,0,True),10)
        self.assertAlmostEqual(r.terminal(True,8,1,True),16/9)
        self.assertEqual(r.terminal(False,0,9,True),-5)
    def test_dash_into_threat_extra_penalty_only_when_executed(self):
        s=self.fixture.state();s['hazards']=[self.fixture.hazard(1)];s['facing_right']=1
        r=Reward();r.score(s,dict(s,time=.08,dashing=1,hp=8),.08,1,16)
        self.assertEqual(r.breakdown['dash_damage'],-2)
        r=Reward();r.score(s,dict(s,time=.08,dashing=0,hp=8),.08,1,16)
        self.assertEqual(r.breakdown['dash_damage'],0)
    def test_avoidance_waits_and_does_not_pay_after_hurt(self):
        s=self.fixture.state();s['hazards']=[self.fixture.hazard(1)]
        r=Reward();r.score(s,dict(s,time=.08),.08,0)
        safe=dict(s,time=.4,hero_cy=3)
        r.score(s,safe,.32,0);self.assertEqual(r.avoidances,0)
        r.score(safe,dict(safe,time=.56),.16,0);self.assertEqual(r.avoidances,1)
        r=Reward();r.score(s,dict(s,time=.08),.08,0)
        r.score(s,safe,.32,1);r.score(safe,dict(safe,time=.56),.16,0)
        self.assertEqual(r.avoidances,0)
    def test_hurt_immunity_excluded_shadow_allowed(self):
        s=self.fixture.state();s.update(invulnerable=1,shadowDashing=0)
        self.assertTrue(Reward.damaging_invulnerability(s))
        s['shadowDashing']=1;self.assertFalse(Reward.damaging_invulnerability(s))

if __name__=='__main__':unittest.main()
