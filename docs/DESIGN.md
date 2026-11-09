# agent-tool-kits · 设计文档

> 2026-09-10 · 状态：Phase 0 已落地（skills 全局分发）

## 1. 问题

我会持续积累大量 agent 资产（skill、subagent、command、rule、plugin），并同时使用多个平台
（Claude Code、Codex、Cursor、OpenCode、pi……）。每个平台读取资产的目录不同、格式略有差异，
而且资产要按需分发：有的全局可用，有的只给某个项目，有的只给某个平台。手动复制不可持续：

- 同一技能出现多份分叉副本（曾经的 `~/.codex/skills/gh-search-projects` vs `~/.agents/skills/searching-github-projects`）。
- 技能散落在 5 个目录，部分平台（Claude/Cursor/OpenCode 的全局目录）根本没吃到。
- 平台插件各自缓存，版本漂移。

## 2. 结论：不造安装器，造"仓库 + 清单 + 薄胶水"

调研结论（Star 数为 2026-09-10 实时核验）：

| 项目 | Stars | 对本方案的角色 |
|---|---|---|
| [vercel-labs/skills](https://github.com/vercel-labs/skills) | 30.8k | 事实标准的 skill 安装器（79 个 agent）。**外部技能**直接委托给它。 |
| [eljulians/skillfile](https://github.com/eljulians/skillfile) | 145 | 声明式 `Skillfile` + lock + patch 的思路，是 profile 格式的参考。 |
| [dyoshikawa/rulesync](https://github.com/dyoshikawa/rulesync) | 1.4k | rules/commands/mcp/subagents/hooks 的多平台生成器，Phase 3 接入。 |
| [intellectronica/ruler](https://github.com/intellectronica/ruler) | 2.9k | rules + MCP 分发，与 rulesync 二选一。 |

关键源码发现（`vercel-labs/skills/src/installer.ts`）：其 symlink 模式并不是链到你的源目录，而是先
**copy** 到规范目录 `~/.agents/skills/<name>`，再从各平台目录 symlink 过去。因此仓库里改了
SKILL.md 不会实时生效。这决定了本仓库自有技能由 `graft` **直接 symlink 到仓库**，只有外部技能才交给它。

## 3. 架构

```
agent-tool-kits/
├── skills/                   # vault：自有技能，SKILL.md 目录（agentskills.io 格式）
├── plugins/                  # 自有插件：plugin.yaml + skills/（拷贝同步；目前 matt-agent-skills）
├── profiles/
│   ├── global.yaml           # 机器级：什么 → 哪个平台的全局目录
│   └── projects/<name>.yaml  # 项目级（Phase 2）
├── src/graft/                # CLI（Python 3.11+，uv）
│   ├── platforms.py          #   平台注册表：各平台 project/global skills 目录、本地插件目录
│   ├── vault.py              #   仓库根定位、技能/插件发现、frontmatter 解析
│   ├── profile.py            #   YAML 清单加载/校验/回写（ruamel，保留注释）
│   ├── engine.py             #   plan / apply：对比清单与磁盘，幂等修正
│   ├── importer.py           #   graft import：收编散落技能
│   ├── external.py           #   委托 `npx skills add`
│   └── fsutil.py             #   symlink、拷贝、备份、目录等价比较
├── docs/DESIGN.md
└── README.md
```

### 3.1 四类资产、四条通道

| 资产 | 通道 | 说明 |
|---|---|---|
| vault 内 skill | `graft` 直接 symlink：`<平台目录>/<name> → <repo>/skills/<name>` | 编辑即生效；绝对路径；仓库移动后重新 `apply` 即可 |
| 外部 skill（`source: owner/repo`） | `npx -y skills@latest add <source> --skill <name> -a <平台…> -g -y` | 不 vendor；由其 `~/.agents/.skill-lock.json` 记录 hash；更新用 `npx skills update` |
| vault 内 plugin（`plugins/<name>/plugin.yaml`） | `graft` **拷贝**：`<平台插件目录>/<name>` ← `<repo>/plugins/<name>`，逐文件比较判定 ok / sync | 编辑后需再 `apply`；目前只有 Cursor（`~/.cursor/plugins/local`）有本地插件目录 |
| rules / MCP / pi extension | Phase 3 | 见路线图 |

**为什么插件不是 symlink**：Cursor 的 `loadUserLocalPlugins` 对 `~/.cursor/plugins/local/` 下每个 symlink 条目做
`realpath`，结果必须仍在该目录内，否则 `rejected: symlink target … is outside`；marketplace 路径的文件读取器还会对
每个文件做同样的逃逸检查。这是刻意的安全防护，没有开关。其它备选（真实目录 + 内部软链、`agent --plugin-dir`、
借道 Claude Code 的 `importThirdPartyPlugins`、注册为 marketplace）要么钻防护的缝、要么只对 CLI 生效、要么本质上也是
拷贝快照。拷贝同步是唯一落在 Cursor 设计意图之内、又能由 graft 无状态管理的方案。

### 3.2 平台路径（与 vercel skills 一致）

| id | 项目级 | 全局 |
|---|---|---|
| `claude-code` | `.claude/skills` | `$CLAUDE_CONFIG_DIR|~/.claude/skills` |
| `codex` | `.agents/skills` | `$CODEX_HOME|~/.codex/skills` |
| `cursor` | `.agents/skills` | `~/.cursor/skills` |
| `opencode` | `.agents/skills` | `$XDG_CONFIG_HOME/opencode/skills` |
| `pi` | `.pi/skills` | `~/.pi/agent/skills` |
| `gemini-cli` / `antigravity` / `github-copilot` | `.agents/skills` | `~/.gemini/skills` / `~/.gemini/antigravity/skills` / `~/.copilot/skills` |
| `universal` | `.agents/skills` | `~/.agents/skills`（vercel skills 的规范目录，amp/cline/zed 读取） |

项目级里 Codex / Cursor / OpenCode 共用 `.agents/skills`，一个 symlink 三家共享。

### 3.3 清单格式

```yaml
targets: [claude-code, codex, cursor, opencode, universal]

skills:
  searching-github-projects: { to: [codex, cursor] }   # vault 技能
  mcp-builder: { to: "*" }                             # "*" = 全部 targets
  frontend-design:                                     # 外部技能
    source: anthropics/skills
    to: [cursor, claude-code]
  pdf: [codex]                                         # 简写

plugins:
  matt-agent-skills: { to: [cursor] }                  # vault 插件；"*" 只展开到支持插件的平台
```

`plugins:` 目前只允许出现在机器级清单（不能与 `path:` 同现），`to` 里的平台必须有本地插件目录，否则加载时报错。

### 3.4 无状态的 drift 检测

不维护 lock。"被 graft 管理"的定义：

- 技能：**该路径是 symlink，且解析后落在 `<repo>/skills/` 内**。
- 插件：**该路径是真实目录，且目录名对应 `<repo>/plugins/` 里的一个插件**（symlink 做不到，见 3.1）。

据此可以纯靠文件系统判定：

| state | 适用 | 含义 | `apply` 动作 |
|---|---|---|---|
| `ok` | 技能 / 插件 | 已链接 / 拷贝与 vault 一致 / 外部技能已存在 | 无 |
| `link` | 技能 | 目标不存在 | 建链 |
| `relink` | 技能 | 是 symlink 但指向别处 / 断链 | 重建 |
| `adopt` | 技能 | 真实目录且与 vault 内容一致 | 备份后换成 symlink |
| `copy` | 插件 | 目标不存在，或是指向 vault 的（无效）symlink | unlink 后拷贝 |
| `sync` | 插件 | 真实目录但内容与 vault 不同 | 备份后重新拷贝 |
| `conflict` | 技能 / 插件 | 真实目录且内容不同（技能）；普通文件或指向 vault 之外的 symlink（插件） | 报错；`--force` 备份后换链 / 拷贝 |
| `external-missing` | 技能 | 外部技能缺失 | 分组调用 `npx skills add` |
| `orphan` | 技能 / 插件 | 被 graft 管理但清单未声明 | `--prune`：symlink 删除，真实拷贝备份 |
| `not-in-vault` | 技能 / 插件 | 清单写了 vault 里没有的资产 | 报错 |

插件的 `sync` 不要求 `--force`：目标目录名对应 vault 插件即视为 graft 的拷贝，过期是常态。为了守住"不删用户文件"，
每次重新拷贝前旧副本仍进备份目录（`<时间戳>/cursor-plugins/<name>`），代价是备份目录会随更新次数增长。

任何被替换的真实目录都移动到 `~/.local/share/graft/backup/<时间戳>/`，永不直接删除。

### 3.5 `graft import` 的收编规则

对每个含 `SKILL.md` 的目录（名字取 frontmatter `name`，回退目录名；平台按路径前缀推断）：

1. 已是指向 vault 的 symlink → 只补清单。
2. 外部技能（`--source` 指定、清单已有 `source`、或出现在 vercel lock 里）→ 文件原地不动，只记 `source` + `to`。
3. vault 中已有同名且内容一致 → 原目录备份，换成 symlink。
4. vault 中已有同名但内容不同 → 报 conflict，跳过（`--rename` 另存）。
5. 新技能 → 移入 `skills/<name>`，在原目录的**规范名**位置留 symlink，写入清单。

## 4. Phase 0 执行记录（2026-09-10）

- `.agents/skills/searching-github-projects` → `skills/`（顶层 vault）。
- 收编：`sora`、`skill-lookup`（原目录名 `skills-lookup`）进入 vault；`figma-use/pdf/playwright` 记为 `openai/skills` 外部；
  `find-skills/mcp-builder/skill-creator/frontend-design` 记为外部（vercel-labs/skills、anthropics/skills）。
- 旧分叉副本 `~/.codex/skills/gh-search-projects` 归档到 `~/.local/share/graft/backup/manual/`。
- 删除 `~/.agents/skills/.git`（GitKraken 残留，非真实仓库）和各处 `.DS_Store`。
- `graft apply` 后 `searching-github-projects` 在 Claude Code / Codex / Cursor / OpenCode / universal 五处全局可用；`graft status` = 14 ok。

## 5. 路线图

**Phase 1 · plugins**
- ✅ 清单 `plugins:` 段；`vault.plugins()` 枚举 `plugins/<name>/plugin.yaml`；`platforms` 登记本地插件目录（目前只有 Cursor）。
- ✅ Cursor 安装策略 = **拷贝同步**（`copy` / `sync` / 插件 `orphan`，见 3.4）；替代原计划的 symlink（被 Cursor 拒绝）。
- ✅ `matt-agent-skills` 已按方案 A 落到 `plugins/matt-agent-skills/`，并由 graft 管理。
- ☐ `plugins/<name>/plugin.yaml` → 生成 / 校验 `.cursor-plugin/plugin.json`、`.claude-plugin/plugin.json`、`.codex-plugin/plugin.json`（`graft plugin build --check`）。三家共享标识字段（`name`/`version`/`description`/`author`/`keywords`/`skills`），展示字段按平台投影，不是字节级同构；Cursor 多 `rules/agents/commands`，Codex 多 `apps/interface`。
- ☐ Claude Code / Codex 的插件通道：二者没有"放一个目录就被发现"的本地插件机制，要走 marketplace（Claude `claude plugin marketplace add <path>` + `installed_plugins.json`；Codex `~/.agents/plugins/marketplace.json`）。设计上对应 `PluginSpec` 增加按平台的 `strategy: copy | marketplace`，`marketplace` 策略只委托原生命令，与外部技能的 `npx skills add` 同一模式。
- ☐ 外部插件（如 superpowers）只记来源，调各平台原生命令安装。

**Phase 2 · 项目级 + 体检**
- `profiles/projects/<name>.yaml`（含 `path:`），`graft apply <name>`；`graft link` 在任意项目目录内生成并应用。
- `graft doctor`：各平台 marketplace 注册状态、CLI 是否在 PATH、断链、`.DS_Store`。
- 引擎已按 `project` 参数抽象，主要是 CLI 与清单发现的工作。

**Phase 3 · rules / MCP / hooks / pi**
- 接 rulesync（生成模式）分发 AGENTS.md / CLAUDE.md / `.cursor/rules` / MCP / hooks。
- 仓库根 `package.json` 增加 `pi` 字段，使 `pi install git:<repo>` 能装 TS extension。
- GitHub Action：`graft plugin build --check` 防止 manifest 漂移。

## 6. 约定

- **语言以中文为主**：README、设计文档、清单注释、CLI 帮助与输出、自有技能的 SKILL.md 正文都用中文。
  技能 frontmatter 的 `description` 可以中英混写，保留英文触发词以便各平台匹配。
- 从上游原样收编、仍与上游对齐的技能（如 `sora`，Apache-2.0）保持原文，不做翻译，方便日后对比更新。
- 代码标识符、状态名（`ok/link/relink/adopt/copy/sync/conflict/orphan`）、平台 id 保持英文，它们是机器值。

## 7. 已知取舍

- 清单回写用 ruamel.yaml 保留注释，但被 `import` 改写的条目会丢失该条目自己的行内注释。
- 外部技能的"是否已安装"仅看目标路径是否存在，不校验 hash；版本更新交给 `npx skills update`。
- 插件拷贝的 ok / sync 判定用 `filecmp` 浅比较（类型 + 大小 + mtime）；拷贝时用 `copy2` 保留 mtime 让刚拷完即 ok。
  大小与 mtime 都相同但内容不同的编辑理论上会漏判，实际编辑器写文件都会更新 mtime。
- 插件每次 `sync` 都备份旧副本，备份目录随更新次数增长，需要时手工清理 `~/.local/share/graft/backup/`。
- Windows 未考虑（symlink 权限）。
- `universal` 平台对应 `~/.agents/skills`；vercel skills 新版把 universal agent 的全局目录改成了 `~/.config/agents/skills`，但规范拷贝仍在 `~/.agents/skills`，所以存在性判断不受影响。
