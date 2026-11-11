---
name: atkits-release-workflow
description: "在 agent-tool-kits 仓库中发布、升级或 bump 技能/插件版本：确定资产类型、提升 SemVer、运行测试和 lint、打包、打 tag、推送并校验 CI/catalog。适用于本仓库资产的 release/publish/upgrade/version bump/tag；不用于普通 Git 操作或外部技能管理。"
metadata:
  version: 0.1.0
---

# atkits 发布工作流

当用户要求“发布”“升级版本”“打 tag”“bump 版本”本仓库中的技能或插件时，使用本技能。

## 目标

只针对一个资产，产出经过验证、已打 tag 的发布版本，不修改无关文件。

## 发布前检查

1. 确认仓库是干净的，或只有目标资产发生了修改。
2. 识别资产类型：
   - 技能：`skills/<name>/SKILL.md`
   - 插件：`plugins/<name>/plugin.yaml`
3. 读取当前版本。
4. 如果用户没有明确说明升级幅度，先和用户确认目标版本。
5. 除非用户明确要求发布 `cli-v<version>`，否则不要用本技能发布 CLI wheel。

## 版本规则

使用 SemVer 2.0.0。

- 修复错字、文档或小 bug → patch
- 新增能力且不破坏现有用法 → minor
- 破坏性变更或行为大幅改变 → major
- 试验版本 → prerelease

不要复用已经存在的版本号。

## 发布步骤

1. 只修改版本字段：
   - 技能：`SKILL.md` 里的 `metadata.version`
   - 插件：`plugin.yaml` 里的 `version`
2. 运行：
   ```bash
   uv run pytest
   uvx ruff format src tests scripts
   uvx ruff check src tests scripts
   uv build --quiet
   ```
3. 本地打包单个资产：
   ```bash
   uv run python scripts/package_asset.py skill <name> <version> . dist
   ```
   或：
   ```bash
   uv run python scripts/package_asset.py plugin <name> <version> . dist
   ```
4. 确认压缩包和 `.sha256` 文件都存在。
5. 创建 tag：
   ```text
   skill-<name>-v<version>
   plugin-<name>-v<version>
   ```
6. 只有在用户确认之后，才允许推送 tag。
7. 检查 GitHub Actions 和生成的 Release。
8. 确认 CI 已更新 `catalog.json`。

## 硬性规则

- 不许跳过测试或 lint。
- 不许版本不变就发布新内容。
- 不许复用同一个版本号发布不同内容。
- 不许在没有用户确认的情况下推送 tag。
- 不许修改无关文件。
- 不许把外部技能当作本仓库的版本化资产处理。
- 任何检查失败都立即停止并报告，不许继续打 tag。
