import unittest
import numpy as np
import torch
import gymnasium as gym
from integrated_observation import CombatFeatures,CombatPolicy,transfer_four_frames,OBS_SIZE,FRAME_SIZE
from single_boss_core import CurriculumPolicy
from combat_start_profiles import TRAIN,VALIDATION,CONFIRMATION
from tests.test_defense_v2 import DefenseV2Tests

class SixFrameTests(unittest.TestCase):
    def policy(self,cls,size):
        return cls(gym.spaces.Box(-5,5,(size,),np.float32),gym.spaces.Discrete(25),lambda _:3e-4,
                   net_arch=dict(pi=[128,128],vf=[128,128]))
    def test_migration_preserves_probabilities_and_values(self):
        torch.manual_seed(42)
        old=self.policy(CurriculumPolicy,836);new=self.policy(CombatPolicy,OBS_SIZE)
        state=new.state_dict();transfer_four_frames(old.state_dict(),state);new.load_state_dict(state)
        a=torch.randn(5,836);b=torch.randn(5,OBS_SIZE)
        for f in range(4):b[:,(f+2)*FRAME_SIZE:(f+2)*FRAME_SIZE+209]=a[:,f*209:(f+1)*209]
        # Check each task mask, including heal and full, at the newest frame.
        a[:,3*209+179:3*209+184]=torch.eye(5)
        b[:,5*220+179:5*220+184]=torch.eye(5)
        with torch.no_grad():
            torch.testing.assert_close(old.get_distribution(a).distribution.probs,new.get_distribution(b).distribution.probs)
            torch.testing.assert_close(old.predict_values(a),new.predict_values(b))
        self.assertEqual(new.get_distribution(b).distribution.probs[0,18:].sum().item(),0)
        self.assertEqual(new.get_distribution(b).distribution.probs[1,21:].sum().item(),0)
        self.assertGreater(new.get_distribution(b).distribution.probs[4,24].item(),0)
    def test_new_combat_state_visible(self):
        s=DefenseV2Tests().state()
        s.update(soul=66,spellQuake=0,boss_hp=50,boss_max_hp=100,boss_valid=1,
                 hero_focusing=1,focus_elapsed=.75,focus_drain_timer=.2,focus_mp_amount=11,
                 hero_casting=0,hero_castRecoiling=0,hero_attacking=0,hero_preventDash=1,hasShadowDash=1)
        f=CombatFeatures().frame(s,120,120,None,0,'full',0)
        self.assertEqual(f.shape,(220,));self.assertEqual(f[209],.5)
        self.assertEqual(f[211],1);self.assertEqual(f[212],.5)
        self.assertTrue(np.isfinite(f).all())
    def test_start_banks_are_disjoint(self):
        self.assertFalse(set(TRAIN)&set(VALIDATION))
        self.assertFalse(set(TRAIN)&set(CONFIRMATION))
        self.assertFalse(set(VALIDATION)&set(CONFIRMATION))

if __name__=='__main__':unittest.main()
