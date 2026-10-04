import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import integrated_combat_pipeline as pipeline

class ExecutionTests(unittest.TestCase):
    def test_skill_gate_requires_30_actual_successes_per_skill(self):
        state={'skill_history':{'heal':[True]*29,'dive':[True]*30}}
        self.assertFalse(pipeline.skills_mastered(state))
        state['skill_history']['heal']=[True]*24+[False]*6
        self.assertTrue(pipeline.skills_mastered(state))
        state['skill_history']['dive']=[True]*23+[False]*7
        self.assertFalse(pipeline.skills_mastered(state))
    def test_assisted_runs_cannot_be_normal_evaluation(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'evaluation.json'
            path.write_text(json.dumps({'episodes':[dict(normal_start=False,start_hp=6,start_soul=99)]}))
            with self.assertRaises(RuntimeError):pipeline.normal_episodes(path,1)
    def test_best_keeps_stronger_model_without_rewinding_latest(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'latest.zip';source.write_bytes(b'first')
            source.with_name('config.json').write_text('{}')
            state=dict(task='basic',checkpoint=str(source),steps=10000)
            result=dict(success_rate=.8,flawless_rate=.2,winning_hp_lost=2,winning_fight_seconds=20)
            with patch.object(pipeline,'OUT',root):
                pipeline.retain_best(state,result)
                source.write_bytes(b'second');state['steps']=20000
                pipeline.retain_best(state,dict(result,success_rate=.7))
                self.assertEqual((root/'best-basic/model.zip').read_bytes(),b'first')
                self.assertEqual(source.read_bytes(),b'second')
                pipeline.retain_best(state,dict(result,flawless_rate=.5))
                self.assertEqual((root/'best-basic/model.zip').read_bytes(),b'second')
                self.assertEqual(state['checkpoint'],str(source))

if __name__=='__main__':unittest.main()
