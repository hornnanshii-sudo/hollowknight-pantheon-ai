import unittest
from dodge_train import DODGE_ACTIONS
class ActionTests(unittest.TestCase):
    def test_no_offense_or_focus(self):
        self.assertEqual(len(DODGE_ACTIONS),12)
        for mask,pulse in DODGE_ACTIONS:
            self.assertEqual(mask & ~23,0)
            self.assertEqual(pulse & ~20,0)
            self.assertFalse(mask & 1 and mask & 2)
