# ARC3 V3 Cognitive Guard

第三版比赛候选，基于 V2 Apex Fusion（LB 28.04）的完整 D′ 调度架构，全面启用 Level 1 认知防御（Cognitive Guards）、死循环拦截与策略超时审计（Strategy-Audit）。

## 核心改进与设计逻辑

1. **延续 V2 完整 D′ 调度架构**：
   - 采用 $A \cdot M \cdot C + B \cdot \phi$ 连续非线性期望收益模型。
   - 彻底废除 2,000,000 新游戏硬优先级抢占，由 `install_d` 实现真正的平滑准入。
   - `FormPace` 动态关卡耗费观测与最后 40% 时间窗口的尾部衰减（$\phi \to 0$）。
2. **启用 Level 1 认知防御（Cognitive Guards）**：
   - Franzen 原版基线将 `ARC3_GUARDS_FROM_LEVEL` 默认为 2，导致 Level 1 处于完全无防御状态，极易在第 1 关陷入无效空操作（no-op）或反复试错死亡。
   - V3 将 `ARC3_GUARDS_FROM_LEVEL` 调整为 1，确保从第一关起就受到防死锁与防无效动作保护。
3. **全面激活防死循环卫士（Anti-Loop Guards）**：
   - `ARC3_NOOP_REPEAT_GUARD=1`：对相同棋盘状态下已证实为无效（no-op）的动作进行精准拦截，避免浪费宝贵的动作配额。
   - `ARC3_DEATH_REPEAT_GUARD=1`：拦截导致死亡的相同动作路径，杜绝重复踏入同一陷阱。
   - `ARC3_DEATH_LEDGER=1`：建立死亡状态账本，跨回合记忆致死状态。
4. **安全加固的策略超时审计（Strategy-Audit）**：
   - 针对 `ToolAgent._build_user_prompt` 采用自适应透明包装器（兼容所有参数签名），当单关累计动作数 $\ge 24$ 时注入认知干预提示：
     `[STRATEGY AUDIT]: High action count on this level without progression. Stop repeating similar action sequences. Re-examine the board for overlooked objects or mechanics, and consider testing UNDO or RESET...`
   - 保护比赛核心指标——相对人类动作效率（RHAE 平方惩罚 $\min(115, 100 \times (\text{Human}/\text{Agent})^2)$）。

## 验证与状态

- **本地测试**：`python3 verify.py` 4 项单元测试全部通过（D′ 数值基准 100% 对齐、FormPace 统计、Gate 拦截、Strategy-Audit 多签名及触发测试）。
- **Notebook 构建**：`python3 build.py` 生成 `upload/arc3-v3-cognitive-guard.ipynb` 及 `kernel-metadata.json`，全量代码通过 AST 静态语法检验。
- **Kaggle Kernel**：[`jessewudao/arc3-v3-cognitive-guard`](https://www.kaggle.com/code/jessewudao/arc3-v3-cognitive-guard)
- **运行状态**：已推送 Kaggle 触发 RTX PRO 6000 远程烟雾测试（`KernelWorkerStatus.RUNNING`）。
