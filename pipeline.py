"""Finite unattended training/evaluation; all reports and weights remain local."""
import argparse
import json
import statistics
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent
OUT=ROOT/"artifacts"/"pipeline"

def status(**data):
    data["updated_at"]=time.strftime("%Y-%m-%d %H:%M:%S")
    temp=OUT/"status.tmp"
    temp.write_text(json.dumps(data,indent=2),encoding="utf-8")
    temp.replace(OUT/"status.json")

def run(arguments, log):
    with log.open("w",encoding="utf-8") as file:
        subprocess.run([sys.executable,"-u",str(ROOT/"train.py"),*arguments],cwd=ROOT,stdout=file,stderr=subprocess.STDOUT,check=True)

def main():
    global OUT
    parser=argparse.ArgumentParser()
    parser.add_argument("--skills",action="store_true")
    parser.add_argument("--steps",type=int,default=10000)
    parser.add_argument("--stages",type=int,default=3)
    parser.add_argument("--initial-checkpoint",type=Path)
    parser.add_argument("--wait-pid",type=int)
    parser.add_argument("--total-steps",type=int)
    parser.add_argument("--output-name")
    args=parser.parse_args()
    if args.output_name and any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in args.output_name):
        parser.error("Invalid output name")
    OUT=ROOT/"artifacts"/(args.output_name or ("skills-pipeline" if args.skills else "pipeline"))
    OUT.mkdir(parents=True,exist_ok=True)
    checkpoint=None if args.skills else ROOT/"artifacts/gruz-aggressive/latest.zip"
    if args.initial_checkpoint:
        checkpoint=args.initial_checkpoint
    extra=["--skills"] if args.skills else []
    reports=[]
    try:
        if args.wait_pid:
            status(phase="training",segment="existing first 100000 steps",target_steps=args.total_steps,completed=[])
            subprocess.run(["powershell.exe","-NoProfile","-Command",f"if (Get-Process -Id {args.wait_pid} -ErrorAction SilentlyContinue) {{ Wait-Process -Id {args.wait_pid} }}"],check=True)
        if args.total_steps:
            with zipfile.ZipFile(checkpoint) as archive:
                trained=json.loads(archive.read("data"))["num_timesteps"]
            args.steps=args.total_steps-trained
            if args.steps<=0 or (args.skills and args.steps%1000):
                raise RuntimeError("Checkpoint does not permit exact requested total")
            args.stages=1
        for stage in range(1,args.stages+1):
            name=f"{args.output_name}-stage-{stage}" if args.output_name else f"gruz-{'skills-' if args.skills else ''}stage-{stage}"
            status(stage=stage,phase="training",steps_per_stage=args.steps,total_stages=args.stages,skills=args.skills,completed=reports)
            run(extra+(["--checkpoint",str(checkpoint)] if checkpoint else [])+["--steps",str(args.steps),"--run-name",name],OUT/f"stage-{stage}-train.log")
            checkpoint=ROOT/"artifacts"/name/"latest.zip"
            status(stage=stage,phase="evaluation",completed=reports)
            run(extra+["--checkpoint",str(checkpoint),"--eval","20","--run-name",name+"-eval"],OUT/f"stage-{stage}-eval.log")
            raw=json.loads((ROOT/"artifacts"/(name+"-eval")/"evaluation.json").read_text())
            episodes=raw["episodes"]
            report={"stage":stage,"win_rate":raw["win_rate"],"wins":raw["wins"],"episodes":20}
            for metric in ["start_hp","hp","hp_lost","effective_hits","damage_dealt","fight_seconds"]:
                report["mean_"+metric]=statistics.mean(e[metric] for e in episodes)
            victories=[e["fight_seconds"] for e in episodes if e["is_success"]]
            report["mean_win_seconds"]=statistics.mean(victories) if victories else None
            reports.append(report)
            text=f"# 第 {stage} 段真实游戏评测\n\n胜利：{raw['wins']}/20。\n\n|指标|均值|\n|---|---:|\n"
            text += "\n".join(f"|{k}|{v:.2f}|" for k,v in report.items() if k.startswith("mean_") and v is not None)
            text += "\n\n有效命中：Boss TakeDamage 实际扣血事件数，不是按键次数。时间为游戏内时间；均值包含失败局，获胜时间单列。20局不足以证明稳定胜率。"
            if len(reports)>1:
                delta=report["win_rate"]-reports[-2]["win_rate"]
                text+=f"\n\n相对上一段胜率变化：{delta:+.0%}；需要结合血量和成功局用时判断是否值得继续。"
            (OUT/f"stage-{stage}-report.md").write_text(text,encoding="utf-8")
            status(stage=stage,phase="stage_complete",completed=reports)
        status(stage=args.stages,phase="complete",completed=reports)
    except Exception as exc:
        status(phase="failed",error=str(exc),completed=reports)
        raise

if __name__=="__main__":
    main()
