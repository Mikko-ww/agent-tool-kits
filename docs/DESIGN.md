# agent-tool-kits · 设计文档

> 当前实现：Release Registry + 版本化包管理 + 用户显式平台选择。
> 详细架构见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 1. 当前设计

`atkits` 不再是“本地目录同步器”，而是：

1. 私有 GitHub Releases 作为远端事实来源。
2. `catalog.json` 描述资产、版本、preset 和外部收藏。
3. `~/.atkits/state.json` 记录本机安装 provenance。
5. 用户显式选择逻辑平台。
6. 系统按 OS 和环境变量解析物理路径。
7. Skill 默认 symlink，Plugin/Copy 按需复制。
8. 外部技能仅作为收藏，委托 `npx skills add`。

## 2. 关键决策

- **不依赖 Git**：运行时只使用 HTTPS。
- **不默认全平台安装**：交互多选，非交互显式平台。
- **多路径平台模型**：Cursor/OpenCode 等同时拥有 primary 和 shared/compatibility 路径。
- **共享路径单版本**：同一物理目录只能激活一个版本。
- **本机状态**：必须记录 provenance，否则无法安全卸载插件或检测用户修改。
- **干净重构**：不保留旧 `apply/import`，不迁移旧安装状态。

## 3. 与旧实现的关系

旧 `engine/profile/importer` 已经删除。
当前代码以 `models/home/state/github/registry/packages/platforms/installers/lifecycle/cli` 为核心。
旧设计的“无 lock 推导”思路保留在历史提交中，但不再适用于插件 copy 模式。

## 4. 后续方向

- 项目级 update。
- 插件 marketplace 通道。
- 更完整的 doctor 检查。
- 外部技能卸载与更新。
- Windows 实机验证。
