"""Six-frame interface; append critical combat state without disturbing old features."""
import numpy as np
import torch as th
from single_boss_core import ACTIONS,CurriculumPolicy
from integrated_combat_core import RelativeFeatures

HISTORY=6
OLD_FRAME_SIZE=209
FRAME_SIZE=220
OBS_SIZE=HISTORY*FRAME_SIZE
SCHEMA='integrated-combat-220x6-actions25-v2'

class CombatFeatures(RelativeFeatures):
    def frame(self,s,*args):
        base=super().frame(s,*args)
        extra=[max(0,s['boss_hp'])/max(s['boss_max_hp'],1),s['boss_valid'],
               s['hero_focusing'],s['focus_elapsed']/1.5,s['focus_drain_timer'],s['focus_mp_amount']/33,
               s['hero_casting'],s['hero_castRecoiling'],s['hero_attacking'],s['hero_preventDash'],s['hasShadowDash']]
        f=np.concatenate([base,extra]).astype(np.float32)
        if f.shape!=(FRAME_SIZE,) or not np.isfinite(f).all():raise RuntimeError('Invalid six-frame combat state')
        return np.clip(f,-5,5)

class CombatPolicy(CurriculumPolicy):
    def _distribution(self,obs,latent):
        stages=obs[:,(HISTORY-1)*FRAME_SIZE+179:(HISTORY-1)*FRAME_SIZE+184].argmax(dim=1)
        ids=th.arange(len(ACTIONS),device=obs.device)[None,:]
        mask=(ids<18)|((ids<21)&(stages[:,None]>=1))|((ids<24)&(stages[:,None]>=2))|(stages[:,None]>=3)
        return self.action_dist.proba_distribution(action_logits=self.action_net(latent).masked_fill(~mask,-1e9))

def transfer_four_frames(source,target):
    """Preserve the four most recent frames; new history/state starts at zero weight."""
    for key,value in target.items():
        if key not in source:raise RuntimeError(f'Missing policy tensor {key}')
        previous=source[key]
        if previous.shape==value.shape:value.copy_(previous)
        elif key in ('mlp_extractor.policy_net.0.weight','mlp_extractor.value_net.0.weight'):
            if previous.shape[1]!=836 or value.shape[1]!=OBS_SIZE:raise RuntimeError('Unexpected migration dimensions')
            value.zero_()
            for frame in range(4):
                value[:,(frame+2)*FRAME_SIZE:(frame+2)*FRAME_SIZE+OLD_FRAME_SIZE].copy_(previous[:,frame*OLD_FRAME_SIZE:(frame+1)*OLD_FRAME_SIZE])
        else:raise RuntimeError(f'Unsupported policy migration {key}')
