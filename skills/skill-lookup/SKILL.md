---
name: skill-lookup
description: 当用户询问 Agent Skills、想找可复用的 AI 能力、需要安装技能，或提到给 Codex 加技能时触发。用于发现、获取和安装技能。
---

当用户需要 Agent Skills、想扩展 agent 的能力、或在找可复用的 agent 组件时，使用 prompts.chat 的 MCP server。

## 何时使用

用户出现以下意图时启用本技能：

- 索要 Agent Skill（“帮我找一个代码审查的 skill”）
- 想搜索技能（“有哪些测试相关的技能？”）
- 需要获取某个具体技能（“把 XYZ 这个 skill 拿下来”）
- 想安装技能（“安装那个写文档的 skill”）
- 提到用技能扩展 agent 的能力

## 可用工具

使用 prompts-chat MCP 提供的工具：

- `search_skills`：按关键词搜索技能
- `get_skill`：按 ID 获取某个技能及其全部文件

## 如何搜索

调用 `search_skills`，参数：

- `query`：从用户请求中提取的关键词
- `limit`：返回条数（默认 10，最大 50）
- `category`：按分类 slug 过滤（如 `coding`、`automation`）
- `tag`：按标签 slug 过滤

展示结果时包含：

- 标题与描述
- 作者
- 文件列表（SKILL.md、参考文档、脚本）
- 分类与标签
- 技能链接

## 如何获取

调用 `get_skill`，参数：

- `id`：技能 ID

返回技能元数据和全部文件内容：

- SKILL.md（主说明）
- 参考文档
- 辅助脚本
- 配置文件

## 如何安装

用户要求安装时：

1. 调用 `get_skill` 取回全部文件。
2. 优先放进本仓库金库 `skills/{slug}/`，再在 `profiles/global.yaml` 声明目标平台，运行 `atkits apply`。
3. 如果只是临时试用，也可以直接写到当前项目的 `.agents/skills/{slug}/`（Codex / Cursor / OpenCode 共用）。
   - `SKILL.md` → `{slug}/SKILL.md`
   - 其余文件 → `{slug}/{filename}`

## 技能结构

- **SKILL.md**（必需）：带 frontmatter 的主说明
- **参考文档**：补充说明文件
- **脚本**：Python、shell 等辅助脚本
- **配置文件**：JSON、YAML

## 原则

- 先搜索，再建议用户自己写技能。
- 搜索结果要可读，并标出文件数量。
- 安装后确认文件已落盘。
- 解释该技能做什么、何时触发。
