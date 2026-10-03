import unittest
from combat_reward import CombatReward

def state(hp=9, boss_hp=650, time=0, won=False):
    return dict(hp=hp, boss_hp=boss_hp, boss_max_hp=650, time=time, won=won)

class RewardTests(unittest.TestCase):
    def test_no_damage_cannot_farm_bonus(self):
        reward = CombatReward()
        self.assertLess(reward.score(state(), state(time=1)), 0)
        self.assertEqual(reward.combo, 0)

    def test_clean_chain_bonus_and_cap(self):
        reward = CombatReward()
        old = state()
        for i in range(1, 20):
            new = state(boss_hp=650-i*10, time=i*0.2)
            value = reward.score(old, new)
            self.assertLessEqual(value, 12*10/650*1.25)
            old = new
        self.assertEqual(reward.combo, 19)

    def test_hurt_resets_chain(self):
        reward = CombatReward()
        reward.score(state(), state(boss_hp=640,time=0.2))
        reward.score(state(boss_hp=640,time=0.2),state(hp=8,boss_hp=630,time=0.4))
        self.assertEqual(reward.combo, 0)

    def test_missing_boss_is_not_a_kill(self):
        reward = CombatReward()
        self.assertLessEqual(reward.score(state(),state(boss_hp=0,time=1)),0)

    def test_combo_expires(self):
        reward = CombatReward()
        reward.score(state(),state(boss_hp=640,time=0.2))
        reward.score(state(boss_hp=640,time=0.2),state(boss_hp=630,time=3))
        self.assertEqual(reward.combo,1)

if __name__ == "__main__":
    unittest.main()
