"""Five finite defense stages, one real-game test every 20000 steps."""
import argparse,json,subprocess,sys,time,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
OUT=ROOT/"artifacts/dodge-engaged-100k-pipeline"
def status(**data):
    data.update(updated_at=time.strftime("%Y-%m-%d %H:%M:%S"),total_steps=100000,steps_per_stage=20000,total_stages=5)
    t=OUT/"status.tmp";t.write_text(json.dumps(data,indent=2),encoding="utf-8");t.replace(OUT/"status.json")
def run(args,log):
    with log.open("w",encoding="utf-8") as f:
        subprocess.run([sys.executable,"-u",str(ROOT/"dodge_train.py"),*args],cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,check=True,timeout=10800)
def main():
    OUT.mkdir(parents=True,exist_ok=True);reports=[]
    p=argparse.ArgumentParser();p.add_argument("--initial-checkpoint",type=Path);a=p.parse_args()
    checkpoint=a.initial_checkpoint
    previous_steps=json.loads(zipfile.ZipFile(checkpoint).read("data"))["num_timesteps"] if checkpoint else 0
    if previous_steps<0 or previous_steps>=20000 or previous_steps%1000:raise RuntimeError("Unexpected starting checkpoint")
    try:
        for stage,horizon in enumerate((10,20,40,80,120),1):
            name=f"dodge-engaged-100k-stage-{stage}"
            status(stage=stage,phase="training",horizon_seconds=horizon,completed=reports)
            args=["--steps",str(20000-previous_steps if stage==1 else 20000),"--horizon",str(horizon),"--run-name",name]
            if checkpoint:args+=["--checkpoint",str(checkpoint)]
            run(args,OUT/f"stage-{stage}-train.log");checkpoint=ROOT/"artifacts"/name/"latest.zip"
            status(stage=stage,phase="evaluation",completed=reports)
            run(["--checkpoint",str(checkpoint),"--eval","1","--run-name",name+"-eval"],OUT/f"stage-{stage}-eval.log")
            e=json.loads((ROOT/"artifacts"/(name+"-eval")/"evaluation.json").read_text(encoding="utf-8"))["episodes"][0]
            report=dict(stage=stage,steps=stage*20000,**{k:e[k] for k in ("is_success","fight_seconds","start_hp","hp","hp_lost","effective_hits","damage_dealt","watchdog_timeout","out_of_view","estimated_avoidances","near_fraction","far_seconds")})
            reports.append(report)
            text=f"# 第{stage}段纯躲避评测\n\n目标：120秒无伤。仅1局，不代表稳定成功率。\n\n|指标|值|\n|---|---|\n"
            text+="\n".join(f"|{k}|{v}|" for k,v in report.items())
            if len(reports)>1:text+=f"\n\n无伤持续时间变化：{report['fight_seconds']-reports[-2]['fight_seconds']:+.2f}秒。"
            (OUT/f"stage-{stage}-report.md").write_text(text,encoding="utf-8")
        status(stage=5,phase="complete",completed=reports)
    except Exception as exc:status(phase="failed",error=str(exc),completed=reports);raise
if __name__=="__main__":main()
