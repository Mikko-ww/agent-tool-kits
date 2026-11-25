import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "skills" / "gh-research" / "scripts" / "gh_research.py"


@pytest.fixture(scope="module")
def gr():
    spec = importlib.util.spec_from_file_location("gh_research_store", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["gh_research_store"] = module
    spec.loader.exec_module(module)
    return module


def test_slugify_strips_unsafe_characters(gr):
    slug = gr.slugify("Agent Memory API / 通用记忆")
    assert slug
    assert "/" not in slug and " " not in slug
    assert slug == slug.lower()
    assert all(ord(ch) < 128 for ch in slug)


def test_slugify_rejects_traversal(gr):
    slug = gr.slugify("../../etc/passwd")
    assert ".." not in slug
    assert "/" not in slug
    assert not slug.startswith(".")


def test_slugify_falls_back_when_empty(gr):
    assert gr.slugify("通用记忆") == "research"
    assert gr.slugify("") == "research"


def test_slugify_truncates(gr):
    assert len(gr.slugify("a" * 200)) <= 60


def test_session_dir_stays_inside_root(gr, tmp_path):
    path = gr.session_dir("agent-memory", root=tmp_path)
    assert path == tmp_path / "gh-research" / "agent-memory"


def test_session_dir_rejects_escape(gr, tmp_path):
    with pytest.raises(ValueError):
        gr.session_dir("../escape", root=tmp_path)


def test_merge_record_keeps_human_judgement(gr):
    existing = gr.new_record("owner/repo", "q1")
    existing["scores"] = {"similarity": 90}
    existing["evidence"] = [{"id": "e1", "level": "E1"}]
    existing["notes"] = "人工备注"
    existing["grade"] = "A"
    existing["first_seen"] = "2026-11-01"
    fresh = gr.new_record("owner/repo", "q2")
    fresh["stars"] = 1234
    merged = gr.merge_record(existing, fresh)
    assert merged["scores"] == {"similarity": 90}
    assert merged["evidence"] == [{"id": "e1", "level": "E1"}]
    assert merged["notes"] == "人工备注"
    assert merged["grade"] == "A"
    assert merged["first_seen"] == "2026-11-01"
    assert merged["stars"] == 1234
    assert set(merged["source_queries"]) == {"q1", "q2"}


def test_new_record_uses_single_schema(gr):
    record = gr.new_record("Owner/Repo", "q")
    for alias in ("forks_count", "is_archived", "open_issues_count", "github_url"):
        assert alias not in record
    for field in (
        "repo_id",
        "url",
        "stars",
        "forks",
        "archived",
        "is_fork",
        "open_issues",
        "evidence",
        "scores",
    ):
        assert field in record


def test_load_candidates_dedupes_case_insensitively(gr, tmp_path):
    path = tmp_path / "candidates.jsonl"
    rows = [gr.new_record("Owner/Repo", "q1"), gr.new_record("owner/repo", "q2")]
    rows[1]["stars"] = 99
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )
    loaded = gr.load_candidates(path)
    assert len(loaded) == 1
    assert loaded["owner/repo"]["stars"] == 99
    assert set(loaded["owner/repo"]["source_queries"]) == {"q1", "q2"}


def test_save_candidates_is_atomic_and_readable(gr, tmp_path):
    path = tmp_path / "sub" / "candidates.jsonl"
    records = {"owner/repo": gr.new_record("owner/repo", "q")}
    gr.save_candidates(path, records)
    assert path.is_file()
    assert gr.load_candidates(path) == records
    assert list(path.parent.iterdir()) == [path]


def test_load_candidates_missing_file_returns_empty(gr, tmp_path):
    assert gr.load_candidates(tmp_path / "nope.jsonl") == {}


def test_load_candidates_skips_corrupt_lines(gr, tmp_path):
    path = tmp_path / "candidates.jsonl"
    good = gr.new_record("owner/repo", "q")
    path.write_text("{not json}\n" + json.dumps(good) + "\n\n", encoding="utf-8")
    assert list(gr.load_candidates(path)) == ["owner/repo"]
