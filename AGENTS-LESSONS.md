# AGENTS-LESSONS.md · 已知问题与经验记录

> 面向在本仓库工作的 agent 和开发者。记录已确认的问题与正确做法，避免重复发生。
> 约定：每条包含「问题」（现象 + 根因）和「正确做法」（可执行的替代动作）；不写长篇分析、过程记录和状态标签。
> 收录有门槛：会复发、根因明确、可转行动、有证据、够稳定、不重复，六条全过才收录；机械可检查的问题优先转自动化检查，不写散文。
> 与 AGENTS.md 硬性约束或验证要求重复的内容不收录（如非交互 `--platform`、共享路径归并、卸载前算 consumers、替换前备份、测试用 tmp_path 与假 HOME、改 `src/atkits` 后全量测试、文案中文优先），一律以 AGENTS.md 为准。
> 新问题的提取、判定与合并走 `.agents/skills/atkits-lessons-workflow`；未经用户确认不写入本文件。

## 1. 环境与工具

- **问题**：受限沙箱里 `uv run` 可能失败，报 `~/.cache/uv/sdists-v9/.git: Operation not permitted`。
  **正确做法**：改用仓库内 `.venv/bin/python` 执行同一脚本；确需 uv 时再申请提权。
- **问题**：本机 `git` 命令会输出 `xcrun_db` / `DVTFilePathFSEvents` 警告，看起来像报错。
  **正确做法**：以退出码和实际输出为准，这些警告是噪音，可忽略。
- **问题**：沙箱对 `.git/` 与 `.agents/` 只读，`git checkout/commit` 因无法创建 `index.lock` 失败，`mkdir/cp` 报 `Operation not permitted`。
  **正确做法**：`.git/` 用文件级手动还原，或使用已批准的 `git add` 前缀与 MCP git 工具；`.agents/` 先在 `/private/tmp` 准备好文件，再申请一次提权写入。

## 2. 引入与入库（temp_ref → 金库）

- **问题**：把 `temp_ref/` 当成仓库内容提交，或整理时修改原件；它已 gitignore，CI 和其他机器上不存在。
  **正确做法**：`temp_ref/` 只是本机引入参考，只读不改，入库后原件保留不动。
- **问题**：外部技能 frontmatter 常带 `compatibility`、`author` 等多余字段，或目录名与 `name` 不一致、版本随手写。
  **正确做法**：入库时只保留 `name`、`description`、`metadata.version`；目录名必须等于 `name`；新资产统一从 `0.1.0` 开始（`package_asset.py` 会对 name/version 不一致直接失败）。
- **问题**：复制技能时把 `.DS_Store`、`__pycache__` 一起带进 `skills/`，或资产目录里藏 symlink。
  **正确做法**：复制阶段就剔除垃圾文件、拒绝 symlink；不要依赖打包器兜底。
- **问题**：把项目内部技能或外部技能当成本仓库版本化资产处理（注册 `profiles/global.yaml`、打 Release tag、复制外部包体进仓库）。
  **正确做法**：`.agents/skills/atkits-*` 内部工作流技能不注册、不发布、不分发；外部技能只进 `favorites.yaml`，安装委托 `npx skills add`。
- **问题**：直接执行 temp_ref 里第三方技能的脚本。
  **正确做法**：一律当作不可信代码，只跑只读校验（validate/preflight）；执行业务逻辑前必须静态预检并逐项确认。

## 3. 打包与发布

- **问题**：一个 Release 里放多个或零个 `.tar.gz` / `.whl`，catalog 构建要求对应资产数量恰为 1（见提交 `eefbc2d` 的修复）。
  **正确做法**：skill/plugin Release 必须恰好含一个 `.tar.gz` 和对应 `.sha256`；CLI Release 必须恰好含一个 `.whl`。
- **问题**：资产版本、tag、打包参数三处不一致；`dist/` 本地打包产物误入提交。
  **正确做法**：发布前核对三处版本完全一致；`dist/` 已 gitignore，产物不提交。
- **问题**：复用已发布的版本号发布不同内容，同版本重复发布会失败。
  **正确做法**：内容变化必须升版本；发布前确认目标版本未曾使用。
