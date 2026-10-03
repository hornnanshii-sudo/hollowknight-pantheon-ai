"""Real-game Gruz Mother PPO baseline. Requires the bundled training bridge."""
import argparse
import json
from pathlib import Path
import socket
import subprocess
import time

import gymnasium as gym
import numpy as np
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import BaseCallback
from stable_baselines3.common.monitor import Monitor
from combat_reward import CombatReward
from skill_actions import SKILL_ACTIONS, skill_observation

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "artifacts" / "gruz"
# Movement x jump x attack; no scripted combat policy.
ACTIONS = [move | jump | attack for move in (0, 1, 2) for jump in (0, 4) for attack in (0, 8)]


class Bridge:
    def __init__(self):
        self.socket = socket.create_connection(("127.0.0.1", 9851), timeout=35)
        self.stream = self.socket.makefile("rw", encoding="utf-8")

    def request(self, command):
        self.stream.write(command + "\n")
        self.stream.flush()
        line = self.stream.readline()
        if not line:
            raise ConnectionError("Game bridge disconnected")
        state = json.loads(line)
        if "error" in state:
            raise RuntimeError(f"Bridge: {state['error']}; command={command}")
        return state

    def close(self):
        try:
            self.request("release")
        except (OSError, ConnectionError, RuntimeError):
            pass
        finally:
            self.stream.close()
            self.socket.close()


def observation(s):
    return np.array([
        s["x"] / 40, s["y"] / 20, s["vx"] / 30, s["vy"] / 30,
        (s["bx"] - s["x"]) / 30, (s["by"] - s["y"]) / 20,
        s["bvx"] / 30, s["bvy"] / 30, s["hp"] / 9,
        s["boss_hp"] / max(s["boss_max_hp"], 1), s["soul"] / 99, s["grounded"],
    ], dtype=np.float32)


class GruzEnv(gym.Env):
    def __init__(self, aggressive=True, skills=False):
        self.bridge = Bridge()
        self.aggressive = aggressive
        self.skills = skills
        self.history = []
        self.action_space = gym.spaces.Discrete(len(SKILL_ACTIONS) if skills else len(ACTIONS))
        self.observation_space = gym.spaces.Box(-np.inf, np.inf, (104 if skills else 12,), np.float32)
        self.state = None

    def observe(self, s, reset=False):
        if not self.skills:
            return observation(s)
        frame = skill_observation(s, observation(s))
        if reset:
            self.history = [frame.copy() for _ in range(4)]
        else:
            self.history = (self.history + [frame])[-4:]
        return np.concatenate(self.history)

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self.bridge.request("reset")
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            s = self.bridge.request("state")
            if s["ready"]:
                self.state = s
                self.started = s["time"]
                self.start_hp = s["hp"]
                self.hits_start = s.get("effective_hits",0)
                self.damage_start = s.get("damage_dealt",0)
                self.hp_lost = 0
                self.reward_model = CombatReward(self.aggressive)
                return self.observe(s, reset=True), {}
            time.sleep(0.1)
        raise TimeoutError("Boss reset never became ready; inspect BepInEx log")

    def step(self, action):
        if self.skills:
            name, mask, pulse = SKILL_ACTIONS[int(action)]
            if pulse:
                self.bridge.request(f"step {mask & ~pulse}")
            s = self.bridge.request(f"step {mask}")
        else:
            s = self.bridge.request(f"step {ACTIONS[int(action)]}")
        old = self.state
        if s["scene"] != "GG_Gruz_Mother":
            raise RuntimeError(f"Unexpected scene during episode: {s['scene']}")
        reward = self.reward_model.score(old, s)
        self.hp_lost += max(0, old["hp"]-s["hp"])
        terminated = bool(s["won"] or s["hp"] <= 0)
        truncated = s["time"] - self.started >= 90 and not terminated
        self.state = s
        return self.observe(s), reward, terminated, truncated, {"is_success": bool(s["won"]), "hp": s["hp"], "boss_hp": s["boss_hp"], "combo": self.reward_model.combo, "fight_seconds": s["time"]-self.started, "start_hp": self.start_hp, "hp_lost": self.hp_lost, "effective_hits": s.get("effective_hits",0)-self.hits_start, "damage_dealt": s.get("damage_dealt",0)-self.damage_start}

    def close(self):
        self.bridge.close()


class SaveProgress(BaseCallback):
    def _on_step(self):
        for info in self.locals["infos"]:
            if "episode" in info:
                record = {"steps": self.num_timesteps, **info["episode"], "won": info["is_success"], "hp": info["hp"], "boss_hp": info["boss_hp"], "fight_seconds": info["fight_seconds"], "combo": info["combo"]}
                with (OUTPUT / "episodes.jsonl").open("a", encoding="utf-8") as file:
                    file.write(json.dumps(record) + "\n")
                print(record, flush=True)
                if record["won"]:
                    self.model.save(OUTPUT / "winner")
        if self.n_calls % 2048 == 0:
            self.model.save(OUTPUT / "latest")
        return True


def ensure_game(game_dir):
    try:
        bridge = Bridge()
    except OSError:
        launcher = "Start-Process 'steam://rungameid/367520' -WindowStyle Hidden"
        subprocess.run(["powershell.exe", "-NoProfile", "-Command", launcher], check=True)
        deadline = time.monotonic() + 60
        while True:
            try:
                bridge = Bridge()
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise TimeoutError("Game bridge did not start")
                time.sleep(1)
    try:
        deadline = time.monotonic() + 60
        while True:
            s = bridge.request("state")
            if s["scene"] == "Menu_Title":
                bridge.request("load")
                break
            if s["x"] != 0:
                return
            if time.monotonic() > deadline:
                raise TimeoutError("Title menu not ready")
            time.sleep(0.5)
        while bridge.request("state")["x"] == 0:
            if time.monotonic() > deadline:
                raise TimeoutError("Save did not load")
            time.sleep(0.5)
    finally:
        bridge.close()


def main():
    global OUTPUT
    parser = argparse.ArgumentParser()
    parser.add_argument("--skills", action="store_true", help="Expanded skills and four observation frames; requires updated bridge and new checkpoint")
    parser.add_argument("--steps", type=int, default=20000)
    parser.add_argument("--eval", type=int, default=0)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--reward-style", choices=["balanced", "aggressive"], default="aggressive")
    parser.add_argument("--run-name", default="gruz-aggressive")
    args = parser.parse_args()
    if not args.run_name or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in args.run_name):
        parser.error("run-name must contain only letters, digits, hyphens and underscores")
    OUTPUT = ROOT / "artifacts" / args.run_name
    OUTPUT.mkdir(parents=True, exist_ok=True)
    config_path = ROOT / "config" / "local.json"
    if not config_path.exists():
        config_path = ROOT / "config" / "local.example.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    ensure_game(Path(config["game_dir"]))
    env = Monitor(GruzEnv(aggressive=args.reward_style=="aggressive", skills=args.skills), str(OUTPUT / "monitor.csv"))
    model = PPO.load(args.checkpoint, env=env, device="cpu") if args.checkpoint else PPO("MlpPolicy", env, device="cpu", n_steps=1000 if args.skills else 1024, batch_size=125 if args.skills else 128, n_epochs=4, learning_rate=3e-4, gamma=0.995, ent_coef=0.01, policy_kwargs={"net_arch":dict(pi=[128,128], vf=[128,128])}, seed=42, verbose=1)
    try:
        if args.eval:
            wins = 0
            results = []
            for _ in range(args.eval):
                obs, _ = env.reset()
                done = False
                while not done:
                    action, _ = model.predict(obs, deterministic=True)
                    obs, _, term, trunc, info = env.step(action)
                    done = term or trunc
                wins += int(info["is_success"])
                results.append({"episode":len(results)+1, **info})
                print(json.dumps(results[-1]), flush=True)
            report={"evaluation_episodes": args.eval, "wins": wins, "win_rate":wins/args.eval, "episodes":results}
            (OUTPUT/"evaluation.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
            print(json.dumps({"evaluation_episodes": args.eval, "wins": wins}), flush=True)
        else:
            model.learn(args.steps, callback=SaveProgress(), reset_num_timesteps=not bool(args.checkpoint))
    finally:
        if not args.eval:
            model.save(OUTPUT / "latest")
        env.close()


if __name__ == "__main__":
    main()
