import unittest
import tests.test_defense_v2 as fixture
from engaged_defense import EngagedReward

class EngagementTests(unittest.TestCase):
    def state(self):
        s=fixture.DefenseV2Tests().state()
        s.update(boss_cx=12,boss_cy=0,terrain_distances=[20,.2,5,20,20,20,20,20],terrain_hits=[0,1,1,0,0,0,0,0])
        return s
    def test_long_wall_escape_penalized_after_grace(self):
        s=self.state();r=EngagedReward()
        for i in range(40):
            new=dict(s,time=(i+1)*.08);r.score(s,new,.08,0);s=new
        self.assertLess(r.breakdown['disengagement'],0)
        self.assertLess(r.breakdown['corner_camping'],0)
        self.assertEqual(r.breakdown['survival'],0)
        self.assertFalse(r.qualified_engagement)
    def test_short_retreat_not_penalized(self):
        s=self.state();r=EngagedReward();r.score(s,dict(s,time=.08),.08,0)
        self.assertEqual(r.breakdown['disengagement'],0)
        self.assertEqual(r.breakdown['corner_camping'],0)
    def test_jump_near_boss_not_penalized(self):
        s=self.state();s['boss_cx']=3;r=EngagedReward()
        for i in range(50):
            new=dict(s,time=(i+1)*.08);r.score(s,new,.08,0);s=new
        self.assertEqual(r.breakdown['corner_camping'],0)
        self.assertTrue(r.qualified_engagement)

if __name__=='__main__':unittest.main()
