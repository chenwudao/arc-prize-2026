# v1 正式成绩分析与桌面同步

2026-10-10 通过 Kaggle CLI 和官方 API 核查。结论：**首版运行正常，公开榜 24.22，尚未证明调度改动带来提升，也还不是高分方案。**

## 已验证的结果

| 项目 | 结果 |
| --- | --- |
| 正式提交 | 56988179，Notebook v1 |
| 团队 / 账号 | Goat / jessewudao |
| 状态 | COMPLETE，error_description 为空 |
| 公开榜 RHAE | **24.22** |
| 私榜成绩 | 未公布，不能推断 |
| 当前账号排名 | **1108** |
| 当前榜首 | Yi-Chia Chen，**62.96** |
| 当前第 50 名 | **33.23**；我们的差距为 **9.01 分** |

官方列表显示 4092 支报名团队，但不等于全部已有分数。榜单与排名会变化。原始证据在 `experiments/v1-dprime-coverage/` 的 `formal-submissions.json`、`formal-submission-detail.json`、`competition-2026-10-10.json`、`leaderboard-2026-10-10.json`。

RHAE 综合关卡完成、关卡权重和动作效率；**24.22 不等于完成了 24.22% 的游戏**。官方链接：[提交记录](https://www.kaggle.com/competitions/arc-prize-2026-arc-agi-3/submissions)、[排行榜](https://www.kaggle.com/competitions/arc-prize-2026-arc-agi-3/leaderboard)、[评分方法](https://docs.arcprize.org/methodology)。

## 如何比较公开方案

Franzen 作者报告的历史成绩为 27.89，我们低 3.67 分；Affectify 作者报告的一次 D′ 提交为 31.54，我们低 7.32 分。这些不是我们账号上匹配预算、输入版本和重复次数的配对对照，不能把差值解释为改动造成的下降。目前只有一次正式实验，还没有原版对照。

公开复现记录同一不可变版本两次得到 27.80 和 21.01，进一步说明单次比较的局限。

我们也没有原样复现 Affectify：它移除了未开始游戏优先准入；v1 为照顾陌生游戏覆盖，保留了 Franzen 的这项机制。v1 是未经对照验证的组合，不能把 31.54 当作它的预期分数。

来源：[Franzen 实验说明](https://github.com/da-fr/arc-agi-3-solution/blob/main/WRITEUP.md)、[Affectify](https://www.kaggle.com/code/shiiin9/affectify-arc-31-54-in-a-single-sub)、[同版本复现审计](https://www.kaggle.com/code/skarin/arc-agi-3-27-80-lb-100-trajectory-audit)。

## 发现的调度风险

v1 公式为 `即时收益 × pace × patience + 剩余关卡奖励 × 时间衰减`。消耗增加会降低 patience，但剩余关卡奖励不乘 patience。长期卡在第一关的游戏仍保留较大的剩余关卡奖励。

用实际代码计算静态样例：均为 10 关游戏，v1 的已观察 pace 为 30,000 token/完成关卡，原版 pace 为默认 1。

| 场景 | Franzen 优先级 | v1 前期优先级 | v1 尾部奖励完全衰减后 |
| --- | --- | --- | --- |
| 第一关卡住，150 动作、250,000 token | 61 | 16,036 | 36 |
| 正在第十关，30 动作、20,000 token | 193 | 3,874 | 3,874 |

两个公式的缩放不同，不能横向比较大小，应看同一列的排序。原版把第十关排在卡住的第一关前面，v1 前期却相反。这说明 v1 可能过度照顾没有进展但剩余关卡多的游戏。

未开始游戏的高准入优先级还会在槽位交接时延迟已有进展的游戏继续求解。它改善覆盖，但是否值得，需要实测覆盖率、等待时间和过关收益。

以上是代码机制与静态检查，**不是对 24.22 分的因果归因**；实际调度还受热缓存、历史裁剪和可用槽位影响。样例在 `scheduler-scenarios.json`。此次 `competitions episodes` 返回 No episodes found，Submission API 未提供逐游戏轨迹；已有本地事件来自公开短测，不能冒充正式隐藏集记录。

## 短测的边界

四个公开游戏各运行五分钟：89 个动作、109,123 个生成 token、0 个完成关卡、得分 0。服务无异常的证据支持链路正常，没有高分证据。

四个游戏少于十个活跃槽位，也无法检验大量游戏竞争槽位时的预算分配效果。后续公开对照应更接近正式规模。

## 下一轮实验建议

1. 固定模型、输入版本、采样、游戏集合和总预算，先做原版 Franzen 与 v1 的配对对照；重复完整运行并保存逐游戏/逐关数据。
2. 分别试验未开始游戏的准入策略，以及卡住游戏的剩余收益惩罚；不要同时更换模型、服务、记忆和提示词。
3. 记录未启动比例、等待时间、token/完成关卡、完成关卡数、RHAE、缓存命中与裁剪次数，判断追加计算是否产生收益。
4. 用未参与调参的游戏/机制验证。当前公开榜仅提供反馈，最终目标仍是私榜 55 个未知游戏。

本次只分析成绩和同步文件，没有启动新 GPU 实验或提交 v2。

## 桌面项目

路径：`/home/jesse/桌面/arc-prize-2026`。

- 克隆团队远程 `concious1949/arc-prize-2026` 最新 `main`，commit `80815638ae06a6ec622029ff97b1fb0b77c529c6`，包含已合并的 PR #1。
- 抓取贡献仓库的 `feat/project-optimization-summary-20261009` 分支；其文档已合并进 main。
- v1 实验代码、提交记录和本文是本地新增文件，未推送远程。
- 构建/验证脚本使用实验目录自带的输入元数据和验证参考，可以从桌面运行；已提交 Notebook 的代码及 SHA256 保持一致。
