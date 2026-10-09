# 项目调研与优化变量总结

日期：2026-10-09。本文汇总团队项目理解、Kaggle CLI 接入、比赛与模型调研，以及可控变量和实验路线。

**证据边界：** 比赛页面、公开 Notebook、模型清单与评分运行时已读取；模型推理、正式提交和团队性能复现尚未执行。文中的公开成绩是作者报告或平台快照，不是本团队成绩。参数取值是基线配置或待验证实验建议，不代表最优值。

## 1. 项目现状与路线

- 比赛是 ARC-AGI-3 交互式推理：agent 观察画面、主动探索、理解规则、建立计划，在陌生游戏中完成关卡。
- 团队选择复现 Daniel Franzen 的 Milestone 2 方案，再做逐项改进。该方案建立在 Tufa Labs Duck Harness 上。
- 核查时，仓库有 Franzen 与 Tufa 两份参考 Notebook；`src/`、`agents/`、`docs/` 尚未形成自研实现或实验记录。
- 仓库里的 Franzen Notebook 代码单元与本次 CLI 拉取的最新公开副本一致。
- 按仓库约定，通过 `feat/`、`fix/`、`exp/` 分支和 PR 协作；权重、比赛数据和运行产物不加入 Git。

README 提及 34.30，作者公开 write-up 报告 27.89。公开 Notebook 页面、团队排行榜与不同运行版本的分数可能不是同一口径；目前没有证据支持把 34.30 当作这份代码稳定可复现的成绩。团队基线必须记录自己的完整运行、版本和实际分数。

## 2. Kaggle CLI 与比赛约束

本次工作环境已安装 Kaggle CLI 2.2.4，版本与依赖检查通过，之后的账号认证及 API 访问也已验证。已读取比赛页面、文件清单、公开 Notebook 元数据、模型文件清单与排行榜，并下载一个小型评分运行时 wheel；没有上传 Notebook 或执行比赛提交。

这是本次工作环境的状态，不代表其他成员的机器已配置。新成员可按官方说明安装独立 CLI 环境并认证：

```bash
# 安装方式二选一；需预先安装相应工具
uv tool install kaggle
# 或 pipx install kaggle

kaggle auth login
kaggle competitions list --group entered -s arc-prize-2026
kaggle competitions files arc-prize-2026-arc-agi-3
```

账号凭证保存在个人环境中，不加入仓库。GitHub 协作与 Kaggle 比赛组队需要分别设置。

| 约束 | 核查结果 |
| --- | --- |
| 提交方式 | Kaggle Notebook |
| 运行预算 | CPU/GPU 最长 9 小时 |
| 网络 | 提交评测时关闭 Internet |
| 外部资源 | 允许公开可获得的外部数据与预训练模型；还需符合赛事相关要求 |
| 每日正式提交 | 1 次 |
| 最终可选提交 | 2 个 |
| 团队上限 | 8 人 |
| 比赛硬件公告 | `g4-standard-48`，RTX PRO 6000 Blackwell Server Edition |

Google 官方规格中，`g4-standard-48` 配有 48 vCPU、180GB 主机内存和一张 96GB 显存 GPU。实际运行仍需记录设备信息，不应与旧款 48GB RTX 6000 混淆。

| 截止事项 | UTC | 北京时间 |
| --- | --- | --- |
| 接受规则、组队/合并 | 2026-10-26 23:59 | 2026-10-27 07:59 |
| 最终提交 | 2026-11-02 23:59 | 2026-11-03 07:59 |

时间、硬件、配额和平台规则可能更新，临近实验或提交时再次核查官方页面。

## 3. 核心优化目标

**在固定时间、断网和硬件预算下，提高陌生游戏上的平均 RHAE：完成更多、更深的关卡，同时用更少的环境动作。**

本次比赛文件清单包含 25 个公开游戏；官方数据说明写明正式评测另用 110 个隐藏游戏，公开榜和私榜各使用一半。公开开发集指标与公开排行榜成绩必须分别记录。

已读取比赛附带 `arc_agi-0.9.8` wheel 的 `arc_agi/scorecard.py`，其单关百分制评分为：

```text
未完成关卡：0
完成关卡：min(115, 100 × (human_baseline_actions / agent_actions)²)
```

游戏内按关卡编号加权，再受完成关卡的加权比例限制；最终聚合各游戏成绩。后面关卡的权重更大。

例如，人类基准为 10 步：agent 用 20 步，关卡效率分为 25%；用 100 步，只有 1%。内部推理和只读观察不直接计入环境动作数，但会消耗时间与 token。

**评分文档存在一处差异：** Kaggle 数据页简述将效率截断到 1.0；实际读取的运行时和官方评分文档允许单关最高 1.15，再限制游戏整体分数。评测器应对齐运行时实现，并固定版本。

因此，tokens/s、缓存命中率和生成长度是解释性能的中间指标；最终比较仍是相同预算下的得分、完成深度和动作效率。

## 4. 当前基线的模型与部署

| 组件 | 固定引用 | 用途 |
| --- | --- | --- |
| 主模型 | `dfranzen/intel-qwen3.8-flash-next-w4a16-autoround/Transformers/default/1` | 视觉观察、规则推理、规划与 Python 工具调用 |
| MTP draft | `dfranzen/albucino-qwen3-8-flash-next-drafter/Transformers/default/1` | 辅助投机解码 |
| 推理运行时 | `dfranzen/pennyroyal-v253` | 离线 SGLang Pennyroyal 部署 |
| 源码 bundle | `dfranzen/taaf-kaggle-source-bundle-copy` | Duck Harness 原始源码，由 Notebook 应用补丁 |
| 比赛输入 | `arc-prize-2026-arc-agi-3` | ARC wheels 与公开环境等 |

Qwen 官方卡标注：主体 125B 参数、每次激活 6B，另有 51B n-gram embedding 与 4B MTP。每次激活参数少，不代表只需要存储 6B 权重。

Franzen 部署使用 W4A16 AutoRound，配合 PLE embedding 主机内存卸载、MTP draft 和专用 SGLang fork。Kaggle 文件清单合计主模型约 181.24GB，draft 约 4.16GB；这是输入文件体积，不是 GPU 显存占用。本次没有下载大型权重。

本地较小显存设备适合工具验证和日志分析；完整基线优先在比赛硬件上复现。较小模型的功能验证需单独登记，不能替代主基线成绩。

模型卡标注 `qwen-community-1.0`；赛事获奖要求另有系统、模型及权重的开放条款。本次没有对具体方案的获奖许可资格作判断。

### 部署与提交容易混淆的地方

- Notebook 的源码并非全部依赖，模型、离线 wheelhouse 与源码 bundle 必须一起固定。
- 公开副本元数据固定了容器摘要；比赛输入有多个 `cp312` wheel，需核对实际 Python 版本兼容性。
- 普通运行玩公开环境，结束时写占位 `submission.parquet`；文件存在不代表获得比赛成绩。
- 正式提交通过 `KAGGLE_IS_COMPETITION_RERUN` 分支连接 gateway，运行隐藏游戏。
- `kernels push` 上传并启动 Notebook，不自动完成比赛提交。

## 5. 能改动的变量

### 5.1 模型与生成方式

| 变量 | 当前基线 | 影响与实验重点 |
| --- | --- | --- |
| 主模型 | Qwen3.8-Flash-Next | 视觉、推理与代码质量；可将 Qwen3.8-27B 作为待验证对照候选 |
| 权重量化 | W4A16 AutoRound | 内存、速度和精度，收益取决于硬件与算子支持 |
| draft 模型 | Albucino MTP | 接受率、加速效果和额外占用；需与主模型兼容 |
| 思考模式 | 开启 | 单轮成本与判断质量 |
| 最大输出 | 12,288 tokens | 推理上限、截断频率和决策成本 |
| temperature / top-p / top-k | 0.7 / 0.95 / 20 | 探索多样性、稳定性与运行波动 |

换主模型时，还需适配 tokenizer、聊天模板、视觉处理、工具/推理输出格式及服务端；不能仅替换路径。模型更小、更快是否有益，要比较相同总预算下的完成深度和动作效率。

### 5.2 推理服务与上下文

| 变量 | 当前基线 | 影响与取舍 |
| --- | --- | --- |
| 活跃模型请求 | 10 | 总吞吐、排队和缓存竞争 |
| harness 上下文 | 128Ki | 历史保留、输入计算和缓存占用 |
| 服务端上下文 | 136Ki | 服务容量，需与 harness 及输出预算配套 |
| 历史裁剪目标 | 58Ki | 裁剪后信息保留与前缀重复计算 |
| KV dtype | FP8 E4M3 | 缓存容量与数值精度 |
| Mamba 缓存 | 60 槽位 | 混合架构的状态复用 |
| 静态显存比例 | 0.96 | 缓存池与运行时空间分配 |
| chunked prefill | 8,192 tokens | 长输入的峰值资源与处理延迟 |
| speculative steps | 3 | 候选长度、验证成本和接受率 |
| 加载、预取、缓存策略 | 已有专项优化 | 启动时间和剩余可用游戏时间 |

这些变量有耦合，不应全部向大值调整。例如，并发过高可能驱逐前缀缓存；缩短上下文可能提高速度，也可能使 agent 忘记已学规则。量化或投机解码的收益需要在实际工作负载上测量。

正式运行的 `solver.concurrency=120` 表示可以管理大量游戏会话，真正同时进入模型的活跃请求为 10。二者是不同层的控制变量。

当前基线是专门修改的 Pennyroyal fork；最新 SGLang 文档用于理解参数，实际支持和行为以固定部署版本为准。

### 5.3 Agent 策略

| 变量 | 主要作用 |
| --- | --- |
| 游戏优先级与调度 | 将时间分配给仍可能推进的游戏 |
| 每关思考、动作与停止预算 | 平衡持续探索和及时转移资源 |
| 图像缩放、差分、动画 | 在观察成本与信息完整性之间取舍 |
| 批量行动长度及中途验证 | 减少调用成本，同时避免执行失效计划 |
| 无效动作与死亡循环保护 | 减少浪费的环境动作 |
| 跨关记忆与辅助函数保留 | 复用已学机制和工具，避免重复生成 |
| 提示词、对象表示与 Python 工具 | 支持可验证假设与短路径规划 |

基线已经开启 10 倍画面缩放、差分图、动画、UNDO、部分无效动作保护和游戏内函数保留。`ARC3_MEMORY_SECTIONS=off` 只表示原有结构化文本世界模型机制关闭，不代表全部记忆关闭。

## 6. 公开方案比较

| 方案 | 与基线的主要差异 | 目前能得出的结论 |
| --- | --- | --- |
| Franzen Milestone 2 | 主基线：模型、服务、工具与调度整合 | 需要团队自己的原版完整复现 |
| Affectify D′ | 相同模型，主要替换模型槽位的调度优先级公式 | 作者报告单次 31.54，并明确不足以证明稳定提升；适合单因素对照 |
| sujanmajhisuzan M2 top | 相同模型，多项跨关记忆、反循环、死亡提醒与部署调整 | 已检查代码与输入，未验证性能；应拆开测，不能用标题中的 SOTA 代替证据 |

Affectify 的普通保存运行只使用一个公开游戏约 5 分钟，而 Franzen 最新公开副本安排 25 游戏×4 次开发运行。比较时必须统一集合、预算与运行模式。

三份已检查公开方案使用同一主模型，支持先研究策略与调度的实验路线，但不证明这个模型是比赛中的最优选择，也不能从公开排行榜反推未公开方案的方法。

## 7. 实验指标与推荐顺序

每次运行记录代码提交、Notebook 版本、容器摘要、模型和输入版本、全部配置、游戏集合、预算、随机种子（如适用）及日志。

| 指标层 | 最少记录内容 |
| --- | --- |
| 最终效果 | RHAE、完成关卡数、各关动作数、各游戏分数 |
| Agent 行为 | 重复死亡、无效动作、卡住位置、工具错误和提前终止 |
| 推理性能 | 启动时间、总生成吞吐、请求延迟、前缀缓存复用、投机接受率 |
| 资源与稳定性 | 显存/内存峰值、等待时间、异常退出数 |

建议的实验顺序，**尚未执行**：

1. 固定原版模型、输入与服务配置，完成公开环境运行及一次正式评测，建立团队基线。
2. 比较原调度与 D′：相同模型、游戏集合和总预算，分析每个游戏得到的计算量与进展。
3. 比较活跃请求数，例如 6、8、10，测吞吐、缓存及最终得分；这只是候选网格，不是已验证建议值。
4. 比较上下文和输出预算，配套调整服务容量，并记录丢失信息、截断和重复计算。
5. 从失败轨迹出发，逐项改进无效循环、死亡循环、跨关旧计划和遗漏动画。
6. 最后做模型与量化对照，连同加载、部署、质量及动作成本一起比较。

先用短流程验证排除加载和工具链错误，再做完整公开集评测。初步有收益的改动进行重复运行，最后再比较组合效果。每天一次正式提交优先使用已完成开发验证的版本。

## 8. 官方与原作者参考

- [比赛概览与约束](https://www.kaggle.com/competitions/arc-prize-2026-arc-agi-3/overview)
- [比赛规则](https://www.kaggle.com/competitions/arc-prize-2026-arc-agi-3/rules)
- [官方 RHAE 评分](https://docs.arcprize.org/methodology)
- [Kaggle CLI 安装与认证](https://github.com/Kaggle/kaggle-cli/blob/main/docs/README.md)
- [Franzen Notebook](https://www.kaggle.com/code/dfranzen/arc-agi-3-milestone-2-solution)
- [Franzen 完整源码与 write-up](https://github.com/da-fr/arc-agi-3-solution)
- [Affectify D′ Notebook](https://www.kaggle.com/code/shiiin9/affectify-arc-31-54-in-a-single-sub)
- [M2 top Notebook](https://www.kaggle.com/code/sujanmajhisuzan/arc-agi-3-m2-top-submission)
- [Qwen3.8-Flash-Next 模型卡](https://huggingface.co/Qwen/Qwen3.8-Flash-Next)
- [Qwen3.8-27B 模型卡](https://huggingface.co/Qwen/Qwen3.8-27B)
- [Google G4 硬件规格](https://docs.cloud.google.com/compute/docs/accelerator-optimized-machines#g4-machine-types)
- [SGLang 服务参数](https://docs.sglang.io/docs/advanced_features/server_arguments)
- [SGLang 投机解码](https://docs.sglang.io/docs/advanced_features/speculative_decoding)
