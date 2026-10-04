"""Six structured frames with executable-action state and head history."""
import numpy as np
from single_boss_core import CurriculumPolicy
from integrated_observation import CombatFeatures
from complete_combat_actions import capabilities,HEADS,SIZES,ConditionalDistribution

HISTORY=6
CAP_KEYS=('can_jump','can_dash','can_attack','can_charge','can_cast','charge_ready',
          'nail_held','jump_held','fireball','scream','dive','focus','advanced','charge_overheld')
EXTRA_KEYS=('charge_progress','hasNailArt','hasDashSlash','hasUpwardSlash','hasCyclone',
            'hero_nailCharging','hero_nailArt_active','hero_recoiling','airDashed',
            'fireballLevel','quakeLevel','screamLevel')
FRAME_SIZE=220+len(CAP_KEYS)+len(EXTRA_KEYS)+sum(SIZES)
OBS_SIZE=FRAME_SIZE*HISTORY
SCHEMA=f'complete-combat-{FRAME_SIZE}x6-multidiscrete-v3'

class CompleteFeatures(CombatFeatures):
    def frame(self,s,remaining,horizon,last_action,dt,task,loss):
        # Legacy action slots stay zero; new head one-hots have their own slots.
        old=super().frame(s,remaining,horizon,None,dt,task,loss)
        c=capabilities(s,task in ('dive','heal','full'))
        extra=[float(c[k]) for k in CAP_KEYS]+[s[k] for k in EXTRA_KEYS]
        head=np.zeros(sum(SIZES),np.float32);offset=0
        if last_action is not None:
            for value,size in zip(last_action,SIZES):head[offset+int(value)]=1;offset+=size
        f=np.concatenate([old,np.array(extra,np.float32),head])
        if f.shape!=(FRAME_SIZE,) or not np.isfinite(f).all():raise RuntimeError('Invalid complete-action observation')
        return np.clip(f,-5,5)

class CompletePolicy(CurriculumPolicy):
    def _distribution(self,obs,latent):
        offset=(HISTORY-1)*FRAME_SIZE+220
        c={key:obs[:,offset+i]>.5 for i,key in enumerate(CAP_KEYS)}
        return ConditionalDistribution(self.action_net(latent),c)

def migrate_encoder(source,target):
    """Carry the learned state encoder, not the incompatible 25-action head."""
    for key,value in target.items():
        if key.startswith('action_net.'):continue
        previous=source[key]
        if previous.shape==value.shape:value.copy_(previous)
        elif key in ('mlp_extractor.policy_net.0.weight','mlp_extractor.value_net.0.weight'):
            if previous.shape[1]!=1320 or value.shape[1]!=OBS_SIZE:raise RuntimeError('Unexpected source schema')
            value.zero_()
            for frame in range(6):
                value[:,frame*FRAME_SIZE:frame*FRAME_SIZE+220].copy_(previous[:,frame*220:(frame+1)*220])
        else:raise RuntimeError(f'Unsupported encoder migration {key}')
