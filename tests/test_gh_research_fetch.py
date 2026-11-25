import base64
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "skills" / "gh-research" / "scripts" / "gh_research.py"


@pytest.fixture(scope="module")
def gr():
    spec = importlib.util.spec_from_file_location("gh_research_fetch", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["gh_research_fetch"] = module
    spec.loader.exec_module(module)
    return module


def _completed(stdout="", stderr="", code=0):
    return subprocess.CompletedProcess(args=["gh"], returncode=code, stdout=stdout, stderr=stderr)


def test_missing_gh_degrades_without_exiting(gr, monkeypatch):
    monkeypatch.setattr(gr.shutil, "which", lambda name: None)
    repos, status = gr.search_repos("agent memory", limit=10, sort="stars")
    assert repos == []
    assert status == "degraded"


def test_rate_limit_degrades(gr, monkeypatch):
    monkeypatch.setattr(gr.shutil, "which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr(gr.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        gr.subprocess, "run", lambda *a, **k: _completed(stderr="API rate limit exceeded", code=1)
    )
    repos, status = gr.search_repos("agent memory", limit=10, sort="stars")
    assert repos == []
    assert status == "degraded"


def test_timeout_degrades(gr, monkeypatch):
    monkeypatch.setattr(gr.shutil, "which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr(gr.time, "sleep", lambda seconds: None)

    def raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="gh", timeout=30)

    monkeypatch.setattr(gr.subprocess, "run", raise_timeout)
    ok, detail = gr.run_gh(["api", "/search/repositories"])
    assert ok is False
    assert "timeout" in detail.lower() or "超时" in detail


def test_search_maps_to_single_schema(gr, monkeypatch):
    payload = {
        "items": [
            {
                "full_name": "Owner/Repo",
                "html_url": "https://github.com/Owner/Repo",
                "description": "a memory api",
                "stargazers_count": 1200,
                "forks_count": 30,
                "language": "Python",
                "license": {"spdx_id": "MIT"},
                "topics": ["memory"],
                "archived": False,
                "fork": False,
                "created_at": "2024-01-01T00:00:00Z",
                "pushed_at": "2026-11-01T00:00:00Z",
                "open_issues_count": 5,
            }
        ]
    }
    monkeypatch.setattr(gr.shutil, "which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr(gr.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        gr.subprocess, "run", lambda *a, **k: _completed(stdout=json.dumps(payload))
    )
    repos, status = gr.search_repos("memory", limit=1, sort="stars")
    assert status == "ok"
    record = repos[0]
    assert record["repo_id"] == "owner/repo"
    assert record["stars"] == 1200
    assert record["forks"] == 30
    assert record["license"] == "MIT"
    assert record["is_fork"] is False
    assert record["open_issues"] == 5
    for alias in ("forks_count", "is_archived", "open_issues_count", "github_url"):
        assert alias not in record


def test_readme_handles_invalid_utf8_and_marks_truncation(gr, monkeypatch):
    raw = ("x" * 100).encode("utf-8") + b"\xff\xfe"
    payload = {"content": base64.b64encode(raw).decode("ascii")}
    monkeypatch.setattr(gr.shutil, "which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr(gr.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        gr.subprocess, "run", lambda *a, **k: _completed(stdout=json.dumps(payload))
    )
    result = gr.fetch_readme("owner/repo", max_chars=50)
    assert result is not None
    assert result["readme_length"] > 50
    assert result["truncated"] is True
    assert len(result["readme_text"]) == 50


def test_readme_missing_returns_none(gr, monkeypatch):
    monkeypatch.setattr(gr.shutil, "which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr(gr.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        gr.subprocess, "run", lambda *a, **k: _completed(stderr="404 Not Found", code=1)
    )
    assert gr.fetch_readme("owner/repo", max_chars=100) is None


def test_code_search_returns_locators(gr, monkeypatch):
    payload = {
        "items": [
            {
                "path": "src/nodes/registry.ts",
                "html_url": "https://github.com/Owner/Repo/blob/main/src/nodes/registry.ts",
                "repository": {"full_name": "Owner/Repo"},
            }
        ]
    }
    monkeypatch.setattr(gr.shutil, "which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr(gr.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        gr.subprocess, "run", lambda *a, **k: _completed(stdout=json.dumps(payload))
    )
    hits = gr.search_code("registerNode", limit=5)
    assert hits[0]["repo_id"] == "owner/repo"
    assert hits[0]["path"] == "src/nodes/registry.ts"
    assert hits[0]["url"].startswith("https://github.com/")


def test_evidence_records_level_and_timestamp(gr):
    evidence = gr.make_evidence(
        "E1", "code-search", "命中节点注册接口", "src/a.ts:41", "2026-11-24"
    )
    assert evidence["level"] == "E1"
    assert evidence["locator"] == "src/a.ts:41"
    assert evidence["checked_at"] == "2026-11-24"
    assert evidence["id"]


def test_evidence_rejects_unknown_level(gr):
    with pytest.raises(ValueError):
        gr.make_evidence("E9", "code-search", "x", "", "2026-11-24")


def test_fetch_metadata_degrades_per_repo(gr, monkeypatch):
    monkeypatch.setattr(gr.shutil, "which", lambda name: None)
    records, status = gr.fetch_metadata(["owner/a", "owner/b"])
    assert status == "degraded"
    assert records == {}
