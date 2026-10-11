# ARC3 V3 Cognitive Guard: 架构设计与理论假设 (2026-10-11)

## 1. 背景与现状

在第二版候选 V2 Apex Fusion（ID: 57062234）中，我们成功对齐了 Affectify / Yukai Liu 的完整 $D'$ 期望收益调度公式，并彻底消除了 Franzen 遗留的 2,000,000 新游戏硬优先级抢占缺陷。
**公共榜得分由 V1 的 24.22 跃升至 28.04（排名前移 357 名至第 751 位）**，超越了 Daniel Franzen 原作者基准（27.89）。

然而，深入分析 Franzen 原型数以百计副本的评测分布（均值 25.77，标准差 3.93，上四分位数 31.54，极值 34.30）可以发现：
- 34.30 分**并非**来自新的模型或感知架构，而是 Franzen 代码随机漫步中恰好避开了死亡陷阱与死循环的“上尾幸存者（Top 1% draw）”。
- **当前瓶颈（28.04 到 35 分的关键差距）**：
  1. **动作通胀与平方惩罚**：比赛核心评价指标 RHAE 为：
     $$\text{Efficiency} = \min\left(115, 100 \times \left(\frac{\text{Human Actions}}{\text{Agent Actions}}\right)^2\right)$$
     当 Agent 在某一关卡动作数超过人类基准（如 12 步）达到 25 步时，效率由 $100\%$ 暴跌至 $(12/25)^2 \approx 23\%$；若耗费 40 步则仅剩 $9\%$。
  2. **Level 1 防御真空**：Franzen 源码中默认将 `ARC3_GUARDS_FROM_LEVEL` 硬编码为 `2`。这意味着在关卡 1，模型完全没有防无效动作（no-op）与防重复死亡的保护，大量活跃游戏在第 1 关就消耗了数百步甚至遭遇死循环。
  3. **死循环与重复无用动作**：Harness 内置了 `ARC3_NOOP_REPEAT_GUARD`、`ARC3_DEATH_REPEAT_GUARD` 和 `ARC3_DEATH_LEDGER`，但在基准中默认处于未启用（`False`）状态。

---

## 2. V3 核心改进架构

### 2.1 启用 Level 1 认知防御与防死循环卫士
- **`ARC3_GUARDS_FROM_LEVEL = 1`**：降低防御门槛，让第 1 关同等享受防死循环和无效动作拦截保护。
- **`ARC3_NOOP_REPEAT_GUARD = 1`**：实时比对当前棋盘哈希与历史尝试，一旦模型试图执行已知无变化的动作，立即拦截并告知模型，节约动作步数。
- **`ARC3_DEATH_REPEAT_GUARD = 1`**：在相同棋盘状态下，拦截曾导致 Game Over 的动作，避免二次死亡。
- **`ARC3_DEATH_LEDGER = 1`**：建立跨回合死亡账本，记录所有致死状态。

### 2.2 策略超时认知审计（Strategy-Audit）
- 借鉴顶级解法（如 Lord Han Solo 的反思审计机制），在 `ToolAgent._build_user_prompt` 中挂载非侵入式自适应包装器。
- 当且仅当单关累计动作数达到 $\ge 24$ 且尚未通关时，主动向模型注入高优先级认知反思指引：
  ```text
  [STRATEGY AUDIT]: High action count on this level without progression. 
  Your working hypothesis may be incomplete or invalid. Stop repeating similar action sequences. 
  Re-examine the board for overlooked objects or mechanics, and consider testing UNDO or RESET 
  if you have reached an irreversible or dead-end board state.
  ```
- 促使大模型及时跳出局部极值假说，主动尝试 `UNDO` 或 `RESET` 恢复到干净状态，从而拯救濒临归零的 RHAE 指标。

### 2.3 保持底层模型与推理底座零风险
- 保留 Pennyroyal v253 运行时与 Intel Qwen3.8 Flash-Next W4A16 AutoRound 权重不变。
- 保留完整的 $D'$ 调度公式与 `FormPace` 动态关卡耗费观测。

---

## 3. 理论收益预期

| 模块 | 机制 | 预期动作节约率 | 预期对 RHAE 效率提升 |
| :--- | :--- | :---: | :---: |
| Level-1 Guards | 消除第 1 关无效探索与自杀循环 | 15% ~ 25% (Level 1) | +1.5 ~ +2.0 分 |
| Anti-Loop / Death Ledger | 拦截已知致死与无变化动作 | 10% ~ 15% (全局) | +2.0 ~ +3.0 分 |
| Strategy-Audit | $\ge 24$ 步强制反思，触发 UNDO/RESET | 避免极端 60+ 步拖垮均值 | +1.0 ~ +2.0 分 |
| **综合预期** | **压低均值方差，提升分布期望** | **平均动作减少 20%+** | **预期冲击 32.0 ~ 35.0+** |

---

## 4. 实施流程与提交策略

1. **构建与离线检验**：
   - `scheduler.py` 实现自适应签名与守卫参数设置。
   - `verify.py` 4 项单元测试（D' 数值对齐、FormPace、Gate 拦截、Strategy-Audit 签名兼容）100% 通过。
   - `build.py` 注入 Cell 4 守卫参数与 Cell 17 调度补丁，全量代码通过 AST 语法检验。
2. **Kaggle GPU 烟雾测试**：
   - 目标 Slug：`jessewudao/arc3-v3-cognitive-guard`。
   - 机器配置：NvidiaRtxPro6000 (96GB VRAM)。
   - 离线 4 局 Smoke Test 验证环境启动与无异常报错。
3. **正式比赛提交**：
   - 每日比赛正式提交重置时间：UTC 00:00:00（北京时间 08:00）。
   - 在配额重置后（或确认有配额时）一键提交 `submission.parquet`。
