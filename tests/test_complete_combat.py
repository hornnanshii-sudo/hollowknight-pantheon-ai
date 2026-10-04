import unittest
import numpy as np
import torch
import gymnasium as gym
from complete_combat_actions import capabilities,legal,encode,SIZES,ConditionalDistribution
from complete_combat_observation import CompletePolicy,CompleteFeatures,OBS_SIZE,FRAME_SIZE,CAP_KEYS
from combat_inactivity import Inactivity
from tests.test_defense_v2 import DefenseV2Tests

def state():
    s=DefenseV2Tests().state()
    s.update(soul=99,max_hp=9,boss_hp=100,boss_max_hp=100,boss_valid=1,spellQuake=0,
             hero_focusing=0,focus_elapsed=0,focus_drain_timer=0,focus_mp_amount=0,
             hero_casting=0,hero_castRecoiling=0,hero_attacking=0,hero_preventDash=0,hasShadowDash=1,
             can_jump=1,can_dash=1,can_attack=1,can_charge=1,can_cast=1,charge_ready=0,input_mask=0,
             fireballLevel=2,quakeLevel=2,screamLevel=2,equippedCharm_33=0,
             nailChargeTimer=0,nailChargeTime=1.35,hero_nailCharging=0,hero_nailArt_active=0,hero_recoiling=0,
             damage_dealt=0,hero_healed=0,charge_progress=0,hasNailArt=1,hasDashSlash=1,
             hasUpwardSlash=1,hasCyclone=1,airDashed=0)
    return s

class CompleteActionsTests(unittest.TestCase):
    def test_combined_air_up_down_attacks_and_hold_release(self):
        c=capabilities(state(),True)
        for aim in (0,1,2):
            action=[0,2,aim,2,1,0]
            self.assertTrue(legal(c,action))
            mask,pulse=encode(action);self.assertTrue(mask&2 and mask&4 and mask&8)
            self.assertEqual(pulse,12)
        self.assertEqual(encode([0,0,0,0,0,0]),(0,0))
        self.assertEqual(encode([0,0,0,1,2,0]),(12,0))
    def test_cyclone_extension_uses_native_button_repeat(self):
        s=state();s.update(can_attack=0,nail_art_state='Cyclone Spin')
        self.assertTrue(legal(capabilities(s,True),[0,0,0,0,1,0]))
        s['nail_art_state']='Cyclone End'
        self.assertFalse(legal(capabilities(s,True),[0,0,0,0,1,0]))
    def test_resource_and_cooldown_masks(self):
        s=state();s.update(soul=0,can_dash=0,can_attack=0,can_jump=0)
        c=capabilities(s,True)
        self.assertFalse(legal(c,[1,0,0,0,0,0]))
        self.assertFalse(legal(c,[0,0,0,2,0,0]))
        self.assertFalse(legal(c,[0,0,0,0,1,0]))
        self.assertFalse(legal(c,[0,0,0,0,0,1]))
        self.assertTrue(legal(c,[0,0,0,0,0,0]))
    def test_spells_force_direction_and_focus_blocks_movement(self):
        s=state();s['hp']=6;c=capabilities(s,True)
        self.assertTrue(legal(c,[1,1,0,0,0,0]))
        self.assertTrue(legal(c,[2,1,1,0,0,0]))
        self.assertTrue(legal(c,[3,2,2,0,0,0]))
        self.assertFalse(legal(c,[1,1,1,0,0,0]))
        self.assertTrue(legal(c,[4,0,0,0,0,0]))
        self.assertFalse(legal(c,[4,1,0,0,0,0]))
        s['input_mask']=8
        self.assertFalse(legal(capabilities(s,True),[4,0,0,0,0,0]))
    def test_charge_hold_survives_initial_nail_recovery(self):
        s=state();s.update(input_mask=8,can_charge=0,can_attack=0)
        self.assertTrue(legal(capabilities(s,True),[0,0,0,0,2,0]))
        s['input_mask']=0
        self.assertFalse(legal(capabilities(s,True),[0,0,0,0,2,0]))
    def test_basic_stage_cannot_cast_charge_or_heal(self):
        c=capabilities(state(),False)
        self.assertFalse(legal(c,[1,0,0,0,0,0]))
        self.assertFalse(legal(c,[0,0,0,0,2,0]))
    def test_sampling_and_training_use_same_conditional_probability(self):
        policy=CompletePolicy(gym.spaces.Box(-5,5,(OBS_SIZE,),np.float32),gym.spaces.MultiDiscrete(SIZES),lambda _:3e-4,net_arch=dict(pi=[128,128],vf=[128,128]))
        f=CompleteFeatures().frame(state(),120,120,None,0,'full',0)
        obs=torch.tensor(np.tile(f,6)[None,:]).repeat(64,1)
        with torch.no_grad():
            actions,values,log=policy(obs)
            values2,log2,entropy=policy.evaluate_actions(obs,actions)
        torch.testing.assert_close(log,log2);torch.testing.assert_close(values,values2)
        self.assertTrue(torch.isfinite(entropy).all())
        for action in actions.numpy():self.assertTrue(legal(capabilities(state(),True),action))
    def test_idle_has_cost_but_real_damage_is_exempt(self):
        s=state();idle=Inactivity();cost=0
        for i in range(200):cost+=sum(idle.score(s,s,.08).values())
        self.assertLess(cost,0);self.assertGreater(idle.idle_seconds,10)
        progress=Inactivity();cost=0
        for i in range(200):
            new=dict(s,damage_dealt=s['damage_dealt']+(1 if i%10==0 else 0))
            cost+=sum(progress.score(s,new,.08).values());s=new
        self.assertEqual(cost,0)
    def test_focus_and_charge_spam_cannot_exempt_forever(self):
        s=state();s.update(hero_focusing=1);r=Inactivity();cost=0
        for i in range(200):cost+=sum(r.score(s,s,.08).values())
        self.assertLess(cost,0)
    def test_movement_without_progress_is_not_rewarded(self):
        r=Inactivity();s=state();cost=0
        for i in range(300):
            new=dict(s,hero_cx=i*.1)
            cost+=sum(r.score(s,new,.08).values());s=new
        self.assertLess(cost,0);self.assertEqual(r.idle_seconds,0)

if __name__=='__main__':unittest.main()
