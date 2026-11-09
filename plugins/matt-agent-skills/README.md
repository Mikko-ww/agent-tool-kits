# Matt Agent Skills · 使用说明

这份说明给人看。26 条 `matt-*` 技能里，**多数工作只走一条主链路**；其余是岔路、急救和底层词汇。不必全记，按「我现在想做什么」选一条即可。

不确定点哪条时，在对话里显式调用 **`matt-skill-flows`**，让 agent 按当前情境指路。只想看清单、不决策，用 **`matt-agent-skills-help`**。

## 怎么调用

| 平台 | 写法 | 例子 |
| --- | --- | --- |
| Cursor | `/技能id` | `/matt-to-spec` |
| Claude | `/matt-agent-skills:技能id` | `/matt-agent-skills:matt-to-spec` |
| Codex | `$技能id` | `$matt-to-spec` |

标了「请你点」的技能，agent **不会自己开**，必须你显式调用。标了「agent 可自己用」的，匹配任务时它会自己采用；你想强制走某套纪律时，也可以自己点。

## 我现在该点哪条

先找最像你的那一行，点那一列的技能。

| 你现在的情况 | 点这条 | 它实际在做什么 |
| --- | --- | --- |
| 第一次用这套工程技能，仓库还没配 tracker / 文档布局 | `matt-configure-project-docs` | 配好后续技能默认会用的 issue tracker、triage 标签、domain 文档结构。只跑一次。 |
| 有想法，仓库里能写文件，想先把方案问清楚再动手 | `matt-grill-with-docs` | 对计划做无情追问，同时把约定写进 `CONTEXT.md` / ADR。主链路的起点。 |
| 同样要追问，但没有可写的工作目录 | `matt-grill-me` | 同一套追问，不落盘。有仓库时不要用这条，用上面那条。 |
| 方案已经聊清楚，要收成一份可交给 agent 的 Spec | `matt-to-spec` | 只综合已讨论内容，不访谈，发布到项目 issue tracker。 |
| Spec（或当前计划）要拆成可一张张做的票 | `matt-to-tickets` | 拆成 tracer-bullet ticket，声明谁挡住谁，发到 tracker。 |
| 按 Spec 或某张票开始写代码 | `matt-implement` | 在约定 seam 上走 TDD，收尾做 code review。默认不 commit，除非你明确要求。 |
| 工作大到一次会话装不下，路还看不见 | `matt-wayfinder` | 在 tracker 上画「决策票」地图，一次只解决一张决策，**不直接写功能**。路清了再进 `matt-to-spec`。 |
| 别人提的 bug / 外来 PR / 外来需求，要先分拣 | `matt-triage` | 分类、核实、必要时追问，写成 agent-ready brief。自己用 `matt-to-tickets` 拆出来的票**不要再 triage**。 |
| 东西坏了、看不穿、间歇失败、性能回退 | `matt-diagnosing-bugs` | 先找到能复现这个 bug 的紧反馈循环，再修。不是「先猜再改」。 |
| 想扫一遍代码库，找能加深的模块 | `matt-improve-codebase-architecture` | 出可视化报告，你点候选后再追问。找到的是**想法**，不是直接改架构。 |
| 设计问题必须跑一段才能回答（状态机、UI 长什么样） | `matt-prototype` | 写可丢弃的小原型回答问题，不当正式实现。 |
| 要对照某个 commit / 分支 / PR 做审查 | `matt-code-review` | 两轴：有没有遵守仓库标准，有没有忠实实现 originating spec。 |
| 就是要测试先行写一段行为 | `matt-tdd` | red-green-refactor。完整功能交付仍用 `matt-implement`（它会内部调用这条）。 |
| 正在 merge / rebase，有冲突且不要 abort | `matt-resolving-merge-conflicts` | 按意图逐 hunk 解决，不挑行、不 abort。 |
| 要把当前对话交给另一个 agent / 另一个目录继续 | `matt-handoff` | 压成一份可带走的 handoff 文档。同会话继续聊不必用。 |
| 刚那句没听懂，请用更清楚的话说一遍 | `matt-wait-what` | 停下重述。不换技能、不换题目。 |
| 卡住你的信息不在你脑子里，在别人脑子里 | `matt-to-questionnaire` | 做成给别人填的问卷。收回来再拿去 grill 或写 Spec。 |
| 只有你能完成的步骤（控制台、密钥、一次性切换） | `matt-wizard` | 给你分阶段人类清单（可带脚本）。agent 自己能做的事不要用这条。 |
| 要对照官方文档 / API 查事实，并写进仓库 | `matt-research` | 对着 primary source 调研，留下带引用的 Markdown。 |
| 想在这个工作区里学一个概念，跨好几次会话 | `matt-teach` | 有状态的教学，不是一次性讲解。 |
| 讨论术语、改 `CONTEXT.md`、记 ADR | `matt-domain-modeling` | 打磨项目的领域语言。 |
| 设计某个模块该怎么切、接口落在哪 | `matt-codebase-design` | deep module 的共享词汇：interface、depth、seam。 |
| 要写 skill / AGENTS.md 这类给 agent 看的文档 | `matt-writing-for-agents` | 写作纪律，不是功能开发流程。 |
| 不知道从哪条开始 | `matt-skill-flows` | 路由器：问清情境后告诉你该走哪条路。 |
| 只要技能清单，不要帮我选路 | `matt-agent-skills-help` | 输出总览表。不替代上面那条。 |

## 主链路（日常默认）

大多数「我有一个想法，想做成」走这条：

```
matt-grill-with-docs  →  matt-to-spec  →  matt-to-tickets  →  matt-implement
                                              （内部）matt-tdd
                                              （收尾）matt-code-review
```

怎么走：

1. **先问清楚。** `matt-grill-with-docs` 把未决分支问死，并留下文档。没有仓库时改用 `matt-grill-me`。
2. **纸上答不了的问题**（必须跑起来才知道）：先 `matt-handoff` 出去 → `matt-prototype` → 再 `matt-handoff` 带回原对话。
3. **一次会话做不完** → `matt-to-spec` 收束，再 `matt-to-tickets` 拆票；每张票开**新对话**跑 `matt-implement`，避免上下文互相污染。
4. **一次会话做得完** → 聊清楚后直接 `matt-implement`。

从 grill 到拆票，尽量留在**同一次对话**里，推理链不断。拆完票之后，每次实现从票重新开始。

第一次在某个仓库跑工程流程前，先跑一次 **`matt-configure-project-docs`**。

## 三条常见岔路

这些不替代主链路，做完再并回去。

| 岔路 | 入口 | 做完之后 |
| --- | --- | --- |
| 外来 issue / PR 堆着 | `matt-triage` | 产出 agent-ready 议题，用 `matt-implement` 领取 |
| 线上/本地坏了，原因不明 | `matt-diagnosing-bugs` | 修好；若根因是模块切得太浅，再交给 `matt-improve-codebase-architecture` |
| 工作大到你握不住整条路 | `matt-wayfinder` | 决策地图清晰后，交给 `matt-to-spec`，**不要**直接 `matt-implement` |

空闲时想改善代码库适不适合 agent 操作：用 `matt-improve-codebase-architecture` 找候选，选中后再回主链路的 `matt-grill-with-docs`。

## 容易用错的几对

| 别混 | 区别 |
| --- | --- |
| `matt-skill-flows` vs `matt-agent-skills-help` | 前者帮你**选路**；后者只**列表**。 |
| `matt-grill-with-docs` vs `matt-grill-me` vs `matt-grilling` | 有仓库用 with-docs；没仓库用 grill-me；grilling 是二者内部的追问原语，一般不用你点。 |
| `matt-to-spec` vs `matt-to-tickets` vs `matt-implement` | 收成一份计划 → 拆成票 → 按票写代码。不要跳步把聊天记录直接交给 implement。 |
| `matt-triage` vs `matt-to-tickets` | triage 处理**别人送来的**原始议题；to-tickets 拆的是**你已经想清楚的**计划。 |
| `matt-diagnosing-bugs` vs `matt-triage` | 前者是「这个坏了，查因」；后者是「这堆 issue 怎么分类」。 |
| `matt-wayfinder` vs `matt-grill-with-docs` | grill 打磨你**单次会话握得住**的想法；wayfinder 只给**握不住**的大雾。已界定清楚的功能不要用 wayfinder。 |
| `matt-handoff` vs `matt-wait-what` | handoff 是换人/换目录/换会话；wait-what 是同一条消息没听懂，重说一遍。 |
| `matt-improve-codebase-architecture` vs `matt-codebase-design` | 前者是勘测「哪里值得加深」；后者是对已选方案设计模块形状。 |
| `matt-implement` vs `matt-tdd` | 交付一条功能/一张票用 implement；只想对某个行为强制测试先行，才单独点 tdd。 |
| `matt-wizard` | 只有你本人能点的按钮、密钥、控制台。agent 能自己做的步骤不要走 wizard。 |

## 你通常不用自己点的

这些匹配任务时 agent 会自己采用。想强制某种纪律时再显式调用。

| 技能 | 它在别人下面做什么 |
| --- | --- |
| `matt-grilling` | 追问原语。grill-me / grill-with-docs / triage / wayfinder 会用到。 |
| `matt-tdd` | implement 写代码时的测试先行循环。 |
| `matt-code-review` | implement 收尾，或你明确要求 review 时。 |
| `matt-diagnosing-bugs` | 你描述 broken / failing / slow 时。 |
| `matt-prototype` | 设计必须跑起来才能拍板时。 |
| `matt-research` | 你要查官方事实并落盘时。 |
| `matt-domain-modeling` | 术语、CONTEXT.md、ADR。 |
| `matt-codebase-design` | 模块切分、seam、可测性。 |
| `matt-resolving-merge-conflicts` | 已经处在冲突中时。 |
| `matt-wizard` | 撞上只有人类能过的墙时。 |
| `matt-writing-for-agents` | 在写 skill / agent 文档时。 |

## 完整目录（按工作，不按文件名）

### 选路与说明书

| 技能 | 请你点？ | 一句话 |
| --- | --- | --- |
| `matt-skill-flows` | 是 | 当前情境该走哪条技能或 flow。 |
| `matt-agent-skills-help` | 是 | 把全部技能打成总览表，不替你选。 |

### 想清楚再动手

| 技能 | 请你点？ | 一句话 |
| --- | --- | --- |
| `matt-configure-project-docs` | 是 | 首次配置 tracker 与文档布局。 |
| `matt-grill-with-docs` | 是 | 有仓库时的追问 + 落盘。 |
| `matt-grill-me` | 是 | 无仓库时的追问，不落盘。 |
| `matt-grilling` | 否 | 追问原语本身。 |
| `matt-to-spec` | 是 | 把已讨论内容收成 Spec。 |
| `matt-to-tickets` | 是 | 把计划拆成带依赖的票。 |
| `matt-wayfinder` | 是 | 大雾工作的决策地图，不构建。 |
| `matt-to-questionnaire` | 是 | 把必须问别人的决策做成问卷。 |
| `matt-prototype` | 否 | 用一次性代码回答设计问题。 |
| `matt-research` | 否 | 查 primary source，写成带引用的笔记。 |
| `matt-domain-modeling` | 否 | 打磨领域语言与 ADR。 |
| `matt-codebase-design` | 否 | 设计模块接口与 seam。 |

### 做出来、修好、看一眼

| 技能 | 请你点？ | 一句话 |
| --- | --- | --- |
| `matt-implement` | 是 | 按 Spec / 票实现，带 TDD 与收尾 review。 |
| `matt-tdd` | 否 | 测试先行写一段行为。 |
| `matt-code-review` | 否 | 相对固定点做 Standards + Spec 双轴审查。 |
| `matt-triage` | 是 | 外来 issue / PR 分成 agent-ready。 |
| `matt-diagnosing-bugs` | 否 | 难缠 bug / 性能回退的诊断循环。 |
| `matt-improve-codebase-architecture` | 是 | 扫描 deepening 机会，再对你选的候选追问。 |
| `matt-resolving-merge-conflicts` | 否 | 解决进行中的 conflict，不 abort。 |
| `matt-wizard` | 否 | 只有人类能完成的分步引导。 |

### 对话本身出了问题

| 技能 | 请你点？ | 一句话 |
| --- | --- | --- |
| `matt-handoff` | 是 | 把当前对话压成给下一个 agent 的文档。 |
| `matt-wait-what` | 是 | 上一条没落地，用更清楚的方式重说。 |
| `matt-teach` | 是 | 在当前工作区跨会话教一个概念。 |
| `matt-writing-for-agents` | 否 | 写给 agent 看的文档时用的写法。 |

各技能的门禁、模板和完整流程，以 `skills/<id>/SKILL.md` 为准。本页只回答「该不该点、点了会发生什么」。

---

## 本机启用（Cursor）

由 `atkits` 管理。清单 `profiles/global.yaml` 里已声明：

```yaml
plugins:
  matt-agent-skills: { to: [cursor] }
```

```bash
uv run atkits status        # 插件行显示 copy / sync / ok
uv run atkits apply         # 拷贝到 ~/.cursor/plugins/local/matt-agent-skills
```

这是**拷贝**不是 symlink：Cursor 的本地插件加载器对 `~/.cursor/plugins/local/` 下的每个条目做
`realpath` 校验，指向目录外的软链会被 `rejected: symlink target … is outside` 拒绝（可在
`Cursor Plugins.log` 里看到）。因此改了本目录任何文件后，需要再跑一次 `atkits apply`；`status` 会把过期的
拷贝标为 `sync`，重新拷贝前旧副本会移到 `~/.local/share/atkits/backup/<时间戳>/cursor-plugins/`。
Cursor 会在几秒内自动重新扫描本地插件目录，不需要重启。
