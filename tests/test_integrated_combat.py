import unittest,json,sys,tempfile,zipfile
from pathlib import Path
from unittest.mock import patch
import tests.test_defense_v2 as fixtures
from integrated_combat_core import CombatReward,transition

class IntegratedRewardTests(unittest.TestCase):
    def state(self):
        s=fixtures.DefenseV2Tests().state();s.update(boss_hp=100,boss_max_hp=100,damage_dealt=0)
        return s
    def test_idle_flee_has_no_positive_reward(self):
        old=self.state();r=CombatReward();new=dict(old,time=120,hero_cx=-10)
        total=r.score(old,new,120,0)+r.terminal(False,9,0,True,True)
        self.assertLess(total,0)
        self.assertNotIn('survival',r.breakdown)
    def test_damage_requires_real_health_loss_and_counter(self):
        s=self.state();r=CombatReward();r.score(s,dict(s,boss_hp=90,damage_dealt=10),.08,0)
        self.assertEqual(r.breakdown['boss_damage'],1)
        r.score(s,dict(s,boss_hp=0,damage_dealt=0),.08,0)
        self.assertEqual(r.breakdown['boss_damage'],0)
    def test_overkill_capped_and_clean_win_preferred(self):
        s=self.state();r=CombatReward();r.score(s,dict(s,boss_hp=-10,damage_dealt=110),.08,0)
        self.assertEqual(r.breakdown['boss_damage'],10)
        clean=r.terminal(True,9,0,True);hurt=r.terminal(True,8,1,True)
        self.assertGreater(clean,hurt)
    def test_winning_trajectory_beats_camping(self):
        s=self.state();r=CombatReward()
        win=r.score(s,dict(s,boss_hp=0,damage_dealt=100),40,2)+r.terminal(True,7,2,True)
        r=CombatReward();camp=r.score(s,dict(s,time=120),120,0)+r.terminal(False,9,0,True,True)
        self.assertGreater(win,camp+10)
    def test_budget_forces_progression_without_mastery(self):
        result=dict(episodes=30,out_of_view=0,watchdog_timeout=0,success_rate=0,winning_hp_lost=9)
        self.assertEqual(transition('basic',100000,result,0),(True,'budget_unmastered',0))
        self.assertFalse(transition('full',300000,result,0)[0])
    def test_leaving_view_cannot_be_cheap_early_exit(self):
        s=self.state();r=CombatReward();value=r.score(s,dict(s,hero_cx=-100),.08,0)
        self.assertLessEqual(value,-12)
    def test_whole_pipeline_reaches_300k_with_all_phases(self):
        import integrated_combat_pipeline as pipeline
        result=dict(episodes=30,out_of_view=0,watchdog_timeout=0,success_rate=0,winning_hp_lost=9)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            def fake_run(args,log):
                name=args[args.index('--run-name')+1];out=root/'artifacts'/name;out.mkdir(parents=True,exist_ok=True)
                if '--eval' in args:(out/'evaluation.json').write_text(json.dumps({'episodes':[]}))
                else:
                    count=pipeline.steps(Path(args[args.index('--checkpoint')+1])) if '--checkpoint' in args else 0
                    count+=int(args[args.index('--steps')+1])
                    with zipfile.ZipFile(out/'latest.zip','w') as z:z.writestr('data',json.dumps({'num_timesteps':count}))
            with patch.object(pipeline,'ROOT',root),patch.object(pipeline,'OUT',root/'pipeline'),patch.object(pipeline,'run',fake_run),patch.object(pipeline,'summary',lambda _:result),patch.object(sys,'argv',['pipeline']):
                pipeline.main()
            state=json.loads((root/'pipeline/status.json').read_text())
            self.assertEqual(state['steps'],300000)
            self.assertEqual(state['phase'],'complete')
            self.assertEqual(len(state['completed']),30)
            self.assertEqual([t['steps'] for t in state['transitions']],[100000,200000])

if __name__=='__main__':unittest.main()
