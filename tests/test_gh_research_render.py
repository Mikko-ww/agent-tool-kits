import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RENDER = REPO_ROOT / "skills" / "gh-research" / "scripts" / "render_report.py"
SCRIPT = REPO_ROOT / "skills" / "gh-research" / "scripts" / "gh_research.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gr():
    return _load("gh_research_for_render", SCRIPT)


@pytest.fixture(scope="module")
def render(gr):
    return _load("gh_research_render", RENDER)


@pytest.fixture
def brief():
    return {
        "topic": "自托管低代码工作流平台",
        "slug": "self-hosted-workflow",
        "must": ["节点画布", "自定义节点"],
        "exclude": ["纯 SDK"],
        "constraints": "MIT/Apache-2.0，TypeScript 优先",
        "goal": "内部团队技术选型",
    }


@pytest.fixture
def records(gr):
    good = gr.new_record("owner/good", "q1")
    good["description"] = "A self-hosted workflow platform"
    good["stars"] = 12400
    good["language"] = "TypeScript"
    good["license"] = "MIT"
    good["verified_at"] = "2026-11-24"
    evidence = gr.make_evidence(
        "E1", "code-search", "节点注册接口", "src/nodes/registry.ts:41", "2026-11-24"
    )
    good["evidence"] = [evidence]
    good["scores"] = {"similarity": 92, "fit": 88, "quality": 84}
    good["score_evidence"] = {dim: [evidence["id"]] for dim in ("similarity", "fit", "quality")}
    good["capabilities"] = {"节点画布": {"required": True, "evidence": [evidence["id"]]}}
    good["grade"] = "A"
    good["notes"] = "许可证宽松，可自托管"

    unscored = gr.new_record("owner/unscored", "q2")
    unscored["description"] = "尚未取证"
    return [good, unscored]


def test_html_escapes_hostile_description(render, brief, records):
    records[0]["description"] = '<script>alert("xss")</script><img src=x onerror=alert(1)>'
    html = render.render_html(brief, records, "2026-11-24T09:00:00Z")
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html
    assert "<img src=x" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html


def test_html_is_self_contained(render, brief, records):
    html = render.render_html(brief, records, "2026-11-24T09:00:00Z")
    assert "<link" not in html.lower()
    assert "<script src" not in html.lower()
    assert "@import" not in html
    assert "https://fonts." not in html
    assert "cdn." not in html


def test_html_supports_dark_mode(render, brief, records):
    html = render.render_html(brief, records, "2026-11-24T09:00:00Z")
    assert "prefers-color-scheme" in html


def test_html_shows_three_dimensions_and_evidence(render, brief, records):
    html = render.render_html(brief, records, "2026-11-24T09:00:00Z")
    for label in ("相似度", "适合度", "项目质量"):
        assert label in html
    assert "src/nodes/registry.ts:41" in html
    assert "92" in html and "88" in html and "84" in html


def test_html_puts_unscored_records_in_unverified_section(render, brief, records):
    html = render.render_html(brief, records, "2026-11-24T09:00:00Z")
    assert "未核验" in html
    assert html.index("owner/good") < html.index("owner/unscored")


def test_unscored_candidates_are_compact_rows_not_cards(render, brief, records, gr):
    """候选池可能上百个；未评分的不该撑出上百张卡片。"""
    pool = [records[0]] + [gr.new_record(f"owner/pool{i}", "q") for i in range(40)]
    html = render.render_html(brief, pool, "2026-11-24T09:00:00Z")
    assert html.count("<div class='card") == 1
    assert "未核验候选（40）" in html
    assert "owner/pool39" in html


def test_large_candidate_pool_stays_collapsed(render, brief, records, gr):
    """57 个未核验候选默认折叠，报告不该被候选池撑成几十屏。"""
    pool = [records[0]] + [gr.new_record(f"owner/pool{i}", "q") for i in range(57)]
    html = render.render_html(brief, pool, "2026-11-24T09:00:00Z")
    assert "<details>" in html
    assert "<summary>展开 57 个未核验候选</summary>" in html
    assert "<details open>" not in html


def test_small_candidate_pool_is_expanded(render, brief, records, gr):
    pool = [records[0]] + [gr.new_record(f"owner/pool{i}", "q") for i in range(3)]
    html = render.render_html(brief, pool, "2026-11-24T09:00:00Z")
    assert "<details open>" in html


def test_markdown_unscored_section_is_a_table(render, brief, records, gr):
    pool = [records[0]] + [gr.new_record(f"owner/pool{i}", "q") for i in range(5)]
    markdown = render.render_markdown(brief, pool, "2026-11-24T09:00:00Z")
    assert "## 未核验候选（5）" in markdown
    assert markdown.count("### [") == 1


def test_archived_repo_is_flagged_even_when_unscored(render, brief, records, gr):
    """不隐瞒归档：候选池里的已归档仓库也必须标出来。"""
    dead = gr.new_record("owner/dead", "q")
    dead["archived"] = True
    dead["stars"] = 50000
    html = render.render_html(brief, [records[0], dead], "2026-11-24T09:00:00Z")
    markdown = render.render_markdown(brief, [records[0], dead], "2026-11-24T09:00:00Z")
    row_html = html[html.index("owner/dead") : html.index("owner/dead") + 400]
    row_md = markdown[markdown.index("| owner/dead") : markdown.index("| owner/dead") + 200]
    assert "已归档" in row_html
    assert "已归档" in row_md


def test_html_links_to_repo(render, brief, records):
    html = render.render_html(brief, records, "2026-11-24T09:00:00Z")
    assert 'href="https://github.com/owner/good"' in html.replace("'", '"')


def test_html_includes_evidence_legend(render, brief, records):
    html = render.render_html(brief, records, "2026-11-24T09:00:00Z")
    for level in ("E1", "E2", "E3", "E4"):
        assert level in html


def test_markdown_escapes_pipes_in_table(render, brief, records):
    records[0]["description"] = "a | b | c"
    markdown = render.render_markdown(brief, records, "2026-11-24T09:00:00Z")
    assert "a \\| b \\| c" in markdown


def test_markdown_has_grade_sections_and_data_notes(render, brief, records):
    markdown = render.render_markdown(brief, records, "2026-11-24T09:00:00Z")
    assert "A 级" in markdown
    assert "数据说明" in markdown
    assert "2026-11-24" in markdown


def test_markdown_marks_unverified_trend(render, brief, records):
    markdown = render.render_markdown(brief, records, "2026-11-24T09:00:00Z")
    assert "近期 Star 趋势：未核验" in markdown


def test_empty_records_still_render(render, brief):
    html = render.render_html(brief, [], "2026-11-24T09:00:00Z")
    markdown = render.render_markdown(brief, [], "2026-11-24T09:00:00Z")
    assert "未核验" in html or "暂无" in html
    assert isinstance(markdown, str) and markdown.strip()


def test_records_sorted_by_composite_within_grade(render, brief, records, gr):
    lower = gr.new_record("owner/lower", "q3")
    lower["scores"] = {"similarity": 86, "fit": 85, "quality": 85}
    lower["grade"] = "A"
    lower["evidence"] = records[0]["evidence"]
    lower["score_evidence"] = records[0]["score_evidence"]
    html = render.render_html(brief, [lower, records[0]], "2026-11-24T09:00:00Z")
    assert html.index("owner/good") < html.index("owner/lower")
