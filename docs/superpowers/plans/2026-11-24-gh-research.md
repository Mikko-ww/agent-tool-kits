# gh-research 技能实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 新建 `skills/gh-research/` 技能，继承 `searching-github-projects` 的判断力规范，补上取证脚本、四档证据分级、`./gh-research/{slug}/` 落盘证据库和自包含 HTML 报告。

**Architecture:** 单入口多子命令脚本 `gh_research.py` 承担取证与渲染；判断（消歧、评分、分级）仍由模型完成，脚本只校验「分数是否有证据支撑」。七步流程不新增阶段，取证垫在第 4–6 步底下。

**Tech Stack:** Python ≥ 3.10 标准库；`gh` CLI 取数（可降级）；pytest；ruff 0.17.5。

**Spec:** [docs/superpowers/specs/2026-11-24-gh-research-design.md](../specs/2026-11-24-gh-research-design.md)

## Global Constraints

- 新资产版本 `0.1.0`；frontmatter 只留 `name`、`description`、`metadata.version`；目录名等于 `name`。
- 脚本仅 Python 标准库，Python ≥ 3.10，跨 macOS/Linux/Windows。
- 不写用户绝对路径（`/Users/`、`/home/`、`/tmp/`、`C:\Users\` 均被 validate 拒绝）；技能目录用 `Path(__file__).resolve().parents[1]` 自解析。
- 顶层 SKILL.md 正文 ≤ 500 行；`@references/...` 只能出现在顶层 SKILL.md。
- 文案中文优先，机器值（字段名、状态、证据档位 id）英文。
- 落盘根目录固定 `./gh-research/{slug}/`，相对当前工作目录。
- 证据档位：`E1` 代码级 / `E2` 文档级 / `E3` 元数据级 / `E4` 未核验。
- 综合参考值权重：相似度 45% + 适合度 35% + 项目质量 20%。
- 核心能力仅有 E2 时相似度封顶 75。
- 不改 `skills/searching-github-projects/` 任何文件；不改 `temp_ref/`；不发布、不打 tag、不 commit（用户未要求）。
- 验证命令统一用 `.venv/bin/python`（沙箱下 `uv run` 可能因缓存权限失败）。

## Review Focus

1. **`gh` 未安装/未认证/限流**：脚本必须返回降级状态并继续，不得 `exit(1)` 中断整条流程，也不得用记忆数据补齐指标。
2. **候选库被外部数据污染**：仓库描述、README 含 HTML 标签、`<script>`、超长文本、非 UTF-8 字节时，HTML 报告必须转义且不破坏结构。
3. **分数无证据支撑**：只给数字不给证据 id、或引用 E4 证据时，`score` 必须拒绝写入并说明原因。
4. **slug 冲突与路径穿越**：产品指纹含 `../`、绝对路径、中文、空格时，落盘目录必须落在 `./gh-research/` 内。
5. **重复运行**：同一 slug 二次运行必须合并去重而非覆盖已有证据与人工分数。

---

### Task 1: 技能骨架与依赖声明

**Files:**
- Create: `skills/gh-research/SKILL.md`
- Create: `skills/gh-research/skill-dependencies.json`
- Create: `skills/gh-research/scripts/check_environment.py`（从 `skills/skill-smith/assets/dependency-kit/check_environment.py` 原样复制）
- Create: `skills/gh-research/references/setup-guide.md`
- Test: `tests/test_gh_research_skill.py`

**Interfaces:**
- Produces: 技能目录 `skills/gh-research/`；capabilities 列表 `["discover", "verify", "score", "report"]`；dependency id `gh-cli`（type `cli`, required false, auth_type `browser-login`）、`python-runtime`（type `runtime`, required true, auth_type `none`）。

- [ ] **Step 1: 写失败测试**

`tests/test_gh_research_skill.py`：调用 `skills/skill-smith/scripts/skill_ops.py` 的 `validate_skill(Path)`，断言 `skills/gh-research` 返回空 issues 列表；断言 frontmatter `name == "gh-research"`、`metadata.version == "0.1.0"`；断言 `check_environment.py` 内容与 dependency-kit 源文件字节一致。

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_gh_research_skill.py -q`
Expected: FAIL（目录不存在）

- [ ] **Step 3: 建目录与依赖清单**

复制 checker（`shutil.copyfile`，不修改）。写 `skill-dependencies.json`：`schema_version: "1"`，四个 capabilities，两个 dependency，每个 capability 都要有对应的 `functional_degradations` 条目（8 个字段全填，`evidence_label` 取 `已验证|部分验证|推断|未验证` 之一）。`gh-cli` 的 setup 用官方地址 `https://cli.github.com/`、`https://cli.github.com/manual/`，`verified_at: "2026-11-24"`，`applies_to_version: "2.102.0"`；含 `login_url`、`console_path`、`credential_storage`、`rotate_or_revoke`（auth_type 非 none 时必填）。

- [ ] **Step 4: 写 SKILL.md 与 setup-guide.md**

SKILL.md 七步流程继承 `searching-github-projects` 的判断规范（实体消歧、赛道分叉只问一个问题、三维分开打分、A/B/C/D 分级、质量护栏），在第 4–6 步挂脚本命令，第 7 步末尾输出 HTML 路径。用 `<skill-dir>` 表示技能目录。正文 ≤ 500 行。

- [ ] **Step 5: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_gh_research_skill.py -q`
Expected: PASS

---

### Task 2: 候选库与 slug（`gh_research.py` 基础层）

**Files:**
- Create: `skills/gh-research/scripts/gh_research.py`
- Test: `tests/test_gh_research_store.py`

**Interfaces:**
- Produces:
  - `slugify(fingerprint: str) -> str` — 小写、非字母数字转 `-`、去重复与首尾 `-`、截断 60 字符；空结果回退 `"research"`；拒绝 `.` 开头。
  - `session_dir(slug: str, root: Path | None = None) -> Path` — 返回 `root/gh-research/<slug>`，`root` 默认 `Path.cwd()`；校验解析后仍在 `root/gh-research` 内，否则抛 `ValueError`。
  - `load_candidates(path: Path) -> dict[str, dict]` — 按 `repo_id` 小写归一为键。
  - `save_candidates(path: Path, records: dict[str, dict]) -> None` — 原子写（临时文件 + `os.replace`）。
  - `merge_record(existing: dict, fresh: dict) -> dict` — 新值覆盖，但保留 `scores`、`evidence`、`notes`、`grade`、`first_seen`。
  - `new_record(repo_id: str, source_query: str) -> dict` — 统一 schema，字段名唯一（`repo_id/url/description/stars/forks/language/license/topics/archived/is_fork/created_at/pushed_at/open_issues/source_queries/evidence/scores/grade/notes/verified_at`）。

- [ ] **Step 1: 写失败测试**

覆盖：`slugify("Agent Memory API / 通用记忆")` 返回不含 `/`、空格、中文且非空的 slug；`slugify("../../etc")` 结果不含 `..`；`session_dir` 对穿越 slug 抛 `ValueError`；`merge_record` 保留人工 `scores`；`load_candidates` 对大小写不同的同一 `repo_id` 去重；`save_candidates` 后文件可解析且无残留临时文件。

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_gh_research_store.py -q`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现基础层**

用 `importlib` 从测试加载脚本（脚本在技能目录内，非包）。

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_gh_research_store.py -q`
Expected: PASS

---

### Task 3: 取证与降级（`gh` 适配层）

**Files:**
- Modify: `skills/gh-research/scripts/gh_research.py`
- Test: `tests/test_gh_research_fetch.py`

**Interfaces:**
- Consumes: Task 2 的 `new_record` / `merge_record` / `load_candidates` / `save_candidates`
- Produces:
  - `gh_available() -> bool`
  - `run_gh(args: list[str], timeout: int = 30) -> tuple[bool, str]` — 返回 `(ok, stdout)`；任何失败（未安装、非零退出、超时、非 JSON）都返回 `(False, reason)`，**不抛异常、不 exit**。
  - `search_repos(query: str, limit: int, sort: str) -> tuple[list[dict], str]` — 第二项为状态 `"ok"|"degraded"`。
  - `fetch_metadata(repo_ids: list[str]) -> tuple[dict[str, dict], str]`
  - `fetch_readme(repo_id: str, max_chars: int) -> dict | None` — 含 `readme_text`、`readme_length`、`truncated`。
  - `search_code(query: str, limit: int) -> list[dict]` — 每项含 `repo_id`、`path`、`url`。
  - `make_evidence(level: str, source: str, detail: str, locator: str, checked_at: str) -> dict`

- [ ] **Step 1: 写失败测试**

用 `monkeypatch` 替换 `subprocess.run` 与 `shutil.which`：`gh` 不存在时 `search_repos` 返回 `([], "degraded")` 且进程不退出；非零退出含 `rate limit` 时返回 `"degraded"`；超时时返回 `"degraded"`；正常 JSON 时映射出统一字段名（断言不出现 `forks_count`/`is_archived` 等上游别名）；`fetch_readme` 对含非 UTF-8 字节的 base64 不崩溃并标记 `truncated`。

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_gh_research_fetch.py -q`
Expected: FAIL

- [ ] **Step 3: 实现适配层**

所有 `gh` 调用经 `run_gh`；限流时 sleep 后有限重试（≤2 次）再降级。

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_gh_research_fetch.py -q`
Expected: PASS

---

### Task 4: 证据校验与评分闸门

**Files:**
- Modify: `skills/gh-research/scripts/gh_research.py`
- Test: `tests/test_gh_research_scoring.py`

**Interfaces:**
- Consumes: Task 2/3
- Produces:
  - `EVIDENCE_LEVELS = ("E1", "E2", "E3", "E4")`
  - `validate_scores(record: dict) -> list[str]` — 返回违规说明列表，空表示通过。规则：三维分数在 0–100；每维至少一条 E1–E3 证据 id；引用的证据 id 必须存在；核心能力仅 E2 时相似度 ≤ 75；Star 趋势无 E1/E2 时间序列证据时必须为 `None` 且 notes 标未核验。
  - `composite(scores: dict) -> float | None` — `0.45*similarity + 0.35*fit + 0.20*quality`，任一维缺失返回 `None`。
  - `grade_of(composite_value: float) -> str` — `A>=85, B>=70, C>=55, D<55`。

- [ ] **Step 1: 写失败测试**

覆盖：无证据的分数被拒；引用 E4 被拒；引用不存在的 id 被拒；核心能力仅 E2 且相似度 90 被拒、75 通过；缺维度时 `composite` 返回 `None`；分级边界 85/70/55 各自落在 A/B/C。

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_gh_research_scoring.py -q`
Expected: FAIL

- [ ] **Step 3: 实现校验与计算**

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_gh_research_scoring.py -q`
Expected: PASS

---

### Task 5: HTML 与 Markdown 报告渲染

**Files:**
- Create: `skills/gh-research/scripts/render_report.py`
- Test: `tests/test_gh_research_render.py`

**Interfaces:**
- Consumes: Task 4 的 `composite` / `grade_of`
- Produces:
  - `render_html(brief: dict, records: list[dict], generated_at: str) -> str`
  - `render_markdown(brief: dict, records: list[dict], generated_at: str) -> str`
  - 两者按分级分组、组内按 composite 降序；缺分数的记录进「未核验」区。

- [ ] **Step 1: 写失败测试**

覆盖：描述含 `<script>alert(1)</script>` 时输出中不出现裸 `<script>`（已转义）；含 `|` 的 Markdown 表格不破裂；输出不含 `http://`/`https://` 的外部资源引用（自包含，仓库链接除外——断言无 `<link`、无 `<script src`、无 `@import`）；含 `prefers-color-scheme`；三维分数与证据锚点均出现；中文标题出现；无分数记录落入未核验区。

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_gh_research_render.py -q`
Expected: FAIL

- [ ] **Step 3: 实现渲染**

用 `html.escape` 转义所有外部文本；内联 CSS；无 JS 依赖。

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_gh_research_render.py -q`
Expected: PASS

---

### Task 6: CLI 子命令串联

**Files:**
- Modify: `skills/gh-research/scripts/gh_research.py`
- Test: `tests/test_gh_research_cli.py`

**Interfaces:**
- Consumes: Task 2–5 全部
- Produces: `main(argv: list[str] | None = None) -> int`，子命令 `init` / `search` / `verify` / `readme` / `code-search` / `score` / `report`；全部输出 JSON 到 stdout，状态到 stderr；降级时退出码 0 且 JSON 含 `"status": "degraded"`。

- [ ] **Step 1: 写失败测试**

在 `tmp_path` 下用假 HOME 跑：`init` 建目录与 brief；`search`（monkeypatch 掉 `run_gh`）写入候选；`score` 对无证据分数返回非零并保留原文件；`report` 产出 `report.md` 与 `report.html` 且 stdout JSON 含 html 路径；二次 `search` 同 slug 不丢人工分数。

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_gh_research_cli.py -q`
Expected: FAIL

- [ ] **Step 3: 实现 CLI**

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_gh_research_cli.py -q`
Expected: PASS

---

### Task 7: references、evals 与入库注册

**Files:**
- Create: `skills/gh-research/references/search-strategy.md`
- Create: `skills/gh-research/references/evidence-and-scoring.md`
- Create: `skills/gh-research/references/report-format.md`
- Create: `skills/gh-research/evals/evals.json`
- Modify: `profiles/global.yaml`
- Test: `tests/test_gh_research_skill.py`（扩展）

**Interfaces:**
- Consumes: Task 1–6

- [ ] **Step 1: 写失败测试**

断言 SKILL.md 中所有 `@references/...` 目标存在；evals JSON 可解析且 ≥5 条，其中至少一条考降级、一条考 HTML 路径、一条考赛道澄清；`profiles/global.yaml` 含 `gh-research` 且 `kind: skill`。

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_gh_research_skill.py -q`
Expected: FAIL

- [ ] **Step 3: 写 references / evals，注册 collection**

`profiles/global.yaml` 新增 `gh-research: {kind: skill, description: 取证式 GitHub 项目调研，产出证据链与 HTML 报告}`。

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_gh_research_skill.py -q`
Expected: PASS

---

### Task 8: 全量验证与真实端到端测试

**Files:**
- Modify: 视问题而定

- [ ] **Step 1: 静态校验**

Run: `.venv/bin/python skills/skill-smith/scripts/skill_ops.py validate skills/gh-research`
Expected: `"ok": true`

Run: `.venv/bin/python skills/skill-smith/scripts/skill_ops.py preflight skills/gh-research`
Expected: 无 blocked

- [ ] **Step 2: 打包校验**

Run: `.venv/bin/python scripts/package_asset.py skill gh-research 0.1.0 . dist`
Expected: 产出 `dist/gh-research-0.1.0.tar.gz` 与 `.sha256`

- [ ] **Step 3: 仓库全量测试与 lint**

Run: `.venv/bin/python -m pytest -q`
Expected: 全部 PASS（原 134 条 + 新增）

Run: `.venv/bin/python -m ruff format skills/gh-research/scripts tests`
Run: `.venv/bin/python -m ruff check src tests scripts skills/gh-research/scripts`
Expected: All checks passed

- [ ] **Step 4: 真实端到端**

用真实 `gh`（已认证）跑一个真实需求，全程不 mock：`init` → `search`（≥3 组查询）→ `verify` → `readme` → `code-search` → `score` → `report`。

- [ ] **Step 5: 检查真实产物**

打开 `./gh-research/{slug}/report.html` 与 `report.md`，逐项核对：链接可点、Star 为实时值且带取证日期、三维分数各有证据锚点、趋势未核验时明确标注、分级正确、结尾有 HTML 路径。用浏览器实际渲染 HTML 检查排版。

- [ ] **Step 6: 有问题则修复并重测**

任何不符项回到对应 Task 修复，重跑 Step 1–5，直到真实产物全部符合。