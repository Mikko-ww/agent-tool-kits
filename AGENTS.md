# AGENTS.md · agent-tool-kits

> 给接手本仓库的 AI agent / 开发者看的交接文档。
> 语言约定：面向人的文字以简体中文为主；代码、标识符、状态名和平台 id 保持英文。

## 1. 项目定位

`atkits` 是一个个人私有 GitHub Release 包管理器，管理版本化 Agent Skill / Plugin：

- 远端事实来源：GitHub Releases + `catalog.json`。
- 本地事实来源：`~/.atkits/state.json`。
- 用户显式选择逻辑平台，系统解析到物理路径。
- 不提供旧 `apply/import` 兼容入口，不迁移旧安装状态。

## 2. 核心目录

```text
agent-tool-kits/
├── AGENTS.md
├── README.md
├── docs/
│   ├── ARCHITECTURE.md
│   ├── DESIGN.md
│   └── superpowers/plans/2026-11-10-release-registry-refactor.md
├── skills/
├── plugins/
├── profiles/global.yaml       # v2 collection 输入，供 CI 生成 catalog
├── favorites.yaml             # 外部技能收藏
├── scripts/
├── .github/workflows/release.yml
└── src/atkits/
```

## 3. 代码地图

| 文件 | 职责 |
|---|---|
| `models.py` | Catalog、AssetVersion、InstallTarget、preset 与外部收藏模型 |
| `home.py` | `~/.atkits` 布局、TOML 配置、原子写入 |
| `state.py` | 安装状态、文件锁、原子 JSON 写入 |
| `github.py` | GitHub Releases API、跨主机重定向剥离 Authorization |
| `registry.py` | catalog 获取、缓存、版本解析 |
| `packages.py` | 包下载校验、安全解压、版本缓存 |
| `platforms.py` | 平台注册表、OS 路径解析、物理目标归并 |
| `installers.py` | symlink/copy/editable 安装与卸载 |
| `lifecycle.py` | install/update/uninstall/status/doctor/prune 编排 |
| `cli.py` | 用户命令入口 |
| `external.py` | 外部技能收藏委托与健康检查 |
| `self_update.py` | CLI wheel 自更新 |

## 4. 硬性约束

1. 运行时不得调用 Git，不要求用户维护 clone。
2. 私有资源只通过只读 token 访问；token 不得写入仓库或明文配置。
3. 跨主机重定向必须剥离 Authorization。
4. Release 包必须校验 SHA-256。
5. tar 解包必须拒绝路径穿越、symlink、hardlink、设备文件。
6. 不默认安装到所有平台；非交互必须显式 `--platform` / `--preset` / `--all`。
7. 同一物理路径只能激活一个版本。
8. 卸载共享目标时必须先计算剩余 consumers。
9. 真实用户目录替换前必须备份；不得直接删除。
10. `cache prune` 不得清理 backup 或 editable source。
11. Skill/Plugin 使用 SemVer 2.0.0；CLI 使用 PEP 440。
12. CLI tag 必须与 `pyproject.toml` 静态版本一致。
13. 平台 registry 使用 OS 条件与环境变量模板，不得存展开后的绝对路径。
14. 仓库文案中文优先；机器值保持英文。

## 5. 验证要求

```bash
uv sync --group dev
uv run pytest
uvx ruff format src tests scripts
uvx ruff check src tests scripts
uv build
unzip -p dist/atkits-*.whl atkits/platform_registry.json | python3 -m json.tool >/dev/null
```

- 所有测试使用 `tmp_path` 与假 HOME。
- 测试不得访问真实 GitHub token。
- 无 Git PATH 集成测试必须通过。
- 修改 `src/atkits/` 后必须运行完整测试和 ruff。

## 6. 发布流程

1. 修改 Skill / Plugin / CLI。
2. 更新版本号。
3. 推送标签：
   - `skill-<name>-v<version>`
   - `plugin-<name>-v<version>`
   - `cli-v<version>`
4. GitHub Actions 运行测试、打包、发布 Release。
5. catalog job 串行更新 `registry` Release 中的 `catalog.json`。

## 7. 已知设计取舍

- 外部技能仅作为收藏，安装委托 `npx skills add`，不管理其版本。
- 项目级更新尚未实现。
- Windows symlink 权限不足时会失败，需显式 `--method copy`。
- 插件本地 marketplace 通道尚未实现。
