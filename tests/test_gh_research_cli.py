import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "skills" / "gh-research" / "scripts" / "gh_research.py"


@pytest.fixture
def gr(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("gh_research_cli", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["gh_research_cli"] = module
    spec.loader.exec_module(module)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return module


def _run(gr, argv, capsys):
    code = gr.main(argv)
    captured = capsys.readouterr()
    payload = json.loads(captured.out) if captured.out.strip() else {}
    return code, payload


def _init(gr, capsys, slug="workflow-platform"):
    return _run(
        gr,
        ["init", "--slug", slug, "--topic", "自托管工作流平台", "--must", "节点画布,自定义节点"],
        capsys,
    )


def test_init_creates_session(gr, capsys, tmp_path):
    code, payload = _init(gr, capsys)
    assert code == 0
    session = tmp_path / "gh-research" / "workflow-platform"
    assert (session / "brief.md").is_file()
    assert (session / "candidates.jsonl").is_file()
    assert payload["session_dir"].endswith("gh-research/workflow-platform")


def test_init_is_idempotent(gr, capsys, tmp_path):
    _init(gr, capsys)
    path = tmp_path / "gh-research" / "workflow-platform" / "candidates.jsonl"
    records = gr.load_candidates(path)
    records["owner/a"] = gr.new_record("owner/a", "q")
    records["owner/a"]["notes"] = "保留我"
    gr.save_candidates(path, records)
    _init(gr, capsys)
    assert gr.load_candidates(path)["owner/a"]["notes"] == "保留我"


def test_search_from_json_writes_candidates(gr, capsys, tmp_path):
    _init(gr, capsys)
    incoming = tmp_path / "incoming.json"
    incoming.write_text(
        json.dumps([{"repo_id": "Owner/A", "description": "desc", "stars": 10}]), encoding="utf-8"
    )
    code, payload = _run(
        gr,
        [
            "search",
            "--slug",
            "workflow-platform",
            "--query",
            "q",
            "--intent",
            "产品形态",
            "--from-json",
            str(incoming),
        ],
        capsys,
    )
    assert code == 0
    records = gr.load_candidates(
        tmp_path / "gh-research" / "workflow-platform" / "candidates.jsonl"
    )
    assert "owner/a" in records
    assert payload["added"] == 1


def test_search_degrades_when_gh_missing(gr, capsys, monkeypatch):
    _init(gr, capsys)
    monkeypatch.setattr(gr.shutil, "which", lambda name: None)
    code, payload = _run(
        gr, ["search", "--slug", "workflow-platform", "--query", "q", "--intent", "形态"], capsys
    )
    assert code == 0
    assert payload["status"] == "degraded"


def test_score_rejects_unsupported_and_keeps_file(gr, capsys, tmp_path):
    _init(gr, capsys)
    path = tmp_path / "gh-research" / "workflow-platform" / "candidates.jsonl"
    records = {"owner/a": gr.new_record("owner/a", "q")}
    gr.save_candidates(path, records)
    before = path.read_text(encoding="utf-8")
    scores_file = tmp_path / "scores.json"
    scores_file.write_text(
        json.dumps(
            [{"repo_id": "owner/a", "scores": {"similarity": 90, "fit": 80, "quality": 70}}]
        ),
        encoding="utf-8",
    )
    code, payload = _run(
        gr, ["score", "--slug", "workflow-platform", "--from-json", str(scores_file)], capsys
    )
    assert code != 0
    assert payload["rejected"]
    assert path.read_text(encoding="utf-8") == before


def test_rescore_without_evidence_links_is_rejected(gr, capsys, tmp_path):
    """改分必须重新给证据；沿用旧链接等于让新分数无据可依。"""
    _init(gr, capsys)
    path = tmp_path / "gh-research" / "workflow-platform" / "candidates.jsonl"
    record = gr.new_record("owner/a", "q")
    evidence = gr.make_evidence("E1", "code-search", "节点注册", "src/a.ts:1", "2026-11-24")
    record["evidence"] = [evidence]
    record["scores"] = {"similarity": 80, "fit": 70, "quality": 60}
    record["score_evidence"] = {dim: [evidence["id"]] for dim in ("similarity", "fit", "quality")}
    gr.save_candidates(path, {"owner/a": record})
    before = path.read_text(encoding="utf-8")
    scores_file = tmp_path / "rescore.json"
    scores_file.write_text(
        json.dumps(
            [{"repo_id": "owner/a", "scores": {"similarity": 99, "fit": 95, "quality": 95}}]
        ),
        encoding="utf-8",
    )
    code, payload = _run(
        gr, ["score", "--slug", "workflow-platform", "--from-json", str(scores_file)], capsys
    )
    assert code != 0
    assert payload["rejected"]
    assert path.read_text(encoding="utf-8") == before


def test_score_accepts_evidence_backed_scores(gr, capsys, tmp_path):
    _init(gr, capsys)
    path = tmp_path / "gh-research" / "workflow-platform" / "candidates.jsonl"
    record = gr.new_record("owner/a", "q")
    evidence = gr.make_evidence("E1", "code-search", "节点注册", "src/a.ts:1", "2026-11-24")
    record["evidence"] = [evidence]
    record["capabilities"] = {"节点画布": {"required": True, "evidence": [evidence["id"]]}}
    gr.save_candidates(path, {"owner/a": record})
    scores_file = tmp_path / "scores.json"
    scores_file.write_text(
        json.dumps(
            [
                {
                    "repo_id": "owner/a",
                    "scores": {"similarity": 92, "fit": 88, "quality": 84},
                    "score_evidence": {
                        "similarity": [evidence["id"]],
                        "fit": [evidence["id"]],
                        "quality": [evidence["id"]],
                    },
                    "notes": "许可证宽松",
                }
            ]
        ),
        encoding="utf-8",
    )
    code, payload = _run(
        gr, ["score", "--slug", "workflow-platform", "--from-json", str(scores_file)], capsys
    )
    assert code == 0
    stored = gr.load_candidates(path)["owner/a"]
    assert stored["grade"] == "A"
    assert payload["accepted"] == 1


def test_report_writes_markdown_and_html(gr, capsys, tmp_path):
    _init(gr, capsys)
    path = tmp_path / "gh-research" / "workflow-platform" / "candidates.jsonl"
    record = gr.new_record("owner/a", "q")
    record["description"] = "a workflow platform"
    record["stars"] = 500
    gr.save_candidates(path, {"owner/a": record})
    code, payload = _run(gr, ["report", "--slug", "workflow-platform"], capsys)
    assert code == 0
    session = tmp_path / "gh-research" / "workflow-platform"
    assert (session / "report.md").is_file()
    assert (session / "report.html").is_file()
    assert payload["html"].endswith("report.html")
    assert payload["markdown"].endswith("report.md")
    assert "owner/a" in (session / "report.html").read_text(encoding="utf-8")


def test_second_search_keeps_human_scores(gr, capsys, tmp_path):
    _init(gr, capsys)
    path = tmp_path / "gh-research" / "workflow-platform" / "candidates.jsonl"
    record = gr.new_record("owner/a", "q1")
    evidence = gr.make_evidence("E1", "code-search", "x", "src/a.ts:1", "2026-11-24")
    record["evidence"] = [evidence]
    record["scores"] = {"similarity": 92, "fit": 88, "quality": 84}
    record["score_evidence"] = {dim: [evidence["id"]] for dim in ("similarity", "fit", "quality")}
    record["grade"] = "A"
    gr.save_candidates(path, {"owner/a": record})
    incoming = tmp_path / "again.json"
    incoming.write_text(json.dumps([{"repo_id": "owner/a", "stars": 999}]), encoding="utf-8")
    _run(
        gr,
        [
            "search",
            "--slug",
            "workflow-platform",
            "--query",
            "q2",
            "--intent",
            "形态",
            "--from-json",
            str(incoming),
        ],
        capsys,
    )
    stored = gr.load_candidates(path)["owner/a"]
    assert stored["stars"] == 999
    assert stored["scores"]["similarity"] == 92
    assert stored["grade"] == "A"
    assert set(stored["source_queries"]) == {"q1", "q2"}


def test_unknown_slug_command_fails_cleanly(gr, capsys):
    code, payload = _run(gr, ["report", "--slug", "never-created"], capsys)
    assert code != 0
    assert "error" in payload


def test_verify_degrades_without_gh(gr, capsys, monkeypatch):
    _init(gr, capsys)
    monkeypatch.setattr(gr.shutil, "which", lambda name: None)
    code, payload = _run(
        gr, ["verify", "--slug", "workflow-platform", "--repos", "owner/a"], capsys
    )
    assert code == 0
    assert payload["status"] == "degraded"


def test_readme_and_code_search_attach_evidence(gr, capsys, monkeypatch, tmp_path):
    _init(gr, capsys)
    path = tmp_path / "gh-research" / "workflow-platform" / "candidates.jsonl"
    gr.save_candidates(path, {"owner/a": gr.new_record("owner/a", "q")})
    monkeypatch.setattr(
        gr,
        "fetch_readme",
        lambda repo_id, max_chars=6000: {
            "repo_id": repo_id,
            "readme_text": "支持自定义节点",
            "readme_length": 8,
            "truncated": False,
        },
    )
    code, payload = _run(
        gr, ["readme", "--slug", "workflow-platform", "--repos", "owner/a"], capsys
    )
    assert code == 0
    stored = gr.load_candidates(path)["owner/a"]
    assert any(item["level"] == "E2" for item in stored["evidence"])

    monkeypatch.setattr(
        gr,
        "search_code",
        lambda query, limit=20: [
            {
                "repo_id": "owner/a",
                "path": "src/nodes.ts",
                "url": "https://github.com/owner/a/blob/main/src/nodes.ts",
            }
        ],
    )
    code, payload = _run(
        gr,
        [
            "code-search",
            "--slug",
            "workflow-platform",
            "--query",
            "registerNode",
            "--capability",
            "自定义节点",
        ],
        capsys,
    )
    assert code == 0
    assert payload["attached"] == 1
    stored = gr.load_candidates(path)["owner/a"]
    assert any(item["level"] == "E1" for item in stored["evidence"])
    assert "自定义节点" in stored["capabilities"]
