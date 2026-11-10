# atkits Release Registry 重构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 atkits 从“依赖本地工作仓库的目录同步器”重构为“通过私有 GitHub Releases 分发版本化 Skill/Plugin 的个人包管理器”，并由用户显式选择逻辑平台，归并到真实物理安装路径。

**Architecture:** Git 只用于开发与发布；CI 将 CLI、每个 Skill、每个 Plugin 的每个版本分别构建为不可变制品，并维护统一 `catalog.json`。运行时仅使用 HTTPS，下载制品到统一的 `~/.atkits`。安装前先由用户选择逻辑平台，再解析成可共享的物理目标；每个物理目标记录 consumers、版本、symlink/copy 策略和 provenance，从而完成安装、卸载、更新、回退与健康检查。

**Tech Stack:** Python 3.11+、uv、Typer、ruamel.yaml、semver、packaging、filelock、GitHub Releases REST API、GitHub Actions、pytest。

**Spec:** 本文件第 1–10 节是目标架构契约；[docs/DESIGN.md](../../DESIGN.md) 仅用于理解旧实现和现有平台路径。

## Global Constraints

- 私有 GitHub 仓库继续作为源码与 Release 的托管位置；运行时不得调用 `git`，也不要求用户维护 clone。
- `skills/`、`plugins/` 的内容目录结构保持不变；只有发布元数据、平台选择和打包流程可以调整。
- CLI 仍是 uv 包，命令名仍为 `atkits`；CLI 使用 wheel 发布。
- Skill/Plugin 使用独立 SemVer 2.0.0；CLI 使用 PEP 440 静态版本。默认安装最高稳定资产版本，支持 `name@version` 安装和回退。
- 所有 atkits 自有数据默认放在 `~/.atkits`；可用 `ATKITS_HOME` 覆盖。平台目标目录和 uv 自身工具环境不强制迁移。
- 不默认安装到所有平台。交互模式必须让用户多选平台；非交互模式必须显式 `--platform` 或 `--all`。记住的选择只作为预选中。
- 逻辑平台必须先归并为物理路径。Codex/Cursor/OpenCode 等共享 `.agents/skills` 时只安装一份；`universal` 不是可选平台。
- 同一物理路径同一时间只能激活一个版本；不同物理路径可以不同版本。
- `profiles/global.yaml` 改为远端 collection 与显式 preset，不再用 `targets`/`to` 决定本机安装位置。
- 新架构允许并要求本机 `state.json` 记录安装 provenance；旧 AGENTS.md 的“完全不引入状态文件”约束在新核心中废止。
- 本次是干净重构：不提供旧 `apply/import` 兼容入口，不提供 `migrate-legacy`，不迁移旧安装状态。
- 平台路径必须按 OS 和环境变量运行时解析；registry 只保存模板，不保存展开后的绝对路径。
- 私有资源只通过只读 GitHub token 访问；token 不写入仓库、日志或明文 `config.toml`。跨主机重定向必须剥离 Authorization。
- 不直接删除用户真实目录；冲突处理和备份规则必须延续。平台 symlink 只在 provenance 匹配时 unlink。
- 外部技能只作为收藏夹，第一阶段只支持远端展示和委托 `npx skills add`，不 vendor、不实现完整更新/卸载。
- 文档和 CLI 文案使用简体中文；代码、标识符和提交内容保持英文；提交信息使用中文且一次提交一个主题。
- 所有测试使用 `tmp_path` 和假 HOME，禁止访问真实平台目录或真实 GitHub token。

## 1. 目标架构

```text
开发侧
  Git commit/tag
    → GitHub Actions 校验、测试、打包
    → GitHub Releases：CLI wheel、Skill/Plugin 独立压缩包
    → 固定 registry Release：catalog.json

运行侧（无 Git 依赖）
  atkits
    → HTTPS 读取 catalog.json
    → 用户选择逻辑平台 / scope / method
    → 解析成物理目标并展示路径
    → 下载并校验 name@version 制品
    → 解压到 ~/.atkits/packages/<kind>/<name>/<version>/
    → symlink / copy 到物理目标
    → 写入本机 state.json（含 consumers 和 provenance）
```

### 1.1 关键边界

- 远端 catalog 回答“有什么、有哪些版本、最新稳定版是什么”。
- 本机 state 回答“这台电脑装了什么、哪个版本、装到哪个物理路径、服务哪些逻辑平台、是否被用户修改”。
- 远端 Git commit 只用于追溯，不参与运行时解析。
- 同一资产可缓存多个版本；不同物理目标可激活不同版本；同一物理目标只能激活一个版本。
- 远端资产 `latest` 按 SemVer precedence 计算，不按最后上传时间计算。

## 2. 发布物与版本契约

### 2.1 资产版本

Skill 在 `SKILL.md` 中声明：

```yaml
---
name: ai-image-prompt-engineer
description: ...
metadata:
  version: 1.1.0
---
```

Plugin 在 `plugin.yaml` 中声明：

```yaml
name: matt-agent-skills
version: 1.3.0
```

资产版本规则：

- Skill/Plugin 使用 SemVer 2.0.0，例如 `1.2.0`、`1.3.0-beta.1`、`1.3.0+build.1`。
- 使用 `semver.Version.parse()` 校验；catalog key 保存规范化后的 SemVer 字符串。
- SemVer precedence 忽略 build metadata。若两个版本仅 build metadata 不同，catalog 构建失败，要求发布不同版本号。
- 本地开发不必每次修改都升版；发布时 CI 强制检查版本与标签一致。
- 同一 `kind/name/version` 不允许重新发布不同内容。
- 预发布版本不进入默认 `latest`，只有显式 `name@1.3.0-beta.1` 才能安装。

CLI 版本规则：

- CLI 使用 PEP 440，`pyproject.toml` 中的静态 `version` 是唯一来源。
- `cli-v0.2.0` 标签必须与 `pyproject.toml` 完全一致，否则 CI 发布失败。
- 不在 CI 中动态改写版本，避免 wheel 名、catalog 和 `__version__` 来源不一致。

### 2.2 Release 与标签

```text
cli-v0.2.0
skill-ai-image-prompt-engineer-v1.1.0
plugin-matt-agent-skills-v1.3.0
registry                              # 固定 Release，存放最新 catalog.json
```

每个 Skill/Plugin Release 只包含该资产该版本的压缩包与校验文件：

```text
ai-image-prompt-engineer-1.1.0.tar.gz
ai-image-prompt-engineer-1.1.0.tar.gz.sha256
```

压缩包保留原资产目录：

```text
ai-image-prompt-engineer/
├── SKILL.md
├── references/
└── canvas-fonts/
```

CLI Release 包含：

```text
atkits-0.2.0-py3-none-any.whl
```

### 2.3 Catalog schema v1

```json
{
  "schema_version": 1,
  "generated_at": "2026-11-10T00:00:00Z",
  "cli": {
    "latest": "0.2.0",
    "versions": {
      "0.2.0": {
        "asset_id": 9001,
        "archive": "atkits-0.2.0-py3-none-any.whl",
        "sha256": "<64-hex>",
        "source_revision": "<commit-sha>"
      }
    }
  },
  "skills": {
    "ai-image-prompt-engineer": {
      "latest": "1.1.0",
      "versions": {
        "1.1.0": {
          "asset_id": 10002,
          "archive": "ai-image-prompt-engineer-1.1.0.tar.gz",
          "sha256": "<64-hex>",
          "source_revision": "<commit-sha>",
          "description": "Create and optimize AI image prompts"
        }
      }
    }
  },
  "plugins": {},
  "external_skills": {
    "pdf": {
      "source": "openai/skills",
      "description": "PDF workflow"
    }
  },
  "collection": {
    "presets": {
      "daily-coding": {
        "scope": "global",
        "platforms": ["codex", "cursor"],
        "method": "symlink"
      }
    }
  }
}
```

`profiles/global.yaml` 是 CI 生成 catalog 的输入之一：资产和外部收藏进入对应段落，`presets` 进入 `collection.presets`。运行时只读取 catalog，不再解析仓库内 profile。

## 3. 本地目录与状态

```text
~/.atkits/
├── config.toml
├── state.json
├── registry/catalog.json
├── packages/
│   ├── skills/<name>/<version>/
│   └── plugins/<name>/<version>/
├── downloads/
├── backup/<timestamp>/
├── locks/
├── logs/
└── tmp/
```

`config.toml` 只保存非秘密配置：

```toml
registry_repo = "Mikko-ww/agent-tool-kits"
catalog_release = "registry"
catalog_ttl_seconds = 300
preferred_platforms = ["codex", "cursor"]
preferred_method = "symlink"
```

`preferred_platforms` 只是交互多选的预选中，不得导致非交互默认全平台安装。

Token 读取顺序：

```text
ATKITS_GITHUB_TOKEN → GITHUB_TOKEN → GH_TOKEN
```

`state.json` 按物理目标记录：

```json
{
  "schema_version": 1,
  "installs": {
    "skill:ai-image-prompt-engineer:global:agents": {
      "kind": "skill",
      "name": "ai-image-prompt-engineer",
      "scope": "global",
      "project_id": null,
      "version": "1.1.0",
      "target_id": "agents",
      "path": "/home/user/.agents/skills/ai-image-prompt-engineer",
      "strategy": "symlink",
      "consumers": ["codex", "cursor", "opencode"],
      "package_path": "packages/skills/ai-image-prompt-engineer/1.1.0",
      "artifact_sha256": "<64-hex>",
      "content_sha256": "<64-hex>"
    },
    "skill:searching-github-projects:project:<project-id>:agents": {
      "kind": "skill",
      "name": "searching-github-projects",
      "scope": "project",
      "project_id": "<sha256-of-normcase-resolved-project-root>",
      "version": "1.0.0",
      "target_id": "agents",
      "path": "/home/user/work/project/.agents/skills/searching-github-projects",
      "strategy": "symlink",
      "consumers": ["codex", "cursor", "opencode"],
      "package_path": "packages/skills/searching-github-projects/1.0.0",
      "artifact_sha256": "<64-hex>",
      "content_sha256": "<64-hex>"
    },
    "skill:ai-image-prompt-engineer:global:editable": {
      "kind": "skill",
      "name": "ai-image-prompt-engineer",
      "scope": "editable",
      "project_id": null,
      "target_id": "editable",
      "path": "/home/user/.agents/skills/ai-image-prompt-engineer",
      "strategy": "editable",
      "consumers": ["codex"],
      "source_path": "/home/user/work/agent-tool-kits/skills/ai-image-prompt-engineer",
      "artifact_sha256": null,
      "content_sha256": null
    }
  }
}
```

字段规则：

- `project_id` 对 global/editable 为 `null`；对 project scope 是 `SHA256(os.path.normcase(str(Path(project_root).resolve())))` 的十六进制摘要。
- state key 统一为 `kind:name:scope:<project-id|global|editable>:<target-id>`，避免多个项目互相覆盖。
- `target_id` 是 registry 中物理路径定义的稳定 ID，而不是路径字符串。
- `consumers` 是用户选择的逻辑平台；共享路径的其他 agent 可能也能读取，但未选中不写入记录。
- `version` 属于物理目标，因此不同物理路径可以激活不同版本。
- symlink 资产的 `content_sha256` 记录包目录 hash，用于检测包缓存是否被修改。
- copy 资产的 `content_sha256` 记录安装时目标目录 hash，用于检测用户是否修改目标。
- editable 必须记录独立的 `source_path`；`package_path` 保持 `null` 或缺省，且 `cache prune` 永远不清理 `source_path`。

## 4. CLI 契约

| 命令 | 行为 |
|---|---|
| `atkits init --registry owner/repo` | 写入配置、创建目录、刷新 catalog |
| `atkits list` | 列出本机安装记录、物理路径、consumers 和激活版本 |
| `atkits list --remote` | 只读取 catalog，列出远端资产，不下载资产包 |
| `atkits check` | 强制刷新 catalog，显示可更新项 |
| `atkits status` | 检查本地健康；默认显示缓存更新信息，`--online` 强制刷新 |
| `atkits install <name>[@version]` | 安装或切换版本；交互选择 scope、平台、方法并确认路径 |
| `atkits install <name> --platform codex,cursor` | 非交互指定逻辑平台 |
| `atkits install <name> --scope global --method symlink` | 指定范围和安装方式 |
| `atkits install <name> --all` | 显式安装到所有支持的平台 |
| `atkits install <name> --preset daily-coding` | 使用 catalog 中的显式 preset |
| `atkits install <name> --no-input` | 禁用交互；必须同时提供 `--platform`/`--preset`/`--all` |
| `atkits install ./skills/foo --editable` | 链接到工作目录，仅用于开发，不参与远端更新 |
| `atkits uninstall <name>` | 交互选择平台并展示将删除/保留的物理路径 |
| `atkits uninstall <name> --platform codex` | 只处理指定逻辑平台 |
| `atkits update [name]` | 更新一个或全部 managed 资产到最新稳定版 |
| `atkits doctor` | 检查配置、token、catalog、包完整性、共享路径和平台目标 |
| `atkits doctor --fix` | 重新下载损坏的版本包并恢复 provenance 匹配的 symlink |
| `atkits cache prune` | 清理无安装记录引用的版本包和下载缓存；不清理 backup |
| `atkits self-update` | 下载最新 CLI wheel 并调用 uv 重新安装 |

交互安装流程：

```text
选择范围：Global / Project
多选平台：展示每个逻辑平台解析后的路径
选择方法：Symlink / Copy
确认摘要：物理路径、策略、包来源、影响 consumers
执行并后置验证
```

非交互规则：

- 未提供 `--platform`、`--preset`、`--all` 且无法交互时，安装失败并提示平台参数。
- `preferred_platforms` 只能作为交互预选，不能代替非交互参数。

### 4.1 退出码

- `0`：操作成功，或 `status` 未发现异常/更新；有可用更新但未更新不是错误。
- `1`：冲突、包损坏、安装后验证失败、卸载 provenance 不匹配。
- `2`：命令参数、配置或清单格式错误。
- `3`：网络、认证、权限或 GitHub API 限流错误。

## 5. 下载与安装算法

### 5.1 安装 `foo@1.1.0 --platform codex,cursor`

1. 读取 catalog，精确解析 `skills.foo.versions["1.1.0"]`。
2. 解析平台选择：
   - Codex/Cursor 项目级都归并到 `<cwd>/.agents/skills`。
   - 若全局均读取 canonical，则归并到 `~/.agents/skills`。
   - 非共享平台解析到各自目录。
3. 展示每个物理路径、策略和 consumers，等待确认。
4. 请求 `/repos/{owner}/{repo}/releases/assets/{asset_id}`，Header 包含 token 和 `Accept: application/octet-stream`。
5. 跟随 200/302 响应，但跨主机重定向时剥离 `Authorization`。
6. 校验 SHA-256、压缩包路径、文件类型、资产名和包内版本。
7. 解压到唯一临时目录，验证后仅在最终目录不存在时原子移动。
8. 检查平台目标：
   - 不存在：直接安装。
   - 是本记录对应的 symlink/copy：允许切换。
   - 真实目录与包内容一致：备份后改为受管安装。
   - 其他内容：报告冲突，不覆盖。
9. 创建/替换平台链接或拷贝，并写入 `state.json`。
10. 重新读取目标和状态，验证安装结果。

### 5.2 更新与回退

- `update` 解析最新稳定版，复用安装流程；旧版本目录默认保留。
- 安装已缓存版本时不访问资产下载 API，只切换激活目标。
- 更新共享物理目标时，必须展示所有会同时升级的 consumers。
- 不同物理路径可激活不同版本；同一物理路径必须保持一个版本。

### 5.3 卸载

- 交互先选择要移除的逻辑平台，再展示将删除和保留的物理路径。
- 共享物理目标仍有其他 consumers 时，只从记录中移除该 consumer，不删除路径。
- 共享物理目标没有剩余 consumers 时，才按策略删除。
- symlink：仅当仍指向记录中的包目录时 unlink；否则报告冲突。
- copy：仅当当前 `content_sha256` 与安装记录一致时备份并移除；用户修改过则报告冲突。
- editable：只移除记录中的 symlink，不删除工作目录。
- 未被引用的包版本由 `cache prune` 另行清理；backup 不自动清理。

## 6. 平台选择、OS 路径解析与物理目标归并

### 6.1 数据模型

```python
@dataclass(frozen=True)
class PathSpec:
    id: str
    template: str
    role: str  # primary | shared | compatibility
    os: tuple[str, ...] | None = None  # None = all supported OSes
    precedence: int | None = None

@dataclass(frozen=True)
class Platform:
    id: str
    display_name: str
    project_paths: tuple[PathSpec, ...]
    global_paths: tuple[PathSpec, ...]
    supports_plugins: bool = False
    plugin_strategy: str | None = None
    detect: tuple[dict[str, object], ...] = ()

@dataclass(frozen=True)
class PhysicalTarget:
    target_id: str
    path: Path
    consumers: tuple[str, ...]
    strategy: str
    role: str
    shared: bool
```

`resolve_targets(scope, platform_ids, cwd, os_name, env)` 返回按 resolved path 分组后的 `PhysicalTarget` 列表。

### 6.2 OS 与环境变量解析

平台 registry 不保存展开后的绝对路径，只保存模板。运行时按当前 OS 过滤并展开：

```text
$HOME
$USERPROFILE
$APPDATA
$LOCALAPPDATA
$XDG_CONFIG_HOME
$XDG_DATA_HOME
$CODEX_HOME
$CLAUDE_CONFIG_DIR
```

解析规则：

- `~` 等价于当前用户 home。
- `$VAR` 只从进程环境读取；未定义时使用该变量的显式默认值。
- `darwin/linux/windows` 是 `os_name` 的合法值。
- PathSpec 的 `os` 不匹配当前系统时忽略。
- 展开后必须转为 `Path(...).expanduser().resolve()`。
- 归并和 provenance 比较使用 resolved path；Windows 额外使用 `os.path.normcase`。
- 不允许模板包含 `..`、绝对盘符或解析后逃逸到 home/config 之外的路径。
- 项目级路径必须始终锚定在 `Path(cwd).resolve()` 下。

### 6.3 多路径模型

一个平台可以同时有多个可读取路径，不能简化成单一 `global_skills_dir`。示例：

```json
{
  "id": "cursor",
  "display_name": "Cursor",
  "project_paths": [
    { "id": "agents", "template": ".agents/skills", "role": "shared" },
    { "id": "cursor", "template": ".cursor/skills", "role": "primary" }
  ],
  "global_paths": [
    { "id": "agents", "template": "$HOME/.agents/skills", "role": "shared" },
    { "id": "cursor", "template": "$HOME/.cursor/skills", "role": "primary" }
  ],
  "detect": [
    { "type": "path", "template": "$HOME/.cursor" }
  ]
}
```

OpenCode 示例：

```json
{
  "id": "opencode",
  "project_paths": [
    { "id": "agents", "template": ".agents/skills", "role": "shared" },
    { "id": "opencode", "template": ".opencode/skills", "role": "primary" }
  ],
  "global_paths": [
    { "id": "agents", "template": "$HOME/.agents/skills", "role": "compatibility" },
    { "id": "opencode", "template": "$XDG_CONFIG_HOME/opencode/skills", "role": "primary" }
  ]
}
```

Codex 示例：

```json
{
  "id": "codex",
  "project_paths": [
    { "id": "agents", "template": ".agents/skills", "role": "shared" }
  ],
  "global_paths": [
    { "id": "agents", "template": "$HOME/.agents/skills", "role": "primary" }
  ]
}
```

### 6.4 归并规则

- 选择逻辑平台后，先按 OS 过滤 PathSpec。
- 展开环境变量并 resolve。
- 按 resolved path 分组；同一路径只生成一个 `PhysicalTarget`。
- `consumers` 记录选择了该路径的逻辑平台。
- `role=shared/compatibility` 的路径可以作为跨平台归并目标，例如 `~/.agents/skills`。
- `role=primary` 的路径用于平台自身主目录；安装摘要必须同时显示 primary 和 shared/compatibility 选项。
- 用户选择平台后，atkits 展示可选物理路径，由用户确认；不能暗中替用户选择 primary 或 shared。
- `universal` 不作为逻辑平台出现；共享路径通过 PathSpec 的 role 表达。
- 同一物理目标同一时间只能一个版本；不同物理目标可以不同版本。

### 6.5 Windows symlink 策略

- Windows 上先尝试 symlink。
- 权限不足时不静默 fallback，交互模式询问是否改用 copy。
- 非交互模式必须显式 `--method copy`，否则失败并说明权限原因。
- macOS/Linux 默认 symlink。
- 插件安装仍按平台要求使用 copy。

### 6.6 平台注册表打包

`platform_registry.json` 位于 `src/atkits/`，必须随 wheel 打包，并在测试中从安装后的 wheel 解包验证：

```toml
[tool.hatch.build.targets.wheel.force-include]
"src/atkits/platform_registry.json" = "atkits/platform_registry.json"
```

## 7. 私有访问与安装入口

- Release 资产通过 `/releases/assets/{asset_id}` 和 `Accept: application/octet-stream` 下载，客户端同时处理 200/302。
- 自定义 redirect handler：当重定向目标 host 不是 `api.github.com` 时，移除 `Authorization`，避免把 token 发送到 `release-assets.githubusercontent.com`。
- 公开安装脚本只负责引导，不包含秘密；脚本通过 token 下载最新 wheel 到临时目录，再执行 `uv tool install <local-wheel>`。
- 直接公开 wheel URL 只适用于公开资源；私有仓库不能提供匿名永久下载链接。
- 不把 GitHub Packages 当 PyPI 使用；若未来公开发布 PyPI，可增加 `uv tool install atkits`，但不影响本方案。
- CLI 自更新通过 catalog 查询新 wheel，不能假设 `uv tool upgrade` 能自动发现 GitHub Releases。

## 8. 安全与可靠性

- 所有网络请求设置超时；离线和 API 限流时使用缓存 catalog，并明确显示缓存时间。
- 跨主机 302 必须剥离 `Authorization`；测试记录两跳请求并断言第二跳无 token。
- tar 解压拒绝绝对路径、`..`、symlink、hardlink、设备文件；CI 生成的包只含普通文件和目录。
- 包目录已存在且 hash 一致时复用；不一致时停止，不能覆盖。
- 版本包最终目录必须不存在才能原子移动；已存在非空目录时不得调用 `os.replace` 直接覆盖。
- `state.json` 使用同目录临时文件 + `os.replace` 原子写入；所有变更操作使用 `filelock`。
- 安装、更新、卸载后重新扫描，禁止只依据下载器或 npx 的退出码报告成功。
- 真实目录替换前必须备份；冲突和错误返回非零。
- `doctor --fix` 仅重新下载 provenance 匹配的损坏包；用户修改过的 copy 目标仍需人工确认。
- 日志不得打印 token、完整授权 Header 或带凭据的 URL。
- `cache prune` 不删除 `backup/`；备份保留策略写入文档。

## 9. 干净重构与切换策略

1. 本次重构不提供向上兼容，不读取旧 `profiles/global.yaml` 的 `targets/to`，不迁移旧 symlink、旧插件拷贝或旧外部技能安装状态。
2. 新 CLI 直接替换旧 `status/apply/import` 命令；旧命令不保留兼容入口。
3. `profiles/global.yaml` 直接改写为 v2 collection 输入，供 CI 生成 catalog。
4. 旧 `engine/profile/importer` 相关代码在新 CLI 切换并测试通过后删除，不进入最终包。
5. 用户如需保留旧安装，可手动备份旧平台目录；atkits 不自动处理。
6. 旧 `~/.local/share/atkits/backup/` 与新 `~/.atkits/backup/` 互不影响，不做迁移或删除。

## 10. 验收标准

- 在没有 Git 可执行文件的 PATH 中，使用本地 HTTP fixture 完成远端 list、安装、更新、回退和卸载。
- 私有 API 测试只使用 mock token 和本地 HTTP fixture；任何测试都不访问真实 GitHub。
- `list --remote` 不下载资产包。
- 默认安装最高稳定 SemVer；预发布版本只有显式指定才安装。
- 未显式选择平台时，非交互安装失败；`--all` 才能安装全部支持平台。
- Codex/Cursor/OpenCode 共享 `.agents/skills` 时只创建一个物理目标，并在摘要中显示共享 consumers。
- 共享物理目标只允许一个版本；不同物理目标可以不同版本。
- 卸载共享目标的部分 consumers 时，只更新记录；全部 consumers 移除后才删除路径。
- 插件本地修改会产生冲突，不会被静默覆盖；删除/改名后仍能根据 state 清理。
- broken symlink、普通文件、缺失 `SKILL.md` 都不会被判定为有效安装。
- 跨主机重定向后的请求不携带 Authorization。
- 所有安装和更新操作都有后置验证；失败返回非零。
- CI 能从标签生成独立包并串行更新 catalog；重复发布同版本不同内容会失败。
- 文档包含新机器引导、token 创建、平台选择、primary/shared 路径、日常命令、editable 开发和卸载。
- Windows/macOS/Linux 路径解析均有单元测试；Windows symlink 权限失败不会静默降级。
- preset 来自 catalog `collection.presets`，不依赖本地 profile。
- 最终 wheel 内包含 `platform_registry.json`。
---

## 文件结构

### 新核心

- `src/atkits/models.py`：Catalog、AssetVersion、InstallTarget 等领域模型与严格校验。
- `src/atkits/home.py`：`ATKITS_HOME`、配置、目录布局和原子 JSON 读写。
- `src/atkits/state.py`：安装记录查询、写入、删除和文件锁。
- `src/atkits/github.py`：GitHub Releases API、token、跨主机重定向剥离和错误映射。
- `src/atkits/registry.py`：catalog 获取、缓存、版本解析和 latest 计算。
- `src/atkits/packages.py`：hash、制品缓存、安全解压和包目录管理。
- `src/atkits/platforms.py`：加载 `platform_registry.json`，解析逻辑平台到物理目标。
- `src/atkits/platform_registry.json`：随 CLI 打包的平台路径与检测元数据。
- `src/atkits/installers.py`：symlink/copy/editable 策略、共享 consumers、备份和卸载。
- `src/atkits/lifecycle.py`：install/update/uninstall/status/doctor/cache prune 用例编排。
- `src/atkits/cli.py`：新命令入口，仅负责参数、交互和输出。
- `src/atkits/external.py`：外部技能 npx 委托和健康检查。
- `src/atkits/self_update.py`：CLI wheel 自更新。

### 发布与引导

- `profiles/global.yaml`：v2 collection 输入，CI 将资产、外部收藏和 preset 投影到 catalog。
- `scripts/package_asset.py`：从工作仓库构建单个资产版本包。
- `scripts/release.py`：解析标签并调用打包/发布流程。
- `scripts/update_catalog.py`：从 Release 元数据生成并上传 catalog。
- `scripts/install-atkits.sh`：新机器引导入口。
- `.github/workflows/release.yml`：标签驱动的测试、打包、发布和串行 catalog 更新。

### 测试

- `tests/test_models.py`
- `tests/test_home_state.py`
- `tests/test_registry_github.py`
- `tests/test_packages.py`
- `tests/test_platforms.py`
- `tests/test_installers.py`
- `tests/test_lifecycle.py`
- `tests/test_cli.py`
- `tests/test_package_asset.py`
- `tests/test_self_update.py`
- `tests/test_external.py`
- `tests/test_no_git.py`
- `tests/conftest.py`

`tests/conftest.py` 必须提供统一假件契约：

- `http_server`：暴露 `url`、按序记录的 `requests`、可编程路由和 `set_offline(True)`。
- `fake_registry`：暴露 `refresh/resolve/latest/set_offline/remove`，不访问网络。
- `fake_registry_server`：`http_server` 的 catalog 专用别名，预置 catalog 和资产下载路由。
- `asset_package`：生成合法 tar 包、恶意 tar 包和 hash 不匹配包。
- `platform_env`：假 HOME、假 cwd、假 `env`、假 `xdg_config`、假平台目录、`ATKITS_HOME`，并包含仅测试用的 `example-windows-only` 平台定义。
- `fake_lifecycle`：记录安装请求、包下载数量、`fail_network`、`damage_managed_package` 和 `repaired_target`。
- `catalog/asset/home/install_target/project_install_target/other_project_install_target`：领域模型和状态基础假件。
- `package_store/package_v2/malicious_archive`：版本包与安全解包假件。
- `installer/plugin_record/shared_skill_record/skill_record/editable_record/source_repo`：安装策略、共享目标、editable 和普通源码目录假件。
- `project_root/other_project_root`：两个隔离的临时项目根，用于 project scope 测试。
- `repo_with_two_skills/releases/favorites`：打包和 catalog 构造假件。
- `fake_runtime`：自更新测试假件。
- `lifecycle/cli/external_installer`：端到端 CLI、生命周期和外部技能测试假件。

---

### Task 1: 建立测试骨架与领域模型

**Files:**
- Modify: `pyproject.toml`
- Modify: `AGENTS.md`
- Create: `src/atkits/models.py`
- Create: `tests/conftest.py`
- Create: `tests/test_models.py`

**Interfaces:**
- Produces: `AssetVersion(kind, name, version, asset_id, archive, sha256, source_revision=None, description=None)`、`Catalog.latest(kind, name)`、`Catalog.require_version(kind, name, version)`、`InstallTarget.key()`。
- Consumes: 后续 registry、packages、state 和 lifecycle 只使用这些模型。

- [x] **Step 1: 写失败测试**

```python
def test_latest_ignores_prerelease_and_upload_order(catalog):
    assert catalog.latest("skill", "foo").version == "1.1.0"
    assert catalog.latest("skill", "foo").asset_id == 10002


def test_semver_build_metadata_does_not_change_precedence():
    with pytest.raises(RegistryError, match="same precedence"):
        Catalog({"schema_version": 1, "skills": {
            "foo": {
                "latest": "1.1.0",
                "versions": {
                    "1.1.0": {"asset_id": 1, "archive": "a", "sha256": "0" * 64},
                    "1.1.0+build.1": {"asset_id": 2, "archive": "b", "sha256": "1" * 64},
                }
            }
        }})


def test_install_target_key_is_stable(install_target):
    assert install_target.key() == "skill:foo:global:agents"
```

- [x] **Step 2: 验证测试因模型不存在而失败**

Run: `uv run python -c "import atkits" && uv run pytest tests/test_models.py -v`
Expected: import 成功；pytest FAIL，`ModuleNotFoundError: atkits.models`。

- [x] **Step 3: 实现模型和测试依赖**

在 `pyproject.toml` 增加：

```toml
[project]
dependencies = [
  "typer>=0.12",
  "ruamel.yaml>=0.18",
  "semver>=3",
  "packaging>=24",
  "filelock>=3.16",
]

[dependency-groups]
dev = ["pytest>=8", "pytest-cov>=5"]
```

资产版本用 `semver.Version.parse()` 校验；CLI 版本用 `packaging.version.Version` 校验。catalog 解析拒绝未知 schema、非法 hash、空名称、重复版本和相同 precedence 的不同版本。

- [x] **Step 4: 运行模型测试和静态检查**

Run: `uv run pytest tests/test_models.py -v && uvx ruff format src/atkits/models.py tests/test_models.py && uvx ruff check src/atkits/models.py tests/test_models.py`
Expected: 全部 PASS。

- [x] **Step 5: 提交**

```bash
git add AGENTS.md pyproject.toml uv.lock src/atkits/models.py tests/conftest.py tests/test_models.py
git commit -m "建立重构领域模型与测试骨架"
```

### Task 2: 实现统一目录和原子状态存储

**Files:**
- Create: `src/atkits/home.py`
- Create: `src/atkits/state.py`
- Create: `tests/test_home_state.py`

**Interfaces:**
- Produces: `AtkitsHome.discover(env, cwd)`、`ensure_layout()`、`load_config()`、`save_config()`；`StateStore.all()/get_target(kind, name, scope, project_id, target_id)/put()/remove()/remove_consumer()`。

- [x] **Step 1: 写失败测试**

```python
def test_state_round_trip_and_atomic_replace(home, install_target):
    store = StateStore(home)
    store.put(install_target)
    assert store.get_target(
        "skill", "foo", "global", install_target.project_id, install_target.target_id
    ) == install_target
    assert not list(home.path.glob("state.json.tmp*"))


def test_remove_consumer_keeps_shared_target(home, install_target):
    store = StateStore(home)
    store.put(dataclasses.replace(install_target, consumers=("codex", "cursor")))
    store.remove_consumer(
        "skill", "foo", "global", install_target.project_id, install_target.target_id, "codex"
    )
    record = store.get_target(
        "skill", "foo", "global", install_target.project_id, install_target.target_id
    )
    assert record.consumers == ("cursor",)


def test_project_state_keys_do_not_collide(home, project_install_target, other_project_install_target):
    store = StateStore(home)
    store.put(project_install_target)
    store.put(other_project_install_target)
    assert store.get_target(
        "skill", "foo", "project", project_install_target.project_id, "agents"
    ) is project_install_target
    assert store.get_target(
        "skill", "foo", "project", other_project_install_target.project_id, "agents"
    ) is other_project_install_target


def test_home_never_writes_outside_override(tmp_path, monkeypatch):
    monkeypatch.setenv("ATKITS_HOME", str(tmp_path / "custom"))
    home = AtkitsHome.discover()
    home.ensure_layout()
    assert (tmp_path / "custom/packages").is_dir()
```

- [x] **Step 2: 验证失败**

Run: `uv run pytest tests/test_home_state.py -v`
Expected: FAIL，缺少 `AtkitsHome` 和 `StateStore`。

- [x] **Step 3: 实现配置、目录和锁定写入**

`discover()` 优先读取 `ATKITS_HOME`，否则使用 `Path.home()/".atkits"`。state key 使用 `kind:name:scope:<project-id|global|editable>:<target-id>`。`put/remove/remove_consumer` 使用 `FileLock(locks/state.lock)`，写入临时文件后 `os.replace`。配置不得包含 token。

- [x] **Step 4: 验证通过**

Run: `uv run pytest tests/test_home_state.py -v`
Expected: PASS，且测试 HOME 外无文件变化。

- [x] **Step 5: 提交**

```bash
git add src/atkits/home.py src/atkits/state.py tests/test_home_state.py
git commit -m "实现统一目录与共享目标安装状态"
```

### Task 3: 实现 GitHub 客户端和 catalog 缓存

**Files:**
- Create: `src/atkits/github.py`
- Create: `src/atkits/registry.py`
- Create: `tests/test_registry_github.py`

**Interfaces:**
- Produces: `GitHubReleaseClient.get_release_by_tag(tag)`、`download_asset(asset_id, destination)`；`RegistryClient.refresh()/cached()/resolve(kind, name, version=None)`。

- [x] **Step 1: 写本地 HTTP 失败测试**

```python
def test_private_asset_download_strips_token_on_cross_host_redirect(http_server, home):
    client = GitHubReleaseClient("owner/repo", token="secret", base_url=http_server.url)
    client.download_asset(42, home.downloads / "asset.tar.gz")

    assert http_server.requests[0].path == "/repos/owner/repo/releases/assets/42"
    assert http_server.requests[0].headers["Authorization"] == "Bearer secret"
    assert http_server.requests[0].headers["Accept"] == "application/octet-stream"
    assert "Authorization" not in http_server.requests[1].headers


def test_offline_registry_uses_cached_catalog(fake_registry):
    fake_registry.set_offline(True)
    catalog = fake_registry.cached()
    assert catalog.latest("skill", "foo").version == "1.1.0"
```

- [x] **Step 2: 验证失败**

Run: `uv run pytest tests/test_registry_github.py -v`
Expected: FAIL，客户端尚未实现。

- [x] **Step 3: 实现安全 HTTPS 客户端**

使用 `urllib.request`，设置 20 秒超时和 GitHub API version Header；自定义 `HTTPRedirectHandler`，当重定向目标 host 不是 `api.github.com` 时删除 `Authorization`。401/403/404/429 分别映射为认证、权限、资源不存在和限流错误，错误文本不包含 token。`refresh()` 定位固定 `registry` Release 中的 `catalog.json` 并原子替换本地缓存。

- [x] **Step 4: 验证通过**

Run: `uv run pytest tests/test_registry_github.py -v`
Expected: PASS，无真实外网请求。

- [x] **Step 5: 提交**

```bash
git add src/atkits/github.py src/atkits/registry.py tests/test_registry_github.py
git commit -m "实现私有发布目录与安全下载客户端"
```

### Task 4: 实现制品校验和安全包缓存

**Files:**
- Create: `src/atkits/packages.py`
- Create: `tests/test_packages.py`

**Interfaces:**
- Produces: `sha256_file(path)`、`sha256_tree(path)`、`PackageStore.ensure(asset)`、`PackageStore.path_for(kind, name, version)`。

- [x] **Step 1: 写失败测试**

```python
def test_package_rejects_path_traversal(package_store, malicious_archive):
    with pytest.raises(PackageError, match="unsafe path"):
        package_store.extract(malicious_archive, "skill", "foo", "1.0.0")


def test_package_hash_mismatch_does_not_create_package(package_store, asset):
    with pytest.raises(PackageError, match="sha256"):
        package_store.ensure(asset, downloader=write_corrupted_archive)
    assert not package_store.path_for("skill", "foo", "1.1.0").exists()


def test_existing_non_empty_package_dir_is_not_replaced(package_store, asset):
    package_store.ensure(asset, downloader=write_valid_archive)
    target = package_store.path_for("skill", "foo", "1.1.0")
    target.rename(target.with_suffix(".keep"))
    (package_store.path_for("skill", "foo", "1.1.0")).mkdir()
    (package_store.path_for("skill", "foo", "1.1.0") / "unexpected.txt").write_text("x")
    with pytest.raises(PackageError, match="already exists"):
        package_store.ensure(asset, downloader=write_valid_archive)
```

- [x] **Step 2: 验证失败**

Run: `uv run pytest tests/test_packages.py -v`
Expected: FAIL。

- [x] **Step 3: 实现最小包管理**

下载到临时文件并校验 SHA-256；tar 条目只允许普通文件和目录，拒绝绝对路径、`..` 和所有链接。解压后校验 `SKILL.md`/`plugin.yaml` 的名称和版本。最终目录不存在时才从唯一临时目录 rename；已存在非空目录时报错。

- [x] **Step 4: 验证通过**

Run: `uv run pytest tests/test_packages.py -v`
Expected: PASS。

- [x] **Step 5: 提交**

```bash
git add src/atkits/packages.py tests/test_packages.py
git commit -m "实现版本包校验与安全缓存"
```

### Task 5: 实现 OS 感知平台注册表与物理目标归并

**Files:**
- Modify: `src/atkits/platforms.py`
- Create: `src/atkits/platform_registry.json`
- Modify: `pyproject.toml`
- Create: `tests/test_platforms.py`

**Interfaces:**
- Produces: `load_registry()`、`detect_platforms(os_name, env, home)`、`resolve_targets(scope, platform_ids, cwd, os_name, env)`、`project_id(project_root)`、`same_physical_path(left, right)`。

- [x] **Step 1: 写失败测试**

```python
def test_project_codex_cursor_opencode_share_agents_dir(platform_env):
    targets = resolve_targets(
        "project", ["codex", "cursor", "opencode"], platform_env.cwd,
        os_name="darwin", env=platform_env.env,
    )
    agents = [t for t in targets if t.target_id == "agents"]
    assert len(agents) == 1
    assert agents[0].path == platform_env.cwd / ".agents/skills"
    assert set(agents[0].consumers) == {"codex", "cursor", "opencode"}
    assert agents[0].shared is True


def test_cursor_global_has_primary_and_shared_paths(platform_env):
    targets = resolve_targets(
        "global", ["cursor"], platform_env.cwd,
        os_name="darwin", env=platform_env.env,
    )
    paths = {t.target_id: t.path for t in targets}
    assert paths["cursor"] == platform_env.home / ".cursor/skills"
    assert paths["agents"] == platform_env.home / ".agents/skills"


def test_opencode_uses_xdg_primary_and_agents_compatibility(platform_env):
    targets = resolve_targets(
        "global", ["opencode"], platform_env.cwd,
        os_name="linux", env=platform_env.env,
    )
    paths = {t.target_id: t.path for t in targets}
    assert paths["opencode"] == platform_env.xdg_config / "opencode/skills"
    assert paths["agents"] == platform_env.home / ".agents/skills"
    roles = {t.target_id: t.role for t in targets}
    assert roles["opencode"] == "primary"
    assert roles["agents"] == "compatibility"


def test_windows_path_spec_is_filtered_by_os(platform_env):
    targets = resolve_targets(
        "global", ["example-windows-only"], platform_env.cwd,
        os_name="darwin", env=platform_env.env,
    )
    assert targets == ()


def test_windows_path_comparison_uses_normcase(platform_env):
    assert same_physical_path(
        Path("C:/Users/Foo/Skills"), Path("c:\users\foo\skills")
    )


def test_project_id_is_stable_for_equivalent_paths(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    assert project_id(root) == project_id(root / "." )
    assert project_id(root) != project_id(tmp_path / "other")
```

- [x] **Step 2: 验证失败**

Run: `uv run pytest tests/test_platforms.py -v`
Expected: FAIL。

- [x] **Step 3: 实现注册表和解析器**

加载 `platform_registry.json`；实现 OS 过滤、环境变量展开、`~` 展开、resolved path 归并、Windows `normcase`、`project_id` 和 `same_physical_path`。在 `pyproject.toml` 中显式 force-include registry JSON。

- [x] **Step 4: 验证通过和 wheel 打包**

Run: `uv run pytest tests/test_platforms.py -v && uv build && unzip -p dist/atkits-*.whl atkits/platform_registry.json | python3 -m json.tool >/dev/null`
Expected: 测试 PASS；wheel 中存在合法 JSON。

- [x] **Step 5: 提交**

```bash
git add src/atkits/platforms.py src/atkits/platform_registry.json pyproject.toml tests/test_platforms.py
git commit -m "实现跨平台路径解析与物理目标归并"
```

### Task 6: 实现安装策略与共享目标卸载

**Files:**
- Create: `src/atkits/installers.py`
- Create: `tests/test_installers.py`

**Interfaces:**
- Produces: `Installer.install(record, package_dir)`、`uninstall(record, consumers)`、`health(record)`、`BackupStore.backup(path)`。

- [x] **Step 1: 写失败测试**

```python
def test_copy_update_detects_user_modification(installer, plugin_record, package_v2):
    (plugin_record.target_path / "user.txt").write_text("local edit")
    with pytest.raises(InstallConflict, match="local modification"):
        installer.install(plugin_record, package_v2)


def test_uninstall_subset_keeps_shared_symlink(installer, shared_skill_record):
    installer.uninstall(shared_skill_record, consumers={"codex"})
    assert shared_skill_record.target_path.is_symlink()


def test_uninstall_all_consumers_removes_shared_symlink(installer, shared_skill_record):
    installer.uninstall(shared_skill_record, consumers={"codex", "cursor"})
    assert not shared_skill_record.target_path.exists()


def test_uninstall_does_not_touch_symlink_replacement(installer, skill_record, tmp_path):
    skill_record.target_path.unlink()
    skill_record.target_path.symlink_to(tmp_path / "other")
    with pytest.raises(InstallConflict):
        installer.uninstall(skill_record, consumers={"codex"})
    assert skill_record.target_path.is_symlink()


def test_editable_install_uses_source_path_not_package_cache(
    installer, editable_record, source_repo
):
    installer.install(editable_record, package_dir=None)
    assert editable_record.target_path.readlink() == source_repo.skill_path
    assert editable_record.package_path is None
```

- [x] **Step 2: 验证失败**

Run: `uv run pytest tests/test_installers.py -v`
Expected: FAIL。

- [x] **Step 3: 实现策略**

symlink 只在目标指向记录包路径或 editable `source_path` 时替换或 unlink；copy 只有当前 hash 与记录一致时才备份并更新。真实用户目录默认冲突。共享目标卸载时先比较剩余 consumers。所有真实目录移除前移动到 `~/.atkits/backup/<UTC时间戳>/`。

- [x] **Step 4: 验证通过**

Run: `uv run pytest tests/test_installers.py -v`
Expected: PASS。

- [x] **Step 5: 提交**

```bash
git add src/atkits/installers.py tests/test_installers.py
git commit -m "实现共享物理目标安装与卸载策略"
```

### Task 7: 实现资产生命周期编排

**Files:**
- Create: `src/atkits/lifecycle.py`
- Create: `tests/test_lifecycle.py`

**Interfaces:**
- Produces: `Lifecycle.install(kind, name, version=None, *, scope, platform_ids, method, project_root=None)`、`uninstall(kind, name, *, scope, platform_ids, project_root=None)`、`update(kind, name, *, scope)`、`plan_update(kind, name, *, scope)`、`status(online=False)`、`prune_cache()`。

- [ ] **Step 1: 写失败测试**

```python
def test_install_update_and_offline_rollback(lifecycle):
    installed = lifecycle.install("skill", "foo", platform_ids=["codex"], scope="global", method="symlink")
    assert installed.version == "1.0.0"
    updated = lifecycle.update("skill", "foo", scope="global")
    assert updated.version == "1.1.0"
    lifecycle.fake_registry.set_offline(True)
    rolled_back = lifecycle.install(
        "skill", "foo", "1.0.0", platform_ids=["codex"], scope="global", method="symlink"
    )
    assert rolled_back.version == "1.0.0"


def test_shared_target_rejects_version_mismatch(lifecycle):
    lifecycle.install(
        "skill", "foo", "1.0.0", platform_ids=["codex"], scope="project", method="symlink"
    )
    with pytest.raises(InstallConflict, match="shared target"):
        lifecycle.install(
            "skill", "foo", "1.1.0", platform_ids=["cursor"], scope="project", method="symlink"
        )


def test_project_targets_are_isolated_by_project_id(lifecycle, project_root, other_project_root):
    first = lifecycle.install(
        "skill", "foo", "1.0.0", platform_ids=["codex"], scope="project",
        project_root=project_root, method="symlink",
    )
    second = lifecycle.install(
        "skill", "foo", "1.1.0", platform_ids=["codex"], scope="project",
        project_root=other_project_root, method="symlink",
    )
    assert first.path != second.path
    assert first.project_id != second.project_id
    assert first.version == "1.0.0"
    assert second.version == "1.1.0"


def test_update_shared_target_reports_all_affected_consumers(lifecycle):
    lifecycle.install(
        "skill", "foo", "1.0.0", platform_ids=["codex", "cursor"], scope="global", method="symlink"
    )
    plan = lifecycle.plan_update("skill", "foo", scope="global")
    assert set(plan.affected_consumers) == {"codex", "cursor"}
    assert plan.path.name == "foo"


def test_uninstall_removed_remote_asset_still_uses_local_state(lifecycle):
    lifecycle.install("plugin", "bar", platform_ids=["cursor"], scope="global", method="copy")
    lifecycle.fake_registry.remove("plugin", "bar")
    lifecycle.uninstall("plugin", "bar", scope="global", platform_ids=["cursor"])
    assert lifecycle.state.all() == []
```

- [ ] **Step 2: 验证失败**

Run: `uv run pytest tests/test_lifecycle.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现生命周期**

写操作按 `registry → platform resolution → package → target → state → health` 执行。共享路径版本不一致时报冲突。平台成功但 state 写入失败时恢复安装前目标，无法恢复则保留备份并返回明确错误。更新只解析最新稳定 SemVer。

- [ ] **Step 4: 验证通过**

Run: `uv run pytest tests/test_lifecycle.py -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add src/atkits/lifecycle.py tests/test_lifecycle.py
git commit -m "实现版本化资产生命周期"
```

### Task 8: 切换 CLI 到平台选择式命令

**Files:**
- Modify: `src/atkits/cli.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produces: 第 4 节命令。旧 `apply/import` 命令直接移除，不提供兼容入口。

- [ ] **Step 1: 写失败测试**

```python
def test_remote_list_does_not_download_packages(cli, fake_lifecycle):
    result = cli.invoke(app, ["list", "--remote"])
    assert result.exit_code == 0
    assert "foo" in result.output
    assert fake_lifecycle.package_downloads == 0


def test_install_requires_explicit_platform_with_no_input(cli, fake_lifecycle):
    result = cli.invoke(app, ["install", "foo", "--no-input"])
    assert result.exit_code == 2
    assert "platform" in result.output


def test_install_specific_version_and_platforms(cli, fake_lifecycle):
    result = cli.invoke(
        app,
        ["install", "foo@1.0.0", "--scope", "global", "--platform", "codex,cursor", "--method", "symlink"],
    )
    assert result.exit_code == 0
    assert fake_lifecycle.last_request["platform_ids"] == ["codex", "cursor"]


def test_network_error_returns_exit_code_3(cli, fake_lifecycle):
    fake_lifecycle.fail_network = True
    result = cli.invoke(app, ["check"])
    assert result.exit_code == 3


def test_doctor_fix_repairs_package_and_symlink(cli, fake_lifecycle):
    fake_lifecycle.damage_managed_package()
    result = cli.invoke(app, ["doctor", "--fix"])
    assert result.exit_code == 0
    assert fake_lifecycle.repaired_target is not None
```

- [ ] **Step 2: 验证失败**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL，新命令尚不存在。

- [ ] **Step 3: 实现命令和中文输出**

支持交互多选、scope、method、primary/shared 路径摘要和确认；支持 `--no-input`。非交互必须 `--platform`/`--preset`/`--all`。参数错误返回 2，冲突/验证失败返回 1，网络错误返回 3。`status/check/doctor --fix` 均有对应测试。

- [ ] **Step 4: 验证核心测试并确认旧命令移除**

Run: `uv run pytest -v && uvx ruff format src tests && uvx ruff check src tests && ! uv run atkits --help | grep -q "apply"`
Expected: 全部 PASS；帮助中不再出现旧 `apply` 命令。

- [ ] **Step 5: 提交**

```bash
git add src/atkits/cli.py tests/test_cli.py
git commit -m "切换 atkits 到平台选择式命令"
```

### Task 9: 实现独立资产打包与发布目录

**Files:**
- Modify: `profiles/global.yaml`
- Create: `favorites.yaml`
- Create: `scripts/package_asset.py`
- Create: `scripts/release.py`
- Create: `scripts/update_catalog.py`
- Create: `.github/workflows/release.yml`
- Create: `tests/test_package_asset.py`
- Modify: `skills/ai-image-prompt-engineer/SKILL.md`
- Modify: `skills/searching-github-projects/SKILL.md`
- Modify: `skills/skill-lookup/SKILL.md`
- Modify: `skills/sora/SKILL.md`

**Interfaces:**
- Produces: `package_asset(kind, name, version, repo_root, output_dir) -> Path`、`build_catalog(releases, favorites) -> dict`。

- [ ] **Step 1: 写失败测试**

```python
def test_package_contains_only_selected_skill(repo_with_two_skills, tmp_path):
    archive = package_asset("skill", "foo", "1.1.0", repo_with_two_skills, tmp_path)
    with tarfile.open(archive) as tf:
        names = tf.getnames()
    assert "foo/SKILL.md" in names
    assert not any(name.startswith("bar/") for name in names)


def test_catalog_latest_uses_semver_precedence(releases, favorites):
    catalog = build_catalog(releases, favorites)
    assert catalog["skills"]["foo"]["latest"] == "1.2.0"
    assert catalog["external_skills"]["pdf"]["source"] == "openai/skills"
```

- [ ] **Step 2: 验证失败**

Run: `uv run pytest tests/test_package_asset.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现打包、v2 collection 和 workflow**

将 `profiles/global.yaml` 直接改写为 v2 collection；从旧带 `source` 的条目生成 `favorites.yaml`。四个现有 Skill 初始化 `metadata.version: 0.1.0`，Plugin 沿用现有版本。CI 将资产、外部收藏和 preset 投影到 catalog 的 `collection.presets`。workflow 设置 `permissions: contents: write`，并给 catalog job 配置：

```yaml
concurrency:
  group: catalog
  cancel-in-progress: false
```

CLI 标签必须匹配 `pyproject.toml` 静态版本。`update_catalog.py` 按 SemVer 计算 latest，合并 favorites，并串行上传 `catalog.json`。

- [ ] **Step 4: 本地验证发布产物**

Run: `uv run pytest tests/test_package_asset.py -v && uv build && uv run python scripts/package_asset.py skill ai-image-prompt-engineer 0.1.0 . /tmp/atkits-dist`
Expected: 测试 PASS，wheel 和单技能包均生成，包内版本与参数一致。

- [ ] **Step 5: 提交**

```bash
git add profiles/global.yaml favorites.yaml scripts .github/workflows/release.yml tests/test_package_asset.py   skills/ai-image-prompt-engineer/SKILL.md skills/searching-github-projects/SKILL.md   skills/skill-lookup/SKILL.md skills/sora/SKILL.md
git commit -m "建立独立资产打包与串行发布目录"
```

### Task 10: 实现新机器引导和 CLI 自更新

**Files:**
- Create: `scripts/install-atkits.sh`
- Create: `src/atkits/self_update.py`
- Create: `tests/test_self_update.py`

**Interfaces:**
- Produces: `latest_cli_wheel(registry) -> AssetVersion`、`self_update(uv_executable="uv") -> Version`。

- [ ] **Step 1: 写失败测试**

```python
def test_self_update_downloads_verified_wheel_and_invokes_uv(fake_runtime):
    updated = self_update(uv_executable=fake_runtime.uv)
    assert updated == Version("0.2.0")
    assert fake_runtime.installed_wheel.name == "atkits-0.2.0-py3-none-any.whl"
    assert fake_runtime.downloaded_asset.sha256 == fake_runtime.expected_hash
```

- [ ] **Step 2: 验证失败**

Run: `uv run pytest tests/test_self_update.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现引导和自更新**

引导脚本要求 token，下载并校验 wheel 后调用 `uv tool install --force <wheel>`；缺少 uv 时给出官方安装文档地址并退出 1。自更新使用同一实现，不依赖 `uv tool upgrade` 发现 Release。

- [ ] **Step 4: 验证通过**

Run: `uv run pytest tests/test_self_update.py -v && bash -n scripts/install-atkits.sh`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add scripts/install-atkits.sh src/atkits/self_update.py tests/test_self_update.py
git commit -m "实现私有仓库命令安装与自更新"
```

### Task 11: 接入外部收藏

**Files:**
- Modify: `src/atkits/external.py`
- Modify: `src/atkits/cli.py`
- Create: `tests/test_external.py`

**Interfaces:**
- Produces: `install_external(name, platform_ids)`、`external_health(name)`。

- [ ] **Step 1: 写失败测试**

```python
def test_broken_external_symlink_is_not_installed(external_installer):
    assert external_installer.health("missing").installed is False


def test_external_install_requires_resolved_skill_dir(external_installer):
    result = external_installer.install("pdf", platform_ids=["codex"])
    assert result.installed is True
    assert (result.path / "SKILL.md").is_file()
```

- [ ] **Step 2: 验证失败**

Run: `uv run pytest tests/test_external.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现外部技能委托**

外部收藏来自 catalog `external_skills`。安装继续委托 `npx skills add`，但安装后必须检查目标为可解析目录且包含 `SKILL.md`；broken symlink、普通文件或空目录都视为未安装并返回错误。

- [ ] **Step 4: 验证通过**

Run: `uv run pytest tests/test_external.py -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add src/atkits/external.py src/atkits/cli.py tests/test_external.py
git commit -m "接入外部技能收藏安装"
```

### Task 12: 清理旧核心、更新文档并执行最终验收

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `docs/DESIGN.md`
- Create: `docs/ARCHITECTURE.md`
- Delete: `src/atkits/engine.py`
- Delete: `src/atkits/profile.py`
- Delete: `src/atkits/importer.py`
- Delete: `profiles/global.yaml` 中旧 `targets/to` 语义（保留 v2 collection）
- Create: `tests/test_no_git.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produces: 与新 CLI 完全一致的用户文档、维护文档和无 Git 集成验收。

- [ ] **Step 1: 写文档和无 Git 失败测试**

```python
def test_core_workflow_runs_without_git_in_path(fake_registry_server, tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    (tmp_path / "empty-bin").mkdir(exist_ok=True)
    assert shutil.which("git") is None

    result = runner.invoke(app, ["list", "--remote"])
    assert result.exit_code == 0

    result = runner.invoke(
        app,
        ["install", "foo@1.0.0", "--scope", "global", "--platform", "codex", "--method", "symlink"],
    )
    assert result.exit_code == 0
```

- [ ] **Step 2: 验证失败**

Run: `uv run pytest tests/test_no_git.py -v`
Expected: FAIL，当前 CLI 尚未完成或文档命令缺失。

- [ ] **Step 3: 清理旧核心并更新文档**

删除不再被新 CLI 引用的 `engine/profile/importer`。README 覆盖 token 创建、新机器安装、平台选择、primary/shared 路径、远端列表、指定版本、回退、editable 和卸载；AGENTS.md 用新架构替换旧约束；DESIGN.md 标记旧引擎为历史设计；ARCHITECTURE.md 记录 catalog、state、路径解析和发布流水线。

- [ ] **Step 4: 执行完整验收**

```bash
uv run pytest -v
uvx ruff format src tests scripts
uvx ruff check src tests scripts
uv build
uv venv /tmp/atkits-final/test-venv
uv pip install --python /tmp/atkits-final/test-venv/bin/python dist/atkits-*.whl
unzip -p dist/atkits-*.whl atkits/platform_registry.json | python3 -m json.tool >/dev/null
env -i PATH="/tmp/atkits-final/test-venv/bin" HOME=/tmp/atkits-final/home \
  ATKITS_HOME=/tmp/atkits-final/root \
  /tmp/atkits-final/test-venv/bin/atkits --help
```

Expected: 测试、ruff、构建全部通过；集成测试证明无 Git PATH 下 list/install 可用；wheel 包含平台注册表；真实 HOME 无改动。随后由用户在测试发布仓库执行一次带只读 token 的私有 Release 安装验收。

- [ ] **Step 5: 提交**

```bash
git add README.md AGENTS.md docs/DESIGN.md docs/ARCHITECTURE.md profiles/global.yaml \
  src/atkits tests/test_no_git.py tests/test_cli.py
git commit -m "完成跨平台包管理架构验收"
```

## 完成后的明确非目标

- 不实现公开技能市场、评分、搜索排名或多租户权限。
- 不实现 Skill/Plugin 之间的依赖解析；每个发布包必须自包含。
- 不实现外部技能的完整版本管理。
- 不实现 Claude/Codex marketplace、项目级 profile、rules/MCP/hooks 分发。
- 不为了统一目录而改写 uv 或各平台自身的目录规范。
