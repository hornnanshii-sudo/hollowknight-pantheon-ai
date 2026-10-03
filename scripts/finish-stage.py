"""Finish an already-running evaluation without launching another stage."""
import argparse,json,statistics,subprocess,time
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument("--pid",type=int,required=True)
p.add_argument("--stage",type=int,required=True)
p.add_argument("--out",type=Path,required=True)
p.add_argument("--evaluation",type=Path,required=True)
a=p.parse_args()
def save(data):
    data["updated_at"]=time.strftime("%Y-%m-%d %H:%M:%S")
    temp=a.out/"status.tmp";temp.write_text(json.dumps(data,indent=2),encoding="utf-8");temp.replace(a.out/"status.json")
state=json.loads((a.out/"status.json").read_text(encoding="utf-8"))
state.update(stop_after_stage=a.stage,target_additional_steps=a.stage*50000)
save(state)
try:
    subprocess.run(["powershell.exe","-NoProfile","-Command",f"if (Get-Process -Id {a.pid} -ErrorAction SilentlyContinue) {{ Wait-Process -Id {a.pid} }}"],check=True)
    raw=json.loads(a.evaluation.read_text(encoding="utf-8"));episodes=raw["episodes"]
    if len(episodes)!=20:raise RuntimeError("Incomplete evaluation")
    report=dict(stage=a.stage,win_rate=raw["win_rate"],wins=raw["wins"],episodes=len(episodes))
    for metric in ("start_hp","hp","hp_lost","effective_hits","damage_dealt","fight_seconds"):
        report["mean_"+metric]=statistics.mean(e[metric] for e in episodes)
    wins=[e for e in episodes if e["is_success"]]
    for label,key in (("mean_win_seconds","fight_seconds"),("mean_win_hp","hp"),("mean_win_hp_lost","hp_lost")):
        report[label]=statistics.mean(e[key] for e in wins) if wins else None
    report["no_damage_win_rate"]=sum(e.get("no_damage_win",False) for e in episodes)/len(episodes)
    report["mean_end_soul"]=statistics.mean(e.get("end_soul",0) for e in episodes)
    reports=[r for r in state.get("completed",[]) if r["stage"]!=a.stage]+[report]
    text=f"# 第 {a.stage} 段真实游戏评测\n\n胜利：{report['wins']}/20。\n\n|指标|均值|\n|---|---:|\n"
    text+="\n".join(f"|{k}|{v:.2f}|" for k,v in report.items() if k.startswith("mean_") and v is not None)
    text+=f"\n|no_damage_win_rate|{report['no_damage_win_rate']:.0%}|\n\n按用户要求第三段后停止，未启动第四段。"
    (a.out/f"stage-{a.stage}-report.md").write_text(text,encoding="utf-8")
    state.update(stage=a.stage,phase="complete",completed=reports,stop_reason="User requested stop after stage 3",total_stages=a.stage)
    save(state)
except Exception as exc:
    state.update(phase="failed",error=str(exc));save(state);raise
