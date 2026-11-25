import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "skills" / "gh-research"
KIT_CHECKER = (
    REPO_ROOT / "skills" / "skill-smith" / "assets" / "dependency-kit" / "check_environment.py"
)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def skill_ops():
    return _load_module(
        "skill_ops_for_gh_research",
        REPO_ROOT / "skills" / "skill-smith" / "scripts" / "skill_ops.py",
    )


def test_skill_passes_skill_smith_validation(skill_ops):
    issues = skill_ops.validate_skill(SKILL_DIR)
    assert issues == [], "\n".join(f"{i.code} {i.path}:{i.line} {i.message}" for i in issues)


def test_frontmatter_matches_repo_intake_rules(skill_ops):
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    metadata, body, issues = skill_ops.parse_frontmatter(text)
    assert issues == []
    assert metadata["name"] == "gh-research"
    assert metadata["metadata"]["version"] == "0.1.0"
    assert set(metadata) <= {"name", "description", "metadata"}
    assert len(body.splitlines()) <= 500


def test_environment_checker_is_verbatim_kit_copy():
    """checker 必须原样复制：改动后要重新静态审查，所以这里锁死内容哈希。

    注意 ruff format 会波及本文件，格式化后需从 dependency-kit 重新复制。
    """
    assert hashlib.sha256(
        (SKILL_DIR / "scripts" / "check_environment.py").read_bytes()
    ).hexdigest() == (hashlib.sha256(KIT_CHECKER.read_bytes()).hexdigest())


def test_authored_scripts_pass_repo_lint_style():
    """自写脚本必须干净；checker 是受信任原样模板，不参与格式化。"""
    import subprocess

    authored = [
        str(SKILL_DIR / "scripts" / "gh_research.py"),
        str(SKILL_DIR / "scripts" / "render_report.py"),
    ]
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--check", *authored],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_dependency_manifest_is_valid_for_kit_checker():
    checker = _load_module("gh_research_checker", SKILL_DIR / "scripts" / "check_environment.py")
    manifest = json.loads((SKILL_DIR / "skill-dependencies.json").read_text(encoding="utf-8"))
    checker.validate_manifest(manifest)
    assert manifest["schema_version"] == "1"
    assert set(manifest["capabilities"]) == {"discover", "verify", "score", "report"}


def test_top_level_references_all_exist():
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    targets = {
        match.group(1)
        for match in __import__("re").finditer(r"@((?:references|scripts)/[A-Za-z0-9._/-]+)", text)
    }
    assert targets, "SKILL.md 必须引用 references 或 scripts"
    for target in targets:
        assert (SKILL_DIR / target).is_file(), target


def test_evals_cover_new_guarantees():
    data = json.loads((SKILL_DIR / "evals" / "evals.json").read_text(encoding="utf-8"))
    assert data["skill_name"] == "gh-research"
    evals = data["evals"]
    assert len(evals) >= 5
    blob = json.dumps(evals, ensure_ascii=False)
    assert "report.html" in blob
    assert "降级" in blob
    assert "澄清" in blob
    for item in evals:
        assert item["expectations"], item["id"]


def test_registered_in_collection():
    from ruamel.yaml import YAML

    yaml = YAML(typ="safe", pure=True)
    profile = yaml.load((REPO_ROOT / "profiles" / "global.yaml").read_text(encoding="utf-8"))
    entry = profile["assets"]["gh-research"]
    assert entry["kind"] == "skill"
    assert entry["description"].strip()


def test_skill_package_is_not_gitignored():
    """落盘目录 gh-research/ 的忽略规则必须锚定根目录，不能误伤 skills/gh-research/。"""
    import subprocess

    result = subprocess.run(
        ["git", "check-ignore", "-q", "skills/gh-research/SKILL.md"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0, "技能包被 .gitignore 误伤"


def test_existing_searching_skill_is_untouched():
    untouched = REPO_ROOT / "skills" / "searching-github-projects" / "SKILL.md"
    text = untouched.read_text(encoding="utf-8")
    assert "metadata:\n  version: 0.1.0" in text
    assert "gh-research" not in text
