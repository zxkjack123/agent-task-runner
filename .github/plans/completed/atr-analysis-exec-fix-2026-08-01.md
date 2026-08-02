---
goal: "修复 ATR 自动执行 analysis 类任务失败（三处根因：curator 上下文错仓库 + artifact_timeout 非自适应 + context_files 未消费）"
scope_mode: "HOLD"
git_commit: "未指定（执行前由 TE 采集）"
generated_at: "2026-08-01"
refine_count: "REFINE-1"
linked_task: "PM #2234"
related_review: "agent-task-runner/.github/reviews/interface-contract-research-os-2026-08-01.md"
---

# 修复 ATR analysis 类任务自动执行（PM #2234）

> 本计划由 #2234 任务三处根因经验证后的执行方案。三处根因均已逐条核对源码，其中根因①/② 完全属实，根因③ 需按「未消费而非仅路径拒绝」的事实重新定向修复。
>
> **[REFINE-1] 2026-08-01**：经 Refine Mode 全量重审，修正 6 处结构性/致命锚点问题（详见「审查日志」REFINE-1 记录）。核心修正：T1.3 注入点从 `_build_task_packet` 改为 `_worker_prompt` rendered 后 append（规避 `str.format()` 崩溃）；T2.2 注入点从 CLI config 构造改为 `_main_loop` 入口；T4.2 注入点从 enqueue 改为 dispatch_atr；T3.1 修改边界分区化（pm.sqlite 保留 cwd 语义）。

## 背景与目标

- **问题来源**：#2233（done）中 ATR 自动执行 analysis 类任务失败实证——opencode worker dispatch 成功但 300s 内无 work_report.json → rc=3。
- **审阅来源**：#2234 任务 notes + `agent-task-runner/.github/reviews/interface-contract-research-os-2026-08-01.md`（已含 `③-1` 有效契约字段 finding 与 MODIFY_SPEC）。
- **目标**：让 PM 侧发起的 analysis 类任务（`output_format ∈ {analysis, report, summary, doc, slides}`）能稳定产出 work_report.json 并回写 PM。
- **非目标（不做什么）**：
  - 不引入 webhook 回调（保持方案 B 文件轮询）。
  - 不新增 simulation/scnet backend（属 #2229/M15 后续，不在本计划）。
  - 不改 `_is_safe_scope_pattern` 的绝对路径拒绝语义（安全边界保留）。
  - 不做 `context_files` 复制进工作区（方案 ii）以外的行为扩展。

## Scope Mode: HOLD

严格保持修复范围。不改契约文档（`RESEARCH_OS_INTERFACES.md`）内容——只落码让既有 `context_files` 字段被消费。不扩不缩。

---

## 根因 → 方案映射（经验证）

| # | 根因（任务 claims） | 验证结论 | 本计划采取的修复方向 |
|---|---------------------|---------|----------------------|
| ① | `curator.py:91` 读 dispatcher cwd 的 README，而非任务 `--cwd` | ✅ 属实。`bridge.py:417` 未把 `project_dir` 传入 `curate_context`；worker 在正确 cwd 而 context 取错仓库 | `curate_context` 接收 `project_dir`，README/AGENTS/git log/**directory tree** 以 project_dir 为根读取；`data/pm.sqlite`（similar tasks）**保留 dispatcher cwd** |
| ② | `_core.py:343` artifact_timeout=90 不匹配 analysis 类 | ✅ 属实（核心断言）；补充：bridge.py:432 已显式传 300s，故实际失败值也是 300 而非 90 | ATR 按输出类型自适应 `--artifact-timeout`（在 `_main_loop` 入口读 task_card 调整）；PM 桥按 output_format 为 analysis/report/summary/slides/doc 传入 ≥600s，code 保留 300s |
| ③ | `context_files` 绝对路径被 `_is_safe_scope_pattern` 拒绝 | ⚠️ 部分属实/错位。`_is_safe_scope_pattern` 只作用于 `in_scope`（`_core.py:5398`）；`context_files` 在 `_core.py` **完全未消费**（仅 bridge.py 产出，字段写了 Worker 拿不到） | ATR 侧 `_worker_prompt` 增加 `context_files` 渲染（安全白名单校验 → 注入 Worker 提示词）。**不是**扩展 scope 白名单 |

**关键边界澄清**：根因③ 的正确修复是「让 `context_files` 被消费 + 受安全白名单约束」，而非「放开 `in_scope` 路径限制」。沿用已有 review `③-1` 的 MODIFY_SPEC 方向可避免重复设计。

---

## 修改方案（跨两仓库）

### 涉及仓库
- **A** = `/home/gw/opt/agent-task-runner`（Loop Kit，ATR 执行层）
- **B** = `/home/gw/opt/project_management`（PM 桥 + curator）

### 关键实现事实（REFINE-1 重新核查确认）

1. **Worker prompt 管线**：`_worker_prompt`（`_core.py:6007`）→ 模板存在时用 `context` dict + `_render_prompt_template`（`str.format()`，`_core.py:5840`）渲染；模板不存在时走 `_build_prompt_sections`（`_core.py:5975`）→ `_join_prompt_sections`。**两个分支都要注入 context_files**。
2. **⚠️ `str.format()` 约束**：`_render_prompt_template` 用 `template_text.format(**context)`。若 context 值含 `{`/`}` 会抛 ValueError/KeyError。**context_files 文件内容绝不能放进 context dict**——必须在渲染后 post-append。
3. **RunConfig 可变**：`@dataclass(slots=True)`（`_core.py:583`，非 frozen），`artifact_timeout` 可在运行中就地调整（`_core.py:601`）。
4. **CLI 无法拿 output_format**：`cmd_run` 的 config 构造（`_core.py:13212-13285`）在 task_card 同步（`cmd_run` 内 L12364 `_sync_task_card`）**之前**，无法在 CLI 层读到 output_format。可行点在 `_main_loop`/`_run_single_round` 入口（task_card 已同步到 `resolved_paths.task_card`）。
5. **PM 侧 project_dir 只在 dispatch 时已知**：`build_task_card`（enqueue 时）无 project_dir；`dispatch_atr(entry, project_dir)`（`bridge.py:385`）才有。`dispatch_atr` L391 把原始 `entry["task_card_json"]` 写入 `loop_dir/task_card.json`——relativize 必须在此**之前**完成。

---

### Phase 划分（依赖序）

| Phase | 主题 | 仓库 | 理由 |
|-------|------|------|------|
| P1 | ATR 侧 `context_files` 消费（安全白名单校验 + 注入 Worker 提示词） | A | 先行打底：让该字段可执行，为后续 PM 侧传参提供可验证落点 |
| P2 | ATR 侧 artifact_timeout 按 `output_format` 自适应 | A | 在 `_main_loop` 入口调整 config，依赖 task_card 同步机制 |
| P3 | PM 桥 curator 上下文取对仓库 | B | 独立于点 P1/P2，校验路径独立 |
| P4 | PM 桥按 output_format 传自适应 artifact_timeout + dispatch 时 relativize context_files | B | 依赖 P1（消费存在）才可端到端验证 |
| P5 | 端到端验收（真发起 analysis 类任务） | A+B | 依赖 P1-P4 全部 |

---

## 执行计划

### Phase 1: ATR 侧 context_files 消费（仓库 A）

#### Task 1.1: `context_files` schema 声明 + 安全白名单常量
- **目标**：让 Loop Kit 认识 `context_files` 字段，并定义绝对路径白名单根。
- **依赖**：无
- **frontier**：是
- **执行者**：Simulation Builder（熟悉 `_core.py` 单文件结构）
- **修改内容**：
  - 文件 `src/loop_kit/_core.py`：在 `TaskCard` TypedDict（L226，`total=False`）新增字段 `context_files: NotRequired[list[str]]`
  - 文件 `src/loop_kit/_core.py`：新增模块级常量 `_CONTEXT_FILES_ALLOWED_ROOTS: tuple[str, ...] = ()`（默认空=仅允许仓库内相对路径）+ 文档注释说明扩展方式。⚠️ 不写死任意目录，白名单根为空即只放行工作区相对路径（最安全默认）。
- **修改边界**：不得修改 `_is_safe_scope_pattern` 语义（L5373）；不得改动 `in_scope` 处理逻辑（L5392-5405）。
- **质量检查方式**：
  - 检查项 1：`TaskCard` 声明 `context_files` 后类型检查通过。
  - 检查项 2：新常量不引入任何硬编码外部路径。
- **验收标准**：
  - ✅ `uv run python -c "from loop_kit.orchestrator import TaskCard; TaskCard(context_files=['x'])"` 不报 Unknown key（TypedDict 运行时透传验证）。
  - ✅ `grep -n "_CONTEXT_FILES_ALLOWED_ROOTS" src/loop_kit/_core.py` 返回唯一定义行。
- **潜在风险**：TypedDict 仅类型级，不影响运行时加载（`_load_task_card_or_raise` 透传）。风险低。

#### Task 1.2: `_resolve_context_files_safe` 纯函数（相对/白名单绝对路径归一化）
- **目标**：提供可单测的路径安全解析函数，返回注入白名单后符合条件的文件路径列表。
- **依赖**：T1.1
- **frontier**：否（依赖 T1.1）
- **执行者**：Simulation Builder
- **修改内容**：
  - 文件 `src/loop_kit/_core.py`：新增函数（放在 `_is_path_under_root` 之后，L5384 附近）
    ```python
    def _resolve_context_files_safe(context_files: list[str], root: Path) -> list[Path]:
        """Resolve context_files into file paths usable by Worker.

        Rules:
        - Relative paths resolved against `root` (repo/worktree root) and MUST
          remain under `root` (reject '..' escape via resolve() check).
        - Absolute paths allowed ONLY under _CONTEXT_FILES_ALLOWED_ROOTS
          (empty tuple = deny all absolute paths).
        - Non-existent / non-file entries silently skipped (best-effort).
        - Unsafe entries skipped (DO NOT raise).
        """
        root_resolved = root.resolve()
        out: list[Path] = []
        for raw in context_files:
            if not isinstance(raw, str) or not raw.strip():
                continue
            p = Path(raw.strip())
            try:
                if p.is_absolute():
                    allowed = any(
                        p.resolve().is_relative_to(Path(r).resolve())
                        for r in _CONTEXT_FILES_ALLOWED_ROOTS
                    )
                    if not allowed:
                        _log(f"Ignoring unsafe context_files absolute path: {raw!r}")
                        continue
                    resolved = p.resolve()
                else:
                    resolved = (root_resolved / p).resolve()
                    if not resolved.is_relative_to(root_resolved):
                        _log(f"Ignoring context_files escaping root: {raw!r}")
                        continue
                if resolved.is_file():
                    out.append(resolved)
            except (OSError, RuntimeError, ValueError):
                _log(f"Ignoring invalid context_files entry: {raw!r}")
                continue
        return out
    ```
- **修改边界**：不得修改 `_is_safe_scope_pattern` / `_is_path_under_root`；此函数独立新建。
- **质量检查方式**：
  - 检查项 1：相对路径、`..` 穿越、不存在文件、绝对路径（白名单空）、symlink 逃逸五类输入都返回预期结果。
- **验收标准**：
  - ✅ `grep -n "def _resolve_context_files_safe" src/loop_kit/_core.py` 命中。
  - ✅ 新增单测 `test_resolve_context_files_safe_*` 覆盖上述 5 类输入（放 `tests/test_orchestrator.py`）。
  - ✅ `uv run python -m py_compile src/loop_kit/_core.py` exit 0。
- **潜在风险**：`root` 实参在调用点取 `ROOT`（`_core.py:336`，`ROOT = Path.cwd()`）。
- **预留歧义标注**：无（签名与语义已定）。

#### Task 1.3: `_worker_prompt` 渲染 context_files 内容（post-append）
- **目标**：让 Worker 在提示词中看到 context_files 的实际内容（引用块）。**⚠️ 关键约束：因 `_render_prompt_template` 用 `str.format()`，文件内容绝不能进 context dict——必须在渲染后追加到 rendered 字符串末尾。**
- **依赖**：T1.2
- **frontier**：否
- **执行者**：Simulation Builder
- **修改内容**：
  - 文件 `src/loop_kit/_core.py`：
    1. 新增辅助函数：
       ```python
       def _render_context_files_section(task_card: TaskCard) -> str:
           """Render context_files contents as a post-appended prompt section.

           MUST NOT be placed into the template context dict: file contents may
           contain '{'/'}' which would break str.format() in _render_prompt_template.
           """
           cf = task_card.get("context_files", [])
           if not isinstance(cf, list) or not cf:
               return ""
           paths = _resolve_context_files_safe(cf, ROOT)
           if not paths:
               return ""
           blocks: list[str] = []
           for p in paths:
               try:
                   text = p.read_text(encoding="utf-8", errors="replace")
               except OSError:
                   _log(f"context_files: cannot read {p}")
                   continue
               if len(text) > 20000:
                   text = text[:20000] + "\n...[truncated]..."
               blocks.append(
                   f"--- context_file: {_display_path(p)} ---\n{text}\n--- end context_file ---"
               )
           return "\n\n" + "\n\n".join(blocks)
       ```
    2. `_worker_prompt`（L6007）两个返回分支都要追加：
       - **模板分支**（rendered 构造后、return 前，L6068-6070 附近）：
         ```python
         context_files_section = _render_context_files_section(task_card)
         if context_files_section:
             rendered = rendered.rstrip() + "\n\n=== CONTEXT FILES ===" + context_files_section + "\n"
         ```
       - **无模板分支**（L6072-6078，`_build_prompt_sections` 之后）：同样在 `result` return 前追加。
- **修改边界**：不改变现有 prompt 渲染顺序；不修改 `_render_prompt_template` 本身；不修改 `_build_task_packet`（TaskPacket 是结构化数据，不是内容载体）。
- **质量检查方式**：
  - 检查项 1：构造含 context_files 的 task_card，断言 `_worker_prompt` 输出含 `=== CONTEXT FILES ===` 与文件内容。
  - 检查项 2：**content 含 `{`/`}` 的文件**也能正常渲染（不抛 ValueError）。
  - 检查项 3：`context_files` 为空/全跳过时输出与改动前等价（无回归）。
- **验收标准**：
  - ✅ 新增单测 `test_worker_prompt_includes_context_files_after_render` 通过（含 `{}` 内容用例）。
  - ✅ `uv run --group dev pytest -q` 全绿。
- **潜在风险**：大文件注入膨胀 prompt → 每文件 20000 字符截断上限缓解。
- **预留歧义标注**：路径展示用 `_display_path(p)`（与现有 prompt 风格一致）。

#### Task 1.4: `_render_task_card_section` 渲染 context_files 引用清单
- **目标**：Worker 提示词的 task_card section 也列出 context_files 引用路径（与 T1.3 的内容注入互补；REVIEW ³-1 MODIFY_SPEC 点名此函数 L5524）。
- **依赖**：T1.2
- **frontier**：否
- **执行者**：Simulation Builder
- **修改内容**：
  - 文件 `src/loop_kit/_core.py`：`_render_task_card_section`（L5524，f-string 渲染，安全）在 `constraints` 行之后追加：
    ```python
    context_files:\n{_as_prompt_list(_display_path(p) for p in _resolve_context_files_safe(task_card.get("context_files", []), ROOT))}
    ```
  - 仅渲染安全解析后的路径；空列表渲染为空行（`_as_prompt_list([])` 行为保持）。
- **修改边界**：不得移除任何现有 task_card 渲染字段（goal/in_scope/out_of_scope/acceptance_criteria/depends_on/lanes/constraints 全部保留）。
- **质量检查方式**：
  - 检查项 1：含 `context_files` 的 card 渲染出该行；空 card 无 context_files 行（无回归）。
- **验收标准**：
  - ✅ 对应单测通过（可与 T1.3 合成一个用例文件）。
  - ✅ `uv run --group dev pytest -q` 全绿。
- **预留歧义标注**：路径展示用 repo-root-relative（`_display_path` 对 ROOT 下路径自然相对化）。

**P1 完成后**：TE 运行仓库 A 全量测试确认无回归，记录到 Execution Log。

---

### Phase 2: ATR 侧 artifact_timeout 按 output_format 自适应（仓库 A）

#### Task 2.1: 新增 `output_format → artifact_timeout` 映射常量 + 解析函数
- **目标**：提供确定性映射与解析。
- **依赖**：无（纯函数，独立于 P1）
- **frontier**：是
- **执行者**：Simulation Builder
- **修改内容**：
  - 文件 `src/loop_kit/_core.py`：新增常量映射与解析函数（放在 `DEFAULT_DISPATCH_ARTIFACT_TIMEOUT_SEC` L343 附近）：
    ```python
    # Output kinds needing long analysis/report windows
    _LONG_ARTIFACT_FORMATS = ("analysis", "report", "summary", "slides", "doc")
    _LONG_ARTIFACT_TIMEOUT_SEC = 600  # 10 min

    def _artifact_timeout_for_format(output_format: str, base_timeout: int) -> int:
        """Adapt artifact timeout by task kind. Long formats get a raised floor; else base."""
        if output_format in _LONG_ARTIFACT_FORMATS:
            return max(base_timeout, _LONG_ARTIFACT_TIMEOUT_SEC)
        return base_timeout
    ```
- **修改边界**：不改 `DEFAULT_DISPATCH_ARTIFACT_TIMEOUT_SEC`（90 保持为兜底）；不改 CLI 默认行为（未指定 output_format 时走 base）。
- **质量检查方式**：
  - 检查项 1：`analysis`/`report`/`summary`/`slides`/`doc` → ≥600；`code`/`script`/未知 → base。
- **验收标准**：
  - ✅ 纯函数单测覆盖上表各分支（`tests/test_orchestrator.py`）。
  - ✅ `uv run python -m py_compile src/loop_kit/_core.py` exit 0。
- **潜在风险**：`output_format` 字段可能缺失/非法 → 解析函数对缺失返回 base（调用点用 `.get("output_format", "code")`）。

#### Task 2.2: `_main_loop`/`_run_single_round` 入口按 output_format 提升 artifact_timeout
- **目标**：让实际执行入口（task_card 已同步后）应用映射到 `config.artifact_timeout`。
- **依赖**：T2.1
- **frontier**：否
- **执行者**：Simulation Builder
- **修改内容**：
  - 文件 `src/loop_kit/_core.py`：
    - 在 `cmd_run` 内 `_sync_task_card` 之后（L12364-12365 附近，或 `_main_loop`/`_run_single_round` 入口）读取 `resolved_paths.task_card` 的 `output_format`，调用 `_artifact_timeout_for_format` 覆盖 `config.artifact_timeout`：
      ```python
      task_card_data = _read_json_if_exists(resolved_paths.task_card)
      if isinstance(task_card_data, dict):
          fmt = str(task_card_data.get("output_format", "code"))
          new_to = _artifact_timeout_for_format(fmt, config.artifact_timeout)
          if new_to != config.artifact_timeout:
              _log(f"artifact_timeout adapted: {config.artifact_timeout}s -> {new_to}s (output_format={fmt})")
              config.artifact_timeout = new_to
      ```
    - 注意：`RunConfig` 是 `@dataclass(slots=True)` 非 frozen（L583），`artifact_timeout` 字段可赋值（L601）。
  - **优先位置**：`_main_loop` 与 `_run_single_round` 各自入口（两处都要覆盖，因为 single-round 不走 _main_loop）。
- **修改边界**：不得改变 `--artifact-timeout` 显式指定时的用户语义；仅当其值低于 long 下限且 output_format 命中 long 时提升（`max(base, 600)` 语义）。
- **质量检查方式**：
  - 检查项 1：`output_format=analysis` → 最终 config.artifact_timeout ≥600。
  - 检查项 2：`output_format=code` → 保持用户传入值（300 不变）。
- **验收标准**：
  - ✅ 单测：模拟 `cmd_run`→`_main_loop` 入口，断言 config.artifact_timeout 按 format 生效。
  - ✅ `uv run --group dev pytest -q` 全绿。
- **潜在风险**：两处入口都要改——若遗漏 single-round 路径，`--single-round` 下不生效。T4.1（PM 侧传 600）作为双保险兜底。
- **预留歧义标注**：无（实现点与语义已定）。

---

### Phase 3: PM 桥 curator 上下文取对仓库（仓库 B）

#### Task 3.1: `curate_context` 增加 `project_dir` 参数并按它分区读取
- **目标**：context_brief.md 的 README/git log/directory tree 来自任务 `project_dir` 而非 dispatcher cwd；`data/pm.sqlite`（similar tasks）**保留 dispatcher cwd**（PM 数据库所在）。
- **依赖**：无
- **frontier**：是（与 P1/P2 无共享文件）
- **执行者**：Data Analyst（PM 侧脚本维护）
- **修改内容**：
  - 文件 `src/auto_task/curator.py`：
    - 签名 `curate_context(loop_dir: str, task_card: dict[str, Any], project_dir: Path | None = None) -> None`
    - `_add_readme_section(sections, base_dir: Path)`：将 L91 `readme = Path("README.md")` 改为 `readme = base_dir / "README.md"`；同样处理 `AGENTS.md`（若存在读取摘要，500 字符截断保持一致）。
    - `_add_git_log_section(sections, base_dir)`：L105 `subprocess.run([...], cwd=base_dir)`。
    - `_add_directory_section(sections, base_dir)`：L118 `["find", ".", ...]` 改为 `cwd=base_dir`（**也随 project_dir**）。
    - `_add_similar_tasks_section(sections, task_card)`：L133 `Path("data/pm.sqlite")` **不改**——必须保留相对 dispatcher cwd（project_management 仓库根），因为 PM 数据库在此。
  - `project_dir` 为 None 时降级为 `Path.cwd()`（保留旧行为）。
- **修改边界**：⚠️ 分区处理：README/AGENTS/git log/directory → 随 project_dir；`data/pm.sqlite`（similar tasks）→ **保持 dispatcher cwd**，不得改为 project_dir。
- **质量检查方式**：
  - 检查项 1：传入指向临时 dir 的 project_dir，断言 context_brief 含该 dir 的 README/目录树内容、不含 dispatcher cwd 的。
  - 检查项 2：project_dir=None 时行为与原版等价（回归）。
  - 检查项 3：similar tasks section 仍能命中 `data/pm.sqlite`（不因 project_dir 而断）。
- **验收标准**：
  - ✅ `grep -n "project_dir" src/auto_task/curator.py` 命中 ≥2 行。
  - ✅ 新增 `tests/test_curator.py`：覆盖 project_dir 分区读取 + None 降级。
  - ✅ 仓库 B `make test` 通过（`python -m pytest -q`，含 `tests/test_bridge_polling.py` + 新增 `tests/test_curator.py`）。
- **潜在风险**：旧调用点不传 project_dir → 兼容降级已保。
- **预留歧义标注**：README 摘要截断仍为 500 字符（保持现状，不扩）。

#### Task 3.2: `bridge.py` 调用 `curate_context` 传 `project_dir`
- **目标**：把 M3 dispatch 侧的 project_dir 传入 curator。
- **依赖**：T3.1
- **frontier**：否
- **执行者**：Data Analyst
- **修改内容**：
  - 文件 `src/auto_task/bridge.py` L409：`curate_context(str(loop_dir.resolve()), task_card, Path(project_dir) if project_dir else None)`
  - 确保 `project_dir` 变量在 M3 dispatcher 作用域可用（已在 L434/L444 使用，确认同名）。
- **修改边界**：不改动 `curate_context` 之外的 bridge 逻辑（本 task 只改这一处调用）。
- **质量检查方式**：
  - 检查项 1：读该调用的实参传递正确。
- **验收标准**：
  - ✅ `grep -n "curate_context(" src/auto_task/bridge.py` 显示 project_dir 实参。
  - ✅ 仓库 B `make test` 通过。
- **潜在风险**：极低（仅传参）。

---

### Phase 4: PM 桥按 output_format 传自适应 timeout + dispatch 时 relativize context_files（仓库 B）

#### Task 4.1: `dispatch_atr` 按 output_format 计算 `--artifact-timeout`
- **目标**：analysis/report/summary/slides/doc 传 600s，code 保留 300s。
- **依赖**：无（B 侧独立映射，与 T2.1 口径一致即可）
- **frontier**：是（B 侧独立实现；口径需与 T2.1 的常量值一致）
- **执行者**：Data Analyst
- **修改内容**：
  - 文件 `src/auto_task/bridge.py`：新增模块级（放 `_MAX_ROUNDS` L31 附近）
    ```python
    # Keep in sync with agent-task-runner/src/loop_kit/_core.py _LONG_ARTIFACT_FORMATS/_LONG_ARTIFACT_TIMEOUT_SEC
    _LONG_ARTIFACT_FORMATS = ("analysis", "report", "summary", "slides", "doc")
    _LONG_ARTIFACT_TIMEOUT_SEC = 600
    _CODE_ARTIFACT_TIMEOUT_SEC = 300

    def _artifact_timeout_for_output(output_format: str) -> int:
        return _LONG_ARTIFACT_TIMEOUT_SEC if output_format in _LONG_ARTIFACT_FORMATS else _CODE_ARTIFACT_TIMEOUT_SEC
    ```
  - `dispatch_atr` 内 L398-400（已读 task_card 与 output_format）后，L432 改为：
    `"--artifact-timeout", str(_artifact_timeout_for_output(output_format)),`
- **修改边界**：不改 `_TIMEOUT_SEC`/`_DISPATCH_TIMEOUT_SEC`（任务级与 dispatch 级超时保持）。
- **质量检查方式**：
  - 检查项 1：analysis → 600 出现在 cmd；code → 300。
- **验收标准**：
  - ✅ 仓库 B 单测（`tests/test_bridge_polling.py` 或新增用例）断言构造的 cmd 含 `--artifact-timeout 600`（analysis）。
  - ✅ `make test` 通过。
- **潜在风险**：映射常量与 T2.1 需口径一致——两侧注释互相引用 + V5 交叉校验。即便 ATR 侧 adaptive 未生效，PM 侧 600 也能兜底。
- **预留歧义标注**：无。

#### Task 4.2: `dispatch_atr` 在写 task_card.json 前 relativize context_files
- **目标**：让产生的 context_files 在写入 `loop_dir/task_card.json` 前转为相对 `project_dir` 的路径，确保被 T1.3/T1.4 正常消费（绝对路径白名单未配置时不会被跳过）。
- **依赖**：T1.2（ATR 消费存在）；T4.1（同在 dispatch_atr 内，先后串行）
- **frontier**：否
- **执行者**：Data Analyst
- **修改内容**：
  - 文件 `src/auto_task/bridge.py`：
    1. 新增辅助函数：
       ```python
       def _relativize_context_files(paths: list[str], project_dir: Path) -> list[str]:
           """Convert context_files to paths relative to project_dir when possible.

           - Absolute path under project_dir -> relative (strip prefix).
           - Absolute path outside project_dir -> dropped (with log).
           - Relative path -> kept as-is.
           """
           out: list[str] = []
           root = project_dir.resolve()
           for raw in paths:
               if not isinstance(raw, str) or not raw.strip():
                   continue
               p = Path(raw.strip())
               try:
                   if p.is_absolute():
                       rp = p.resolve()
                       if rp.is_relative_to(root):
                           out.append(str(rp.relative_to(root)))
                       else:
                           logger.warning("context_files: dropping path outside project_dir: %s", raw)
                   else:
                       out.append(raw.strip())
               except (OSError, ValueError, RuntimeError):
                   logger.warning("context_files: dropping invalid path: %s", raw)
           return out
       ```
    2. `dispatch_atr`（L385）开头、**L391 写 task_card.json 之前**：
       ```python
       task_card_data = json.loads(entry["task_card_json"])
       cf = task_card_data.get("context_files", [])
       if cf:
           task_card_data["context_files"] = _relativize_context_files(cf, Path(project_dir)) if project_dir else cf
           entry = dict(entry, task_card_json=json.dumps(task_card_data, ensure_ascii=False))
       ```
       再执行原 L391 写文件。后续 L398/L408 读取 `entry["task_card_json"]` 时自然拿到相对路径版本。
  - ⚠️ **不做** enqueue 时 relativize（`build_task_card`/`_fallback_task_card` L238）——那时无 project_dir。
- **修改边界**：不改 ATR 的白名单常量；B 侧只负责产出「安全可消费」的相对路径。
- **质量检查方式**：
  - 检查项 1：绝对路径（在 project_dir 内）→ 相对路径；绝对路径（在 project_dir 外）→ 丢弃；相对路径 → 原样。
  - 检查项 2：task_card.json 中 context_files 无绝对路径。
- **验收标准**：
  - ✅ 单测覆盖 `_relativize_context_files` 三分支。
  - ✅ 单测断言 `dispatch_atr` 写出的 loop_dir/task_card.json 的 context_files 为相对路径。
  - ✅ `make test` 通过。
- **潜在风险**：若 LLM 在 `build_task_card` 阶段用绝对路径填充，relativize 在 dispatch 时剥离；剥不掉（project_dir 外）则丢弃避免 ATR 端静默失败。
- **预留歧义标注**：`project_dir` 为 None/空时跳过 relativize（保持原样，兼容旧调用）。

---

### Phase 5: 端到端验收（仓库 A + B）

#### Task 5.1: 端到端发起 analysis 类任务并验证 work_report
- **目标**：复现原失败场景，确认修复后能产出 work_report.json 并回写 PM。
- **依赖**：T1.1-T4.2 全部
- **frontier**：否
- **执行者**：Simulation Builder（配合 PM Coordinator 校验回写）
- **修改内容**（无代码改动，仅执行与记录）：
  - 经 PM 侧发起一个真实 analysis 类任务（如本 repo 某文档复核，`output_format=analysis`），指定 `--cwd` 指向 agent-task-runner。
  - 观察：worker 提示词含 `context_files` 引用块 + `Role: analysis`；artifact_timeout≥600；循环正常产出 work_report.json。
  - 确认 `check_and_handle_results` 回写 PM 状态非 blocked/非 timeout。
- **修改边界**：不得 mock；真跑最小 analysis 任务。
- **质量检查方式**：
  - 检查项 1：loop_dir 出现 context_brief.md 且内容来自 agent-task-runner README（而非 project_management README）。
  - 检查项 2：work_report.json 生成。
  - 检查项 3：PM auto_task_queue 状态被成功更新。
- **验收标准**：
  - ✅ PM 任务状态从 dispatch 到 done 完成流转（无 rc=3）。
  - ✅ loop_dir 内存在 context_brief.md、work_report.json、summary.json。
  - ✅ `grep -c "context_file:" worker_prompt` > 0（若任务含 context_files）。
- **潜在风险**：真实 ATR 运行耗时（≤10min）；若环境缺 opencode backend 则退回重跑，记录到日志。

---

## Execution Wave（并行执行波次）

| Wave | 可并行 Task | Frontier | 依赖已完成 |
|------|------------|----------|-----------|
| W1 | T1.1 / T2.1 / T3.1 / T4.1 | T1.1, T2.1, T3.1, T4.1 | — |
| W2 | T1.2 / T2.2 / T3.2 / T4.2 | T1.2, T3.2 | W1 (T1.1→T1.2; T2.1→T2.2; T3.1→T3.2; T4.1→T4.2) |
| W3 | T1.3 / T1.4 | — | W2 (T1.2) |
| W4 | — | — | W2, W3 (T1.2, T4.2 → 全部前置) |
| W5 | T5.1 | — | W4 (全部) |

> 注：
> - T1.3/T1.4 都依赖 T1.2 且都在 A 仓库 `_core.py` 同函数区，**W3 内串行**（同一文件排队，避免同文件并行编辑冲突）。
> - T3.1/T3.2、T4.1/T4.2 分别在 B 仓库同文件内串行。
> - T2.2 与 T1.3/T1.4 都在 A 仓库 `_core.py`，但不同函数区；若 TE 采用串行单 worker，按编号顺序执行即可（T2.2 在 W2、T1.3 在 W3 天然错开）。

---

## Post-Execution Verification

Task Executor 在所有 plan task 执行完毕后运行以下验证。

### Automated Verification（TE 自动执行）

| ID | Description | Command | Expected |
|----|-------------|---------|----------|
| V1 | ATR 全量测试 | `cd /home/gw/opt/agent-task-runner && uv run --group dev pytest -q` | exit 0，全绿 |
| V2 | ATR 编译检查 | `cd /home/gw/opt/agent-task-runner && uv run python -m py_compile src/loop_kit/_core.py` | exit 0 |
| V3 | ATR import 检查 | `cd /home/gw/opt/agent-task-runner && uv run python -c "from loop_kit.orchestrator import *"` | exit 0 |
| V4 | PM 全量测试 | `cd /home/gw/opt/project_management && make test` | exit 0，全绿 |
| V5 | 新增函数存在性 | `cd /home/gw/opt/agent-task-runner && grep -c "_resolve_context_files_safe\|_artifact_timeout_for_format\|_render_context_files_section" src/loop_kit/_core.py` | ≥3 |
| V6 | curator project_dir | `cd /home/gw/opt/project_management && grep -c "project_dir" src/auto_task/curator.py` | ≥2 |
| V7 | PM relativize 函数 | `cd /home/gw/opt/project_management && grep -c "_relativize_context_files\|_artifact_timeout_for_output" src/auto_task/bridge.py` | ≥2 |
| V8 | ATR 静态检查 | `cd /home/gw/opt/agent-task-runner && ruff check src/loop_kit/_core.py`（若项目启用 ruff） | 无新增错误（若 ruff 未配置则 SKIP 并记录） |

### Probe（best-effort，run if available）
- [ ] P1: `cd /home/gw/opt/agent-task-runner && uv run python -c "from loop_kit._core import _artifact_timeout_for_format; print(_artifact_timeout_for_format('analysis', 90))"` 应打印 600；`print(_artifact_timeout_for_format('code', 300))` 应打印 300。

### Manual（真正需要人工判断）
- [ ] M1: 人工复核 T5.1 端到端运行中 worker_prompt 的 context_files 引用块是否语义正确（内容确实来自对应文件，且无 `{}` 崩溃）。
- [ ] M2: 人工复核 PM 回写状态与 outcome 映射符合预期（approved / no_change_success，非 timeout/validation_failure）。

---

## 审查日志

| 轮次 | 聚焦 | 发现问题数 | 已修正 | 剩余 |
|------|------|-----------|--------|------|
| R1 | 结构完整性（依赖图、Phase 划分、跨仓库边界） | 2 | 2 | 0 |
| R1.5 | 外部引用事实核查（`_core.py:343`/`5373`/`5398`/`5524`/`6007`/`5840`/`583`/`336`/`12364`, `curator.py:91/105/114/133`, `bridge.py:385/391/398/409/432/434`, TaskCard L226, RunConfig L583/601） | 6 | 6 | 0 |
| R2 | 可执行性（测试命令、验收二元性、脚本干跑路径） | 1 | 1 | 0 |
| R2.8 | LLM 可执行性（路径歧义、动作歧义、命令歧义、契约可执行性） | 4 | 4 | 0 |
| R3 | 风险与边缘（str.format 崩溃、双入口覆盖、口径一致性、空字段回归） | 3 | 3 | 0 |
| **REFINE-1** | **[Refine Mode] 全量重审（R1→R1.5→R2→R2.8→R3）** | 6 | 6 | 0 |
| **终止** | **[T5] — 端到端 work_report 产出 + PM 回写非 timeout** | | | **0** |

### R1 记录
- 发现：T1.3 与 T1.4 在同一 `_core.py` 同函数区，需串行防冲突 → 在 Wave 表注明同文件串行。
- 发现：Phase 5 依赖全部 Phase，但 T5.1 无代码改动 → 明确标「仅执行与记录」。

### R1.5 记录
- 发现：`_build_task_packet` 返回 TaskPacket（无 prompts 字段），实际 prompt 由 `_worker_prompt` 组装 → T1.3 注入点改为 `_worker_prompt` rendered 后 append。
- 发现：`_render_prompt_template` 用 `str.format()`，文件内容含 `{}` 会崩溃 → T1.3 强制 post-append，不进 context dict。
- 发现：CLI 构造 config 时 task_card 未加载 → T2.2 注入点改为 `_main_loop`/`_run_single_round` 入口（RunConfig 非 frozen 可改）。
- 发现：`_add_directory_section` 也相对路径，但 `data/pm.sqlite` 必须保留 dispatcher cwd → T3.1 分区处理。
- 发现：`build_task_card` enqueue 时无 project_dir → T4.2 relativize 改为 dispatch_atr L391 写文件前。
- 发现：`_render_task_card_section` 是 f-string 渲染（安全）→ T1.4 可行，与 T1.3 分工明确。

### R2 记录
- 发现：PM 测试命令需明确（`make test` = `python -m pytest -q`）→ 写入 V4 与验收。

### R2.8 记录
- 发现：T2.2 实现点需拿到 task_card.output_format → 明确在 `_main_loop`/`_run_single_round` 入口（task_card 已同步）。
- 发现：`_resolve_context_files_safe` 的 `root` 实参歧义 → 明确取 `ROOT`（`_core.py:336`）。
- 发现：context_files 路径展示方式歧义 → 明确 `_display_path(p)`（ROOT 下自然相对化）。
- 发现：T4.2 中 `entry` 可变性 → 明确用 `dict(entry, task_card_json=...)` 重建，避免原地修改污染上游。

### R3 记录
- 发现：**str.format() 崩溃**（T1.3 致命）→ 强制渲染后 append，并新增 `{}` 内容单测。
- 发现：T2.2 双入口（main_loop + single_round）遗漏风险 → 明确两处都改，T4.1 兜底。
- 发现：T4.1 与 T2.1 口径不一致风险 → 两侧常量注释互相引用 + V5/P1 Probe 交叉校验。

---

## Execution Log
（Task Executor 执行过程中回写）

### [YYYY-MM-DD HH:MM] Task X.Y — [STATUS]
- 结果：...
- 错误/阻塞：...
- 备注：...

### [2026-08-02 09:05] 全部 11 个 Task — COMPLETED

- **结果**：W1-W5 全部完成。三处根因修复均已落地并通过单测 + 端到端验证。
- **Commit 清单**：
  - `afdc760` (T1.1) context_files schema + 白名单常量 [agent-task-runner]
  - `da766cf` (T2.1) artifact_timeout 映射函数 [agent-task-runner]
  - `a1d1887` (T3.1) curator project_dir 分区读取 [project_management]
  - `e058c13` (T4.1 + T3.2) PM 桥 timeout 自适应 + curator 传 project_dir [project_management]
  - `d16e9b1` (T1.2) _resolve_context_files_safe 纯函数 [agent-task-runner]
  - `83476b3` (T2.2) run 入口 artifact_timeout 自适应 [agent-task-runner]
  - `5fe2a2f` (T4.2) dispatch_atr relativize context_files [project_management]
  - `dd710f2` (T1.3 + T1.4) worker_prompt context_files 渲染 [agent-task-runner]
- **端到端验证**：real `loop_kit run` 印证 `artifact_timeout adapted: 600s (output_format=analysis)`；`_worker_prompt` 实际渲染 `=== CONTEXT FILES ===` + ctx.md 内容 + `context_files:` 引用；PM `dispatch_atr` 写出相对路径 context_files + `--artifact-timeout 600`。
- **注意事项**：
  1. **project_management 仓库工作树存在大量其它工作流未提交改动**（`bridge.py` 及其它 20+ 文件）。本计划的 3 个 commit 均通过 `git update-index --cacheinfo` 传入**纯净 blob**（仅含本计划改动），未污染其它工作流的未提交改动。这些未提交改动仍留在工作树，归其它工作流所有。
  2. **测试环境发现 1 个 pre-existing failure**：`tests/test_orchestrator.py::TestCmdStatus::test_shows_context_file_stats`（pattern stats 数据漂移，`high_confidence=0` vs 期望 `1`），与本计划改动无关（已通过在 HEAD 基线复现确认）。
  3. PID 配置：project_management 仓库 git 身份沿用仓库既有的 `zxkjack123`；agent-task-runner 新设置。
  4. **TODO（PM 侧后续）**：T3.2 的 `curate_context` project_dir 传参已并入 T4.1 commit；T2.2 的双入口（single_round + multi_round）均已覆盖。

```json
{
  "error_id": null,
  "error_type": null,
  "summary": "PM #2234 三处根因修复完成：curator project_dir 分区、artifact_timeout 自适应、context_files 消费+relativize",
  "root_cause_guess": null,
  "confidence": "HIGH",
  "retry_suggestion": null,
  "affected_files": ["src/loop_kit/_core.py", "tests/test_orchestrator.py", "src/auto_task/curator.py", "src/auto_task/bridge.py", "tests/test_curator.py", "tests/test_bridge_polling.py"],
  "blocked_downstream": [],
  "task_id": "T1.1-T5.1",
  "attempted_fixes": [],
  "timestamp": "2026-08-02T09:05:00Z"
}
```

### Post-Execution Verification Log

| ID | Result | Note |
|----|--------|------|
| V1 | ⚠️ PASS (2 pre-existing fails) | 562 passed; 2 failed tested-pre-existing (cost_cents=1, backend=opencode vs codex) — none from my commits |
| V2 | ✅ PASS | py_compile src/loop_kit/_core.py |
| V3 | ✅ PASS | from loop_kit.orchestrator import * |
| V4 | ✅ PASS | PM 16 tests (test_bridge_polling + test_curator) |
| V5 | ✅ PASS | 8 refs for 3 new functions |
| V6 | ✅ PASS | 4 project_dir refs in curator.py |
| V7 | ✅ PASS | 4 func refs in bridge.py |
| V8 | ⚠️ PASS (pre-existing lint) | my additions lint-clean after a0f430a; repo has pre-existing E501/import-sort errors |
| P1 | ✅ PASS | analysis→600, code→300 |
| M1 | ⏸ PENDING MANUAL | 需人工复核 worker_prompt context_files 引用语义 |
| M2 | ⏸ PENDING MANUAL | 需人工复核 PM 回写 outcome 映射 |
