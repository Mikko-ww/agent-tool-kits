# gh-research 技能设计

> 日期：2026-11-24
> 状态：已确认，进入实现

## 1. 意图与理由

仓库已有 `searching-github-projects`：一个判断力型选品技能，强在实体消歧、赛道分叉澄清、三维分开打分，弱在**没有取证工具、没有落盘、结论不可追溯**。

参考 `temp_ref/agent-research-skills/skills/github-research`（论文导向的六阶段流水线，13 个标准库脚本）后确认：它的工程骨架值得借鉴，它的流程、评分公式和学术偏置不能要。

本次**不改动** `searching-github-projects`，而是新建 `skills/gh-research/`：保留前者的全部判断力规范，补上取证脚本、证据分级、落盘证据库，并额外产出一份 HTML 报告。

两个技能并存：轻量问答仍走 `searching-github-projects`，需要证据链和可交付报告时走 `gh-research`。

## 2. 目标

- 继承三维评分（相似度/适合度/项目质量）、A/B/C/D 分级、实体消歧与澄清纪律，一字不降级。
- 每个分数挂可核验证据；证据分四档强度，档位决定措辞上限。
- 全过程落盘到 `./gh-research/{slug}/`，可跨会话续跑。
- 对话输出保持原有形状（分级榜单 + 优先阅读顺序 + 数据说明），**结尾给出 HTML 路径**。
- 额外产出 `report.html`：自包含单文件，离线可看，中文排版。
- 工具不可用时降级不中断，不编造指标。

## 3. 非目标

- 不做论文→代码映射、PapersWithCode 检索、deep-research 上游对接。
- 不做 clone 后的深度源码通读、集成计划、复用组件目录（那是另一个技能的产物）。
- 不做六阶段流水线目录结构。
- 不改动 `searching-github-projects` 的任何文件。
- 不发布、不打 tag（交给 `atkits-release-workflow`）。

## 4. 反目标（做出来也算失败）

- 模型行为从「先想清楚用户要什么」滑向「先把脚本跑完」。
- 用 HTML 报告替代对话输出，或把证据库 dump 进对话淹没榜单。
- 用脚本算出的单一总分覆盖三维判断。
- `gh` 不可用时整条流程中断，或用记忆数据补齐指标。

## 5. 约束

来自 `AGENTS.md` 与 skill-smith 规范：

- 新资产版本 `0.1.0`；frontmatter 只留 `name`、`description`、`metadata.version`；目录名等于 `name`。
- 脚本仅用 Python 标准库，Python ≥ 3.10，跨 macOS/Linux/Windows。
- 不写用户绝对路径；脚本用 `Path(__file__).resolve()` 自解析技能目录，不硬编码 `~/.claude/skills/`。
- 顶层 SKILL.md 正文 ≤ 500 行，细节进 `references/`；`@references/...` 只能出现在顶层。
- 依赖型技能须有 `skill-dependencies.json` + `scripts/check_environment.py`（原样复制 dependency-kit）+ `references/setup-guide.md`。
- 文案中文优先，机器值英文。
- `temp_ref/` 只读，不复制其包体结构（上游无许可证）。

## 6. 考虑过的方案

| 方案 | 取舍 | 结论 |
|---|---|---|
| A. 直接改 `searching-github-projects` 加脚本 | 改动小，但把无状态轻量技能变成重型技能，轻量问答被迫落盘 | 用户否决 |
| B. 照搬 github-research 六阶段 | 工程完整，但引入学术偏置、错误评分公式、跑完再说的姿态 | 否决 |
| C. 新建 `gh-research`，判断力规范继承 + 取证垫底 + HTML 产物 | 两个技能各司其职；新增脚本但不新增流程阶段 | **采用** |

## 7. 已确认的决定（用户）

1. 落盘位置：项目目录下的 `./gh-research/{slug}/`。
2. 不改 `searching-github-projects`，新建 `gh-research`。
3. 除原有对话输出外，生成 HTML 报告存于同一目录，报告结尾给出路径。
4. 完成后必须真实测试、检查产物、有问题修复并重测至通过。

## 8. 实现者的判断（我的调用）

### 8.1 证据链的三个位置

- **流程里**：垫在第 4–6 步底下，不新增阶段。取证范围由判断决定——只对进入评分的候选取证。
- **磁盘上**：`./gh-research/{slug}/`，扁平结构。不写技能目录（只读分发物）、不写 `~/.atkits/`（CLI 状态）、不用临时目录（跨会话会丢）。
- **输出里**：每个分数挂一条锚点，完整证据留库；HTML 承载全量。

### 8.2 目录产物

```text
./gh-research/{slug}/
├── brief.md            搜索简报（目标/必须/排除/约束）
├── candidates.jsonl    唯一事实来源：候选 + 证据 + 分数 + 取证日期
├── evidence/           README 摘录、代码命中片段
├── report.md           对话输出的副本
└── report.html         自包含 HTML 报告
```

`slug` 由产品指纹推导，不由用户原话推导。

### 8.3 证据分级

| 档 | 来源 | 措辞上限 |
|---|---|---|
| E1 代码级 | 代码搜索命中 `file:line` | 可断言「具备该能力」 |
| E2 文档级 | README / 官方文档明确描述 | 只能说「声明具备」 |
| E3 元数据级 | stars / license / pushed_at / topics | 只支撑质量与约束，不支撑能力判断 |
| E4 未核验 | 搜索摘要、记忆、推测 | 不得作为打分依据 |

硬规则：
- 核心能力仅有 E2 时相似度封顶 75（够不到 A 级），并在注意事项写明未验证实现。
- 每个维度分数至少引用一条 E1–E3；只有 E4 的维度标「未核验」，不给数字。
- Star 趋势无可靠时间序列一律写「未核验」。

### 8.4 脚本分工

| 脚本 | 职责 |
|---|---|
| `check_environment.py` | dependency-kit 原样复制，只读环境检查 |
| `gh_research.py` | 单一入口，子命令：`init` / `search` / `verify` / `readme` / `code-search` / `score` / `report` |

单入口多子命令而非 13 个独立脚本：减少模型选择负担，共享 JSONL 读写与降级逻辑。

### 8.5 评分公式

沿用 `相似度 45% + 适合度 35% + 项目质量 20%`，三个维度均由模型基于证据给出，脚本只负责校验「分数是否有证据支撑」并计算综合参考值，**不自动生成分数**。明确拒绝上游的 `log(stars)` 绝对归一化与 `open_issues/stars` 活跃度公式。

### 8.6 HTML 报告

自包含单文件：内联 CSS，无外部字体/CDN/JS 依赖，离线可打开。内容含简报、分级卡片（三维分数 + 证据锚点 + 注意事项）、对比表、优先阅读顺序、数据说明与证据档位图例。深浅色跟随 `prefers-color-scheme`。

## 9. 验收

- `skill_ops.py validate` 与 `preflight` 无 error。
- `package_asset.py skill gh-research 0.1.0` 产出 tar.gz + sha256。
- 新增 pytest 覆盖脚本核心逻辑（tmp_path、假 HOME、不触网）。
- 仓库全量 `pytest` 与 `ruff` 通过。
- **真实端到端**：对一个真实需求跑完整流程，产出 `./gh-research/{slug}/`，人工检查 HTML 与对话输出是否符合规范；有问题修复后重测。