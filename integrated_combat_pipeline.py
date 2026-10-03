"""Persistent single-boss curriculum: 10k checks, bounded automatic progression."""
import argparse,json,subprocess,sys,time,zipfile
from pathlib import Path
from defense_v3_pipeline import summary as defense_summary
from integrated_combat_core import PHASES as TASKS,TOTAL_STEPS,PHASE_CAPS as CAPS,transition,REVISION
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'artifacts/integrated-combat-300k-pipeline'

def steps(path):return int(json.loads(zipfile.ZipFile(path).read('data'))['num_timesteps'])
def save(state):
    state.update(updated_at=time.strftime('%Y-%m-%d %H:%M:%S'),total_steps=TOTAL_STEPS,
                 steps_per_stage=10000,eval_episodes=30,horizon_seconds=120)
    OUT.mkdir(parents=True,exist_ok=True)
    tmp=OUT/'status.tmp';tmp.write_text(json.dumps(state,indent=2),encoding='utf-8');tmp.replace(OUT/'status.json')
def run(args,log):
    with log.open('w',encoding='utf-8') as f:
        subprocess.run([sys.executable,'-u',str(ROOT/'integrated_combat_train.py'),*args],cwd=ROOT,
                       stdout=f,stderr=subprocess.STDOUT,check=True,timeout=14400)
def summary(es):
    r=defense_summary(es)
    wins=[e for e in es if e['is_success']]
    r['winning_hp_lost']=sum(e['hp_lost'] for e in wins)/len(wins) if wins else 9.
    attempts=sum(e['dive_attempts'] for e in es)
    r['dive_effective_fraction']=sum(e['dive_effective'] for e in es)/max(attempts,1)
    attempts=sum(e['focus_attempts'] for e in es)
    r['unsafe_focus_fraction']=sum(e['unsafe_focus'] for e in es)/max(attempts,1)
    r['healing_completed']=sum(e['healing_completed'] for e in es)/len(es)
    for key in ('corner_seconds','disengaged_seconds','survived_120s'):
        r[key]=sum(e.get(key,0) for e in es)/len(es)
    dashes=sum(e.get('dash_count',0) for e in es)
    duration=sum(e['fight_seconds'] for e in es)
    r['dashes_per_minute']=60*dashes/max(duration,1e-6)
    r['unnecessary_dash_fraction']=sum(e.get('unnecessary_dashes',0) for e in es)/max(dashes,1)
    r['dash_followup_hurt_fraction']=sum(e.get('dash_followup_hurts',0) for e in es)/max(dashes,1)
    for key in ('dash_count','unnecessary_dashes','approach_dashes','threat_dashes','dash_followup_hurts'):
        r[key]=sum(e.get(key,0) for e in es)/len(es)
    return r


def main():
    p=argparse.ArgumentParser();p.add_argument('--resume',action='store_true');a=p.parse_args()
    if a.resume:
        state=json.loads((OUT/'status.json').read_text())
        if state['phase']=='complete':raise RuntimeError('Completed budget cannot restart')
        # Reward revisions may intentionally skip an interrupted diagnostic
        # evaluation and resume learning at the next authorized 10k boundary.
        if state.pop('resume_training_next_check',False):
            state['next_check']=min(TOTAL_STEPS,(state['steps']//10000+1)*10000)
        # Recover from the most recent saved weights, never replay an entire block.
        candidate=Path(state.get('training_checkpoint') or state.get('checkpoint') or 'missing-checkpoint')
        if candidate.exists() and steps(candidate)>state['steps']:
            state['checkpoint']=str(candidate);state['steps']=steps(candidate)
    else:
        if (OUT/'status.json').exists():raise RuntimeError('Existing run requires explicit resume')
        state=dict(stage=1,phase='training',task='basic',task_start=0,steps=0,next_check=10000,
                   checkpoint=None,completed=[],streak=0,transitions=[],reward_revision=REVISION,from_zero=True)
    try:
        while True:
            stage=state['stage'];task=state['task'];name=f'integrated-combat-block-{stage}-{task}'
            target=min(state['next_check'],TOTAL_STEPS)
            if state['steps']<target:
                state.update(phase='training',training_checkpoint=str(ROOT/'artifacts'/name/'latest.zip'));save(state)
                for attempt in range(3):
                    try:
                        args=['--steps',str(target-state['steps']),'--phase',task,'--run-name',name]
                        if state['checkpoint']:args+=['--checkpoint',state['checkpoint']]
                        run(args,OUT/f'stage-{stage}-train.log')
                        break
                    except subprocess.CalledProcessError as exc:
                        failed_log=OUT/f'stage-{stage}-train.log'
                        failed_log.replace(OUT/f'stage-{stage}-retry-{attempt+1}.log')
                        candidate=Path(state['training_checkpoint'])
                        if candidate.exists():
                            count=steps(candidate)
                            if state['steps']<=count<=target:
                                state.update(checkpoint=str(candidate),steps=count)
                        state['last_recovery']=dict(attempt=attempt+1,error=str(exc),steps=state['steps']);save(state)
                        if state['steps']==target:break
                        if attempt==2:raise
                state['checkpoint']=state['training_checkpoint'];state['steps']=steps(state['checkpoint'])
                if state['steps']!=target:raise RuntimeError('Budget counter overshot target')
            state['phase']='evaluation';save(state)
            for attempt in range(3):
                try:
                    run(['--checkpoint',state['checkpoint'],'--eval','30','--phase',task,
                         '--run-name',name+'-eval'],OUT/f'stage-{stage}-eval.log')
                    break
                except subprocess.CalledProcessError:
                    (OUT/f'stage-{stage}-eval.log').replace(OUT/f'stage-{stage}-eval-retry-{attempt+1}.log')
                    if attempt==2:raise
            es=json.loads((ROOT/'artifacts'/(name+'-eval')/'evaluation.json').read_text())['episodes']
            result=summary(es)
            advance,reason,streak=transition(task,state['steps']-state['task_start'],result,state['streak'])
            passed=streak>0
            report=dict(stage=stage,task=task,steps=state['steps'],target_seconds=120,
                        evaluation=result,gate_passed=passed,advance_reason=reason,
                        reward_revision=state.get('reward_revision','initial'))
            state['completed'].append(report)
            (OUT/f'stage-{stage}-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            (OUT/f'stage-{stage}-report.md').write_text(
                f'# 单Boss第{stage}次检验\n\n任务：{task}，累计{state["steps"]}/300000步。\n\n'+json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            if state['steps']>=TOTAL_STEPS:
                state['phase']='complete';save(state);break
            state['streak']=streak
            if advance:
                new=TASKS[TASKS.index(task)+1]
                state['transitions'].append(dict(previous=task,next=new,reason=reason,steps=state['steps']))
                state.update(task=new,task_start=state['steps'],streak=0)
            state.update(stage=stage+1,next_check=min(TOTAL_STEPS,(state['steps']//10000+1)*10000),phase='training')
            state.pop('training_checkpoint',None);save(state)
    except Exception as exc:
        state.update(phase='failed',error=str(exc));save(state);raise

if __name__=='__main__':main()
