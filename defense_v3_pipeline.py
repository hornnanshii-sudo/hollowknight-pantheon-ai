"""Fresh 100k run: five 20k blocks, 30 independent 120s evaluations each."""
import argparse, json, subprocess, sys, time, zipfile
from pathlib import Path
from defense_v2_pipeline import wilson
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'artifacts/defense-v3-100k-pipeline'

def status(**data):
    OUT.mkdir(parents=True,exist_ok=True)
    data.update(updated_at=time.strftime('%Y-%m-%d %H:%M:%S'),total_steps=100000,
                steps_per_stage=20000,total_stages=5,eval_episodes=30,
                from_zero=True,horizon_seconds=120)
    tmp=OUT/'status.tmp';tmp.write_text(json.dumps(data,indent=2),encoding='utf-8');tmp.replace(OUT/'status.json')

def run(args,log):
    with log.open('w',encoding='utf-8') as f:
        subprocess.run([sys.executable,'-u',str(ROOT/'defense_v3_train.py'),*args],
                       cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,check=True,timeout=14400)

def summary(es):
    n=len(es);wins=sum(e['is_success'] for e in es);perfect=sum(e['flawless_success'] for e in es)
    r=dict(episodes=n,success_rate=wins/n,success_ci95=wilson(wins,n),
           flawless_rate=perfect/n,flawless_ci95=wilson(perfect,n))
    for k in ('fight_seconds','start_hp','hp','hp_lost','effective_hits','damage_dealt',
              'estimated_avoidances','near_fraction','far_seconds','dt_mean','dt_max',
              'first_hurt_seconds','risky_dash_hurts'):
        r[k]=sum(e[k] for e in es)/n
    for k in ('out_of_view','watchdog_timeout'):r[k]=sum(e[k] for e in es)
    total_time=sum(e['fight_seconds'] for e in es)
    r['hp_lost_per_minute']=60*sum(e['hp_lost'] for e in es)/max(total_time,1e-6)
    r['reward_parts']={k:sum(e['reward_parts'].get(k,0) for e in es)/n for k in es[0]['reward_parts']}
    return r

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--resume-first-block',type=Path);a=parser.parse_args()
    if (OUT/'status.json').exists() and not a.resume_first_block:raise RuntimeError('Existing run: refuse duplicate budget')
    reports=[];checkpoint=a.resume_first_block;stage=1;resumed=0
    if checkpoint:
        previous=json.loads((OUT/'status.json').read_text())
        resumed=json.loads(zipfile.ZipFile(checkpoint).read('data'))['num_timesteps']
        if previous['phase']!='failed' or previous['stage']!=1 or previous['completed'] or not 0<resumed<20000:
            raise RuntimeError('Unsupported recovery boundary')
    try:
        for stage in range(1,6):
            name=f'defense-v3-stage-{stage}'
            status(stage=stage,phase='training',completed=reports)
            args=['--steps',str(20000-resumed if stage==1 else 20000),'--horizon','120','--run-name',name]
            if checkpoint:args+=['--checkpoint',str(checkpoint)]
            run(args,OUT/f'stage-{stage}-train.log')
            checkpoint=ROOT/'artifacts'/name/'latest.zip'
            status(stage=stage,phase='evaluation',completed=reports)
            run(['--checkpoint',str(checkpoint),'--eval','30','--horizon','120',
                 '--run-name',name+'-eval'],OUT/f'stage-{stage}-eval.log')
            es=json.loads((ROOT/'artifacts'/(name+'-eval')/'evaluation.json').read_text())['episodes']
            report=dict(stage=stage,steps=stage*20000,target_seconds=120,evaluation=summary(es))
            reports.append(report)
            (OUT/f'stage-{stage}-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            (OUT/f'stage-{stage}-report.md').write_text(
                f'# 第{stage}段连续防御评测\n\n累计{stage*20000}/100000步，30局，每局最多120秒。\n\n'
                +json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        status(stage=5,phase='complete',completed=reports)
    except Exception as exc:
        status(stage=stage,phase='failed',error=str(exc),completed=reports);raise

if __name__=='__main__':main()
