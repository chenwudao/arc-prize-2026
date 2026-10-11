# ARC3 V1 Dprime Coverage

第一版比赛候选，基于团队现有 Franzen Notebook。

仅改变调度评分：移植 Affectify D′ 的进度、动作消耗、生成 token 和过关速度公式，并让剩余关卡收益在最后 40% 时段衰减。保留 Franzen 的未开始游戏优先准入，以及历史裁剪时才交接槽位的机制。未使用游戏 ID、公开/私榜归属或任何隐藏答案。

模型、量化、服务、上下文、10 个活跃流、动画/差分/UNDO 和函数复用沿用基线。这个组合已取得一次公开榜成绩 24.22，不能将 Affectify 的 31.54 作为本版本成绩。

## 验证和运行

- `python3 build.py` 从原基线生成 `upload/` 下私有 Notebook 和元数据。
- `python3 verify.py`：六项检查通过，包括与原作者公式数值一致、真实准入队列的未开始游戏优先顺序、缓存优先级边界、独立游戏的 pace 状态、Notebook 编译和正式/测试分支。
- 原基线 harness patch 在下载的原始 source bundle 上 `git apply --check` 通过；检查日志 `patch-check.log`。
- Kaggle Save & Run：四个公开游戏，各五分钟，单 pass；仅检查 GPU 服务和完整动作链路。
- 正式重跑：从比赛 gateway 发现完整游戏集合，单 pass、120 个候选会话、10 个活跃流、原版 532 分钟每游戏会话预算，Notebook 最长九小时。配额/动作/评分由官方环境管理。

输入元数据在 `upload/kernel-metadata.json`，代码哈希在 `manifest.json`。版本和远端提交状态将在 `submission-status.json` 记录。

Kaggle： https://www.kaggle.com/code/jessewudao/arc3-v1-dprime-coverage

## 本次结果

2026-10-09，Kaggle Notebook v1 短测状态 COMPLETE。服务在约 511 秒后就绪；四个游戏执行 89 个动作，记录约 10.9 万生成 token。五分钟内全部未过关，分数为 0，仅证明推理/动作/保存链路跑通，不构成高分或改进效果证据。服务日志扫描未发现 ERROR、Traceback 或 OOM。

正式提交 **56988179**，提交时间 2026-10-09 03:19:03 UTC（北京时间 11:19:03）。2026-10-10 查询：状态 COMPLETE，公开榜成绩 **24.22**，当前账号排名 1108；私榜成绩未公布。完整分析见 `docs/2026-10-10-v1-score-analysis.md`。后续可用 `kaggle competitions submissions arc-prize-2026-arc-agi-3 --format json` 查询。

## 来源

- Franzen： https://github.com/da-fr/arc-agi-3-solution
- Affectify： https://www.kaggle.com/code/shiiin9/affectify-arc-31-54-in-a-single-sub
- Tufa Duck： https://github.com/Tufalabs/duck-harness

保留来源说明；第三方代码和权重的原有许可继续适用。此版本为个人账号私有比赛试验，未推送团队 GitHub。
