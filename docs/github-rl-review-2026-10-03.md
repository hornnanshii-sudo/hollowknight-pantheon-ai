# GitHub同类项目与当前实现审查（2026-10-03）

结论：PPO可继续作为基线；优先完善环境时间同步、任务终止语义、动作可达性及奖励可信度。496维不是性能保证。此次仅静态审查与文档，不改变运行中的代码、奖励或预算；未运行外部项目，也未复现其成绩。

## 核对的公开项目

|项目|实际阅读|可借鉴|限制|
|---|---|---|---|
|[Abdul-AzizOM/HollowRL](https://github.com/Abdul-AzizOM/HollowRL)|README、python/agent/reward.py、enviroment/state_to_vector.py|实机PPO；44维含动作状态和时间；五个动作头；奖励分项|黄蜂专用常数；其攻击结束且前后血量不变的躲避奖励也不证明因果躲避；受伤惩罚不适合直接照搬|
|[seermer/HollowKnight_RL](https://github.com/seermer/HollowKnight_RL)|hkenv.py、models.py、train.py|截图CNN、Dueling/Noisy DQN、四帧、经验回放、best与latest分开|截图血量和胜负识别脆弱；不能据此认为DQN优于当前结构化PPO|
|[anthonymaltsev/HKRL](https://github.com/anthonymaltsev/HKRL)|hkenv.py、models.py、train.py|原项目分支改进；README将hornet_new称为可多数获胜的版本|该成绩是作者描述，未复现；master仍开发；不是独立于seermer的验证|
|[wzh-xxt/HollowKnight_RL](https://github.com/wzh-xxt/HollowKnight_RL)|Model_ppo.py、train_ppo.py|CNN共享特征、移动与攻击分头|README称约3万步10局5胜，只是其自身设置下小样本结果，不能给我们的训练估时|
|[simonsunyiming/rl-hollowknight-zote](https://github.com/simonsunyiming/rl-hollowknight-zote)|model.py、newenv.py|SB3 PPO、四帧、自定义CNN；更新前释放输入并尝试暂停|Esc截图校验也会失败；不照抄gamma=0.85和固定窗口坐标|
|[AdityaJain1030/HKRL](https://github.com/AdityaJain1030/HKRL)|Environments/BasicEnv.cs、MultiEnv.cs、server/multi_env.py|引擎内输入、帧跳、多实例/向量化架构；真实命中事件|未核实完整训练质量，多实例需要独立端口、场景及状态隔离|
|[amacati/SoulsGym](https://github.com/amacati/SoulsGym)|soulsenv.py、darksouls3/iudex.py|固定推进游戏时间后暂停；动画ID和持续时间；合法动作；可随机初始位置|不同游戏，设计可借鉴，数值不可迁移|
|[Turing-Project/Black-Myth-Wukong-AI](https://github.com/Turing-Project/Black-Myth-Wukong-AI)|PPOWukong_beta/WukongReward.py|拆分生命/体力/伤害识别与奖励|部分检测源码明确未实现；不能把计划中的躲避机制当成已验证成果|

另检索了zhuruili/AI-Hollow-Knight和IDayday/Hollow_Knight_DRL，仅作背景，不把未核对的源码细节当作结论。GitHub API限流后改为下载公开源码压缩包；本地参考文本位于artifacts/research-code，不上传第三方源码。

## P0：先修环境和动作接口

1. **成功终止语义**：dodge_train.py返回failed作为terminated、reached或watchdog作为truncated。对于“无伤活到指定时间”的有限时域任务，reached应是成功terminated；watchdog才是外部truncated。加入剩余时间/目标时长，让critic区分相同几何状态但不同剩余时长。[Gymnasium时间限制规范](https://gymnasium.farama.org/tutorials/gymnasium_basics/handling_time_limits/)
2. **采样同步**：TrainingBridge持续推进游戏，只对step等待3个FixedUpdate；PPO更新和Python通信期间并未暂停。跳跃pulse另有释放/按下帧，动作时长也可能不同。需要测量dt分布、请求时延、更新阶段伤害；实现插件端受控推进及暂停，保证训练更新不产生未归因战斗。不能仅用Esc视作可靠暂停。[SoulsGym实现](https://github.com/amacati/SoulsGym/blob/main/soulsgym/envs/soulsenv.py)
3. **动作可达性**：纯躲避12动作每次jump都重新pulse，没有显式持续按跳；限制可控跳跃高度。旧skill_actions.py的45动作没有focus回血，虽然桥接支持第8位focus。战斗版应加入跳跃保持/释放、focus保持/释放及施法开始/结束/取消事件，逐项实机确认。
4. **接口稳定性**：Serve最外层catch会让服务线程在异常断连后退出；异常重连、心跳、输入释放、错误状态和安全停机需要单独处理。保存checkpoint还应版本化观测/动作/奖励/schema、优化器、训练配置、正常化统计。当前迁移是保留网络与步数、重置优化器，不能称为完全无损续训。

## P1：观测内容与表示

- 当前496=4×124：基础26+几何/朝向8+Boss哈希16+地形/视野20+危险物54。保留了大量恒定解锁等级；纯躲避场景可以消融后精简。应按信息是否改变决策来选特征，不按维度大小选。
- plugin已输出doubleJumped、touchingWallL/R、wallSliding、dashing等，但danger_observation/skill_observation没有把它们全部输入网络。优先增加可二段跳、贴墙、攀墙、动作锁定、上一动作/当前持键、dt、目标剩余时间。
- Boss当前FSM名称哈希为16桶会碰撞，也没有招式已进行多久。改Boss专用稳定招式表、unknown槽、阶段/前摇/攻击/后摇及持续时间；不要把每个FSM状态都直接称为一种招式。[SoulsGym动画观测](https://github.com/amacati/SoulsGym/blob/main/soulsgym/envs/darksouls3/iudex.py)
- 六个危险物按距离重排，槽位可在相邻帧交换，四帧堆叠容易混淆身份。添加稳定ID、种类、生成/消失、剩余生存时间；先稳定跟踪，再考虑共享物体编码+池化或注意力。
- 只扫描DamageHero同物体的Collider2D，可能漏子物体和FSM直接伤害。没有刚体的移动危险物速度被置零；应补差分速度，并校验激活/触发/碰撞层和shadowDashHazard语义。最近6个可能漏掉更远但更快的威胁，需要危险物总数、截断标记及按预计碰撞时间选择。
- AABB保守包围框不是精确攻击形状；八条中心射线也不能完整判断角色宽度能否通过、窄平台和落点。做危险框/射线画面叠加，与真实受伤事件逐项核对；补地面多点探测和可站立区域。摄影视野边缘不是物理竞技场边界。
- 运行均值/方差归一化可作对照，但须保存统计，评测冻结，离散标记单独处理。先测试MLP四帧；若招式历史不足，再比较RecurrentPPO，不能直接断言LSTM更强。[RecurrentPPO官方实现](https://sb3-contrib.readthedocs.io/en/master/modules/ppo_recurrent.html)

## P1：奖励目标一致性

- 当前collision_threat只看Boss AABB/速度，并未使用刚添加的hazards。其他Boss投射物场景中观测与躲避奖励会脱节。
- estimated_avoidances奖励0.3：预测碰撞、移动后无碰撞，不等于确实靠动作躲过。可能奖励来回进入危险再退出；相同招式/危险物每次最多记一次，要求足够接近的威胁事件，排除被动离开和已有无敌，设置每回合辅助奖励上限。真实因果不能仅由这几帧证明，报告仍标记估计。
- 安全近身0.04/秒、远离-0.06/秒、远离静止-0.08/秒可能惩罚正确等待。改“有安全可用攻击窗口时的错失机会”，保留必要撤退、回血和躲大招的空间。位移本身和按下攻击本身不奖励。
- 初期10秒终奖最大5×10/120=0.4167（还乘近身率）；一次受伤-5。120秒近身奖励最多4.8，额外躲避奖励可再累积。必须记录每个奖励分项、每回合总量及终奖占比，确认没有主目标被辅助项淹没。
- gamma=0.995需结合实际dt。举例15Hz、120秒为1800步，gamma^1800约0.00012，早期很难收到终奖信用。不是终奖完全无效，critic仍能传播，但不能只不断加大终奖。先固定控制周期，再比较更长折扣时域、缩短技能课、稠密任务进展；GAE同样影响信用分配。
- 对回血只奖励真实缺血时的有效恢复，封顶；终奖基于实际结束血量且独立记录总受伤，避免“故意受伤再回血”刷分。对黑砸分开统计真实伤害、资源成本、无敌窗口和浪费；不强迫每局必须使用某技能。

## P1：训练与评测流程

- 固定20k步自动从10到20/40/80/120秒，不管是否会躲，并非能力达标课程。下一轮采用能力门槛推进，同时保留上一课样本；本轮不擅自改变用户预算。
- 第一滴血就重置可训练严格无伤，但早期看不到后续招式、昂贵重置也降低有效采样。可对照“受伤允许继续的招式课”和严格无伤验收，加入合法起点/不同阶段/位置随机化。不能用训练用瞬移或资源补满的评测宣称五门能力。
- 1局评测只适合检查能否跑通，不适合估胜率。正式验收建议每Boss至少30局，重要Boss100局；报告置信区间、最差分位数和不同初始资源，而非只看均值。[SB3评测建议](https://stable-baselines3.readthedocs.io/en/master/guide/rl_tips.html)
- 保存latest和按任务指标选的best，使用独立评测避免按训练回报挑选。比较至少多个训练随机种子；Python seed42不等于游戏随机种子可复现。
- 分别对比去掉近身奖励、去掉估计躲避奖励、补状态信息、四帧对LSTM，避免一次全改导致无法归因。仪表记录entropy/KL/clip_fraction/explained_variance、奖励分项、动作实际执行率、重置耗时、有效采样耗时及dt。

## 五门最终目标

单Boss无伤是技能测试，最终目标是连续通关并管理资源。当前每局满血重置、无攻击、没有Boss序列和灵魂继承，不能直接解决五门。

建议课程：短招式安全躲避→带安全反击→黑砸/冲刺防御→缺血、有魂条件下安全回血→完整Boss战→不同血魂初始资源→相邻2/5/10场串联→完整五门。每阶段混入前阶段，避免只会躲或只会治疗。观测包括Boss身份、序列位置、当前/最大血量、灵魂、护符、可恢复窗口；最终真实评测继承血魂，只有游戏允许的恢复。中长期可用多个Boss专用策略加共享移动/资源管理模块，再评估统一策略，不必立即上大网络。

优先实施顺序：终止+时间观测→固定推进/更新暂停→动作执行验收（长短跳和focus）→危险物/招式跟踪→奖励分项和防刷分→多局门槛评测→资源继承及串联。
