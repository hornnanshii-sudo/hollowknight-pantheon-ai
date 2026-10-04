# Hollow Knight Pantheon AI

目标：训练 AI 在正常游戏规则下完成无束缚五门（Pantheon of Hallownest）。

当前状态：已实现 Unity 6/BepInEx 游戏接口和格鲁兹之母 PPO 基线，正在真实游戏中验证训练。尚未宣称稳定击败 Boss 或通关五门。

## 当前运行入口

当前使用六帧1590维结构化观测的综合战斗PPO，累计预算30万步，每1万步10局正常开局评测，单局最多120秒；基础→技能混合→巩固自动升级，技能专项与正常成绩分开。参数和执行契约见[综合战斗课程](docs/integrated-combat.md)。启动或恢复当前流程：`.venv/Scripts/python.exe -u integrated_combat_pipeline.py --resume`。状态位于`artifacts/integrated-combat-300k-pipeline/status.json`。该命令须先完成同目录新观测schema迁移；已有流程不允许重复从零覆盖。

下面的`train.py`和进攻奖励实验是历史基线，不是当前调度入口。

## 格鲁兹之母历史实验

当前版本使用 BepInEx 5.4.23.4、独立第 4 存档槽和本地 TCP 9851。首次安装前备份存档；只有槽位 4 为空时才能从自己的神居存档复制。**训练插件安装期间会阻止 GameManager.SaveGame；恢复个人正常游玩前应关闭游戏并移走 `BepInEx/plugins/PantheonTraining.dll`。**

构建插件：`powershell -File scripts/build-mod.ps1`。训练：`.venv/Scripts/python.exe -u train.py --steps 20000`。程序自动启动游戏（若未运行）、载入槽位 4、进入挑战并反复重置。

继续训练：`.venv/Scripts/python.exe -u train.py --checkpoint artifacts/gruz/latest.zip --steps 20000`。

独立评测：`.venv/Scripts/python.exe -u train.py --checkpoint artifacts/gruz/latest.zip --eval 20`。

动作基线是 12 种移动/跳跃/攻击组合；没有预编写战斗策略。每次动作等待 3 个物理更新，但游戏在网络传输和 PPO 更新期间仍继续运行，暂非严格锁步。当前仅验证普通格鲁兹之母场地，尚未覆盖五门场地或资源继承。日志和权重位于 `artifacts/gruz/`，不上传。

### 进攻奖励实验
默认采用 `--reward-style aggressive --run-name gruz-aggressive`，日志/权重写入对应 `artifacts/<run-name>/`。因此上面的 `artifacts/gruz/` checkpoint 是旧基线；新版继续训练请选择实际输出目录中的权重。

实际伤害总权重由 10 提升至 12；无受伤的连续伤害观测在两秒窗口内累积，每次后续伤害的额外奖励增加 5%，最高 25%。受伤或窗口超时清零。这里的连击是连续产生伤害的采样步骤，并非游戏官方连击计数或每一刀的事件计数。按键、空挥、靠近不加分；每游戏秒扣 0.01，死亡/受伤惩罚保持。新旧奖励分数不能直接比较，应比较独立胜率、击杀时间与剩余 HP。

试训：`.venv/Scripts/python.exe -u train.py --checkpoint artifacts/gruz/latest.zip --steps 1024 --run-name gruz-aggressive`。

## 训练路线

1. 游戏环境闭环：观测、按键、固定游戏步长、奖励事件、可靠重置。
2. 单 Boss 训练与独立评测，覆盖五门对应场地和战斗版本。
3. 随机初始血量、灵魂和位置，训练低资源战斗。
4. 相邻 Boss 连战，保留血量、灵魂与冷却状态。
5. 休息点之间分段挑战，最后完整五门评测。

前期采用结构化游戏状态 + PPO，小型 MLP 验证闭环；后续考虑实体编码、注意力与 GRU。困难 Boss 可先使用专家模型，再考虑统一模型。

## 本地配置

将 `config/local.example.json` 复制为 `config/local.json`，修改游戏路径。该本地文件不会提交。

游戏程序、商业游戏程序集、个人存档、权重、数据集、训练日志及图片视频均留在本机；GitHub 仅存放源代码、配置示例和文档。不要将游戏安装目录复制到仓库。

推荐本地目录：`artifacts/checkpoints`、`artifacts/replays`、`artifacts/logs`。

## 验收原则

- 每个 Boss 记录独立评测局数、胜率、受伤量、剩余资源和游戏时间。
- 完整五门评测不使用训练重置、无敌、血量修改或加速。
- 报告所有完整尝试，避免只展示成功录像。
- 最终训练预算依据本机采样基准确定。

详见 [开发路线](docs/roadmap.md) 与 [环境接口](docs/environment.md)。
