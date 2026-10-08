import copy
import json
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
import numpy as np
import gymnasium as gym
from sb3_contrib import RecurrentPPO
import hornet_core as h
from hornet_train import Policy, preflight
from hornet_pilot import PilotLedger, suspected_completion
from hornet_long import LongLedger
from hornet_logging import TracePolicy
from hornet_v2 import course_profile,select_course

class ContractTests(unittest.TestCase):
    def test_reset_rejects_previous_scene_and_locked_controls(self):
        ready=dict(scene='GG_Hornet_1',body_type=0,grounded=1,invulnerable=0,can_jump=1,can_attack=1,can_dash=1,hp=9,soul=0,hasShadowDash=0,hasDoubleJump=0,hornet=dict(epoch=1,valid=True,opening_applied=True,hurt=0,damage=0,nail_damage=9))
        locked=copy.deepcopy(ready);locked['hornet']['epoch']=2;locked['can_attack']=0
        new=copy.deepcopy(ready);new['hornet']['epoch']=2
        with patch.object(h,'request',side_effect=[ready,ready,ready,locked,new,{},new]) as req,patch.object(h.time,'sleep'):
            self.assertEqual(h.reset()['hornet']['epoch'],2)
            self.assertEqual(req.call_count,7)
    def test_course_fades_and_selection_rejects_worse_hurt(self):
        import random
        rng=random.Random(42)
        self.assertEqual({course_profile(40000,rng) for _ in range(100)},{'native'})
        self.assertEqual({course_profile(0,rng) for _ in range(100)},{'native','near-left','near-right'})
        a=dict(mean_damage=10,mean_hurt=3,hit_episodes=2)
        self.assertFalse(select_course(a,dict(mean_damage=20,mean_hurt=4,hit_episodes=3)))
        self.assertTrue(select_course(a,dict(mean_damage=20,mean_hurt=3,hit_episodes=3)))
    def test_long_continuation_cannot_reset_total_budget(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'ledger.json';l=LongLedger(p)
            l.data['actual']=199999;l.data['stage_actual'][0]=199999
            l.reserve(True);l.settle()
            self.assertEqual(h.Ledger(p).data['actual'],200000)
            with self.assertRaises(RuntimeError):l.reserve(True)
            l.reserve(False);l.settle()
            self.assertEqual(l.data['actual'],200000)
    def test_transport_reuses_connection(self):
        h.disconnect()
        sock=MagicMock();sock.makefile.return_value.readline.return_value=b'{"ok": true}\n'
        with patch.object(h.socket,'create_connection',return_value=sock) as connect:
            self.assertTrue(h.request('state')['ok']);h.request('state')
            self.assertEqual(connect.call_count,1);self.assertEqual(sock.sendall.call_count,2)
        h.disconnect()
    def test_pilot_budget_uses_total_ledger(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'ledger.json';l=PilotLedger(p)
            l.data['actual']=4999;l.data['stage_actual'][0]=4999
            l.reserve(True);l.settle()
            with self.assertRaises(RuntimeError):l.reserve(True)
            self.assertEqual(h.Ledger(p).data['actual'],5000)
            l.data['note']='中文故障记录';h.write_json(p,l.data)
            self.assertEqual(h.Ledger(p).data['note'],'中文故障记录')

    def test_pilot_stops_before_unverified_terminal_is_learned(self):
        s=dict(scene='GG_Hornet_1',hornet=dict(valid=True,hp=9))
        self.assertFalse(suspected_completion(s))
        s['hornet']['native_death']=True
        self.assertTrue(suspected_completion(s))
    def test_missing_acceptance_never_starts_training(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)
            with self.assertRaises(RuntimeError):preflight(out)
            report=json.loads((out/'startup-check.json').read_text())
            self.assertFalse(report['passed']);self.assertFalse(report['model_created'])
            self.assertFalse((out/'ledger.json').exists())
    def test_corrupted_event_or_timing_is_rejected(self):
        old=dict(scene='GG_Hornet_1',time=1.,physics_ticks=50,hp=9,hornet=dict(epoch=1,actor=2,damage=0,hurt=0,hits=0,attacks=0,hp=900,max_hp=900))
        new=dict(scene='GG_Hornet_1',time=1.04,physics_ticks=52,hp=8,hazard_count=0,hero_healed=0,soul=11,hornet=dict(epoch=1,actor=2,damage=9,hurt=1,hits=1,attacks=1,hp=891,max_hp=900,valid=True,events=[dict(kind='damage',amount=9),dict(kind='hurt',amount=1)]))
        h.validate(old,new)
        bad=copy.deepcopy(new);bad['hornet']['events']=[]
        with self.assertRaises(RuntimeError):h.validate(old,bad)
        bad=copy.deepcopy(new);bad['physics_ticks']=53
        with self.assertRaises(RuntimeError):h.validate(old,bad)

    def test_budget_and_uncertain_execution(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'ledger.json';l=h.Ledger(p)
            l.reserve(True)
            with self.assertRaises(RuntimeError):h.Ledger(p)
            l.settle();self.assertEqual(l.data['actual'],1)
            l.reserve(False);l.settle();self.assertEqual(l.data['actual'],1)
            self.assertEqual(l.data['evaluation'],1)
            l.data['stage_actual'][0]=20000
            with self.assertRaises(RuntimeError):l.reserve(True)

    def test_action_semantics_and_native_masks(self):
        s=dict(can_jump=1,can_dash=1,can_attack=1,input_mask=0)
        self.assertEqual(h.buttons([1,1,3,0],s),(1|4|8|32,8))
        self.assertEqual(h.buttons([2,0,2,1],s),(2|8|128|16,8|16))
        s['can_attack']=0
        with self.assertRaises(ValueError):h.buttons([0,0,1,0],s)
        s['can_jump']=0;s['input_mask']=4
        self.assertEqual(h.buttons([0,1,0,0],s),(4,0))

    def test_victory_requires_native_completion(self):
        s=dict(hp=1,hornet=dict(native_death=True,complete=False,bosses_dead=True))
        self.assertFalse(h.won(s));s['hornet']['complete']=True
        self.assertTrue(h.won(s));s['hp']=0;self.assertFalse(h.won(s))

    def test_reward_keeps_simultaneous_events(self):
        a=dict(hornet=dict(damage=0,hurt=0))
        b=dict(hp=8,hornet=dict(damage=9,hurt=1,native_death=False,complete=False,bosses_dead=False))
        parts=h.reward(a,b,dict(hurt=2))
        self.assertEqual(parts,dict(damage=1,hurt=-2))

    def test_recurrent_mask_survives_real_ppo_update(self):
        class Fake(gym.Env):
            action_space=gym.spaces.MultiDiscrete(h.HEADS)
            observation_space=gym.spaces.Box(-5,5,(20,),dtype=np.float32)
            def reset(self,seed=None,options=None):
                super().reset(seed=seed);self.i=0
                return self.obs(),{}
            def obs(self):
                v=np.zeros(20,np.float32);v[-11:]=[1,1,1,1,0,1,0,0,0,1,0];return v
            def step(self,a):
                assert a[1]==a[2]==a[3]==0, a
                self.i+=1
                return self.obs(),float(a[0]==2),self.i==7,False,{}
        model=RecurrentPPO(TracePolicy,Fake(),n_steps=16,batch_size=8,n_epochs=1,device='cpu',policy_kwargs=dict(lstm_hidden_size=8,net_arch=dict(pi=[8],vf=[8])))
        model.learn(32)
        from sb3_contrib.common.recurrent.buffers import RecurrentRolloutBuffer
        model.n_steps=17
        model.batch_size=17
        model.rollout_buffer=RecurrentRolloutBuffer(17,model.observation_space,model.action_space,(17,1,1,8),device=model.device,gamma=model.gamma,gae_lambda=model.gae_lambda,n_envs=1)
        model.learn(17,reset_num_timesteps=False)
        self.assertEqual(model.num_timesteps,49)
        for head,n in zip(model.policy.last_decision['probabilities'],h.HEADS):
            self.assertEqual(len(head[0]),n);self.assertAlmostEqual(sum(head[0]),1,places=5)
        self.assertTrue(all(np.isfinite(p.detach().numpy()).all() for p in model.policy.parameters()))

if __name__=='__main__':unittest.main()
