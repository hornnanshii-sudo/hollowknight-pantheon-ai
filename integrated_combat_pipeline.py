"""Persistent single-boss curriculum: 10k checks, bounded automatic progression."""
import argparse,json,subprocess,sys,time,zipfile,shutil
from pathlib import Path
from defense_v3_pipeline import summary as defense_summary
from integrated_combat_core import PHASES as TASKS,TOTAL_STEPS,PHASE_CAPS as CAPS,transition,REVISION
from complete_combat_observation import SCHEMA,HISTORY,OBS_SIZE
from defense_v2_pipeline import wilson
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'artifacts/integrated-combat-300k-pipeline'
EVAL_EPISODES=10

def steps(path):return int(json.loads(zipfile.ZipFile(path).read('data'))['num_timesteps'])
def save(state):
    state.update(updated_at=time.strftime('%Y-%m-%d %H:%M:%S'),total_steps=TOTAL_STEPS,
                 steps_per_stage=10000,eval_episodes=EVAL_EPISODES,horizon_seconds=120)
    state.update(schema=SCHEMA,frames=HISTORY,obs_size=OBS_SIZE)
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
    r['winning_fight_seconds']=sum(e['fight_seconds'] for e in wins)/len(wins) if wins else 120.
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
    for key in ('nail_damage','spell_damage','quake_damage','quake_hits','focus_heals','focus_post_hurt','art_hits','art_damage','fireball_damage','scream_damage','inactive_seconds','no_progress_seconds','attack_starts','up_attacks','down_attacks','jump_starts'):
        r[key]=sum(e.get(key,0) for e in es)/len(es)
    return r

def normal_episodes(path,expected):
    es=json.loads(path.read_text(encoding='utf-8'))['episodes']
    if len(es)!=expected or any(not e.get('normal_start') or e['start_hp']!=9 or e['start_soul']!=0 for e in es):
        raise RuntimeError('Formal evaluation must contain all requested normal 9HP/0soul episodes')
    return es

def retain_best(state,result):
    # Compare only within the same action set on normal-resource evaluation.
    task=state['task'];best=state.setdefault('best',{})
    rank=[result['success_rate'],result.get('flawless_rate',0),-result['winning_hp_lost'],
          -result.get('winning_fight_seconds',120)]
    if task in best and rank<=best[task]['rank']:return
    folder=OUT/('best-'+task);folder.mkdir(exist_ok=True)
    source=Path(state['checkpoint'])
    shutil.copy2(source,folder/'model.tmp.zip');(folder/'model.tmp.zip').replace(folder/'model.zip')
    shutil.copy2(source.with_name('config.json'),folder/'config.json')
    best[task]=dict(rank=rank,steps=state['steps'],checkpoint=str(folder/'model.zip'),evaluation=result)

def assess_skills(state,name):
    stage=state['stage'];state['phase']='assessment';save(state)
    results={}
    for skill in ('heal','dive'):
        run(['--checkpoint',state['checkpoint'],'--eval','10','--phase',state['task'],
             '--assessment',skill,'--run-name',name+'-'+skill+'-assessment'],OUT/f'stage-{stage}-{skill}-assessment.log')
        es=json.loads((ROOT/'artifacts'/(name+'-'+skill+'-assessment')/'evaluation.json').read_text())['episodes']
        if len(es)!=10:raise RuntimeError('Incomplete skill assessment')
        history=state.setdefault('skill_history',{}).setdefault(skill,[])
        history.extend(bool(e['assessment_success']) for e in es)
        recent=history[-30:];n=len(recent);count=sum(recent)
        results[skill]=dict(episodes=len(es),successful=sum(bool(e['assessment_success']) for e in es),
                           recent_episodes=n,recent_success_rate=count/max(n,1),
                           recent_ci95=wilson(count,n),mastered=n>=30 and count/n>=.8,
                           resource_assisted=True,max_seconds=20)
    return results

def skills_mastered(state):
    return all(len(state.get('skill_history',{}).get(k,[]))>=30 and
               sum(state['skill_history'][k][-30:])/30>=.8 for k in ('heal','dive'))

def confirm_best(state):
    state['phase']='confirmation';save(state)
    checkpoint=state.get('best',{}).get('full',{}).get('checkpoint',state['checkpoint'])
    name='integrated-combat-final-confirmation'
    run(['--checkpoint',checkpoint,'--eval',str(EVAL_EPISODES),'--phase','full','--eval-bank','confirmation',
         '--run-name',name],OUT/'final-confirmation.log')
    es=normal_episodes(ROOT/'artifacts'/name/'evaluation.json',EVAL_EPISODES)
    result=dict(checkpoint=checkpoint,steps=state['steps'],evaluation=summary(es),
                start_bank='confirmation',normal_start=True,selection_independent=True,
                skills_mastered=skills_mastered(state))
    (OUT/'final-report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    state['final_report']=str(OUT/'final-report.json')


def main():
    p=argparse.ArgumentParser();p.add_argument('--resume',action='store_true');a=p.parse_args()
    if a.resume:
        state=json.loads((OUT/'status.json').read_text())
        if state['phase']=='complete':raise RuntimeError('Completed budget cannot restart')
        if state.get('schema')!=SCHEMA:raise RuntimeError('Explicit observation/action migration required before resume')
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
                   checkpoint=None,completed=[],streak=0,transitions=[],reward_revision=REVISION,from_zero=True,schema=SCHEMA)
    try:
        if state['steps']>=TOTAL_STEPS and state['completed'] and state['completed'][-1]['steps']==TOTAL_STEPS:
            confirm_best(state);state['phase']='complete';save(state);return
        while True:
            stage=state['stage'];task=state['task'];name=f'integrated-combat-v3-block-{stage}-{task}'
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
                    run(['--checkpoint',state['checkpoint'],'--eval',str(EVAL_EPISODES),'--phase',task,
                         '--run-name',name+'-eval'],OUT/f'stage-{stage}-eval.log')
                    break
                except subprocess.CalledProcessError:
                    (OUT/f'stage-{stage}-eval.log').replace(OUT/f'stage-{stage}-eval-retry-{attempt+1}.log')
                    if attempt==2:raise
            es=normal_episodes(ROOT/'artifacts'/(name+'-eval')/'evaluation.json',EVAL_EPISODES)
            result=summary(es)
            retain_best(state,result)
            skill_result=assess_skills(state,name) if task!='basic' and stage%2==0 else None
            advance,reason,streak=transition(task,state['steps']-state['task_start'],result,state['streak'])
            if task=='mixed' and not skills_mastered(state):
                streak=0
                advance=state['steps']-state['task_start']>=CAPS[task]
                reason='budget_unmastered' if advance else 'continue_skills_unmastered'
            passed=streak>0
            report=dict(stage=stage,task=task,steps=state['steps'],target_seconds=120,
                        evaluation=result,gate_passed=passed,advance_reason=reason,
                        reward_revision=state.get('reward_revision','initial'),schema=SCHEMA,
                        skill_assessment=skill_result,skills_mastered=skills_mastered(state))
            state['completed'].append(report)
            (OUT/f'stage-{stage}-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            (OUT/f'stage-{stage}-report.md').write_text(
                f'# 单Boss第{stage}次检验\n\n任务：{task}，累计{state["steps"]}/300000步。\n\n'+json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            if state['steps']>=TOTAL_STEPS:
                confirm_best(state)
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
