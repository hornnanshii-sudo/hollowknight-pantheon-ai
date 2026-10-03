"""Persistent single-boss curriculum: 10k checks, bounded automatic progression."""
import argparse,json,subprocess,sys,time,zipfile
from pathlib import Path
from defense_v3_pipeline import summary as defense_summary
from single_boss_core import TASKS,gate
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'artifacts/single-boss-100k-pipeline'
CAPS=dict(defense=40000,nail=20000,dive=10000,heal=10000,full=100000)

def steps(path):return int(json.loads(zipfile.ZipFile(path).read('data'))['num_timesteps'])
def save(state):
    state.update(updated_at=time.strftime('%Y-%m-%d %H:%M:%S'),total_steps=100000,
                 steps_per_stage=10000,eval_episodes=30,horizon_seconds=120)
    OUT.mkdir(parents=True,exist_ok=True)
    tmp=OUT/'status.tmp';tmp.write_text(json.dumps(state,indent=2),encoding='utf-8');tmp.replace(OUT/'status.json')
def run(args,log):
    with log.open('w',encoding='utf-8') as f:
        subprocess.run([sys.executable,'-u',str(ROOT/'single_boss_train.py'),*args],cwd=ROOT,
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
    return r

def progression(task,spent,passed,streak):
    streak=streak+1 if passed else 0
    advance=task!='full' and (streak>=2 or spent>=CAPS[task])
    reason='mastery' if streak>=2 else 'budget_unmastered' if advance else 'continue'
    return advance,reason,streak

def main():
    p=argparse.ArgumentParser();p.add_argument('--initial-checkpoint',type=Path);p.add_argument('--resume',action='store_true');a=p.parse_args()
    if a.resume:
        state=json.loads((OUT/'status.json').read_text())
        if state['phase']=='complete':raise RuntimeError('Completed budget cannot restart')
        # Reward revisions may intentionally skip an interrupted diagnostic
        # evaluation and resume learning at the next authorized 10k boundary.
        if state.pop('resume_training_next_check',False):
            state['next_check']=min(100000,(state['steps']//10000+1)*10000)
        # Recover from the most recent saved weights, never replay an entire block.
        candidate=Path(state.get('training_checkpoint',state['checkpoint']))
        if candidate.exists() and steps(candidate)>state['steps']:
            state['checkpoint']=str(candidate);state['steps']=steps(candidate)
    else:
        if (OUT/'status.json').exists() or not a.initial_checkpoint:raise RuntimeError('Use explicit resume for an existing run')
        count=steps(a.initial_checkpoint)
        if not 0<=count<100000:raise RuntimeError('Checkpoint outside budget')
        state=dict(stage=1,phase='training',task='defense',task_start=0,steps=count,
                   next_check=max(10000,(count//10000)*10000),checkpoint=str(a.initial_checkpoint),
                   completed=[],streak=0,transitions=[])
    try:
        while True:
            stage=state['stage'];task=state['task'];name=f'single-boss-block-{stage}-{task}'
            target=min(state['next_check'],100000)
            if state['steps']<target:
                state.update(phase='training',training_checkpoint=str(ROOT/'artifacts'/name/'latest.zip'));save(state)
                for attempt in range(3):
                    try:
                        run(['--checkpoint',state['checkpoint'],'--steps',str(target-state['steps']),
                             '--task',task,'--run-name',name],OUT/f'stage-{stage}-train.log')
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
                    run(['--checkpoint',state['checkpoint'],'--eval','30','--task',task,
                         '--run-name',name+'-eval'],OUT/f'stage-{stage}-eval.log')
                    break
                except subprocess.CalledProcessError:
                    (OUT/f'stage-{stage}-eval.log').replace(OUT/f'stage-{stage}-eval-retry-{attempt+1}.log')
                    if attempt==2:raise
            es=json.loads((ROOT/'artifacts'/(name+'-eval')/'evaluation.json').read_text())['episodes']
            result=summary(es);passed=gate(task,result)
            advance,reason,streak=progression(task,state['steps']-state['task_start'],passed,state['streak'])
            report=dict(stage=stage,task=task,steps=state['steps'],target_seconds=120,
                        evaluation=result,gate_passed=passed,advance_reason=reason)
            state['completed'].append(report)
            (OUT/f'stage-{stage}-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            (OUT/f'stage-{stage}-report.md').write_text(
                f'# 单Boss第{stage}次检验\n\n任务：{task}，累计{state["steps"]}/100000步。\n\n'+json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            if state['steps']>=100000:
                state['phase']='complete';save(state);break
            state['streak']=streak
            if advance:
                new=TASKS[TASKS.index(task)+1]
                state['transitions'].append(dict(previous=task,next=new,reason=reason,steps=state['steps']))
                state.update(task=new,task_start=state['steps'],streak=0)
            state.update(stage=stage+1,next_check=min(100000,(state['steps']//10000+1)*10000),phase='training')
            state.pop('training_checkpoint',None);save(state)
    except Exception as exc:
        state.update(phase='failed',error=str(exc));save(state);raise

if __name__=='__main__':main()
