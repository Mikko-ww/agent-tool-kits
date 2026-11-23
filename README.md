# agent-tool-kits

`atkits` 是一个面向个人私有 GitHub 仓库的 **Agent Skill / Plugin 版本管理器**。
它通过 GitHub Releases 分发版本化资产，在本地维护安装状态，并把技能安装到用户显式选择的平台目录。

```text
GitHub Releases
  ├── CLI wheel
  ├── Skill/Plugin 独立版本包
  └── catalog.json
        ↓ HTTPS + 只读 token
~/.atkits
  ├── config.toml
  ├── state.json
  ├── registry/catalog.json
  └── packages/...
        ↓ symlink / copy
Codex / Cursor / OpenCode / Claude / ...
```

## 安装

### 1. 创建 GitHub 只读 token

1. GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens。
2. Repository access 选择 `agent-tool-kits`。
3. Permissions → Contents 设为 Read-only。
4. 生成并复制 token。

### 2. 安装 CLI

```bash
export ATKITS_GITHUB_TOKEN="github_pat_xxx"
curl -fsSL https://example.com/install-atkits.sh | bash
```

也可以在仓库内执行：

```bash
scripts/install-atkits.sh
```

安装脚本会：

- 检查 `uv`。
- 要求 GitHub token。
- 查询最新 CLI Release。
- 下载 wheel 并校验 SHA-256。
- 执行 `uv tool install --force <wheel>`。

### 3. 初始化

```bash
atkits init --registry Mikko-ww/agent-tool-kits
```

## 日常命令

```bash
atkits list --remote          # 分组查看远端自有技能、插件、CLI、外部技能收藏和安装预设
atkits list                   # 按资产汇总本机安装
atkits list --details         # 查看每个安装路径的明细
atkits check                  # 强制刷新 catalog
atkits status                 # 检查本机安装健康状态

atkits install <name>         # 在终端中打开平台多选菜单
atkits install <name>@1.0.0   # 安装指定版本
atkits install <name> --platform codex,cursor
atkits install <name> --scope global --method symlink
atkits install <name> --preset daily-coding
atkits install <path> --editable

atkits update <name>          # 更新到最新稳定版
atkits uninstall <name> --platform codex
atkits doctor                 # 检查本地状态
atkits doctor --fix           # 修复受管损坏目标
atkits cache prune            # 清理未引用版本包

atkits self-update            # 更新 CLI wheel
atkits platforms              # 查看平台路径定义
atkits --version
```

`atkits list` 会把同一资产、同版本且健康状态相同的平台合并显示；版本或状态不同时，分行标明对应平台。用 `--details` 查看各安装路径。

平台菜单显示平台名称和 ID，默认不勾选。可键入名称或 ID 搜索，再用 ↑/↓ 移动、空格勾选、回车确认；按 Ctrl+C 取消。安装范围默认是 `global`。

Windows 交互安装发布版时，如果没有通过 `--method` 或预设选定安装方式，会显示 `copy` / `symlink` 菜单，推荐并默认选中 `copy`；确认后才执行安装。Windows 下显式提供的 `--method` 可覆盖预设的安装方式。macOS、Linux 和非交互安装的默认方式仍为 `symlink`；`--editable` 仍只使用符号链接，外部技能仍由 `npx skills` 安装。

非交互场景（如管道、CI 或显式指定 `--no-input`）不会打开菜单，必须提供 `--platform`、`--preset` 或 `--all`。例如：

```bash
atkits install character-design --platform codex,claude --no-input
atkits install character-design --scope project --project-root "$PWD"
```

## 平台选择

Claude Code 的平台 ID 是 `claude`；旧命令或预设中的 `claude-code` 仍可使用。此变化不改动安装目录，已有安装无需重装。

`atkits` 不默认安装到所有平台。安装前会解析逻辑平台到真实物理路径，并显示 primary/shared/compatibility 目标。

例如 Cursor 同时支持：

```text
项目级：
.agents/skills   → shared
.cursor/skills   → primary

全局：
~/.agents/skills → shared
~/.cursor/skills → primary
```

OpenCode 支持：

```text
全局 primary:      ~/.config/opencode/skills
全局 compatibility: ~/.agents/skills
```

Codex 的全局用户目录是：

```text
~/.agents/skills
```

当多个平台共享同一路径时，`atkits` 只安装一份，并在 `state.json` 中记录 consumers。
同一个物理路径同一时间只能激活一个版本；不同物理路径可以不同版本。

## 版本

- Skill / Plugin 使用 SemVer 2.0.0。
- 默认安装最高稳定版本。
- 预发布版本只有显式指定才安装。
- 可安装历史版本实现回退。
- CLI 使用 PEP 440 静态版本，Release tag 必须与 `pyproject.toml` 一致。

## 外部技能收藏

外部技能保存在 `favorites.yaml`，例如：

```yaml
external_skills:
  pdf:
    source: openai/skills
    description: 读取、生成和检查 PDF 文档
```

新增收藏时，优先从上游对应技能的 `SKILL.md` 的 `description` 提炼一句简体中文简介；必要时核对正文，没有 `SKILL.md` 时查阅该技能的 README 或官方说明，不用整个仓库的介绍代替。简介只写已核实的核心用途。

审查时列出拟登记的简介和出处（原文链接及对应字段或章节）；无法核实时，先询问用户，不凭名称猜测。确认后将简介写入 `external_skills.<name>.description`。旧 catalog 缺少简介时，`atkits list --remote` 显示「—」，不会在列出时临时抓取上游。

安装时 `atkits` 委托 `npx skills add`，但安装后必须验证目标目录存在 `SKILL.md`。
外部技能不进入本仓库，不参与版本管理。

`favorites.yaml` 的改动推送或合并到 `main` 后，GitHub Actions 的 **Refresh Catalog** 工作流会自动重建远端 `catalog.json`。等工作流通过后，用 `atkits list --remote` 查看新收藏；不需要打标签或升级 CLI。版本发布成功后也调用同一个刷新任务。

## Editable 开发安装

```bash
atkits install ./skills/foo --editable --platform codex
```

Editable 安装会把平台目录链接到当前工作目录，适合本地开发。
它不参与远端版本更新，也不会被 `cache prune` 清理。

## 本地目录

```text
~/.atkits/
├── config.toml
├── state.json
├── registry/catalog.json
├── packages/
├── downloads/
├── backup/
├── locks/
├── logs/
└── tmp/
```

`ATKITS_HOME` 可覆盖根目录。

## 安全规则

- 私有 Release 下载需要只读 token。
- 跨主机 302 重定向会剥离 Authorization。
- 所有包校验 SHA-256。
- tar 解包拒绝路径穿越、symlink、hardlink 和设备文件。
- 真实用户目录替换前进入 `~/.atkits/backup/`。
- `cache prune` 不清理 backup 和 editable source。
- Windows 创建符号链接如果遇到 `WinError 1314`，会提示使用 `--method copy` 重试，不会自动切换方式。

## 开发

```bash
uv sync --group dev
uv run pytest
uvx ruff format src tests scripts
uvx ruff check src tests scripts
uv build
```

详细架构见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)，
设计决策与历史见 [docs/DESIGN.md](docs/DESIGN.md)。
