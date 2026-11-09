# agent-tool-kits

一个仓库存放我所有的 agent 资产（目前是 skill；接下来是 agent / command / rule / plugin），
通过声明式清单"嫁接"到我使用的各个平台——Claude Code、Codex、Cursor、OpenCode、pi——
而不是手动复制。

```
skills/                  # 金库（vault）：SKILL.md 目录，agentskills.io 格式
plugins/                 # 插件：plugin.yaml + skills/，拷贝同步到平台本地插件目录
profiles/global.yaml     # 机器级清单：什么装到哪个平台
profiles/projects/*.yaml # 项目级清单（Phase 2）
src/atkits/               # atkits 命令行（Python，uv）
docs/DESIGN.md           # 调研、架构、路线图
```

## 安装

```bash
uv sync                      # 开发方式：之后用 `uv run atkits ...`
uv tool install -e .         # 或者把 `atkits` 装到 PATH
```

## 使用

```bash
atkits status                 # 对比清单与磁盘，不改任何东西
atkits apply --dry-run        # 只看计划
atkits apply                  # 金库技能建 symlink，插件拷贝同步，外部技能走 `npx skills add`
atkits apply --prune          # 同时清理清单里已不存在的金库 symlink / 插件拷贝
atkits import ~/.codex/skills # 把散落的技能收编进金库和清单
atkits platforms              # 各平台读取全局技能 / 本地插件的目录
atkits skills                 # 金库里有什么技能
atkits plugins                # 金库里有什么插件
```

金库里的技能是直接 **symlink** 到各平台技能目录的，改一处 `skills/` 立即处处生效。
外部技能（`source: owner/repo`）不入库，`atkits` 委托 [`npx skills add`](https://github.com/vercel-labs/skills)
安装，由它维护自己的 lock 文件。

插件（`plugins/<name>/`）是 **拷贝同步**，不是 symlink：Cursor 的 `~/.cursor/plugins/local/` 会拒绝
任何指向该目录之外的软链（realpath 校验）。所以改了 `plugins/` 之后要再跑一次 `atkits apply`，
`status` 会把内容过期的拷贝标为 `sync`。目前只有 Cursor 有"放一个目录就能被发现"的本地插件机制，
Claude Code / Codex 走 marketplace，留给后续阶段。

任何东西都不会被直接删除：被 `atkits` 替换掉的真实目录（包括过期的插件拷贝）会移到
`~/.local/share/atkits/backup/<时间戳>/`。

## 清单格式

```yaml
targets: [claude-code, codex, cursor, opencode, universal]

skills:
  searching-github-projects: { to: [codex, cursor] }   # 金库技能
  mcp-builder: { to: "*" }                             # 全部 targets
  frontend-design:                                     # 外部技能
    source: anthropics/skills
    to: [cursor, claude-code]

plugins:
  matt-agent-skills: { to: [cursor] }                  # 金库插件，拷贝到 ~/.cursor/plugins/local/
```

目前的插件是 [`matt-agent-skills`](plugins/matt-agent-skills/README.md)。

完整设计与路线图见 [docs/DESIGN.md](docs/DESIGN.md)。
