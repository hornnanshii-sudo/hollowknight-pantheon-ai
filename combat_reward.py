"""Damage-based combat rewards; button presses and proximity earn nothing."""
class CombatReward:
    def __init__(self, aggressive=True, flawless=False, max_health=9):
        self.aggressive = aggressive
        self.flawless = flawless
        self.max_health = max(max_health, 1)
        self.hp_lost = 0
        self.terminal_paid = False
        self.combo = 0
        self.last_hit_time = None

    def score(self, old, state):
        hurt = max(0, old["hp"] - state["hp"])
        self.hp_lost += hurt
        # A missing enemy object is not proof of damage or victory.
        valid_damage = state["boss_hp"] > 0 or state["won"]
        dealt = max(0, old["boss_hp"] - state["boss_hp"]) if valid_damage else 0
        dt = max(0, state["time"] - old["time"])
        if hurt or (self.last_hit_time is not None and state["time"] - self.last_hit_time > 2):
            self.combo = 0
        base = (12 if self.aggressive else 10) * dealt / max(old["boss_max_hp"], 1)
        bonus = 0.0
        if dealt and not hurt:
            self.combo += 1
            self.last_hit_time = state["time"]
            if self.aggressive:
                bonus = base * min(0.05 * (self.combo - 1), 0.25)
        reward = base + bonus - (1.5 if self.flawless else 0.5) * hurt
        if self.aggressive:
            reward -= 0.01 * dt
        if not self.terminal_paid and (state["won"] or state["hp"] <= 0):
            self.terminal_paid = True
            if state["won"] and state["hp"] > 0:
                reward += 5
                if self.flawless:
                    reward += 5 * min(state["hp"] / self.max_health, 1)
                    if self.hp_lost == 0:
                        reward += 10
            else:
                reward -= 3
        return reward
