"""Versioned real-input skills; no damage, invulnerability or cooldown overrides."""
import numpy as np

# Bits: left,right,jump,attack,dash,down,quickCast,up.
# (label, held mask, edge-trigger bits to release before pressing)
SKILL_ACTIONS = []
for move, label in ((0, "stand"), (1, "left"), (2, "right")):
    for name, mask, pulse in (
        ("wait", 0, 0), ("jump", 4, 4), ("slash", 8, 8),
        ("jump_slash", 12, 12), ("up_slash", 136, 8),
        ("down_slash", 40, 8), ("dash", 16, 16),
        ("shade_soul", 64, 64), ("descending_dark", 96, 64),
        ("abyss_shriek", 192, 64), ("charge", 8, 0),
        ("release_great_slash", 0, 0),
        ("release_cyclone", 128, 0),
        ("charge_dash", 24, 16),
        ("release_dash_slash", 16, 0),
    ):
        SKILL_ACTIONS.append((label + "_" + name, move | mask, pulse))


def skill_observation(state, base):
    required = ("shadowDashTimer", "dashCooldownTimer", "attack_cooldown",
                "nailChargeTimer", "nailChargeTime", "invulnerable",
                "shadowDashing", "spellQuake", "fireballLevel", "quakeLevel",
                "screamLevel", "hasShadowDash", "hasDashSlash",
                "hasUpwardSlash", "hasCyclone")
    missing = [key for key in required if key not in state]
    if missing:
        raise RuntimeError("Updated skills bridge required; missing " + ", ".join(missing))
    extra = [state["shadowDashTimer"] / 1.5, state["dashCooldownTimer"],
             state["attack_cooldown"],
             state["nailChargeTimer"] / max(state["nailChargeTime"], 0.01),
             state["invulnerable"], state["shadowDashing"], state["spellQuake"],
             state["fireballLevel"] / 2, state["quakeLevel"] / 2,
             state["screamLevel"] / 2, state["hasShadowDash"],
             state["hasDashSlash"], state["hasUpwardSlash"], state["hasCyclone"]]
    return np.concatenate([base, np.asarray(extra, dtype=np.float32)])
