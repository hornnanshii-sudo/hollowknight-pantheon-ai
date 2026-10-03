import unittest
import numpy as np
import torch as th
from single_boss_core import ACTIONS,FRAME_SIZE,OBS_SIZE,CurriculumPolicy,allowed,gate
from single_boss_pipeline import progression
import gymnasium as gym

class SingleBossTests(unittest.TestCase):
    def test_fixed_masks(self):
        self.assertEqual(len(ACTIONS),25)
        self.assertEqual(allowed('defense').sum(),18)
        self.assertEqual(allowed('nail').sum(),21)
        self.assertEqual(allowed('dive').sum(),24)
        self.assertEqual(allowed('heal').sum(),25)
    def test_unmastered_budget_advances(self):
        self.assertEqual(progression('defense',40000,False,0),(True,'budget_unmastered',0))
        self.assertFalse(progression('defense',30000,False,0)[0])
        self.assertEqual(progression('nail',10000,True,1),(True,'mastery',2))
        self.assertFalse(progression('full',100000,False,0)[0])
    def test_ppo_mask_in_training_and_evaluation(self):
        policy=CurriculumPolicy(gym.spaces.Box(-np.inf,np.inf,(OBS_SIZE,),np.float32),gym.spaces.Discrete(25),lambda _:3e-4,net_arch=dict(pi=[128,128],vf=[128,128]))
        obs=th.zeros((4,OBS_SIZE));obs[:,3*FRAME_SIZE+179]=1
        actions,values,log=policy(obs)
        self.assertTrue(bool(th.all(actions<18)))
        dist=policy.get_distribution(obs)
        self.assertTrue(bool(th.all(dist.distribution.probs[:,18:]==0)))
        _,evaluated,_=policy.evaluate_actions(obs,actions)
        th.testing.assert_close(log,evaluated)
    def test_empty_evaluation_cannot_pass_gate(self):
        self.assertFalse(gate('defense',dict(episodes=1,out_of_view=0,watchdog_timeout=0)))

if __name__=='__main__':unittest.main()
