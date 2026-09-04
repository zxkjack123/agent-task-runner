# Revision Disposition — ATR Consumer Contract

> PM #3263 T3.2 — ATR-owned specification. The **producer** (upstream that
> writes `mode` / `plan_patch` into the task card) is explicitly
> OUT-OF-SCOPE for this repository.

## ① 背景定位 (Background)

ATR (`loop_kit`) is the **consumer** of a revision-disposition signal: the
task card carries `mode` and, for patch-mode tasks, a `plan_patch` contract.
ATR validates, renders, and post-verifies that contract; it does **not**
author the disposition schema on behalf of the upstream producer.

As of 2026-09-03, the `copilot-agents` repository contains **no**
`revision_disposition` symbol (grep 0 hits) — any conclusion of the form
"the interface should be implemented upstream" must be recorded here and
never implemented in this repo.

## ② mode 枚举语义表 (Mode Enum Semantics)

| mode | 语义 | ATR 行为 |
|------|------|----------|
| `generate` | 缺省：常规生成任务 | 全功能 worker→reviewer 流程；无 plan_patch 契约 |
| `patch` | 按计划打补丁 | 强制 `plan_patch` 契约；动态渲染契约段；worker 完成后 `_verify_plan_patch_scope` 后置硬闸（fail-closed，违例 exit 6 子进程层 / 父进程归一 exit 3，零重试） |
| `revise` | 修订已有产物 | 与 generate 同路径；预留差异语义 |
| `rebuild` | 重建 | 与 generate 同路径；预留差异语义 |

非法值在 `_validate_task_card_contract` 层拒绝（`ConfigError`），零行为漂移。
`_TASK_MODES` 常量（T2.1 定义）与本表及 T3.2 实现点三处一致，变更须三处同步。

## ③ plan_patch 键 schema (Plan Patch Contract Schema)

```yaml
plan_patch:            # 仅 mode=patch 时允许出现；缺失 + mode=patch → fail-closed
  allowed_files:       # [Required] repo-relative 路径列表（含计划文件自身）
    - ".github/plans/xxx.md"
  allowed_anchors:     # [NotRequired] 计划文件内锚点白名单
    - {file: ".github/plans/xxx.md", line: 120}      # 单行
    - {file: ".github/plans/xxx.md", heading: "Phase 2"}  # 标题节（首现位置起，±200 行窗口）
  forbid_new_files: true   # [默认 true] 禁止新建白名单外文件
```

约束：`allowed_files` 非空且每项为字符串；`allowed_anchors` 每项 `file` 必填
且 `line`/`heading` 恰好其一；结构违例 → `ConfigError`（fail-closed，宁拒勿放）。

## ④ 消费点 (Consumption Points)

| 层 | 机制 | 状态 |
|----|------|------|
| 契约校验 | `_validate_task_card_contract`（T2.1） | ✅ 已实现 |
| prompt 渲染 | `_render_task_card_section` 动态注入契约段（仅 patch 模式；静态模板零改动） | ✅ 已实现 |
| 后置硬闸 | `_verify_plan_patch_scope`（T2.3；事实源 `base_sha..head_sha`） | ✅ 已实现 |
| 事件观测 | feed `task_mode` / `plan_patch_verify` / `plan_patch_violation` / `timeout_class` | ✅ 已实现（T3.1） |
| summary 落盘 | `summary.json` 可选 `budget` 块（含 `task_mode`，仅启用时写入） | ✅ 已实现（T3.1） |
| 退出码分层 | `EXIT_PLAN_PATCH_VIOLATION=6` 仅子进程层；父进程归一 exit 3 | ✅ 已实现 |

## ⑤ 生产者最小实现建议 (Producer Guidance — INFORMATIONAL ONLY)

上游（PM 闭环/计划编排侧）若需要 `revision_disposition` 语义，建议最小实现
仅为：写 task card 时提供 `mode`（四值之一）与 `plan_patch`（patch 模式
必填）。ATR 不依赖任何其他上游字段；此处建议不构成对 copilot-agents
或其他仓库的实现要求。

## ⑥ 维护声明 (Maintenance Statement)

- 本契约由 T2.1（校验实现）、T3.2（本文件）共同维护。
- `mode` 枚举变更必须同步：`_TASK_MODES`（T2.1）、本文件 §②、测试锁定。
- `budget` 块字段变更必须同步：D3 定义、T3.1 实现、`TestSummaryBudgetBlock`。
- copilot-agents 当前无 `revision_disposition` 符号——若未来引入，以本文件为
  规范性参考，但实现归属上层仓库。
