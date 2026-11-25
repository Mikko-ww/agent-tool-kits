# GitHub 检索策略

构造查询、发现候选或 `gh` 不可用需要替代路径时读取本文件。

## 工具优先级

1. `gh api /search/repositories`：发现候选，取当前 Star、更新时间、语言与链接（脚本 `search` 子命令）。
2. `gh api /repos/{owner}/{repo}`：核验许可证、是否归档/Fork、创建与推送时间（`verify`）。
3. `gh api /repos/{owner}/{repo}/readme`：确认产品形态与能力（`readme`）。
4. `gh api /search/code`：证实核心能力真的有实现（`code-search`）。
5. Web 搜索与 GitHub 页面：消歧产品、寻找官方站点，或在 `gh` 不可用时替代以上全部。
6. Star History、OSS Insight：仅在能看到明确时间序列时用于 Star 趋势。

`gh` 未安装、未认证或限流时，脚本返回 `status: degraded` 而不是失败退出。此时改用网页检索，并把结果写回同一个候选库：

```bash
python <skill-dir>/scripts/gh_research.py search --slug <slug> --query "<查询>" --intent "<维度>" --from-json <候选JSON>
```

候选 JSON 是数组，每项至少含 `repo_id`，可选 `description`、`stars`、`forks`、`language`、`license`、`url`。**手工填入的数值必须在 notes 里写明实际来源与获取日期**，不得凭记忆填写。

## 查询矩阵

为同一需求构造 3–6 组互补查询：

| 查询类型 | 目的 | 示例 |
|---|---|---|
| 精确实体 | 找官方与生态 | `"LibTV"`、`org:libtv-labs` |
| 产品类别 | 找直接竞品 | `"AI video workspace"` |
| 交互形态 | 找相似体验 | `"infinite canvas" video AI` |
| 核心工作流 | 找业务链路 | `"script to storyboard" video` |
| 技术能力 | 找关键模块 | `"GitHub App" "code review agent"` |
| 自部署/许可证 | 满足落地约束 | `self-hosted language:TypeScript` |
| Topics | 扩展社区词汇 | `topic:ai-video topic:storyboard` |

优先英文检索，再补中文行业词。GitHub 上大量中文项目的描述同时含英文，但不能假定全部如此。

每组查询都要传 `--intent`，记录它覆盖的意图维度。没有维度标注的查询等于没有策略。

## 常用命令

发现候选：

```bash
python <skill-dir>/scripts/gh_research.py search --slug <slug> --query '"infinite canvas" video AI' --intent 交互形态 --limit 30 --sort stars
```

按 Topic 检索：

```bash
python <skill-dir>/scripts/gh_research.py search --slug <slug> --query 'topic:ai-video topic:storyboard' --intent 社区词汇 --limit 30
```

核验元数据（只对准备评分的候选）：

```bash
python <skill-dir>/scripts/gh_research.py verify --slug <slug> --repos owner/a owner/b
```

读取 README：

```bash
python <skill-dir>/scripts/gh_research.py readme --slug <slug> --repos owner/a owner/b --max-chars 6000
```

证实核心能力：

```bash
python <skill-dir>/scripts/gh_research.py code-search --slug <slug> --query 'registerNode repo:owner/a' --capability 自定义节点
```

代码搜索建议加 `repo:` 限定到候选仓库，避免把无关仓库的高频命中当成证据。默认不会把命中的新仓库加进候选库；确需加入时显式传 `--allow-new`，并重新走判断流程。

## 从宽到窄

1. 先搜参考产品和类别，收集仓库描述中的行业词。
2. 用产品形态与工作流词再次搜索。
3. 加入用户硬约束：`self-hosted`、语言、许可证、桌面/Web 等。
4. 各查询结果自动按 `owner/name` 小写去重合并，人工分数与证据不会被后续搜索覆盖。
5. 先粗筛 15–30 个，再深入核验 5–10 个，最终推荐通常不超过 8 个。

结果过窄时去掉一个限定词或改用同义词；过宽时增加产品形态、工作流限定。

## 产品消歧查询

遇到陌生产品名，至少尝试：

```text
"产品名" official
"产品名" GitHub
"产品名" docs
"产品名" [用户描述的领域]
site:github.com "产品名"
```

优先确认官方域名、组织名和产品定位。注意：同名仓库可能属于完全不同领域；官方 GitHub 可能只有 SDK 或插件，产品本身并不开源；第三方仓库可能自称替代品但功能尚未实现。

## 限流与重试

- GitHub 搜索接口额度有限，脚本分页之间自动间隔，限流时最多重试 2 次后降级。
- 查看剩余额度：`gh api rate_limit --jq '.resources.search'`。
- 降级后不要反复重跑同一条查询，改用网页检索或换查询词。
- 命令失败不等于「没有相关项目」，不得据此下结论。

## Star 趋势

当前 Star 与趋势是两个指标：

- 当前 Star：`stargazers_count`，由 `verify` 取得并记录取证日期。
- Star 趋势：带时间戳的累计或新增序列，必须挂 E1 或 E2 证据才能写入 `star_trend`。

可接受的报告：

```text
当前 12,438 Stars（GitHub，2026-11-24）
近 30 天 +1,204 Stars（Star History，查询于 2026-11-24）
```

不可接受的替代：用最近提交数量、创建时间、`updatedAt` 或 `pushed_at` 推断 Star 增量。只能取到最近若干 Stargazer 时，写成下限或样本，不冒充完整 30/90 天趋势。

## 搜索停止条件

满足以下条件即可停止扩展查询：

- 至少有 3 个经过 README 核验的强候选，或确认该领域没有这么多。
- 核心产品形态、工作流和技术能力查询均已覆盖。
- 新查询主要返回重复候选。
- 首选、模块参考和明显误匹配已能区分。