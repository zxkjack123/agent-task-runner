---
plan_id: pm3135-worker-prompt-skill-loading
pm_task: 3135
project: agent-task-runner
scope_mode: HOLD
git_commit: f689c18
generated_at: 2026-09-03
revision: 1
execution_mode: manual（人工执行，不走 ATR 派发）
linked_spec: 无（本任务 ≤3 文件、无外部契约变更，未触发 spec-first）
---

# Plan: worker prompt 接入 skill 加载指引（PM #3135）

## 背景与目标

- **需求**（PM #3135 原文要点）：`DEFAULT_WORKER_PROMPT_TEMPLATE` 各节均无 skill 加载指引，ATR worker 靠 LLM 自觉，实际不会正确使用 skill 工具（skill 工具本身已可用：opencode.jsonc `permission.skill["*"]="allow"`，available_skills 在系统提示可见）。需在 worker 模板增加 "=== SKILL LOADING ===" 节，指示 worker 对照 `~/opt/copilot-agents/skills/index.md`（运行时索引）命中则用 skill 工具加载，未命中跳过；禁止硬编码技能清单/数量。
- **目标**：仅改 `src/loop_kit/_core.py` 的 `DEFAULT_WORKER_PROMPT_TEMPLATE`（新增静态节），刷新物化模板 `.loop/templates/worker_prompt.txt`，新增/扩展测试，全量回归通过。
- **非目标（不做什么）**：
  - ❌ 不改 `DEFAULT_REVIEWER_PROMPT_TEMPLATE`（reviewer 是否接入是 PM scope 决策，本任务不裁决；PM #3135 notes 中"reviewer 若适用"留待 PM 决定）
  - ❌ 不改 `dispatch.py` / `git_helpers.py` / `knowledge.py` / #3155 repo 锁机制
  - ❌ 不引入新 format 占位符；不硬编码技能数量（63 会漂移）
  - ❌ 不触碰 untracked 的 3 个计划文件与 `data/`
  - ❌ 不运行 `loop run`（任何 loop 进程都不启动）；不碰 `.loop/` 下 lock/state/runtime 等运行态文件（`templates/worker_prompt.txt` 除外）

## 需求分解（CoT Stage 1）

```
REQUIREMENT: worker prompt 增加 "=== SKILL LOADING ===" 静态指引节，以 skills/index.md 为运行时索引
CONSTRAINTS:
  - 修改面 = _core.py 单符号 + tests + 物化模板刷新（≤3 文件/task）
  - 模板经 template_text.format(**context) 渲染 → 新节不得含未转义 { }（违者全部渲染崩溃）
  - _write_template_if_missing 只缺省写入 → 已物化的 .loop/templates/worker_prompt.txt 不会自动刷新
  - 该物化文件是 git-tracked（git ls-files .loop/ 确认），刷新 = tracked 修改，必须随代码一起提交
  - 既有物化文件存在漂移：实测 355 字符 vs 代码默认 1071 字符（缺 run_id、QUICKSTART/HANDOFF/KNOWLEDGE/TASK PACKET、物理量验证等节）
BOUNDARY:
  - IN: DEFAULT_WORKER_PROMPT_TEMPLATE 静态节、tests/test_orchestrator.py 两条修改点、.loop/templates/worker_prompt.txt 重物化
  - OUT: reviewer 模板（PM 决策）、fallback 渲染路径 _build_prompt_sections（见风险 R7）、锁机制、dispatch/knowledge
ACCEPTANCE（二元）:
  1. grep "SKILL LOADING" src/loop_kit/_core.py → ≥1 hit 且同节含 skills/index.md 路径
  2. DEFAULT_WORKER_PROMPT_TEMPLATE 以全部 14 个占位符 format() 成功（无 KeyError）
  3. .loop/templates/worker_prompt.txt 字节级 == DEFAULT_WORKER_PROMPT_TEMPLATE + "\n"
  4. uv run --group dev pytest → 0 failed；uv run ruff check src/loop_kit tests → 0 error
  5. 新测试 test_worker_prompt_rendered_includes_skill_loading 通过；test_main_init_creates_prompt_templates_in_loop_dir 扩展断言通过
```

## 假设枚举（CoT Stage 2）

1. `[假设: 新节语言用英文、插入位置在 "=== KNOWLEDGE ===" 节之后、"=== TASK PACKET ===" 节之前]` — 依据：模板全文为英文；语义上"装备技能"介于上下文吸收（KNOWLEDGE）与任务执行指令（TASK PACKET）之间。若用户偏好中文/其他位置，影响仅为文本措辞，低影响。
2. `[假设: 硬编码绝对路径 /home/gw/opt/copilot-agents/skills/index.md 可接受]` — 依据：模板已有先例（第 6079 行硬编码 /home/gw/opt/copilot-agents/scripts/benchmark_physical_quantities.py）。若 copilot-agents 搬迁，该引用失效（风险 R8，已有同型风险）。
3. `[假设: 运行时走模板文件路径而非 fallback 路径]` — 依据：本仓 `.loop/templates/worker_prompt.txt` 存在 → `_worker_prompt` 读文件渲染。fallback（`_build_prompt_sections`）仅在文件缺失时触发，属降级路径，本次不覆盖（R7）。
4. `[假设: 重物化顺带修复既有漂移是可接受的]` — 依据：用户明确指定"删除后由代码重新物化"策略；漂移修复是同一动作的必然结果（355→~1.4KB diff），且方向正确（V3 字节级校验保证与新默认一致）。
5. `[假设: reviewer 接入留待 PM 决策]` — 依据：用户 scope 约束明确。测试中加 `assert "=== SKILL LOADING ===" not in reviewer_template` 锁定本任务边界；未来若 PM 决定接入，由该任务同步更新此断言（计划内注明）。

## 方案设计（CoT Stage 3）

```
DECISION: 单一静态节 + 删除重物化 + 双层测试（物化断言 + 渲染断言）
ALTERNATIVES:
  a) 同时改 fallback 路径 _build_prompt_sections —— 拒绝：超出用户 scope（"只改 DEFAULT_WORKER_PROMPT_TEMPLATE"），且 fallback 仅降级触发
  b) 手工仅追加新节到物化文件（等效手段）—— 拒绝：保留 355 字符陈旧内容（缺 run_id 等节），漂移延续；重物化是代码驱动、可字节校验
  c) 运行时注入 index 内容（新占位符）—— 拒绝：违反"不引入新 format 占位符"约束，且 index 内容膨胀 prompt
RATIONALE: 静态指引 + 运行时索引是 PM #3135 目标原文的直接实现；重物化保证物化文件与代码单一来源一致
RISK: 物化 diff 大于"仅新增节"（含漂移修复）→ 缓解：V3 字节级校验 + 计划中显式声明预期 diff；reviewer 模板不动
```

新节全文（逐字写入，executor 不得改写措辞；已验证无 { }、无新占位符、无硬编码数量）：

```python
    "=== SKILL LOADING ===\n"
    "Skill tools are available in this session. Before executing the task:\n"
    "1. Open the runtime skill index: /home/gw/opt/copilot-agents/skills/index.md\n"
    "2. Match the task against the index 'When to use' descriptions.\n"
    "3. On a match, load the skill with the skill tool, e.g. skill(name='mcnp6-modeling')\n"
    "   for MCNP input work, or skill(name='fusion-statistics') for statistical reporting.\n"
    "4. No match -> skip this section; do not invent or force a skill.\n"
    "5. Skill loading permission is pre-granted (permission.skill['*']='allow'); no approval prompt is expected.\n"
    "6. Do not copy the index content into the work report; loading the skill is enough.\n\n"
```

插入锚点（_core.py 当前 6074-6075 行，executor 执行时以字符串内容为锚，不依赖行号）：

```
old:
    "=== KNOWLEDGE ===\n{knowledge_section}\n\n"
    "=== TASK PACKET ===\n{task_packet_section}\n\n"

new:
    "=== KNOWLEDGE ===\n{knowledge_section}\n\n"
    "=== SKILL LOADING ===\n"
    ...（上述 8 行新节）...
    "=== TASK PACKET ===\n{task_packet_section}\n\n"
```

## 执行计划

> 通用纪律：每个 Phase 首步执行**基线漂移重检**；本计划所有锚点（行号、符号位置）一律执行时重测，禁止沿用本文档快照值。提交前跑 `git diff --stat` 负向验证（只应有 3 个文件）。

### Phase 1: 修改 DEFAULT_WORKER_PROMPT_TEMPLATE

- **基线漂移重检**（强制）：
  `git rev-parse HEAD`（应=f689c18，若已前进则先 pull 再看差异）；`git status --porcelain`（应仅 4 个 untracked：3 计划文件 + data/，另加本计划文件自身）；`grep -n "DEFAULT_WORKER_PROMPT_TEMPLATE = " src/loop_kit/_core.py` 重测行号；`grep -c "SKILL LOADING" src/loop_kit/_core.py` 应=0。
  漂移（HEAD 移动/行号变化/出现脏文件）→ 先更新锚点再动手；出现非预期 tracked 脏文件 → STOP 并上报。

#### Task 1.1: 插入 "=== SKILL LOADING ===" 静态节

- **目标**：在 `DEFAULT_WORKER_PROMPT_TEMPLATE`（_core.py:6059-6085）内、"=== KNOWLEDGE ===" 节后插入上述 8 行新节
- **依赖**：无
- **frontier**：是
- **执行者**：人工（建议 exec 用 Plan Architect 给出的逐字文本，零改写）
- **修改内容**：
  - 文件 `src/loop_kit/_core.py`：按上文"插入锚点"old→new 精确替换。字符串必须与计划"新节全文"逐字一致（含 `\n\n` 结尾、单引号位置）。
- **modify_specs**:
  ```yaml
  - action: insert
    file: src/loop_kit/_core.py
    target: "DEFAULT_WORKER_PROMPT_TEMPLATE 内 '=== KNOWLEDGE ===\\n{knowledge_section}\\n\\n' 与 '=== TASK PACKET ===\\n{task_packet_section}\\n\\n' 两相邻行之间"
    description: "新增 8 行静态 '=== SKILL LOADING ===' 节：运行时索引 skills/index.md、命中用 skill(name=...) 加载、未命中跳过、无占位符/无大括号/无硬编码数量"
  ```
- **修改边界**：
  - 不得修改 `DEFAULT_REVIEWER_PROMPT_TEMPLATE`（6088-6096 保持字节不变）
  - 不得改动 `_render_prompt_template` / `_worker_prompt` / `_write_template_if_missing` / `cmd_init`
  - 不得新增任何 `{...}` 占位符；新节外任何行不改
- **质量检查方式**：
  - 检查项 1：`grep -n "SKILL LOADING" src/loop_kit/_core.py` → 恰 1 hit
  - 检查项 2：`grep -n "skills/index.md" src/loop_kit/_core.py` → ≥1 hit 且落在 SKILL LOADING 节内
  - 检查项 3：静态渲染检查（无 KeyError）：
    ```bash
    uv run python -c "
    from loop_kit._core import DEFAULT_WORKER_PROMPT_TEMPLATE as t
    ph = ('task_id','round_num','run_id','work_report_path','agents_md','role_md','orchestrator_path','function_index','quickstart_section','handoff_section','knowledge_section','task_packet_section','task_card_section','prior_context_section')
    t.format(**{p: 'x' for p in ph})
    assert '=== SKILL LOADING ===' in t and '/home/gw/opt/copilot-agents/skills/index.md' in t
    print('OK')
    "
    ```
- **验收标准**：
  - ✅ grep SKILL LOADING = 1 hit 且节内含 index 路径
  - ✅ 上述静态渲染命令输出 `OK`
  - ✅ `git diff src/loop_kit/_core.py` 的 hunk 仅含新节 8 行（+run_id/物理量验证节零改动）
- **潜在风险**：误加 `{`/`}` → 全部模板渲染崩溃（R3，由检查项 3 与 Phase 2 渲染测试双保险）
- **预留歧义标注**：
  - [ ] 无歧义：节文本逐字给定、锚点字符串给定、边界明确

### Phase 2: 测试更新

- **基线漂移重检**：重测 `grep -n "def test_main_init_creates_prompt_templates_in_loop_dir" tests/test_orchestrator.py` 与 `grep -n "def test_worker_prompt_round2_includes_prior_round_context" tests/test_orchestrator.py`；确认两锚点函数存在且内容与计划假设一致（若已有他人改动 → 先 diff 再并入）。

#### Task 2.1: 扩展物化断言 + 新增渲染断言

- **目标**：① `test_main_init_creates_prompt_templates_in_loop_dir` 追加 3 条断言；② 新增 `test_worker_prompt_rendered_includes_skill_loading`（模板文件路径渲染，真实走 `.format()`）
- **依赖**：T1.1
- **frontier**：是（T1.1 完成后）
- **执行者**：人工
- **修改内容**：
  - 文件 `tests/test_orchestrator.py`，修改点 ①：在 `assert "{handoff_section}" in reviewer_template`（现 421 行）与 `assert (tmp_path / "my-loop" / "handoff").exists()`（现 422 行）之间插入：
    ```python
    assert "=== SKILL LOADING ===" in worker_template
    assert "/home/gw/opt/copilot-agents/skills/index.md" in worker_template
    assert "=== SKILL LOADING ===" not in reviewer_template
    ```
  - 文件 `tests/test_orchestrator.py`，修改点 ②：在 `def test_worker_prompt_round2_includes_prior_round_context(monkeypatch) -> None:` 定义行**之前**插入（逐字，fake 模式复用现 2384 行测试的已验证套路）：
    ```python
    def test_worker_prompt_rendered_includes_skill_loading(monkeypatch) -> None:
        def fake_read(path: Path) -> str | None:
            if path == orchestrator._worker_prompt_template_path():
                return orchestrator.DEFAULT_WORKER_PROMPT_TEMPLATE
            if path.name == "AGENTS.md":
                return "AGENTS_CONTENT"
            if path.name == "code-writer.md":
                return "CODE_WRITER_CONTENT"
            return None

        def fake_read_json(path: Path) -> dict | None:
            _ = path
            return {
                "goal": "Skill loading payload",
                "in_scope": [],
                "out_of_scope": [],
                "acceptance_criteria": [],
                "constraints": [],
            }

        monkeypatch.setattr(orchestrator, "_read_text_optional", fake_read)
        monkeypatch.setattr(orchestrator, "_read_json_if_exists", fake_read_json)

        prompt = orchestrator._worker_prompt("T-603", 1)

        assert "=== SKILL LOADING ===" in prompt
        assert "/home/gw/opt/copilot-agents/skills/index.md" in prompt
    ```
- **modify_specs**:
  ```yaml
  - action: modify
    file: tests/test_orchestrator.py
    target: "test_main_init_creates_prompt_templates_in_loop_dir 内 assert '{handoff_section}' in reviewer_template 行之后"
    description: "追加 worker 模板含 SKILL LOADING 节与 index 路径断言；reviewer 模板不含该节（锁定本任务 worker-only 边界）"
  - action: insert
    file: tests/test_orchestrator.py
    target: "def test_worker_prompt_round2_includes_prior_round_context 定义行之前"
    description: "新增渲染路径测试：fake 模板读取返回 DEFAULT，断言 round-1 渲染后提示含节标记与 index 路径（防大括号逃逸回归）"
  ```
- **修改边界**：不触碰其他任何测试函数；不改 conftest.py 与其他测试文件
- **质量检查方式**：
  - 检查项 1：`uv run --group dev pytest tests/test_orchestrator.py -k "skill_loading or init_creates_prompt_templates"` → 全 pass
  - 检查项 2：`uv run ruff check tests/test_orchestrator.py` → 0 error
- **验收标准**：
  - ✅ 上述 -k 命令 2+2 测试通过（新函数 1 个 + 扩展断言 1 个函数内生效，命令覆盖 ≥2 函数）
  - ✅ 新增测试在**回退 T1.1 后**必失败（执行者可用 `git stash push src/loop_kit/_core.py` 验证再恢复——可选探针）
- **潜在风险**：fake 未覆盖 `_render_knowledge_section` 的真实路径读取 → 复用 2384 已验证同款 fake 即安全
- **预留歧义标注**：
  - [ ] 无歧义：代码逐字给定

### Phase 3: 物化模板刷新 + 全量验证

- **基线漂移重检**：`git status --porcelain`（此刻应恰为 ` M src/loop_kit/_core.py`、` M tests/test_orchestrator.py` + 既有 untracked）；确认**无活跃 loop 进程**（`pgrep -af "loop_kit" || echo none`，若有 → STOP）；确认未持有 repo 锁（不运行任何 loop 命令前先自检，此步只执行 init 不执行 run）。

#### Task 3.1: 删除并重物化 worker_prompt.txt

- **目标**：使物化模板与新 DEFAULT 字节一致（顺带修复既有 355→1071 字符漂移）
- **依赖**：T1.1（T2.1 可与本任务并行）
- **frontier**：是（T1.1 完成后）
- **执行者**：人工
- **修改内容**：
  - ① 删除 `rm .loop/templates/worker_prompt.txt`（git-tracked，删除后将显示为 `D`）
  - ② 在仓库根执行 `.venv/bin/loop init`（或 `uv run loop init`；`ROOT = Path.cwd()`，写入 `./.loop/`；`_write_template_if_missing` 仅补缺，不覆盖 reviewer_prompt.txt 与其他文件；将新建 `.loop/context/project_facts.md`、`patterns.jsonl` —— 均在 gitignore（.gitignore:8 `.loop/`）内，不产生 git 噪音）
  - ③ 字节校验（V3）
- **modify_specs**:
  ```yaml
  - action: delete_then_regenerate
    file: .loop/templates/worker_prompt.txt
    target: "删除后经 loop init 由 DEFAULT_WORKER_PROMPT_TEMPLATE + '\\n' 重新物化"
    description: "刷新物化模板至与新默认一致；diff 为整体重写（含既有漂移修复：run_id、QUICKSTART/HANDOFF/KNOWLEDGE/TASK PACKET、物理量验证节），属预期范围"
  ```
- **修改边界**：不删/不改其余 5 个 template 文件（doc_fix_*、doc_pipeline_*、reviewer_prompt.txt 保持字节不变）；不运行 `loop run` 及任何会持锁的命令；不动 `.loop/` 下 context/state/runtime/logs
- **质量检查方式**：
  - 检查项 1：`git status --porcelain` → 恰好 ` M .loop/templates/worker_prompt.txt`、` M src/loop_kit/_core.py`、` M tests/test_orchestrator.py`，untracked 仅既有 4 项 + 本计划文件，无新噪音
  - 检查项 2：`git diff --stat` 确认恰 3 文件（负向验证）
  - 检查项 3：reviewer_prompt.txt 与 4 个 doc_* 模板 md5 与基线一致（执行时先 `md5sum` 记录再比对）
- **验收标准**：
  - ✅ V3 字节校验通过（物化 == DEFAULT + "\n"）
  - ✅ git status / diff --stat 恰 3 文件、无意外新建
- **潜在风险**：重物化 diff 大于预期（R2，已声明）；init 意外触碰其他文件（检查项 3 兜底）
- **预留歧义标注**：
  - [ ] 无歧义：命令、顺序、边界给定

#### Task 3.2: 全量回归 + 提交 + PM 回写

- **目标**：全量测试/静态检查通过后，人工提交并回写 PM #3135
- **依赖**：T1.1、T2.1、T3.1
- **frontier**：否（收口任务）
- **执行者**：人工
- **修改内容**：无代码修改；执行验证命令（见下节 V1-V6）→ `git add` 恰 3 文件 → 提交
- **modify_specs**: 无（本任务无文件修改）
- **修改边界**：提交前 `git diff --stat` 必须恰 3 文件；提交信息按仓内惯例：`[Plan: pm3135-worker-prompt-skill-loading] T3: add SKILL LOADING section to worker prompt + refresh materialized template + tests (#3135)`
- **质量检查方式**：V1-V6 全绿
- **验收标准**：
  - ✅ V5 全量 pytest 0 failed、ruff 0 error
  - ✅ 提交完成，`git status --porcelain` 仅剩既有 untracked
  - ✅ 经 pm-coordinator 将 PM #3135 置 doing/done（PM 写操作必须经 pm-coordinator 委派，禁止直调 PM 工具）
- **潜在风险**：全量回归暴露与本改动无关的既有失败 → 对照 HEAD 基线先复跑确认非本改动引入，再决定是否阻塞
- **预留歧义标注**：
  - [ ] 无歧义

## Execution Wave（并行执行波次）

| Wave | 可并行 Task | Frontier | 依赖已完成 |
|------|------------|----------|-----------|
| W1 | T1.1 | T1.1 | — |
| W2 | T2.1 ‖ T3.1 | T2.1, T3.1 | W1 |
| W3 | T3.2 | — | W2 |

## Post-Execution Verification

### Automated Verification（人工执行者依次运行，任一失败即 STOP）

| ID | Description | Command | Expected |
|----|-------------|---------|----------|
| V1 | 符号与节存在性 | `grep -n "SKILL LOADING" src/loop_kit/_core.py && grep -n "skills/index.md" src/loop_kit/_core.py` | SKILL LOADING 恰 1 hit；index 路径 ≥1 hit 且同节 |
| V2 | 模板静态渲染（防大括号逃逸） | Phase 1 检查项 3 的 `uv run python -c` 命令 | 输出 `OK` |
| V3 | 物化模板字节一致性 | `uv run python -c "from pathlib import Path; from loop_kit._core import DEFAULT_WORKER_PROMPT_TEMPLATE as t; p=Path('.loop/templates/worker_prompt.txt'); assert p.read_text(encoding='utf-8')==t+'\n'; print('OK')"` | 输出 `OK` |
| V4 | git 变更面负向验证 | `git diff --stat && git status --porcelain` | 恰 3 个 tracked 修改（_core.py、test_orchestrator.py、worker_prompt.txt）；untracked 仅既有 4 项 + 本计划文件 |
| V5 | 全量回归 | `uv run --group dev pytest` 且 `uv run ruff check src/loop_kit tests` | pytest 0 failed；ruff 0 error（基线数量以执行时输出为准，不硬编码） |
| V6 | 定向测试 | `uv run --group dev pytest tests/test_orchestrator.py -k "skill_loading or init_creates_prompt_templates"` | 全部 pass |

### Deferred (needs restart / deployment)

- 无（本任务无服务/进程需重启；执行期间禁止任何 loop 进程运行）。

### Probe (best-effort, run if available)

- [ ] P1: `ls ~/opt/copilot-agents/skills/index.md` 存在（运行时索引可用性；缺失则仅提示，不阻塞本任务——引用为静态文本）
- [ ] P2: `grep -n '"skill"' ~/.config/opencode/opencode.jsonc` 确认 `permission.skill["*"]="allow"` 仍在（信息性复核，不修改）
- [ ] P3（可选，慢）：`uv run --group dev pytest -m e2e`（e2e 在 tmp_path git 仓运行、不提交本仓，基线是否全绿以执行时为准，与本改动无因果关系时不为阻塞项）

### Manual（真正需要人工判断）

- [ ] M1: 人工阅读 `git diff src/loop_kit/_core.py`，确认 hunk 仅含新节 8 行，措辞与计划逐字一致
- [ ] M2: 人工阅读 `git diff .loop/templates/worker_prompt.txt`，确认整体重写符合预期（新节 + 既有漂移修复），无意外删除
- [ ] M3（PM 收口，属 PM #3135 验收链）：ATR 实际跑一个 MCNP 建模类任务，检查轨迹出现 skill 工具调用或 worker 报告声明已加载技能——**本代码任务的产物边界到此为止**；M3 由 PM 侧在提交后另行安排（人工/后续任务），不在本计划执行范围

## 风险与回滚矩阵

| # | 风险 | 影响 | 缓解/处置 |
|---|------|------|-----------|
| R1 | 物化模板不刷新，运行期仍读旧模板 → 验收读不到新节 | 功能不生效 | T3.1 删除+重物化；V3 字节级校验；V4 确认 tracked 修改在提交内 |
| R2 | 重物化 diff 为整体重写（355→~1.4KB），含既有漂移修复 | diff 审阅面扩大 | 已在本计划显式声明；V3 保证方向正确；M2 人工复核 |
| R3 | 新节含未转义 `{`/`}` → `.format()` 抛 KeyError，全部 worker 渲染崩溃 | 高危 | V2 静态渲染 + T2.1 渲染路径测试双保险；M1 人工复核逐字 |
| R4 | 现有测试对模板结构有隐式依赖被破坏 | 回归 | 现有断言均为 `in` 子串断言（实测 407-421、2384+），新增节不破坏；V5 全量回归兜底 |
| R5 | `loop init` 创建新文件造成 git 噪音 | 低 | `.gitignore:8` 覆盖 `.loop/`；V4 验证 untracked 无新增 |
| R6 | 误触 #3155 锁机制 / 误运行 loop 命令 | 中 | 计划禁 run；Phase 3 基线重检含"无活跃 loop 进程"检查；不 import/修改 git_helpers |
| R7 | fallback 渲染路径（`_build_prompt_sections`，模板文件缺失时触发）不含新节 | 低 | 已知缺口，记录在案：fallback 仅降级路径，ATR 常规运行必有物化模板；如需覆盖另行提任务（超本任务 scope） |
| R8 | copilot-agents 搬迁 → 硬编码 index 路径失效 | 低 | 与既有 benchmark 脚本路径（_core.py:6079）同型风险；届时统一改为可配置路径（另行任务） |
| R9 | 全量回归暴露与本改动无关的既有失败 | 中 | 先以 HEAD 基线复跑确认因果；无关失败不阻塞但需记录上报 |

**回滚策略**（两条路径，均以"未提交/已提交"为分界）：
- 未提交：`git restore src/loop_kit/_core.py tests/test_orchestrator.py .loop/templates/worker_prompt.txt` 即全量还原（物化文件为 tracked，git 可还原；还原后可选重跑 `uv run loop init` 恢复与本 commit 一致的物化态）
- 已提交：`git revert <commit-sha>`（单提交变更面小，revert 干净）；物化文件随 revert 一并还原
- 禁止做法：手工改写物化文件（绕过代码单一来源）；`git reset --hard` 前未确认 untracked 计划文件不受影响（本计划文件为 untracked，reset --hard 不删 untracked，但 data/ 目录同样在，谨慎起见不推荐 reset --hard）

## 审查日志

| 轮次 | 聚焦 | 发现问题数 | 已修正 | 剩余 |
|------|------|-----------|--------|------|
| R1 | 结构完整性（task 粒度/边界/frontier/wave） | 2（T3 缺负向验证项、reviewer-only 边界未在测试锁定） | 2（V4 diff --stat；`not in reviewer_template` 断言） | 0 |
| R1.5 | 外部引用事实核查 | 2（PM notes 行号 5921 已漂移到 6059；物化模板与代码默认漂移 355 vs 1071） | 2（全部按本会话实测值落计划；漂移修复纳入 T3.1） | 0 |
| R2 | 可执行性（命令干跑） | 1（静态渲染检查的占位符清单须与模板完全一致） | 1（实测模板仅 14 个占位符，命令逐字给定） | 0 |
| R2.8 | LLM 可执行性（消除猜测空间） | 1（新节措辞若留给 executor 发挥则措辞漂移） | 1（新节/新测试/断言逐字给定，插入锚点用字符串非行号） | 0 |
| R3 | 风险与边缘（跨轮一致性） | 2（fallback 路径缺口未记录、既有漂移修复未声明为预期 diff） | 2（R7、R2 入风险矩阵） | 0 |
| **终止** | **T4 — R3 剩余 issue=0** | | | **0** |

## 交付说明（摘要）

- 计划文件：`/home/gw/opt/agent-task-runner/.github/plans/pm3135-worker-prompt-skill-loading.md`
- 结构：3 Phase / 4 Task（T1.1 → T2.1 ‖ T3.1 → T3.2），3 Wave；每 Task 含 modify_specs（action/file/target/description）
- 关键验收：V3 物化字节一致、V5 全量回归、V6 定向测试；M3（ATR 实测 skill 调用）属 PM #3135 验收链，在代码任务边界之外
- 执行后建议：`@doc-maintainer` 无需（本仓无该 agent）；PM #3135 状态回写经 pm-coordinator
