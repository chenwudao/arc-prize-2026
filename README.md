# ARC Prize 2026 — ARC-AGI-3 团队仓库

Kaggle 比赛 [ARC Prize 2026 - ARC-AGI-3](https://www.kaggle.com/competitions/arc-prize-2026-arc-agi-3/overview) 的团队协作仓库。

目标：构建能在隐藏交互环境中快速适应新任务的 agent（流体智能），不可记忆答案。

## 比赛硬约束（写代码前必读）

- Notebook 提交制：CPU/GPU notebook 均限时 ≤ 9 小时
- 提交时断网（Internet disabled）
- 允许接入公开可得的外部数据与预训练模型（含 quantized 权重）
- submission.parquet 由 agent 实际游玩自动生成
- ARC-AGI-3 专属硬件：RTX Pro 6000（g4-standard-48），断网运行

## 时间线（UTC 11:59 PM）

| 日期 | 事件 |
|---|---|
| 2026-10-26 | Entry deadline（必须接受规则）+ 组队/合并截止 |
| 2026-11-02 | 最终提交截止 |
| 2026-12-04 | 获奖公布 |

## 当前路线：复现 + 改进 Milestone 获奖方案

以 Milestone 2 获奖方案（Daniel Franzen，金牌 34.30）为基线：

- 获奖 notebook：https://www.kaggle.com/code/dfranzen/arc-agi-3-milestone-2-solution
- Franzen write-up：https://www.kaggle.com/writeups/dfranzen/arc-agi-3-milestone-2
- Franzen GitHub（完整方案）：https://github.com/da-fr/arc-agi-3-solution
- 基座 harness：Tufa Labs Duck Harness（6/30 里程碑获奖）
  - GitHub: https://github.com/Tufalabs/duck-harness
  - Write-up: https://www.kaggle.com/competitions/arc-prize-2026-arc-agi-3/discussion/717133
- 模型：Qwen3.8-Flash-Next（W4A16 AutoRound 量化 + MTP draft 投机解码，SGLang Pennyroyal fork 本地推理）

## 目录结构

```
src/        # 自研代码（solver 改动、工具、实验脚本）
notebooks/  # Kaggle notebook 副本与版本（提交用）
agents/     # agent 策略层：prompts、vision、guards、调度
docs/       # 方案调研笔记、write-up 精读、实验记录
```

## 协作流程

1. `git clone https://github.com/concious1949/arc-prize-2026.git`
2. 建分支开发：`git checkout -b feat/xxx`（分支名用 `feat/` `fix/` `exp/` 前缀）
3. 提交并推送：`git push -u origin feat/xxx`
4. 在 GitHub 上发 Pull Request，review 后合入 main
5. 也可 fork 本仓库后提 PR（公开仓库支持 fork）

约定：
- 大文件（模型权重、数据集）不入库，只记录下载脚本/路径
- notebook 修改请附带跑出来的分数（public/private）
- docs/ 下按主题建 md 记录实验结论，避免只在聊天里讨论

## 本地环境

- Kaggle CLI 已配置（`~/.kaggle/kaggle.json`）
- 拉取获奖 notebook：`kaggle kernels pull dfranzen/arc-agi-3-milestone-2-solution -p notebooks/dfranzen`
- 推送前注意走代理（campus network）
