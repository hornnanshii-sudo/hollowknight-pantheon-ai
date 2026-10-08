# Hornet Protector：实现与验收状态

目标为 GG_Hornet_1、Attuned 正常战斗无伤击杀。9 血、0 初始魂、9 骨钉伤害、无护符、无暗影冲刺、无法术/回血/剑技。没有改 Boss 速度、碰撞、血量或注入伤害。

## 实现

- HornetTelemetry 独立记录原生 HP 变化、攻击、受伤、FSM 转换、HealthManager.Die 完成及 BossSceneController 结束事件。未验收的 FSM 窗口不参与奖励。
- 393 维当前观测（固定 FSM 名单、32 个危险对象槽位、原生动作可用性），四个动作头 3/2/4/2；左右移动、持续跳跃、三方向骨钉攻击及冲刺可组合。无额外攻击/冲刺冷却。
- 两个固定物理 tick 为一个动作，目标游戏时间 0.04 秒；严格校验 tick 和时间，不合格立即停止采样。
- RecurrentPPO，128 LSTM，学习率 1e-4，1000 步 rollout，batch 100，4 epochs，gamma .9975，GAE .95，entropy .01，target KL .015。
- 实际训练预算 200000，分配 20000/80000/100000。所有执行过的训练步（包括后来拒绝的数据）计数；评测独立计数。未知命令执行结果留下 pending，禁止自动猜测恢复。
- 首个 5000 步检查可学性，未通过立即停止。后续阶段必须达标才能升级；阶段剩余额度不转移。无伤阶段依次使用 2 血和首次受伤终止，评测始终完整正常战斗。
- 新入口只接受全新运行，不能冒充断点续训。当前尚未实现自动恢复器。

## 启动前置条件

先编译安装 Mod，载入测试存档，再执行 `scripts/check-hornet-live.py`。探测不是模型训练，行为数据不作为模仿学习样本。

入口要求环境 acceptance.passed、独立事件复核 independent_event_review_passed、calibration.passed 同时成立。独立复核不能只凭同一 Hook 的两份计数赋值。奖励标定脚本要求各类基准至少 10 局以及真实完整胜利样本；不足时只输出失败报告，不写默认通过系数。

损害奖励固定实际伤害/9。受伤、击杀、无伤、死亡、超时系数由离线标定生成并锁版本；初版无空挥、持续位置、持续存活及闪避奖励。系数候选排序只是经验检验，不保证训练结果。

## 2026-10-08 实机检查

五种固定探测策略各一局，全部自然死亡，没有完整胜利。等待 0 伤害，站立攻击 180，接近攻击 432，简单跳跃反击 468，远离 0。每局起始 9 血、最终损失 9 血。没有观测到伤害计数/HP、固定 tick 对账错误。简单反击最多 52 次有效命中，仍不足以证明任务已可学或胜利事件准确。

验收未通过：完整死亡与战斗结束链路没有真实覆盖，独立事件复核尚未完成，基准样本量不足。正式训练步数为 0；禁止手动把门槛标为通过以启动训练。

本次实机痕迹在本机 `artifacts/hornet-v1-audit2/`，不上传游戏文件、存档、模型或逐帧大日志。5 项初始离线测试已通过，随后补充损坏事件与时序拒绝测试。Mod 编译通过，仅 Unity 旧 API 警告。

追加检查：7 项离线测试通过，包含缺失验收时不得创建模型/预算账本。训练入口将具体缺失项写入 startup-check.json，不再仅因缺少 calibration.json 抛出无法解释的文件错误。新增 careful 固定探测脚本只用于原生胜利链路验收，不训练模型，不改变原生机制。

GitHub 推送可用系统已有代理进行单次命令设置；不需要修改全局 Git 配置。正式训练尚未获准绕过原验收约束。

## 用户另行授权的有限试训

用户已授权 `hornet_pilot.py` 最多 5000 步独立试训，不等于解除完整训练验收。使用同一个 `artifacts/hornet-v1/ledger.json` 计入总预算。试训入口一次性占用运行目录，拒绝静默重跑；没有自动续训或升级。

试验奖励版本 `hornet-pilot-damage1-hurt1-v1`：每 9 点实际伤害 +1，每滴实际掉血 -1，其他奖励全部为 0。系数未完成标定，可能鼓励换血，试训正是检查这种行为；不宣称该系数是最终方案。

保留时序/HP/事件对账检查；疑似 Boss 死亡或场景结束立即拦截当前采样批次，保存证据，不用于更新。每 1000 步保存包含优化器的模型、随机数状态、预算状态；完整检查点目录写完后再更新指针。异常时保留最近完整检查点，释放键盘，不自动重试。

预算耗尽后输出完整训练局的前后半段描述统计，不自动增加评测或训练；这些统计不是独立评测，不能证明策略进步。末尾未完成的一局不混入整局均值。完整验收标志保持未通过。

## 命令

```powershell
.venv/Scripts/python.exe scripts/build-hornet-mod.py --install
.venv/Scripts/python.exe -m unittest discover -s tests -p test_hornet.py -v
.venv/Scripts/python.exe scripts/check-hornet-live.py --out artifacts/hornet-v1 --episodes 10
.venv/Scripts/python.exe scripts/calibrate-hornet.py --run artifacts/hornet-v1
# 只有所有验收文件通过后才允许启动：
.venv/Scripts/python.exe hornet_train.py --run artifacts/hornet-v1
```

测试结束执行 release 归还键盘。Mod 沿用原有禁止写游戏存档机制；退出训练后常规游玩需要移除训练插件再重启游戏。
