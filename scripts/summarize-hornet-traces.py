"""Read-only trace analysis; incomplete active gzip streams are reported."""
import argparse
from collections import Counter,defaultdict
import gzip
import json
from pathlib import Path
import numpy as np

def summarize(folder):
    groups={};incomplete=[]
    for path in sorted((folder/'traces').glob('*.gz')):
        group=None;previous=None
        try:
            with gzip.open(path,'rt',encoding='utf8') as f:
                for line in f:
                    r=json.loads(line)
                    if r['type']=='reset':
                        key=r['mode']+'/'+r['opening']
                        group=groups.setdefault(key,dict(steps=0,seconds=0.,damage=0,hurt=0,attack_events=0,damage_by_phase=Counter(),hurt_by_phase=Counter(),move_counts=Counter(),probability_sum=[np.zeros(n) for n in (3,2,4,2)],entropy_when_choice=np.zeros(4),choice_steps=np.zeros(4,dtype=int),probability_steps=0))
                        previous=r['state'];continue
                    if r['type']!='step' or group is None:continue
                    group['steps']+=1;group['seconds']+=r['dt'];group['damage']+=r['damage_delta'];group['hurt']+=r['hurt_delta']
                    b=r['state']['hornet'];group['damage_by_phase'][b['phase']]+=r['damage_delta'];group['hurt_by_phase'][b['phase']]+=r['hurt_delta']
                    group['attack_events']+=sum(e['kind']=='attack' for e in b['events']);group['move_counts'][str(r['action'][0])]+=1
                    decision=r.get('decision')
                    if decision:
                        group['probability_steps']+=1
                        for i,p in enumerate(decision['probabilities']):
                            probs=np.asarray(p[0]);group['probability_sum'][i]+=probs
                            if np.count_nonzero(probs>1e-8)>1:
                                group['entropy_when_choice'][i]+=decision['entropy'][i][0];group['choice_steps'][i]+=1
                    previous=r['state']
        except (EOFError,OSError,json.JSONDecodeError) as e:incomplete.append(dict(file=path.name,error=type(e).__name__))
    for group in groups.values():
        group['mean_probabilities']=[(p/max(1,group['probability_steps'])).tolist() for p in group.pop('probability_sum')]
        group['mean_entropy_when_choice']=(group.pop('entropy_when_choice')/np.maximum(1,group['choice_steps'])).tolist()
        group['choice_steps']=group['choice_steps'].tolist()
    return dict(groups=groups,incomplete_files=incomplete,limitations='FSM association at observed step endpoint is not causal attribution; inputs and probabilities are available in original traces.')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directory',type=Path);a=p.parse_args()
    print(json.dumps(summarize(a.directory),ensure_ascii=False,indent=2))
