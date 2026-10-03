"""Combat interface readiness; not enabled in pure defense training."""
from skill_actions import SKILL_ACTIONS
COMBAT_ACTIONS_V2=list(SKILL_ACTIONS)
for move,label in ((0,'stand'),(1,'left'),(2,'right')):
    COMBAT_ACTIONS_V2.extend([(label+'_hold_jump',move|4,0),(label+'_release_jump',move,0),(label+'_hold_focus',move|256,0),(label+'_release_focus',move,0)])
