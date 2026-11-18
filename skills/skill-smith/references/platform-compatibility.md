# 平台兼容规则

制作或打包 Skill 时使用本文件。

## 当前目标

- 规范：<https://agentskills.io/specification>
- 规则核对日期：2026-11-10
- Python 基线：3.10 及以上
- 包内脚本依赖：仅 Python 标准库

产物是一个普通 Skill 目录，不依赖某一家宿主的私有字段。Cursor、Codex、Claude Code 加载的是同一份 `SKILL.md`。差别只在目录放在哪里。

## 目录与 frontmatter

| 项目 | 规则 |
|---|---|
| 目录名 | kebab-case，与 `name` 一致 |
| `name` | 必填，1—64 字符，小写字母、数字、单个连字符 |
| `description` | 必填，20—1024 字符，写清做什么、何时用、关键能力和真实触发短语 |
| `metadata.version` | 必填，严格 `MAJOR.MINOR.PATCH`，新建从 `1.0.0` 开始 |
| `license` / `compatibility` / `allowed-tools` | 可选。`compatibility` 不超过 500 字符 |
| `metadata` 其他键 | 值必须是字符串 |
| `SKILL.md` | 根目录必备，大小写精确 |
| 顶层正文 | 不超过 500 行；细节放 `references/` |

不要写 `agent_created`，也不要把 `version` 放在 frontmatter 顶层。这两处不属于 Agent Skills 规范，严格校验会拒绝。

## 修改范围

只修改当前项目里的 Skill，包括项目中的 `skills/<name>/`、`.agents/skills/<name>/` 和 `.claude/skills/<name>/`。

这些用户级目录只用来识别，不能写入或覆盖：

| 位置 | 目录 |
|---|---|
| Cursor | `~/.cursor/skills/` |
| Codex、通用目录 | `~/.agents/skills/` |
| Claude Code | `~/.claude/skills/` |
| Codex 旧位置 | `~/.codex/skills/` |

用户拿出的 Skill 位于上述目录时，停止修改，请用户提供项目里的那一份。

## 项目内写入目录

新建时，`render` 的 `--output-dir` 指向代理会读取的项目目录。改写时直接修改该目录中的技能。

| 代理 | 项目内路径 |
|---|---|
| Cursor、Codex | `.agents/skills/<name>/` |
| Claude Code | `.claude/skills/<name>/` |

## 版本规则

- 新建：`1.0.0`
- PATCH：不改变能力和兼容性的文案或缺陷修正
- MINOR：新增向后兼容的能力、脚本或模板
- MAJOR：删除能力、改变输入输出，或引入不兼容结构

改写已有技能时升高 `metadata.version`。

## 路径规则

- 文档写 `~/.agents/skills/`、`.agents/skills/` 或相对路径，不写用户名和盘符。
- 脚本用 `Path.home()` 和 `pathlib` 解析路径。
- `render` 拒绝把用户级技能目录当作输出目录。
- `render` 在写入前做静态预检。预检阻断且没有 `--risk-ack` 时不创建目录。

## 编码与文件名

- 文本统一 UTF-8。
- JSON 使用 UTF-8 和标准双引号。
- Python 入口同时能在 Windows、macOS 和 Linux 上运行。
- 不写只适用于某一个 shell 的脚本。
- ZIP 内用 `/` 分隔，并保留顶层 Skill 目录。

## 交付说明要列出

- 目标代理
- 项目内写入目录
- Python 版本要求
- 外部依赖
- 已验证的系统
- 未验证的系统
- 降级行为
