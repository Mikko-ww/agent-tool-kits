#!/usr/bin/env python3
"""把候选库渲染成自包含 HTML 报告与 Markdown 副本。

HTML 内联全部样式，不引用任何外部字体、脚本或 CDN，离线可打开。
所有来自 GitHub 的文本一律转义后再写入。
"""

from __future__ import annotations

import html
import importlib.util
import sys
from pathlib import Path
from typing import Any

_SCRIPT = Path(__file__).resolve().with_name("gh_research.py")
_spec = importlib.util.spec_from_file_location("gh_research_core", _SCRIPT)
_core = importlib.util.module_from_spec(_spec)
sys.modules["gh_research_core"] = _core
_spec.loader.exec_module(_core)

composite = _core.composite
grade_of = _core.grade_of

DIMENSION_LABELS = (("similarity", "相似度"), ("fit", "适合度"), ("quality", "项目质量"))
GRADE_TITLES = {
    "A": "A 级：优先研究",
    "B": "B 级：强参考",
    "C": "C 级：模块级参考",
    "D": "D 级：通常排除",
    "": "未核验：证据不足，暂不分级",
}
GRADE_ORDER = ("A", "B", "C", "D", "")
POOL_EXPAND_LIMIT = 12
LEVEL_LEGEND = (
    ("E1", "代码级", "代码搜索或源码命中 file:line，可断言具备该能力"),
    ("E2", "文档级", "README 或官方文档明确描述，只能表述为声明具备"),
    ("E3", "元数据级", "Star、许可证、推送时间等，只支撑质量与约束"),
    ("E4", "未核验", "搜索摘要、记忆或推测，不得作为打分依据"),
)

CSS = """
:root {
  --bg: #fbfaf8; --surface: #ffffff; --ink: #1c1b19; --muted: #6c6862;
  --line: #e3ded6; --accent: #8a5a2b; --a: #2f6b4f; --b: #7a6320;
  --c: #6b6257; --d: #8c4a3f; --chip: #f2ede5;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #161513; --surface: #201e1b; --ink: #ece7e0; --muted: #a49c92;
    --line: #34302b; --accent: #d3a06a; --a: #7fc3a0; --b: #d9c274;
    --c: #b0a598; --d: #e09384; --chip: #2a2724;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 2.5rem 1.25rem 4rem; background: var(--bg); color: var(--ink);
  font-family: "Noto Sans SC", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", system-ui, sans-serif;
  line-height: 1.7; -webkit-font-smoothing: antialiased;
}
.wrap { max-width: 60rem; margin: 0 auto; }
header { border-bottom: 2px solid var(--ink); padding-bottom: 1.25rem; margin-bottom: 2rem; }
h1 { font-size: 1.75rem; line-height: 1.35; margin: 0 0 .5rem; letter-spacing: -.01em; }
.stamp { color: var(--muted); font-size: .85rem; }
h2 { font-size: 1.15rem; margin: 2.5rem 0 1rem; padding-left: .6rem; border-left: 3px solid var(--accent); }
h3 { font-size: 1rem; margin: 0 0 .5rem; }
.brief { background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 1.1rem 1.25rem; }
.brief dl { display: grid; grid-template-columns: 6.5rem 1fr; gap: .35rem 1rem; margin: 0; }
.brief dt { color: var(--muted); font-size: .85rem; }
.brief dd { margin: 0; }
.card {
  background: var(--surface); border: 1px solid var(--line); border-radius: 10px;
  padding: 1.1rem 1.25rem; margin-bottom: 1rem;
}
.card.a { border-left: 4px solid var(--a); }
.card.b { border-left: 4px solid var(--b); }
.card.c { border-left: 4px solid var(--c); }
.card.d { border-left: 4px solid var(--d); }
.card.none { border-left: 4px solid var(--line); }
.card a { color: var(--accent); text-decoration: none; font-weight: 600; }
.card a:hover { text-decoration: underline; }
.meta { color: var(--muted); font-size: .85rem; margin-bottom: .6rem; }
.desc { margin: .35rem 0 .8rem; }
.scores { display: flex; flex-wrap: wrap; gap: .5rem; margin-bottom: .7rem; }
.score { background: var(--chip); border-radius: 6px; padding: .3rem .6rem; font-size: .85rem; }
.score b { font-variant-numeric: tabular-nums; }
.score span { color: var(--muted); }
ul.ev { list-style: none; padding: 0; margin: .5rem 0; font-size: .85rem; }
ul.ev li { padding: .2rem 0; color: var(--muted); }
code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .82em; background: var(--chip); padding: .1rem .3rem; border-radius: 4px; }
.badge { display: inline-block; font-size: .7rem; letter-spacing: .04em; padding: .1rem .4rem; border-radius: 4px; background: var(--chip); color: var(--muted); margin-right: .4rem; }
.note { font-size: .85rem; color: var(--muted); border-top: 1px dashed var(--line); padding-top: .6rem; margin-top: .6rem; }
table { width: 100%; border-collapse: collapse; font-size: .85rem; margin-top: .5rem; }
th, td { text-align: left; padding: .5rem .6rem; border-bottom: 1px solid var(--line); vertical-align: top; }
th { color: var(--muted); font-weight: 600; }
td.num { font-variant-numeric: tabular-nums; }
details { background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: .6rem 1rem; }
summary { cursor: pointer; color: var(--muted); font-size: .88rem; padding: .2rem 0; }
summary:hover { color: var(--accent); }
details[open] summary { margin-bottom: .5rem; border-bottom: 1px solid var(--line); padding-bottom: .5rem; }
footer { margin-top: 3rem; padding-top: 1.25rem; border-top: 1px solid var(--line); color: var(--muted); font-size: .82rem; }
.empty { color: var(--muted); font-style: normal; }
"""


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def md_cell(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")


def format_stars(stars: Any) -> str:
    try:
        count = int(stars)
    except (TypeError, ValueError):
        return "—"
    if count >= 1000:
        return f"{count / 1000:.1f}k"
    return str(count)


def trend_text(record: dict[str, Any]) -> str:
    trend = record.get("star_trend")
    if not isinstance(trend, dict) or not trend.get("evidence"):
        return "未核验"
    delta = trend.get("delta")
    window = trend.get("window_days")
    source = trend.get("source") or "来源未注明"
    checked = trend.get("checked_at") or record.get("verified_at") or ""
    sign = "+" if isinstance(delta, (int, float)) and delta >= 0 else ""
    return f"近 {window} 天 {sign}{delta}（{source}，{checked}）"


def risk_flags(record: dict[str, Any]) -> list[str]:
    """不可隐瞒的硬风险；即使未评分也要在候选池里标出来。"""
    flags: list[str] = []
    if record.get("archived"):
        flags.append("已归档")
    if record.get("is_fork"):
        flags.append("Fork")
    if record.get("skip_reason"):
        flags.append(str(record["skip_reason"]))
    return flags


def group_records(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {grade: [] for grade in GRADE_ORDER}
    for record in records:
        value = composite(record.get("scores") or {})
        grade = grade_of(value) if value is not None else ""
        groups[grade].append(record)
    for grade, items in groups.items():
        items.sort(
            key=lambda item: (-(composite(item.get("scores") or {}) or -1), item.get("repo_id", ""))
        )
    return groups


def _evidence_by_id(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item["id"]): item
        for item in record.get("evidence") or []
        if isinstance(item, dict) and item.get("id")
    }


def _anchor_items(record: dict[str, Any]) -> list[dict[str, Any]]:
    index = _evidence_by_id(record)
    seen: set[str] = set()
    anchors: list[dict[str, Any]] = []
    for dimension, _label in DIMENSION_LABELS:
        for evidence_id in (record.get("score_evidence") or {}).get(dimension) or []:
            key = str(evidence_id)
            if key in index and key not in seen:
                seen.add(key)
                anchors.append(index[key])
    return anchors


def render_html(brief: dict[str, Any], records: list[dict[str, Any]], generated_at: str) -> str:
    groups = group_records(records)
    parts: list[str] = []
    parts.append("<!DOCTYPE html>")
    parts.append('<html lang="zh-CN"><head><meta charset="utf-8">')
    parts.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    parts.append(f"<title>{esc(brief.get('topic') or 'GitHub 项目调研')} · 取证报告</title>")
    parts.append(f"<style>{CSS}</style></head><body><div class='wrap'>")

    parts.append("<header>")
    parts.append(f"<h1>{esc(brief.get('topic') or 'GitHub 项目调研')}</h1>")
    parts.append(
        f"<div class='stamp'>候选 {len(records)} 个 · 生成于 {esc(generated_at)} · "
        f"slug <code>{esc(brief.get('slug') or '')}</code></div>"
    )
    parts.append("</header>")

    parts.append("<h2>搜索简报</h2><div class='brief'><dl>")
    for label, key in (
        ("目标", "goal"),
        ("必须具备", "must"),
        ("排除", "exclude"),
        ("用户约束", "constraints"),
        ("质量偏好", "quality_preference"),
    ):
        value = brief.get(key)
        if isinstance(value, (list, tuple)):
            value = "、".join(str(item) for item in value)
        parts.append(f"<dt>{esc(label)}</dt><dd>{esc(value or '—')}</dd>")
    parts.append("</dl></div>")

    for grade in GRADE_ORDER:
        items = groups[grade]
        if not items or grade == "":
            continue
        parts.append(f"<h2>{esc(GRADE_TITLES[grade])}</h2>")
        for record in items:
            css_grade = grade.lower() if grade else "none"
            parts.append(f"<div class='card {css_grade}'>")
            parts.append(
                f"<h3><a href='{esc(record.get('url') or '')}'>{esc(record.get('repo_id'))}</a>"
                f" — {esc(format_stars(record.get('stars')))} Stars</h3>"
            )
            meta = " · ".join(
                item
                for item in (
                    record.get("language") or "",
                    record.get("license") or "许可证未知",
                    f"取证 {record.get('verified_at')}" if record.get("verified_at") else "未取证",
                    "已归档" if record.get("archived") else "",
                    "Fork" if record.get("is_fork") else "",
                )
                if item
            )
            parts.append(f"<div class='meta'>{esc(meta)}</div>")
            parts.append(f"<div class='desc'>{esc(record.get('description') or '暂无简介')}</div>")

            parts.append("<div class='scores'>")
            scores = record.get("scores") or {}
            for dimension, label in DIMENSION_LABELS:
                value = scores.get(dimension)
                shown = f"{value}" if isinstance(value, (int, float)) else "未核验"
                parts.append(
                    f"<div class='score'><span>{esc(label)}</span> <b>{esc(shown)}</b></div>"
                )
            total = composite(scores)
            parts.append(
                f"<div class='score'><span>综合参考</span> <b>{esc(total if total is not None else '—')}</b></div>"
            )
            parts.append("</div>")

            parts.append(f"<div class='meta'>近期 Star 趋势：{esc(trend_text(record))}</div>")

            anchors = _anchor_items(record)
            if anchors:
                parts.append("<ul class='ev'>")
                for evidence in anchors:
                    locator = evidence.get("locator") or ""
                    locator_html = f" <code>{esc(locator)}</code>" if locator else ""
                    parts.append(
                        f"<li><span class='badge'>{esc(evidence.get('level'))}</span>"
                        f"{esc(evidence.get('detail'))}{locator_html}"
                        f" · {esc(evidence.get('source'))} · {esc(evidence.get('checked_at'))}</li>"
                    )
                parts.append("</ul>")
            else:
                parts.append("<div class='note'>没有可引用的证据，分数与分级待补。</div>")

            capabilities = record.get("capabilities") or {}
            if capabilities:
                index = _evidence_by_id(record)
                lines = []
                for name, capability in capabilities.items():
                    if not isinstance(capability, dict):
                        continue
                    levels = sorted(
                        {
                            str(index[str(eid)].get("level"))
                            for eid in capability.get("evidence") or []
                            if str(eid) in index
                        }
                    )
                    tag = "必须" if capability.get("required") else "加分"
                    lines.append(f"{name}（{tag}）：{'/'.join(levels) if levels else '未核验'}")
                if lines:
                    parts.append(f"<div class='note'>能力核验 — {esc('；'.join(lines))}</div>")

            if record.get("notes"):
                parts.append(f"<div class='note'>注意事项 — {esc(record['notes'])}</div>")
            parts.append("</div>")

    if not records:
        parts.append("<h2>候选</h2><p class='empty'>暂无候选。请先执行发现与取证。</p>")

    parts.append("<h2>对比表</h2><table><thead><tr>")
    for header in (
        "仓库",
        "Stars",
        "语言",
        "许可证",
        "简介",
        "相似度",
        "适合度",
        "项目质量",
        "分级",
    ):
        parts.append(f"<th>{esc(header)}</th>")
    parts.append("</tr></thead><tbody>")
    for grade in GRADE_ORDER:
        if grade == "":
            continue
        for record in groups[grade]:
            scores = record.get("scores") or {}
            cells = [
                record.get("repo_id"),
                format_stars(record.get("stars")),
                record.get("language") or "—",
                record.get("license") or "—",
                record.get("description") or "—",
            ]
            parts.append("<tr>")
            for cell in cells:
                parts.append(f"<td>{esc(cell)}</td>")
            for dimension, _label in DIMENSION_LABELS:
                value = scores.get(dimension)
                parts.append(
                    f"<td class='num'>{esc(value if isinstance(value, (int, float)) else '未核验')}</td>"
                )
            parts.append(f"<td>{esc(grade or '未核验')}</td></tr>")
    parts.append("</tbody></table>")

    unscored = groups[""]
    if unscored:
        parts.append(f"<h2>未核验候选（{len(unscored)}）</h2>")
        parts.append(
            "<div class='brief'><p>以下仓库进入了发现阶段但未取证、未评分，"
            "因此不参与分级与排序。它们是候选池的留痕，不是推荐结果；"
            "需要时先取证再评分。</p></div>"
        )
        expanded = " open" if len(unscored) <= POOL_EXPAND_LIMIT else ""
        parts.append(f"<details{expanded}>")
        parts.append(f"<summary>展开 {len(unscored)} 个未核验候选</summary>")
        parts.append(
            "<table><thead><tr><th>仓库</th><th>Stars</th><th>语言</th><th>风险</th><th>简介</th></tr></thead><tbody>"
        )
        for record in sorted(
            unscored, key=lambda item: (-int(item.get("stars") or 0), item.get("repo_id", ""))
        ):
            parts.append(
                f"<tr><td><a href='{esc(record.get('url') or '')}'>{esc(record.get('repo_id'))}</a></td>"
                f"<td class='num'>{esc(format_stars(record.get('stars')))}</td>"
                f"<td>{esc(record.get('language') or '—')}</td>"
                f"<td>{esc('、'.join(risk_flags(record)) or '—')}</td>"
                f"<td>{esc(record.get('description') or '—')}</td></tr>"
            )
        parts.append("</tbody></table>")
        parts.append("</details>")

    parts.append(
        "<h2>证据档位</h2><table><thead><tr><th>档位</th><th>名称</th><th>能支撑什么</th></tr></thead><tbody>"
    )
    for level, name, meaning in LEVEL_LEGEND:
        parts.append(f"<tr><td>{esc(level)}</td><td>{esc(name)}</td><td>{esc(meaning)}</td></tr>")
    parts.append("</tbody></table>")

    parts.append("<h2>数据说明</h2><div class='brief'>")
    parts.append(
        "<p>当前 Star 与仓库元数据来自 GitHub 接口，取证日期见每张卡片。"
        "Star 趋势只有取得可靠时间序列时才报告，否则标为未核验。"
        "三维分数由调研者基于所引证据近似判断，不是客观测量；综合参考值仅用于辅助排序。</p>"
    )
    parts.append("</div>")

    parts.append(
        f"<footer>gh-research · 生成于 {esc(generated_at)} · "
        "本页自包含，无外部资源依赖，可离线打开。</footer>"
    )
    parts.append("</div></body></html>")
    return "\n".join(parts)


def render_markdown(brief: dict[str, Any], records: list[dict[str, Any]], generated_at: str) -> str:
    groups = group_records(records)
    lines: list[str] = []
    lines.append(f"# {brief.get('topic') or 'GitHub 项目调研'}")
    lines.append("")
    lines.append(f"候选 {len(records)} 个 · 生成于 {generated_at}")
    lines.append("")
    lines.append("## 搜索简报")
    lines.append("")
    for label, key in (
        ("目标", "goal"),
        ("必须具备", "must"),
        ("排除", "exclude"),
        ("用户约束", "constraints"),
    ):
        value = brief.get(key)
        if isinstance(value, (list, tuple)):
            value = "、".join(str(item) for item in value)
        lines.append(f"- {label}：{value or '—'}")
    lines.append("")

    for grade in GRADE_ORDER:
        items = groups[grade]
        if not items or grade == "":
            continue
        lines.append(f"## {GRADE_TITLES[grade]}")
        lines.append("")
        for record in items:
            scores = record.get("scores") or {}
            total = composite(scores)
            lines.append(
                f"### [{record.get('repo_id')}]({record.get('url')}) — {format_stars(record.get('stars'))} Stars"
            )
            lines.append(f"- 简介：{record.get('description') or '暂无简介'}")
            lines.append(f"- 分级：{grade or '未核验'}")
            for dimension, label in DIMENSION_LABELS:
                value = scores.get(dimension)
                lines.append(
                    f"- {label}：{value}/100"
                    if isinstance(value, (int, float))
                    else f"- {label}：未核验"
                )
            lines.append(f"- 综合参考：{total if total is not None else '—'}")
            lines.append(f"- 近期 Star 趋势：{trend_text(record)}")
            for evidence in _anchor_items(record):
                locator = f" `{evidence['locator']}`" if evidence.get("locator") else ""
                lines.append(
                    f"- 证据 [{evidence.get('level')}]：{evidence.get('detail')}{locator}"
                    f"（{evidence.get('source')}，{evidence.get('checked_at')}）"
                )
            if record.get("notes"):
                lines.append(f"- 注意事项：{record['notes']}")
            lines.append("")

    if not records:
        lines.append("## 候选")
        lines.append("")
        lines.append("暂无候选。请先执行发现与取证。")
        lines.append("")

    lines.append("## 对比表")
    lines.append("")
    lines.append("| 仓库 | Stars | 语言 | 许可证 | 简介 | 相似度 | 适合度 | 项目质量 | 分级 |")
    lines.append("|---|---:|---|---|---|---:|---:|---:|---|")
    for grade in GRADE_ORDER:
        if grade == "":
            continue
        for record in groups[grade]:
            scores = record.get("scores") or {}
            values = [
                md_cell(scores.get(dim) if isinstance(scores.get(dim), (int, float)) else "未核验")
                for dim, _label in DIMENSION_LABELS
            ]
            lines.append(
                "| "
                + " | ".join(
                    [
                        md_cell(record.get("repo_id")),
                        md_cell(format_stars(record.get("stars"))),
                        md_cell(record.get("language") or "—"),
                        md_cell(record.get("license") or "—"),
                        md_cell(record.get("description") or "—"),
                        *values,
                        md_cell(grade or "未核验"),
                    ]
                )
                + " |"
            )
    lines.append("")
    unscored = groups[""]
    if unscored:
        lines.append(f"## 未核验候选（{len(unscored)}）")
        lines.append("")
        lines.append(
            "以下仓库进入了发现阶段但未取证、未评分，不参与分级与排序。"
            "它们是候选池的留痕，不是推荐结果；需要时先取证再评分。"
        )
        lines.append("")
        lines.append("| 仓库 | Stars | 语言 | 风险 | 简介 |")
        lines.append("|---|---:|---|---|---|")
        for record in sorted(
            unscored, key=lambda item: (-int(item.get("stars") or 0), item.get("repo_id", ""))
        ):
            lines.append(
                "| "
                + " | ".join(
                    [
                        md_cell(record.get("repo_id")),
                        md_cell(format_stars(record.get("stars"))),
                        md_cell(record.get("language") or "—"),
                        md_cell("、".join(risk_flags(record)) or "—"),
                        md_cell(record.get("description") or "—"),
                    ]
                )
                + " |"
            )
        lines.append("")
    lines.append("## 数据说明")
    lines.append("")
    lines.append(f"- 当前 Star 与元数据：GitHub 接口，取证日期见各候选，报告生成于 {generated_at}")
    lines.append("- Star 趋势：仅在取得可靠时间序列时报告，否则标为未核验")
    lines.append("- 分数：基于所引证据的近似判断，不是客观测量；综合参考值仅用于辅助排序")
    lines.append("")
    return "\n".join(lines)
