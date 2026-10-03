import unittest
from dodge_reward import DodgeReward,collision_threat,outside_view

def s(x=0,y=0,bx=4,by=0,bvx=-10,time=0):
    return dict(hero_cx=x,hero_cy=y,boss_cx=bx,boss_cy=by,hero_ex=.5,hero_ey=.5,boss_ex=.5,boss_ey=.5,vx=0,vy=0,bvx=bvx,bvy=0,grounded=1,time=time,view_left=-10,view_right=10,view_bottom=-5,view_top=10)
class ShapingTests(unittest.TestCase):
    def test_approach_but_not_retreat_is_threat(self):
        self.assertTrue(collision_threat(s()))
        self.assertFalse(collision_threat(s(bvx=10)))
        self.assertFalse(collision_threat(s(by=5)))
    def test_reward_requires_threat_movement_and_no_hurt(self):
        r=DodgeReward();r.score(s(),s(bx=3.4,time=.06),.06,0)
        r.score(s(bx=3.4,time=.06),s(y=3,bx=0,time=.4),.34,0)
        self.assertEqual(r.avoidances,1)
        r=DodgeReward();r.score(s(),s(bx=3.4,time=.06),.06,0)
        r.score(s(bx=3.4,time=.06),s(y=3,bx=0,time=.4),.34,1)
        self.assertEqual(r.avoidances,0)
    def test_far_camping_not_profitable(self):
        r=DodgeReward();self.assertLess(r.score(s(bx=20,bvx=0),s(bx=20,bvx=0,time=3),3,0),0)
        self.assertEqual(r.near_fraction,0)
    def test_only_fully_off_view_is_outside(self):
        self.assertFalse(outside_view(s(x=10.2)))
        self.assertTrue(outside_view(s(x=11)))
