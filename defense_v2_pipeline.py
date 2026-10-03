"""Five budget blocks, measured mastery gates, 30 validation episodes per block."""
import json,math,subprocess,sys,time,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parent;OUT=ROOT/'artifacts/defense-v2-100k-pipeline';HORIZONS=(10,20,40,80,120)

def wilson(wins,n):
    z=1.96;p=wins/n;den=1+z*z/n;mid=(p+z*z/(2*n))/den;half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return [mid-half,mid+half]
def summary(episodes):
    n=len(episodes);wins=sum(e['is_success'] for e in episodes)
    result={'episodes':n,'success_rate':wins/n,'success_ci95':wilson(wins,n)}
    for k in ('fight_seconds','start_hp','hp','hp_lost','effective_hits','damage_dealt','estimated_avoidances','near_fraction','far_seconds','dt_mean','dt_max'):
        result[k]=sum(e[k] for e in episodes)/n
    for k in ('out_of_view','watchdog_timeout'):result[k]=sum(e[k] for e in episodes)
    result['minimum_survival']=min(e['fight_seconds'] for e in episodes)
    result['reward_parts']={k:sum(e['reward_parts'].get(k,0) for e in episodes)/n for k in episodes[0]['reward_parts']}
    return result

def mastered(result):return result['success_ci95'][0]>=.6 and result['near_fraction']>=.25 and result['out_of_view']==0 and result['watchdog_timeout']==0

def status(**data):
    OUT.mkdir(parents=True,exist_ok=True);data.update(updated_at=time.strftime('%Y-%m-%d %H:%M:%S'),total_steps=100000,steps_per_stage=20000,total_stages=5,eval_episodes=30,from_zero=True)
    t=OUT/'status.tmp';t.write_text(json.dumps(data,indent=2));t.replace(OUT/'status.json')
def run(args,log):
    with log.open('w',encoding='utf-8') as f:
        subprocess.run([sys.executable,'-u',str(ROOT/'defense_v2_train.py'),*args],cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,check=True,timeout=14400)
def main():
    if (OUT/'status.json').exists():raise RuntimeError('Existing run: refuse to silently restart or exceed budget')
    reports=[];checkpoint=None;level=0;best={}
    try:
        for stage in range(1,6):
            horizon=HORIZONS[level];name=f'defense-v2-stage-{stage}'
            status(stage=stage,phase='training',horizon_seconds=horizon,completed=reports)
            args=['--steps','20000','--horizon',str(horizon),'--run-name',name]
            if checkpoint:args+=['--checkpoint',str(checkpoint)]
            run(args,OUT/f'stage-{stage}-train.log');checkpoint=ROOT/'artifacts'/name/'latest.zip'
            status(stage=stage,phase='evaluation',horizon_seconds=horizon,completed=reports)
            run(['--checkpoint',str(checkpoint),'--eval','30','--horizon',str(horizon),'--run-name',name+'-eval'],OUT/f'stage-{stage}-eval.log')
            episodes=json.loads((ROOT/'artifacts'/(name+'-eval')/'evaluation.json').read_text())['episodes'];result=summary(episodes)
            audit=None
            if horizon<120:
                status(stage=stage,phase='evaluation-audit',horizon_seconds=horizon,completed=reports)
                run(['--checkpoint',str(checkpoint),'--eval','1','--horizon','120','--run-name',name+'-audit'],OUT/f'stage-{stage}-audit.log')
                audit=json.loads((ROOT/'artifacts'/(name+'-audit')/'evaluation.json').read_text())['episodes'][0]
            gate=mastered(result);report={'stage':stage,'steps':stage*20000,'target_seconds':horizon,'mastered':gate,'evaluation':result,'audit_120s':audit}
            reports.append(report)
            score=(result['success_rate'],result['near_fraction'],result['fight_seconds'])
            if horizon not in best or score>best[horizon]:
                best[horizon]=score;shutil.copy2(checkpoint,OUT/f'best-{horizon}s.zip')
            (OUT/f'stage-{stage}-report.json').write_text(json.dumps(report,indent=2))
            text=f'# 第{stage}段评测\n\n累计{stage*20000}/100000步；当前目标{horizon}秒；30局；达标：{gate}。\n\n'+json.dumps(result,ensure_ascii=False,indent=2)
            if audit:text+='\n\n120秒独立检查仅1局，不估计成功率：\n'+json.dumps(audit,ensure_ascii=False,indent=2)
            if len(reports)>1:
                previous=reports[-2];text+=f"\n\n上一段目标{previous['target_seconds']}秒，本段{horizon}秒；目标不同时不直接比较成功率。无伤持续时间均值变化{result['fight_seconds']-previous['evaluation']['fight_seconds']:+.2f}秒。"
            (OUT/f'stage-{stage}-report.md').write_text(text,encoding='utf-8')
            if gate:level=min(level+1,len(HORIZONS)-1)
        status(stage=5,phase='complete',horizon_seconds=HORIZONS[level],completed=reports)
    except Exception as exc:status(phase='failed',error=str(exc),completed=reports);raise
if __name__=='__main__':main()
