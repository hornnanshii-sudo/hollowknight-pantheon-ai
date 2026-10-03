import unittest
from combat_reward import CombatReward

def s(hp=9,won=False,time=0):
    return dict(hp=hp,won=won,time=time,boss_hp=650,boss_max_hp=650)

class FlawlessTests(unittest.TestCase):
    def test_clean_win_bonus(self):
        r=CombatReward(flawless=True)
        self.assertEqual(r.score(s(),s(won=True)),20)
        self.assertEqual(r.score(s(won=True),s(won=True)),0)
    def test_healing_does_not_restore_clean_win(self):
        r=CombatReward(flawless=True)
        self.assertEqual(r.score(s(),s(hp=8)),-1.5)
        self.assertEqual(r.score(s(hp=8),s()),0)
        self.assertEqual(r.score(s(),s(won=True)),10)
    def test_low_hp_win_and_mutual_death(self):
        r=CombatReward(flawless=True)
        r.score(s(),s(hp=3))
        self.assertAlmostEqual(r.score(s(hp=3),s(hp=3,won=True)),5+5/3)
        self.assertLess(CombatReward(flawless=True).score(s(),s(hp=0,won=True)),0)
    def test_waiting_cannot_farm_health(self):
        self.assertLess(CombatReward(flawless=True).score(s(),s(time=1)),0)
