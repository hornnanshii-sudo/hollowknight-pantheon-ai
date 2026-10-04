"""Autoregressive legal button combinations, not scripted movement or skills."""
import numpy as np
import torch
from torch.distributions import Categorical

HEADS=('magic','move','aim','jump','nail','dash')
SIZES=(5,3,3,3,3,2)
# magic: release / forward spell / upward spell / dive / hold focus
# move: release / left / right; aim: release / up / down
# jump: release / hold / fresh press; nail: release / tap / hold-charge
# dash: release / tap. Releasing a charged nail invokes native Nail Arts.

def capabilities(s,advanced):
    cost=24 if s.get('equippedCharm_33') else 33
    values=dict(can_jump=bool(s['can_jump']),can_dash=bool(s['can_dash']),
                can_attack=bool(s['can_attack'] or (advanced and s.get('nail_art_state','').startswith('Cyclone') and 'End' not in s['nail_art_state'])),can_charge=bool(s['can_charge']),
                can_cast=bool(s['can_cast']),charge_ready=bool(s['charge_ready']),
                nail_held=bool(s['input_mask']&8),jump_held=bool(s['input_mask']&4),
                fireball=bool(advanced and s['fireballLevel']>0 and s['soul']>=cost),
                scream=bool(advanced and s['screamLevel']>0 and s['soul']>=cost),
                dive=bool(advanced and s['quakeLevel']>0 and s['soul']>=cost),
                focus=bool(advanced and s['hp']<s['max_hp'] and
                           (s['hero_focusing'] or (s['soul']>=33 and s['can_cast']))),
                advanced=bool(advanced),charge_overheld=s['nailChargeTimer']>s['nailChargeTime']+1.)
    return {key:np.bool_(value) for key,value in values.items()}

def masks(c,head,prefix):
    """Boolean scalar/vector mask; same function used by sampling and learning."""
    like=c['can_jump'];zero=like&False;one=like|True
    magic=prefix[0] if prefix else 0
    if head==0:
        cast=c['can_cast'] & ~c['nail_held']
        return [one,cast&c['fireball'],cast&c['scream'],cast&c['dive'],c['focus'] & ~c['nail_held']]
    if head==1:return [one,magic!=4,magic!=4]
    if head==2:
        # Force spell direction, so the selected spell is what the input means.
        return [(magic==0)|(magic==1)|(magic==4),(magic==0)|(magic==2),(magic==0)|(magic==3)]
    if head==3:
        free=magic==0
        return [one,free&(c['jump_held']|c['can_jump']),free&c['can_jump']]
    if head==4:
        free=magic==0
        return [one,free&c['can_attack']&~c['charge_ready'],
                free&c['advanced']&(c['can_charge']|c['nail_held'])&~c['charge_overheld']]
    nail=prefix[4]
    compatible=((nail==0)&~c['charge_ready'])|((nail==2)&c['nail_held'])
    return [one,(magic==0)&c['can_dash']&compatible]

def legal(c,action):
    if len(action)!=len(SIZES):return False
    prefix=[]
    for head,(value,size) in enumerate(zip(action,SIZES)):
        if value!=int(value) or not 0<=int(value)<size or not bool(masks(c,head,prefix)[int(value)]):return False
        prefix.append(int(value))
    return True

def encode(action):
    magic,move,aim,jump,nail,dash=map(int,action)
    mask=(1 if move==1 else 2 if move==2 else 0)|(128 if aim==1 else 32 if aim==2 else 0)
    pulse=0
    if jump:mask|=4
    if jump==2:pulse|=4
    if nail:mask|=8
    if nail==1:pulse|=8
    if dash:mask|=16;pulse|=16
    if magic in (1,2,3):mask|=64;pulse|=64
    if magic==4:mask|=256
    return mask,pulse

class ConditionalDistribution:
    """Chain-rule log probabilities with masks conditional on earlier heads."""
    def __init__(self,logits,c):self.logits=logits.split(SIZES,dim=1);self.c=c;self.last=None
    def _head(self,i,prefix):
        values=masks(self.c,i,prefix)
        mask=torch.stack([v if isinstance(v,torch.Tensor) else torch.full_like(self.c['can_jump'],bool(v)) for v in values],dim=1)
        return Categorical(logits=self.logits[i].masked_fill(~mask,-1e9))
    def get_actions(self,deterministic=False):
        prefix=[]
        for i in range(len(SIZES)):
            dist=self._head(i,prefix)
            prefix.append(dist.probs.argmax(dim=1) if deterministic else dist.sample())
        self.last=torch.stack(prefix,dim=1);return self.last
    def log_prob(self,actions):
        self.last=actions.long();prefix=[];terms=[]
        for i in range(len(SIZES)):
            dist=self._head(i,prefix);terms.append(dist.log_prob(self.last[:,i]));prefix.append(self.last[:,i])
        return torch.stack(terms,dim=1).sum(dim=1)
    def entropy(self):
        if self.last is None:self.get_actions()
        prefix=[];values=[]
        for i in range(len(SIZES)):
            values.append(self._head(i,prefix).entropy());prefix.append(self.last[:,i])
        return torch.stack(values,dim=1).sum(dim=1)
