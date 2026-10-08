"""Offline candidate calibration. Missing evidence is a failure, never a default pass."""
import argparse
import json
import sys
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import hornet_core as h

def calibrate(rows,accepted):
    groups={k:[r for r in rows if r['kind']==k] for k in ('wait','stationary','approach','counter','retreat')}
    missing=[f'{k}: needs 10 baseline episodes, has {len(v)}' for k,v in groups.items() if len(v)<10]
    if not accepted:missing.append('Native event acceptance has not passed')
    wins=[r for r in rows if r['win']]
    if not wins:missing.append('No observed full native victory')
    if missing:return dict(passed=False,reasons=missing,coefficients=None)
    # One successful complete fight establishes the full damage reward scale.
    full=float(np.median([r['damage']/9 for r in wins]))
    candidates=[]
    for hurt in np.linspace(full/18,full/3,21):
        coeff=dict(hurt=float(hurt),win=full,flawless=full/2,death=full,timeout=full/2)
        def score(r):
            return r['damage']/9-hurt*r['hurt']+(full+(full/2 if r['hurt']==0 else 0) if r['win'] else -full if r['hp']<=0 else -full/2)
        scores={k:float(np.mean([score(r) for r in v])) for k,v in groups.items()}
        win_score=float(np.mean([score(r) for r in wins]))
        if win_score>scores['counter']>max(scores['wait'],scores['retreat']) and scores['stationary']<=0:
            candidates.append(dict(coefficients=coeff,scores=scores,win_score=win_score))
    if not candidates:return dict(passed=False,reasons=['No candidate satisfies observed baseline ordering; inspect task design'],coefficients=None)
    chosen=candidates[0]
    return dict(passed=True,version='hornet-event-calibrated-v1',**chosen,limitations='Empirical ordering only; not a guarantee across trajectories. No per-time reward, no empty-swing penalty.')

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args()
    acceptance=json.loads((a.run/'acceptance.json').read_text())
    rows=json.loads((a.run/'baseline-progress.json').read_text())
    result=calibrate(rows,acceptance.get('passed') and acceptance.get('independent_event_review_passed'))
    h.write_json(a.run/'calibration.json',result);print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['passed'] else 2

if __name__=='__main__':sys.exit(main())
