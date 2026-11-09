# AGENTS.md · agent-tool-kits

> 给接手本仓库的 AI agent / 开发者看的交接文档。先读完本文件，再看 `docs/DESIGN.md`。
> 语言约定：本仓库所有面向人的文字（文档、注释、CLI 文案、自有技能）以**简体中文**为主。

## 1. 这个仓库是什么

一个"金库 + 清单 + 薄胶水"：

- **金库（vault）** `skills/`：我自己维护的 skill 的唯一事实来源（后续加 agents / commands / rules）。
- **插件** `plugins/`：自有插件目录（目前 `matt-agent-skills`），每个含 `plugin.yaml`；由清单 `plugins:` 段声明，**拷贝同步**到平台本地插件目录（目前只有 Cursor）。
- **清单（profile）** `profiles/*.yaml`：声明"哪个资产 → 装到哪个平台 → 全局还是某项目"。
- **胶水** `atkits` CLI（Python 3.11 + uv）：读清单、对比磁盘、把差异补齐。金库技能直接 **symlink** 到各平台目录；插件 **拷贝**（Cursor 拒绝指向目录外的软链）；外部技能委托 `npx skills add`（vercel-labs/skills）。

它**不是**新的安装器、不是技能市场、不 vendor 第三方技能。

## 2. 目录结构

```
agent-tool-kits/
├── AGENTS.md                 # 本文件：交接与约束
├── README.md                 # 用户视角的用法
├── docs/DESIGN.md            # 调研结论、架构决策、状态机、路线图（权威设计文档）
├── skills/                   # 金库：每个子目录一个技能，必含 SKILL.md（agentskills.io 格式）
│   ├── ai-image-prompt-engineer/    # 通用图像提示词；保留原方法论，摄影规则按需启用
│   ├── canvas-design/               # 静态视觉设计：设计哲学 → PNG/PDF，字体按需下载
│   ├── searching-github-projects/   # 自有，中文
│   ├── skill-lookup/                # 自有，中文
│   └── sora/                        # 上游原样收编（Apache-2.0），保持英文
├── plugins/                  # 自有插件：<name>/plugin.yaml + skills/ + 三家 plugin.json
│   └── matt-agent-skills/    # 方案 A 收编；atkits 拷贝到 ~/.cursor/plugins/local/
├── profiles/
│   ├── global.yaml           # 机器级清单（当前唯一生效的清单）
│   └── projects/<name>.yaml  # 项目级清单（Phase 2，目录尚未创建）
├── src/atkits/               # CLI 源码，见 §4
├── pyproject.toml            # uv 项目；入口 atkits = atkits.cli:app
└── uv.lock
```

## 3. 核心概念与不变量

| 概念 | 定义 | 不变量 |
|---|---|---|
| 金库技能 | `skills/<name>/SKILL.md` 存在 | 名字取 frontmatter `name`，回退目录名；目录名应与 `name` 一致 |
| 外部技能 | 清单里带 `source: owner/repo` | **不入库**，文件由 `npx skills add` 放置；atkits 只判断目标路径是否存在 |
| 金库插件 | `plugins/<name>/plugin.yaml` 存在 | 名字取 `plugin.yaml` 的 `name`，回退目录名；**拷贝**到平台插件目录，不 symlink |
| 被 atkits 管理（技能） | 目标路径是 symlink，且 `resolve()` 落在 `<repo>/skills/` 内 | 由此无状态判定 ok / orphan，**没有 lock 文件**，也不要加 |
| 被 atkits 管理（插件） | 目标是真实目录，且目录名对应金库里的一个插件 | 内容用 `fsutil.dirs_equal()` 逐文件比较决定 ok / sync；同样不加 lock |
| 备份 | 任何被替换的真实目录移到 `~/.local/share/atkits/backup/<时间戳>/` | **永不直接删除用户文件**；symlink 可直接 unlink；插件 `sync` 前旧副本也进备份 |
| 平台 id | 与 vercel `skills` CLI 的 `--agent` 名一致 | 新增平台必须沿用其命名，路径以其 `src/agents.ts` 为准 |

### 平台路径（`src/atkits/platforms.py`）

| id | 项目级 | 全局 |
|---|---|---|
| `claude-code` | `.claude/skills` | `$CLAUDE_CONFIG_DIR` 或 `~/.claude/skills` |
| `codex` | `.agents/skills` | `$CODEX_HOME` 或 `~/.codex/skills` |
| `cursor` | `.agents/skills` | `~/.cursor/skills` |
| `opencode` | `.agents/skills` | `$XDG_CONFIG_HOME/opencode/skills` |
| `pi` | `.pi/skills` | `~/.pi/agent/skills` |
| `gemini-cli` / `antigravity` / `github-copilot` | `.agents/skills` | `~/.gemini/skills` / `~/.gemini/antigravity/skills` / `~/.copilot/skills` |
| `universal` | `.agents/skills` | `~/.agents/skills`（vercel skills 的规范目录） |

本地插件目录（`Platform._global_plugins_dir`，机器级）：只有 `cursor` → `~/.cursor/plugins/local`。Claude Code / Codex 没有"放目录即发现"的机制，要走 marketplace，属后续工作；清单里给它们声明插件会在加载时报错。

## 4. 代码地图（`src/atkits/`）

| 文件 | 职责 | 改动时注意 |
|---|---|---|
| `platforms.py` | 平台注册表、路径展开、按路径反推平台、本地插件目录 | 路径模板用 `$HOME/$XDG_CONFIG_HOME/$CLAUDE_HOME/$CODEX_HOME` 占位，运行时展开，便于测试时用假 HOME；`_global_plugins_dir=None` 表示该平台不支持本地插件 |
| `vault.py` | 定位仓库根（`$ATKITS_HOME`，兼容旧 `$GRAFT_HOME` → 向上找 `profiles/`+`skills/` → 包所在仓库）、枚举技能与插件、解析 frontmatter | `Vault.contains()` / `contains_plugin()` 是"symlink 是否指向金库"的唯一依据 |
| `profile.py` | 加载/校验/回写清单（ruamel.yaml，保留注释） | `to: "*"` 展开为 `targets`（插件只展开到支持插件的平台）；`to` 里的平台必须在 `targets` 内，否则报错；`plugins:` 不能与 `path:` 同现 |
| `engine.py` | `plan()` 产出 `Action` 列表；`apply()` 执行 | 状态机见下表；`Action.kind` 区分 skill / plugin，插件动作走 `_execute_plugin`；新增状态要同步 `cli._STATE_STYLE` |
| `importer.py` | `atkits import` 收编逻辑 | 外部来源判定顺序：`--source` → 清单已有 `source` → `~/.agents/.skill-lock.json` |
| `external.py` | 组装并执行 `npx -y skills@latest add …` | 按 (source, skill) 分组，一次传多个 `--agent` |
| `fsutil.py` | symlink、拷贝、备份、递归目录等价比较（忽略 `.DS_Store/.git/__pycache__`） | symlink 用绝对路径；`copy_tree()` 用 `copy2` 保留 mtime，使 `dirs_equal()` 浅比较刚拷完即相等 |
| `cli.py` | typer 命令：`status / apply / import / platforms / skills / plugins` | 文案中文；`status` 有差异时退出码 1 |

### 状态机（`engine.State`）

| state | 适用 | 含义 | `apply` 动作 |
|---|---|---|---|
| `ok` | 技能 / 插件 | 已链接 / 拷贝一致 / 外部技能已存在 | 无 |
| `link` | 技能 | 目标不存在 | 建 symlink |
| `relink` | 技能 | 是 symlink 但指向别处或断链 | 重建 |
| `adopt` | 技能 | 真实目录且内容与金库一致 | 备份 → symlink |
| `copy` | 插件 | 目标不存在，或是指向金库 / 断掉的 symlink | unlink → 拷贝 |
| `sync` | 插件 | 真实目录但内容与金库不同 | 备份 → 重新拷贝（不需要 `--force`） |
| `conflict` | 技能 / 插件 | 技能：真实目录且内容不同；插件：普通文件或指向金库外的 symlink | 报错退出 1；`--force` 时备份 → symlink / 拷贝 |
| `external-missing` | 技能 | 外部技能不存在 | 调 `npx skills add`（`--no-external` 跳过） |
| `orphan` | 技能 / 插件 | 被 atkits 管理但清单未声明 | 仅 `--prune` 时：symlink unlink，真实拷贝备份 |
| `not-in-vault` | 技能 / 插件 | 清单声明了金库里没有的资产 | 报错退出 1 |
| `error` | 技能 / 插件 | 文件系统操作失败 | 记录并继续，最终退出 1 |

## 5. 日常工作流

```bash
uv sync                          # 首次
uv run atkits status              # 看差异（退出码 1 = 有事要做）
uv run atkits apply -n            # 预演
uv run atkits apply               # 执行
uv run atkits apply --prune       # 顺带清孤儿链接 / 孤儿插件拷贝
uv run atkits import <path> [-n] [--source owner/repo] [--to a,b] [--rename x]
```

**新增一个自有技能**：`skills/<name>/SKILL.md`（frontmatter `name` 与目录同名）→ 在 `profiles/global.yaml` 的 `skills:` 加一行 → `atkits apply`。

**新增一个外部技能**：在清单加 `source` + `to` → `atkits apply`（会联网调 npx）。**不要**把第三方技能拷进 `skills/`。

**更新外部技能**：`npx skills update`，不归 atkits 管。

**新增 / 修改一个插件**：`plugins/<name>/plugin.yaml` + `.cursor-plugin/plugin.json` + `skills/` → 在 `plugins:` 加一行 → `atkits apply`。插件是拷贝，**改完任何文件都要再跑 `atkits apply`**（`status` 会显示 `sync`）；Cursor 几秒内自动重新扫描 `~/.cursor/plugins/local/`，验证可看 `Cursor Plugins.log` 里的 `loadUserLocalPlugin <name> loaded`。

## 6. 验证要求

- 改 `src/atkits/` 后必须通过：`uvx ruff format src/ && uvx ruff check src/`。
- 手工验证用**隔离环境**，不要直接对真实 HOME 试错：
  ```bash
  export HOME=/tmp/x/home ATKITS_HOME=/tmp/x/vault
  export XDG_CONFIG_HOME=$HOME/.config XDG_DATA_HOME=$HOME/.local/share   # 必须另起一行，否则 $HOME 还是旧值，备份会落进真实目录
  ```
  流程覆盖：import（moved / linked / external / conflict）→ apply（link / adopt / conflict → `--force`）→ 删清单条目 → orphan → `--prune` → 再跑 `status` 应为全 ok。
  插件另覆盖：起点放一条指向假金库的 symlink → apply 应为 `copy` 并换成真目录（不带 `.DS_Store`）→ 改金库 → `sync` → 目标换成普通文件 → `conflict` / `--force` → 删清单条目 → `orphan` → `--prune` 走备份。
- 对真实机器执行前先 `-n` 预演；完成后 `atkits status` 退出码必须为 0。
- 验证脚本放在仓库外（`/tmp`），不要提交。仓库目前**没有** `tests/`，若要加请用 pytest + `tmp_path`，并复用上面的隔离环境思路。

## 7. 硬性约束

1. **不删除用户文件**：只 unlink symlink；真实目录一律走 `fsutil.backup()`。
2. **不引入 lock/状态文件**：管理状态从文件系统推导。
3. **外部技能不入库**；如需本地修改上游技能，先 fork 或放到 `skills/` 并去掉 `source`，二者不可并存。
4. **平台 id 与路径跟随 vercel-labs/skills**，不自造命名。
5. **不碰 `~/.codex/skills/.system/`**（Codex 内置技能）。
6. 清单回写只通过 `Profile.add_skill()/save()`，保留注释；不要用 `yaml.safe_dump` 重写。
7. 中文优先（见 `docs/DESIGN.md` §6）；机器值（状态名、平台 id、标识符）保持英文。
8. 提交信息用中文，一次提交一个主题。

## 8. 路线图与接手点

详细见 `docs/DESIGN.md` §5。摘要：

- **Phase 1 · plugins**：已完成清单 `plugins:` 段、金库插件枚举、Cursor 拷贝同步（`copy / sync / orphan`），`matt-agent-skills` 由 atkits 管理。仍待做：由 `plugin.yaml` 生成/校验三家 manifest（`atkits plugin build --check`）；Claude Code / Codex 走 marketplace 通道（Claude `claude plugin marketplace add <path>`；Codex `~/.agents/plugins/marketplace.json`），设计为 `PluginSpec` 按平台加 `strategy: copy | marketplace`，`marketplace` 只委托原生命令；外部插件记来源。
- **Phase 2 · 项目级**：`profiles/projects/<name>.yaml`（含 `path:`），`atkits apply <name>`；`atkits link` 在项目目录内生成清单；`atkits doctor`。引擎已按 `profile.project` 抽象，主要是 CLI 与清单发现的工作。
- **Phase 3 · rules / MCP / hooks / pi**：接 rulesync 生成 AGENTS.md / CLAUDE.md / `.cursor/rules` / MCP；根 `package.json` 加 `pi` 字段；CI 跑 `atkits plugin build --check`。

接手任一阶段前：先 `uv run atkits status` 确认当前机器状态干净；再读 `docs/DESIGN.md` 对应小节；新增功能沿用"plan 产出 Action → apply 执行"的模式，不要绕过 `engine`。

## 9. 已知坑

- vercel `skills` 的 symlink 模式会把技能**复制**到 `~/.agents/skills/<name>` 再链过去，不是链到源仓库；所以自有技能必须由 atkits 自己建链，否则改动不实时。
- 技能目录名与 frontmatter `name` 不一致时，`import` 以 `name` 为准，并在原目录**规范名**位置留 symlink（历史上 `skills-lookup/` → `skill-lookup`）。
- `universal` 平台对应 `~/.agents/skills`；vercel 新版把 universal agent 的全局目录改成 `~/.config/agents/skills`，但规范拷贝仍在 `~/.agents/skills`，存在性判断不受影响。
- 沙箱环境可能禁止写 `~/.cursor`，本地验证时若报 `Operation not permitted`，是沙箱而非代码问题。
- **Cursor 本地插件不能 symlink**：`~/.cursor/plugins/local/<name>` 若是指向目录外的软链，加载器 `realpath` 校验后直接 `rejected`，日志在 `~/Library/Application Support/Cursor/logs/*/exthost/anysphere.cursor-agent-exec/Cursor Plugins.log`。这就是插件走拷贝的原因；不要再尝试建链。
- `agent --plugin-dir <path>` 只对 Cursor CLI 生效，IDE 不认；`agent plugin marketplace add` 只接 git URL 且按 commit 缓存快照。
- 清单被 `import` 改写的条目会丢失该条目自身的行内注释（ruamel 局限）。
- Windows 未考虑（symlink 权限）。
