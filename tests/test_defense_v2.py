import unittest,numpy as np
from defense_v2_core import ACTIONS,Features,FRAME_SIZE,Reward,ending
from defense_v2_pipeline import mastered,wilson
from combat_actions_v2 import COMBAT_ACTIONS_V2

class DefenseV2Tests(unittest.TestCase):
    def state(self):
        keys=('x','y','vx','vy','bx','by','bvx','bvy','hero_cx','hero_cy','boss_cx','boss_cy','facing_right','doubleJumped','touchingWallL','touchingWallR','wallSliding','dashing','jumping','doubleJumping','invulnerable','shadowDashing','shadowDashTimer','dashCooldownTimer','attack_cooldown','boss_phase_age')
        s={k:0 for k in keys};s.update(hp=9,grounded=1,hero_ex=.5,hero_ey=.5,boss_ex=.5,boss_ey=.5,boss_cx=3,boss_phase='Buzz',boss_phase_names=['Buzz','Fly'],terrain_valid=True,terrain_distances=[1]*8,terrain_hits=[1]*8,view_left=-10,view_right=10,view_bottom=-5,view_top=10,floor_distances=[1]*3,hazards=[],hazard_count=0,time=0,boss_phase_event=1);return s
    def hazard(self,key,x=3):return dict(id=key,cx=x,cy=0,ex=.5,ey=.5,vx=-10,vy=0,damage=1,shadow_hazard=0,kind=1,velocity_valid=1)
    def test_task_success_terminates_watchdog_truncates(self):
        self.assertEqual(ending(0,False,False,True,False),(True,False,True));self.assertEqual(ending(0,False,False,False,True),(False,True,False));self.assertEqual(ending(1,False,False,True,False),(True,False,False))
    def test_hold_jump_and_focus_are_reachable(self):
        self.assertIn((4,0),ACTIONS);self.assertIn((4,4),ACTIONS);self.assertIn((0,0),ACTIONS)
        self.assertTrue(any(mask&256 for _,mask,_ in COMBAT_ACTIONS_V2))
        self.assertTrue(all(mask&~23==0 for mask,_ in ACTIONS))
    def test_features_stable_identity_and_phase(self):
        s=self.state();f=Features();s['hazards']=[self.hazard(1),self.hazard(2,4)];s['hazard_count']=2
        a=f.frame(s,10,10,None,.08);self.assertEqual(a.shape,(FRAME_SIZE,));self.assertTrue(np.isfinite(a).all());s['hazards'].reverse();b=f.frame(s,10,10,None,.08);np.testing.assert_equal(a,b)
    def test_same_threat_cannot_pay_twice(self):
        old=self.state();old['hazards']=[self.hazard(1)];new=dict(old,time=.1);r=Reward();r.score(old,new,.1,0)
        clear=dict(new,time=.4,hero_cy=3);r.score(new,clear,.3,0);self.assertEqual(r.avoidances,1)
        r.score(old,new,.1,0);r.score(new,clear,.3,0);self.assertEqual(r.avoidances,1)
    def test_no_reward_for_stationary_location_and_no_reward_after_hurt(self):
        s=self.state();r=Reward();r.score(s,dict(s,time=.08),.08,0);self.assertEqual(r.breakdown['engagement'],0)
        s['hazards']=[self.hazard(1)];r.score(s,dict(s,time=.1),.1,0);r.score(s,dict(s,time=.4,hero_cy=3),.3,1);self.assertEqual(r.avoidances,0)
    def test_mastery_requires_multiple_successes_and_engagement(self):
        self.assertLess(wilson(1,1)[0],.6);self.assertTrue(mastered(dict(success_ci95=wilson(27,30),near_fraction=.4,out_of_view=0,watchdog_timeout=0)));self.assertFalse(mastered(dict(success_ci95=wilson(27,30),near_fraction=.1,out_of_view=0,watchdog_timeout=0)))
if __name__=='__main__':unittest.main()
