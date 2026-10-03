# 技能动作实验（独立版本）

旧版训练默认保持12动作/12维。`--skills`启用45动作、26维状态的最近4帧（104维）；旧权重不兼容。插件新增第7位up，原7位保持兼容。仅读取状态，不修改解锁、魂量、伤害、无敌或冷却。

法术：quickCast=横波，down+quickCast=下砸，up+quickCast=上吼。存档等级决定白/黑法术；未解锁不能释放。三类法术通常消耗33魂，法术扭曲者24魂。
冲刺：dash输入由游戏决定普通/暗影冲刺。hasShadowDash与shadowDashTimer用于区分；冷却约1.5秒。不要将冷却中的普通冲刺视为无敌。
剑技：连续charge动作维持attack蓄力，模型决定移动、蓄多久和何时松键；release_great_slash松attack，release_cyclone同时按up；charge_dash保持蓄力并按dash，随后release_dash_slash松attack。它们是输入操作而非强制成功技能，实际触发需实测FSM；旋风延长可通过再次slash点击探索。大斩内部解锁字段hasUpwardSlash。
普通slash/jump/dash/cast动作先释放对应边沿输入，再重新按下，避免持续按住无法重复触发；这一操作额外推进3个物理步。charge不释放attack。连续wait与release_great_slash语义相同，保留命名方便读日志。

观测新增普通/暗影冲刺冷却、普攻冷却、剑技蓄力进度、无敌、暗影冲刺、下砸状态、技能解锁。无敌状态不是“所有伤害免疫”保证，场景危险仍应单独判断。尚未读取Boss攻击FSM、投射物和危险碰撞框。

先完成旧训练，再关闭游戏并运行构建脚本部署新插件。新实验命令：
`.venv/Scripts/python.exe train.py --skills --steps 2048 --run-name gruz-skills-smoke`
此命令会新建模型；不要传旧checkpoint。

上线前应逐个验证法术扣魂、进入施法状态、技能造成实际伤害，验证暗影冲刺状态及冷却，验证剑技蓄力松键。源码已编译不等于游戏技能实测成功。当前未部署也未启动新训练，避免打断原三段流程。

学习课程：先普攻积魂+三类施法+冲刺；再剑技连续蓄力与释放；最后混合。奖励沿用有效伤害/受伤/胜负/时间，不给按键或空放技能奖励。评测应新增实际施法次数、有效伤害、躲避后短时间反击、空放比例；仅靠动作选择计数不能证明技能成功。先用格鲁兹之母检验接口，之后必须加入不同攻击方向和弹幕Boss。

机制参考：
https://hollowknight.wiki/w/Shade_Cloak
https://hollowknight.wiki/w/Descending_Dark
https://hollowknight.wiki/w/Spells_and_Abilities_(Hollow_Knight)
