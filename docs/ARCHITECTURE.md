# atkits Architecture

## 1. 总体链路

```text
开发侧
  Git commit
    → GitHub Actions
    → 单资产版本包 / CLI wheel / catalog.json
    → GitHub Releases

运行侧
  atkits CLI
    → HTTPS + token
    → catalog
    → 用户选择平台与安装方式
    → 下载并校验版本包
    → 解包到 ~/.atkits/packages
    → symlink/copy 到物理路径
    → 写入 state.json
```

## 2. 远端模型

### 2.1 Release

- `skill-<name>-v<version>`
- `plugin-<name>-v<version>`
- `cli-v<version>`
- `registry`：固定 Release，存放 `catalog.json`

### 2.2 catalog.json

```json
{
  "schema_version": 1,
  "skills": {},
  "plugins": {},
  "cli": {"latest": "0.2.0", "versions": {}},
  "external_skills": {},
  "collection": {"presets": {}}
}
```

- `latest` 按 SemVer precedence 计算，不按上传时间。
- 预发布版本不进入默认 latest。
- `collection.presets` 来自 `profiles/global.yaml`。
- `external_skills` 来自 `favorites.yaml`。

## 3. 本地模型

```text
~/.atkits/
├── config.toml
├── state.json
├── registry/catalog.json
├── packages/
│   ├── skills/<name>/<version>/
│   └── plugins/<name>/<version>/
├── downloads/
├── backup/
├── locks/
├── logs/
└── tmp/
```

### 3.1 state key

```text
kind:name:scope:<project-id|global|editable>:<target-id>
```

- project scope 使用 `SHA256(normcase(resolve(project_root)))`。
- 同一项目不同写法不会互相覆盖。
- 不同项目可以独立安装不同版本。

### 3.2 InstallTarget

记录：

- kind / name / scope / project_id / version
- target_id / path / strategy
- consumers
- package_path 或 source_path
- artifact_sha256 / content_sha256

## 4. 平台解析

平台定义在 `src/atkits/platform_registry.json`：

```json
{
  "id": "cursor",
  "project_paths": [
    {"id": "agents", "template": ".agents/skills", "role": "shared"},
    {"id": "cursor", "template": ".cursor/skills", "role": "primary"}
  ],
  "global_paths": [
    {"id": "agents", "template": "$HOME/.agents/skills", "role": "shared"},
    {"id": "cursor", "template": "$HOME/.cursor/skills", "role": "primary"}
  ]
}
```

### 4.1 OS 与环境变量

支持：

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

运行时规则：

- 按 `os` 字段过滤 PathSpec。
- 展开环境变量。
- `~` 等价于当前用户 home。
- 路径比较使用 resolved path。
- Windows 使用 `PureWindowsPath` 和小写规范化。
- 不允许模板包含 `..` 或解析后逃逸。

### 4.2 归并

- 先按 resolved path 分组。
- 同一路径只生成一个 PhysicalTarget。
- consumers 记录选择了该路径的逻辑平台。
- `universal` 不是可选平台，共享路径通过 role 表达。
- primary / shared / compatibility 均展示给用户。

## 5. 安装策略

### 5.1 Symlink

```text
~/.agents/skills/foo
→ ~/.atkits/packages/skills/foo/1.0.0
```

- 只替换 provenance 匹配的链接。
- 用户改过的目标报冲突。
- Windows 权限不足时不静默降级。

### 5.2 Copy

- 安装前记录 content hash。
- 更新前比较当前 hash。
- 用户修改过则报冲突。
- 替换前旧目录进入 backup。

### 5.3 Editable

```text
~/.agents/skills/foo
→ /path/to/repo/skills/foo
```

- 使用独立 `source_path`。
- 不使用 package cache。
- 不被 `cache prune` 清理。

## 6. 外部技能

外部技能来自 catalog `external_skills`：

1. 读取 source。
2. 委托 `npx skills add`。
3. 检查目标路径是目录且包含 `SKILL.md`。
4. broken symlink、普通文件、空目录均视为未安装。

## 7. 自更新

- catalog 中的 `cli` 段描述 wheel。
- `self-update` 下载 wheel。
- 校验 SHA-256。
- 调用 `uv tool install --force`。
- 不依赖 `uv tool upgrade` 发现 GitHub Release。

## 8. 安全

- token 只从环境变量读取。
- GitHub API 请求带 timeout。
- 302 跨主机时删除 Authorization。
- Release 包 hash 不匹配即失败。
- tar 条目仅允许普通文件和目录。
- 最终版本目录已存在且非空时不得覆盖。
- state 写入使用临时文件 + `os.replace`。
- 所有状态写入使用 filelock。
- 安装、更新、卸载后必须后置验证。

## 9. CI / Release

```text
tag push
  → test
  → build wheel / asset archive
  → GitHub Release
  → catalog job (concurrency: catalog)
```

- catalog 更新串行。
- CLI tag 与 pyproject version 必须一致。
- 重复发布同版本不同内容会失败。
