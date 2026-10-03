"""Continuous defense episodes; threat rewards are estimates, not causal proof."""
import math
from defense_v2_core import ACTIONS, OBS_SIZE, FRAME_SIZE, Features, collision_time
from dodge_reward import safe_gap, outside_view

SCHEMA = 'defense-v3-continuous-176x4-actions18'

def ending(hurt, dead, outside, reached, watchdog):
    failed = bool(dead or outside)
    return bool(failed or reached), bool(watchdog and not (failed or reached)), bool(reached and not failed)

class Reward:
    def __init__(self):
        self.pending = {}; self.paid = set(); self.risky_dash = None
        self.avoidances = 0; self.dash_hurts = 0; self.aux_paid = 0.
        self.elapsed = 0.; self.near_seconds = 0.; self.far_seconds = 0.
        self.first_hurt = None; self.breakdown = {}

    @staticmethod
    def damaging_invulnerability(s):
        return bool(s['invulnerable'] and not s['shadowDashing'])

    @staticmethod
    def potential(s):
        # No occupancy payout: approaching a safe band improves potential;
        # leaving it pays back. Immediate threats override the proximity goal.
        if any(collision_time(s,h,.35) is not None for h in s['hazards']):
            return -.15
        gap = safe_gap(s)
        return -.03 * min(max(gap-5, 0) + max(.5-gap, 0), 5)

    def score(self, old, s, dt, hurt, action_mask=0):
        self.elapsed += dt
        gap = safe_gap(s)
        self.near_seconds += dt if .5 <= gap <= 5 else 0
        self.far_seconds += dt if gap > 8 else 0
        parts = dict(survival=.02*dt, damage=-5*hurt, death=0.,
                     avoidance=0., dash_damage=0., engagement=0.,
                     outside=-5. if outside_view(s) else 0., success=0.)
        hs = {h['id']:h for h in s['hazards']}
        dash_started = bool(action_mask & 16 and
                            not (old['dashing'] or old['shadowDashing']) and
                            (s['dashing'] or s['shadowDashing']))
        if dash_started:
            direction = -1 if action_mask & 1 else 1 if action_mask & 2 else (1 if old['facing_right'] else -1)
            projected = dict(old, vx=direction*20., vy=0.)
            dangerous = False
            for h in old['hazards']:
                # Approximate 0.15s dash and its landing; normal shade-passable
                # collisions during the initial immunity are not penalized.
                hit = collision_time(projected,h,.3)
                if hit is not None and (not s['shadowDashing'] or h['shadow_hazard'] or hit >= .15):
                    dangerous = True
            if dangerous: self.risky_dash = old['time'] + .5
        if self.risky_dash is not None and s['time'] > self.risky_dash:
            self.risky_dash = None
        if hurt:
            if self.first_hurt is None: self.first_hurt = self.elapsed
            if self.risky_dash is not None:
                parts['dash_damage'] = -2.; self.dash_hurts += 1
            self.risky_dash = None; self.pending.clear()
        else:
            for key, event in list(self.pending.items()):
                if self.damaging_invulnerability(s):
                    del self.pending[key]; continue
                event['shadow_used'] |= bool(s['shadowDashing'])
                if s['time'] < event['deadline']: continue
                h = hs.get(key[0])
                moved = math.hypot(s['hero_cx']-event['x'], s['hero_cy']-event['y']) > .3
                safe = h is not None and collision_time(s,h,.35) is None
                # Also reject immediate overlap at the landing position.
                if safe:
                    safe = not any(abs(q['cx']-s['hero_cx']) < q['ex']+s['hero_ex'] and
                                   abs(q['cy']-s['hero_cy']) < q['ey']+s['hero_ey'] for q in s['hazards'])
                if safe and moved and key not in self.paid and self.aux_paid < 5:
                    value = min(.2,5-self.aux_paid)
                    parts['avoidance'] += value; self.aux_paid += value
                    self.avoidances += 1; self.paid.add(key)
                del self.pending[key]
            if not self.damaging_invulnerability(old):
                for h in old['hazards']:
                    key = (h['id'],old['boss_phase_event'])
                    if collision_time(old,h,.35) is not None and key not in self.paid and key not in self.pending:
                        self.pending[key] = dict(deadline=old['time']+.5,
                                                 x=old['hero_cx'],y=old['hero_cy'],shadow_used=bool(s['shadowDashing']))
        # Discounted potential shaping telescopes consistently with PPO gamma.
        parts['engagement'] = .999*self.potential(s)-self.potential(old)
        self.breakdown = parts
        return sum(parts.values())

    def terminal(self, reached, hp, hp_lost, terminated):
        bonus = (10. if hp_lost == 0 else 2.*max(0,hp)/9.) if reached else 0.
        self.breakdown['success'] = bonus
        if terminated and hp <= 0: self.breakdown['death'] = -5.
        return bonus + self.breakdown['death']

    @property
    def near_fraction(self): return self.near_seconds/max(self.elapsed,1e-6)
