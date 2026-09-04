# dsh Backend 权限映射文档（PM #2665 T1.2）

> ⚠️ **本试点是受控评估，不构成生产安全批准**。下文如实声明 opencode deny 规则与 dsh SDK 运行时组合之间的语义差距；「无运行时强制拦截」意味着越界调用只能被事后证据捕获，不提供事前阻断。

- 日期：2026-09-05（deny 规则实测于 `~/.config/opencode/opencode.jsonc`，共 42 处——计划 2026-08-16 预期 22 处，已漂移，以实测为准）

## 原则层

| 维度 | opencode 现状 | dsh SDK 运行时（0.1.2rc1） |
|------|--------------|---------------------------|
| 批准模型 | `--auto` = 自动批准，但 per-command/per-tool deny 规则仍生效 | cordis 内置组合（agent-spine + llm-deepseek + sessions + subprocess/bush/fs-local）**无 sandbox/guard/approval 插件**；`approval/policy` 类配置无消费方 |
| 命令级拦截 | 命令级 regex deny（`rm /etc/*`、`git reset --hard`、`dd` 等 20 条） | **无等价物**。dsh 权限模型是 sandbox-mode × approval-policy 两旋钮，需自研插件才能落地 |
| 路径级拦截 | 敏感路径 deny（`.ssh`/`.gnupg`/`.aws`/`.kube`/`.config/opencode` 等 17 条） | 无对应 gate |
| 工具级拦截 | 特定 agent 的 edit/webfetch/websearch deny（5 条） | 无对应工具 gate |

## 映射表（42 条 deny 分三类，处置为可执行语句）

### A. 命令级（20 条）

| opencode 规则 | dsh 侧对应 | 试点处置 |
|--------------|-----------|---------|
| `rm /etc/*` / `rm -* /etc/*` / `rm /boot/*` / `rm -* /boot/*` / `rm ~/.ssh/*` / `rm -* ~/.ssh/*` | 无运行时强制拦截 | 试点环境无 root + 一次性 worktree 隔离兜底；**差距声明：越界调用依赖 M3 失败模式分类捕获为事后证据** |
| `reboot *` / `shutdown *` / `poweroff *` / `halt *` / `init *` | 无 | 同上（无 root 时这些命令本身失败） |
| `git reset --hard *` / `git clean *` / `git branch -D *` | 无 | worktree 隔离 + pilot 分支可丢弃兜底 |
| `dd *` / `mkfs *` / `fdisk *` / `parted *` / `iptables *` / `ufw *` | 无 | 无 root 兜底 |

### B. 路径级（17 条，部分节选）

| opencode 规则 | dsh 侧对应 | 试点处置 |
|--------------|-----------|---------|
| `../../.config/opencode/**` / `agent/**` / `context/**` / `memories/**` / `skills/**` / `instructions/**` / `AGENTS.md` / `opencode.jsonc` | 无 | 试点 TaskCard out_of_scope 白名单已排除全部仓库外路径；**差距声明：无运行时路径 gate，依赖 prompt 约束（弱保证）** |
| `../../.ssh/**` / `.gnupg/**` / `.aws/**` / `.kube/**` / `.docker/**` / `.npm/**` / `.cache/pip/**` / `.mozilla/**` / `.thunderbird/**` | 无 | 同上 |

### C. 工具级（5 条）

| opencode 规则 | dsh 侧对应 | 试点处置 |
|--------------|-----------|---------|
| 特定 agent 的 `edit` deny（3 处） | 无工具 gate | 差距声明 + follow-up（sandbox 插件评估） |
| 特定 agent 的 `webfetch`/`websearch` deny | 无 | 试点 TaskCard constraints 声明「禁止网络调用」（prompt 级约束，弱保证） |

## follow-up（不在本试点实施）

1. `packages/sandbox`（landlock）与 approval 插件组合评估
2. dsh 自研 guard 插件（per-command regex deny 的 dsh 等价物）
3. 若试点推广，需先落地至少 sandbox-mode 隔离，否则 dsh 不得用于非隔离 lane

## 附录：42 条 deny 全量枚举（opencode.jsonc 实测，2026-09-05）

路径级 17 条（全部 deny）：
- `../../.config/opencode/**` → deny
- `../../.ssh/**` → deny
- `../../.gnupg/**` → deny
- `../../.aws/**` → deny
- `../../.kube/**` → deny
- `../../.docker/**` → deny
- `../../.npm/**` → deny
- `../../.cache/pip/**` → deny
- `../../.mozilla/**` → deny
- `../../.thunderbird/**` → deny
- `../../.config/opencode/agent/**` → deny
- `../../.config/opencode/context/**` → deny
- `../../.config/opencode/memories/**` → deny
- `../../.config/opencode/skills/**` → deny
- `../../.config/opencode/instructions/**` → deny
- `../../.config/opencode/AGENTS.md` → deny
- `../../.config/opencode/opencode.jsonc` → deny

命令级 20 条（全部 deny）：
- `rm /etc/*` → deny
- `rm -* /etc/*` → deny
- `rm /boot/*` → deny
- `rm -* /boot/*` → deny
- `rm ~/.ssh/*` → deny
- `rm -* ~/.ssh/*` → deny
- `reboot *` → deny
- `shutdown *` → deny
- `poweroff *` → deny
- `halt *` → deny
- `init *` → deny
- `git reset --hard *` → deny
- `git clean *` → deny
- `git branch -D *` → deny
- `dd *` → deny
- `mkfs *` → deny
- `fdisk *` → deny
- `parted *` → deny
- `iptables *` → deny
- `ufw *` → deny

工具级 5 条（全部 deny）：
- `edit` → deny（特定 agent ×3）
- `webfetch` → deny（特定 agent）
- `websearch` → deny（特定 agent）

合计：17 + 20 + 5 = 42 条 deny（与 grep 实测行数一致）。

## 模板适配说明（SDK 0.1.2rc1 API 漂移）

计划（2026-08-16）原定从 venv SDK 复制 cordis.yml 生成试点模板。实测 0.1.2rc1：venv runtime 为单文件二进制（267MB），内置 cordis 无 compression 配置键；SDK 配置面从 `session_root`/`cordis` 参数变为 `dsh_home` + env `DSH_SESSION_ROOT` + `profile`/`patches`。试点隔离改用 env 注入（见 `_run_dsh_sdk_dispatch`），不再需要独立 cordis 模板文件。transcript 压缩格式待 T2.3 真机落盘后实测（见探针报告 docs/dsh-pilot-probe.md）。
