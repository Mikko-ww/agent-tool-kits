import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "skills" / "gh-research" / "scripts" / "gh_research.py"


@pytest.fixture(scope="module")
def gr():
    spec = importlib.util.spec_from_file_location("gh_research_scoring", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["gh_research_scoring"] = module
    spec.loader.exec_module(module)
    return module


def _record(gr, levels, similarity=90, capabilities=None):
    record = gr.new_record("owner/repo", "q")
    record["evidence"] = [
        gr.make_evidence(level, "test", f"证据 {level}", f"loc/{level}", "2026-11-24")
        for level in levels
    ]
    ids = [item["id"] for item in record["evidence"]]
    record["scores"] = {"similarity": similarity, "fit": 80, "quality": 70}
    record["score_evidence"] = {dim: ids for dim in ("similarity", "fit", "quality")}
    if capabilities is not None:
        record["capabilities"] = capabilities
    return record


def test_archived_repo_cannot_be_graded_a_or_b(gr):
    """已归档仓库不得进入优先研究名单，无论分数多高。"""
    record = _record(gr, ["E1"], similarity=95)
    record["archived"] = True
    problems = gr.validate_scores(record)
    assert any("归档" in item for item in problems)


def test_archived_repo_may_be_scored_as_counterexample(gr):
    record = _record(gr, ["E1"], similarity=60)
    record["scores"] = {"similarity": 60, "fit": 40, "quality": 30}
    record["archived"] = True
    assert gr.validate_scores(record) == []


def test_scores_without_evidence_are_rejected(gr):
    record = gr.new_record("owner/repo", "q")
    record["scores"] = {"similarity": 90, "fit": 80, "quality": 70}
    problems = gr.validate_scores(record)
    assert problems
    assert any("证据" in item for item in problems)


def test_e4_only_evidence_is_rejected(gr):
    record = _record(gr, ["E4"])
    assert gr.validate_scores(record)


def test_unknown_evidence_id_is_rejected(gr):
    record = _record(gr, ["E1"])
    record["score_evidence"]["fit"] = ["e1-doesnotexist"]
    problems = gr.validate_scores(record)
    assert any("不存在" in item for item in problems)


def test_out_of_range_score_is_rejected(gr):
    record = _record(gr, ["E1"])
    record["scores"]["similarity"] = 140
    assert gr.validate_scores(record)


def test_core_capability_with_only_e2_caps_similarity(gr):
    capabilities = {"节点画布": {"required": True, "evidence": []}}
    record = _record(gr, ["E2"], similarity=90, capabilities=capabilities)
    e2_id = record["evidence"][0]["id"]
    record["capabilities"]["节点画布"]["evidence"] = [e2_id]
    problems = gr.validate_scores(record)
    assert any("75" in item for item in problems)


def test_core_capability_with_only_e2_allows_capped_similarity(gr):
    capabilities = {"节点画布": {"required": True, "evidence": []}}
    record = _record(gr, ["E2"], similarity=75, capabilities=capabilities)
    record["capabilities"]["节点画布"]["evidence"] = [record["evidence"][0]["id"]]
    assert gr.validate_scores(record) == []


def test_core_capability_with_e1_allows_high_similarity(gr):
    capabilities = {"节点画布": {"required": True, "evidence": []}}
    record = _record(gr, ["E1"], similarity=95, capabilities=capabilities)
    record["capabilities"]["节点画布"]["evidence"] = [record["evidence"][0]["id"]]
    assert gr.validate_scores(record) == []


def test_required_capability_without_evidence_is_rejected(gr):
    record = _record(
        gr, ["E1"], similarity=90, capabilities={"节点画布": {"required": True, "evidence": []}}
    )
    assert gr.validate_scores(record)


def test_composite_requires_all_dimensions(gr):
    assert gr.composite({"similarity": 90, "fit": 80}) is None
    assert gr.composite({}) is None


def test_composite_uses_spec_weights(gr):
    value = gr.composite({"similarity": 100, "fit": 100, "quality": 100})
    assert value == pytest.approx(100.0)
    value = gr.composite({"similarity": 100, "fit": 0, "quality": 0})
    assert value == pytest.approx(45.0)


def test_grade_boundaries(gr):
    assert gr.grade_of(85) == "A"
    assert gr.grade_of(84.9) == "B"
    assert gr.grade_of(70) == "B"
    assert gr.grade_of(69.9) == "C"
    assert gr.grade_of(55) == "C"
    assert gr.grade_of(54.9) == "D"


def test_star_trend_without_timeseries_must_be_unverified(gr):
    record = _record(gr, ["E3"])
    record["star_trend"] = {"window_days": 30, "delta": 800, "source": "guess", "evidence": []}
    problems = gr.validate_scores(record)
    assert any("趋势" in item for item in problems)


def test_star_trend_with_evidence_passes(gr):
    record = _record(gr, ["E1", "E3"])
    e1_id = record["evidence"][0]["id"]
    record["star_trend"] = {
        "window_days": 30,
        "delta": 800,
        "source": "star-history",
        "evidence": [e1_id],
        "checked_at": "2026-11-24",
    }
    assert gr.validate_scores(record) == []


def test_partial_scores_are_allowed_but_not_composite(gr):
    record = _record(gr, ["E1"])
    record["scores"] = {"similarity": 90}
    record["score_evidence"] = {"similarity": [record["evidence"][0]["id"]]}
    assert gr.validate_scores(record) == []
    assert gr.composite(record["scores"]) is None
