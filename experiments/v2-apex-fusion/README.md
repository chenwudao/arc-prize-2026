# ARC3 V2 Apex Fusion

第二版比赛候选，基于团队 Franzen 基线与 Affectify / Yukai Liu 完整 D′ 调度架构。

## 核心改进与设计逻辑

1. **完整对齐 D′ 优先级公式**：
   - 采用 $A \cdot M \cdot C + B \cdot \phi$ 连续非线性收益模型。
   - $A$: 深度线性收益 $\times$ 动作效率 2.5 次方衰减。
   - $M$: 真实观测的通关 Pace（`FormPace`）动态调节系数 $[0.25, 4.0]$。
   - $C$: 动作数（115 步缩放）与 Token 消耗（22.5 万缩放）的综合耐心衰减。
   - $B \cdot \phi$: 剩余关卡延续收益在最后 40% 时间窗口内（$\phi \to 0$）平滑衰减至 0，全力收割当前手头关卡。
2. **彻底修复 v1 调度门禁缺陷（`install_d`）**：
   - 取消 Franzen 粗暴的 `2,000,000 - 顺序` 强制准入机制（v1 正是因为保留了该机制导致新游戏无脑抢占活跃槽位）。
   - 在 `_PriorityGate.acquire` 处拦截新游戏准入请求，按其 $D'$ 初始期望快照（$\ell=1, a=0, t=0$）平滑排序入队。
3. **策略超时审计（Strategy-Audit）**：
   - 当单关累计动作数 $\ge 24$ 仍未通关时，自动在用户提示中追加审计警示，提示模型反思目标假设并尝试 `UNDO` 或 `RESET`，保护 RHAE 平方动作效率指标。

## 验证与状态

- **本地测试**：`python3 verify.py` 4 项单元测试全部通过（含与公开 D′ 数值基准 100% 对齐、FormPace 统计、Gate 拦截及策略审计触发测试）。
- **Notebook 构建**：`python3 build.py` 生成 `upload/arc3-v2-apex-fusion.ipynb` 及 `kernel-metadata.json`，全量代码通过 AST 静态语法检验。
- **Kaggle Kernel**：[`jessewudao/arc3-v2-apex-fusion`](https://www.kaggle.com/code/jessewudao/arc3-v2-apex-fusion)
- **运行状态**：已推送 Kaggle 并触发 RTX PRO 6000 远程执行（`KernelWorkerStatus.RUNNING`）。
