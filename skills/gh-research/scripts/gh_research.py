#!/usr/bin/env python3
"""取证式 GitHub 项目调研：候选库、取证、评分闸门与报告渲染。

仅使用 Python 标准库。所有 gh 调用失败时返回降级状态，不中断流程、不编造数据。
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SKILL_DIR = Path(__file__).resolve().parents[1]
SESSION_ROOT_NAME = "gh-research"
SLUG_MAX = 60
SLUG_FALLBACK = "research"

EVIDENCE_LEVELS = ("E1", "E2", "E3", "E4")
SCORE_DIMENSIONS = ("similarity", "fit", "quality")
WEIGHTS = {"similarity": 0.45, "fit": 0.35, "quality": 0.20}
E2_ONLY_SIMILARITY_CAP = 75
ARCHIVED_COMPOSITE_CAP = 70

PRESERVED_ON_MERGE = ("scores", "evidence", "notes", "grade", "first_seen", "capabilities")


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


# -- slug 与落盘目录 ----------------------------------------------------------


def slugify(fingerprint: str) -> str:
    """把产品指纹转成安全的目录名；无法转换时回退到固定值。"""
    normalized = unicodedata.normalize("NFKD", fingerprint or "")
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_only).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)[:SLUG_MAX].strip("-")
    return slug or SLUG_FALLBACK


def session_dir(slug: str, root: Path | None = None) -> Path:
    """返回 root/gh-research/<slug>，拒绝任何逃出该根目录的 slug。"""
    base = (root or Path.cwd()).resolve()
    container = (base / SESSION_ROOT_NAME).resolve()
    if not isinstance(slug, str) or not slug.strip():
        raise ValueError("slug 不能为空")
    if slug != slug.strip() or "/" in slug or "\\" in slug or ".." in slug or slug.startswith("."):
        raise ValueError(f"slug 含非法路径成分：{slug!r}")
    safe = slugify(slug)
    target = (container / safe).resolve()
    if target.parent != container:
        raise ValueError(f"slug 逃出落盘根目录：{slug!r}")
    return target


# -- 候选库 -------------------------------------------------------------------


def new_record(repo_id: str, source_query: str) -> dict[str, Any]:
    """统一的候选记录 schema。字段名唯一，不使用上游别名。"""
    normalized = repo_id.strip().lower()
    return {
        "repo_id": normalized,
        "url": f"https://github.com/{repo_id.strip()}",
        "description": "",
        "stars": 0,
        "forks": 0,
        "language": "",
        "license": "",
        "topics": [],
        "archived": False,
        "is_fork": False,
        "created_at": "",
        "pushed_at": "",
        "updated_at": "",
        "open_issues": 0,
        "homepage": "",
        "default_branch": "",
        "readme_text": "",
        "readme_length": 0,
        "readme_truncated": False,
        "source_queries": [source_query] if source_query else [],
        "evidence": [],
        "capabilities": {},
        "scores": {},
        "score_evidence": {},
        "star_trend": None,
        "grade": "",
        "notes": "",
        "verified_at": "",
        "first_seen": today(),
        "skip_reason": "",
    }


def merge_record(existing: dict[str, Any], fresh: dict[str, Any]) -> dict[str, Any]:
    """新数据覆盖旧数据，但保留人工判断与已有证据。"""
    merged = dict(existing)
    merged.update(fresh)
    for field in PRESERVED_ON_MERGE:
        if existing.get(field):
            merged[field] = existing[field]
    queries = list(existing.get("source_queries") or [])
    for query in fresh.get("source_queries") or []:
        if query not in queries:
            queries.append(query)
    merged["source_queries"] = queries
    merged["first_seen"] = existing.get("first_seen") or fresh.get("first_seen") or today()
    return merged


def load_candidates(path: Path) -> dict[str, dict[str, Any]]:
    """按小写 repo_id 归并读取；损坏行跳过而不是整体失败。"""
    records: dict[str, dict[str, Any]] = {}
    if not path.is_file():
        return records
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        repo_id = str(row.get("repo_id", "")).strip().lower()
        if not repo_id:
            continue
        row["repo_id"] = repo_id
        records[repo_id] = merge_record(records[repo_id], row) if repo_id in records else row
    return records


def save_candidates(path: Path, records: dict[str, dict[str, Any]]) -> None:
    """原子写入，避免中断时留下半截候选库。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    payload = "".join(
        json.dumps(records[key], ensure_ascii=False, sort_keys=True) + "\n"
        for key in sorted(records)
    )
    try:
        temporary.write_text(payload, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def candidates_path(slug: str, root: Path | None = None) -> Path:
    return session_dir(slug, root) / "candidates.jsonl"


# -- gh 适配层：任何失败都降级，不 exit ---------------------------------------

GH_TIMEOUT = 30
GH_RETRIES = 2
PAGE_SIZE = 30


def gh_available() -> bool:
    return shutil.which("gh") is not None


def run_gh(args: list[str], timeout: int = GH_TIMEOUT) -> tuple[bool, str]:
    """调用 gh；未安装、非零退出、超时或非法 JSON 都返回 (False, 原因)。"""
    if not gh_available():
        return False, "gh CLI 未安装或不在 PATH"
    try:
        completed = subprocess.run(
            ["gh", *args], capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired:
        return False, f"gh 调用超时（timeout {timeout}s）"
    except OSError as exc:
        return False, f"gh 调用失败：{exc}"
    if completed.returncode != 0:
        detail = (completed.stderr or "").strip()
        lowered = detail.lower()
        if "rate limit" in lowered or "403" in lowered or "429" in lowered:
            return False, f"GitHub 限流或权限不足：{detail[:200]}"
        return False, f"gh 退出码 {completed.returncode}：{detail[:200]}"
    return True, completed.stdout


def _gh_json(endpoint: str, params: dict[str, str] | None = None) -> tuple[Any | None, str]:
    target = endpoint
    if params:
        target = f"{endpoint}?{urllib.parse.urlencode(params)}"
    for attempt in range(GH_RETRIES + 1):
        ok, payload = run_gh(["api", target])
        if ok:
            try:
                return json.loads(payload), ""
            except json.JSONDecodeError as exc:
                return None, f"gh 返回非法 JSON：{exc}"
        if "限流" in payload and attempt < GH_RETRIES:
            time.sleep(2 * (attempt + 1))
            continue
        return None, payload
    return None, "gh 重试后仍不可用"


def _license_of(item: dict[str, Any]) -> str:
    info = item.get("license")
    if not isinstance(info, dict):
        return ""
    return str(info.get("spdx_id") or info.get("name") or "")


def map_repo(item: dict[str, Any], source_query: str = "") -> dict[str, Any]:
    """把 GitHub API 仓库对象映射到统一 schema。"""
    full_name = str(item.get("full_name") or "")
    record = new_record(full_name, source_query)
    record.update(
        {
            "url": str(item.get("html_url") or record["url"]),
            "description": str(item.get("description") or ""),
            "stars": int(item.get("stargazers_count") or 0),
            "forks": int(item.get("forks_count") or 0),
            "language": str(item.get("language") or ""),
            "license": _license_of(item),
            "topics": list(item.get("topics") or []),
            "archived": bool(item.get("archived")),
            "is_fork": bool(item.get("fork")),
            "created_at": str(item.get("created_at") or ""),
            "pushed_at": str(item.get("pushed_at") or ""),
            "updated_at": str(item.get("updated_at") or ""),
            "open_issues": int(item.get("open_issues_count") or 0),
            "homepage": str(item.get("homepage") or ""),
            "default_branch": str(item.get("default_branch") or ""),
        }
    )
    return record


def search_repos(
    query: str, limit: int = 30, sort: str = "stars"
) -> tuple[list[dict[str, Any]], str]:
    """搜索仓库；不可用时返回空列表与 degraded，不中断流程。"""
    if not gh_available():
        return [], "degraded"
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    pages = max(1, (min(limit, 100) + PAGE_SIZE - 1) // PAGE_SIZE)
    for page in range(1, pages + 1):
        params = {
            "q": query,
            "order": "desc",
            "per_page": str(min(PAGE_SIZE, limit - len(records))),
            "page": str(page),
        }
        if sort and sort != "best-match":
            params["sort"] = sort
        data, error = _gh_json("/search/repositories", params)
        if not isinstance(data, dict):
            return records, "degraded" if error else "ok"
        items = data.get("items") or []
        if not items:
            break
        for item in items:
            record = map_repo(item, query)
            if record["repo_id"] and record["repo_id"] not in seen:
                seen.add(record["repo_id"])
                records.append(record)
            if len(records) >= limit:
                break
        if len(records) >= limit:
            break
        if page < pages:
            time.sleep(2)
    return records, "ok" if records else "degraded"


def fetch_metadata(repo_ids: list[str]) -> tuple[dict[str, dict[str, Any]], str]:
    """逐个补齐元数据；单个失败只跳过该仓库。"""
    results: dict[str, dict[str, Any]] = {}
    if not gh_available():
        return results, "degraded"
    failures = 0
    for index, repo_id in enumerate(repo_ids):
        data, _error = _gh_json(f"/repos/{repo_id}")
        if isinstance(data, dict):
            results[str(repo_id).strip().lower()] = map_repo(data)
        else:
            failures += 1
        if index < len(repo_ids) - 1:
            time.sleep(0.4)
    if not results:
        return results, "degraded"
    return results, "degraded" if failures else "ok"


def fetch_readme(repo_id: str, max_chars: int = 6000) -> dict[str, Any] | None:
    """取 README，不 clone；非法字节替换而不崩溃。"""
    data, _error = _gh_json(f"/repos/{repo_id}/readme")
    if not isinstance(data, dict):
        return None
    try:
        raw = base64.b64decode(str(data.get("content") or "")).decode("utf-8", errors="replace")
    except (ValueError, TypeError):
        raw = ""
    return {
        "repo_id": str(repo_id).strip().lower(),
        "readme_text": raw[:max_chars],
        "readme_length": len(raw),
        "truncated": len(raw) > max_chars,
    }


def search_code(query: str, limit: int = 20) -> list[dict[str, Any]]:
    """代码搜索，用于取 E1 代码级证据。"""
    if not gh_available():
        return []
    hits: list[dict[str, Any]] = []
    pages = max(1, (min(limit, 100) + PAGE_SIZE - 1) // PAGE_SIZE)
    for page in range(1, pages + 1):
        params = {"q": query, "per_page": str(min(PAGE_SIZE, limit - len(hits))), "page": str(page)}
        data, _error = _gh_json("/search/code", params)
        if not isinstance(data, dict):
            break
        items = data.get("items") or []
        if not items:
            break
        for item in items:
            repository = item.get("repository") or {}
            full_name = str(repository.get("full_name") or "")
            if not full_name:
                continue
            hits.append(
                {
                    "repo_id": full_name.strip().lower(),
                    "path": str(item.get("path") or ""),
                    "url": str(item.get("html_url") or ""),
                }
            )
            if len(hits) >= limit:
                break
        if len(hits) >= limit:
            break
        if page < pages:
            time.sleep(2)
    return hits


def make_evidence(
    level: str, source: str, detail: str, locator: str, checked_at: str
) -> dict[str, Any]:
    """构造一条证据。档位必须是 E1—E4。"""
    if level not in EVIDENCE_LEVELS:
        raise ValueError(f"未知证据档位：{level!r}")
    digest = hashlib.sha256(f"{level}|{source}|{locator}|{detail}".encode()).hexdigest()[:10]
    return {
        "id": f"{level.lower()}-{digest}",
        "level": level,
        "source": source,
        "detail": detail,
        "locator": locator,
        "checked_at": checked_at,
    }


# -- 评分闸门：分数必须挂得住证据 ---------------------------------------------


def _evidence_index(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for item in record.get("evidence") or []:
        if isinstance(item, dict) and item.get("id"):
            index[str(item["id"])] = item
    return index


def _levels_for(ids: list[str], index: dict[str, dict[str, Any]]) -> set[str]:
    return {str(index[item].get("level")) for item in ids if item in index}


def validate_scores(record: dict[str, Any]) -> list[str]:
    """返回违规说明；空列表表示通过。脚本不打分，只校验证据支撑。"""
    problems: list[str] = []
    index = _evidence_index(record)
    scores = record.get("scores") or {}
    links = record.get("score_evidence") or {}

    for dimension, value in scores.items():
        if dimension not in SCORE_DIMENSIONS:
            problems.append(f"未知评分维度：{dimension}")
            continue
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 100:
            problems.append(f"{dimension} 分数必须是 0—100 的数值，当前 {value!r}")
            continue
        ids = [str(item) for item in (links.get(dimension) or [])]
        if not ids:
            problems.append(f"{dimension} 有分数但没有引用任何证据")
            continue
        missing = [item for item in ids if item not in index]
        if missing:
            problems.append(f"{dimension} 引用的证据不存在：{', '.join(missing)}")
        levels = _levels_for(ids, index)
        if not (levels & {"E1", "E2", "E3"}):
            problems.append(f"{dimension} 只有 E4 未核验证据，不得给分数")

    for name, capability in (record.get("capabilities") or {}).items():
        if not isinstance(capability, dict) or not capability.get("required"):
            continue
        ids = [str(item) for item in (capability.get("evidence") or [])]
        if not ids:
            problems.append(f"核心能力「{name}」没有任何证据")
            continue
        missing = [item for item in ids if item not in index]
        if missing:
            problems.append(f"核心能力「{name}」引用的证据不存在：{', '.join(missing)}")
            continue
        levels = _levels_for(ids, index)
        if not (levels & {"E1", "E2"}):
            problems.append(f"核心能力「{name}」只有元数据或未核验证据，不能据此判定具备")
        elif "E1" not in levels:
            similarity = scores.get("similarity")
            if isinstance(similarity, (int, float)) and similarity > E2_ONLY_SIMILARITY_CAP:
                problems.append(
                    f"核心能力「{name}」仅有 E2 文档级证据，相似度不得超过 {E2_ONLY_SIMILARITY_CAP}"
                )

    if record.get("archived"):
        total = composite(scores)
        if total is not None and total >= ARCHIVED_COMPOSITE_CAP:
            problems.append(
                f"仓库已归档，综合参考不得达到 {ARCHIVED_COMPOSITE_CAP}（A/B 级）；"
                "只能作为反例或历史参考，并在注意事项说明"
            )

    trend = record.get("star_trend")
    if trend:
        ids = [str(item) for item in (trend.get("evidence") or [])]
        levels = _levels_for(ids, index)
        if not ids or not (levels & {"E1", "E2"}):
            problems.append("Star 趋势缺少可靠时间序列证据，必须标为未核验")
        elif not trend.get("source") or not trend.get("checked_at"):
            problems.append("Star 趋势必须注明来源与核验日期")

    return problems


def composite(scores: dict[str, Any]) -> float | None:
    """综合参考值；任一维度缺失时返回 None，不用零填充。"""
    values: dict[str, float] = {}
    for dimension in SCORE_DIMENSIONS:
        value = scores.get(dimension)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return None
        values[dimension] = float(value)
    return round(sum(values[dim] * WEIGHTS[dim] for dim in SCORE_DIMENSIONS), 2)


def grade_of(composite_value: float) -> str:
    if composite_value >= 85:
        return "A"
    if composite_value >= 70:
        return "B"
    if composite_value >= 55:
        return "C"
    return "D"


# -- 落盘会话 -----------------------------------------------------------------


def _split_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in re.split(r"[,，]", raw) if item.strip()]


def brief_path(slug: str, root: Path | None = None) -> Path:
    return session_dir(slug, root) / "brief.json"


def load_brief(slug: str, root: Path | None = None) -> dict[str, Any]:
    path = brief_path(slug, root)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def write_brief(slug: str, brief: dict[str, Any], root: Path | None = None) -> Path:
    directory = session_dir(slug, root)
    directory.mkdir(parents=True, exist_ok=True)
    path = brief_path(slug, root)
    path.write_text(json.dumps(brief, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [f"# {brief.get('topic') or slug}", "", "## 搜索简报", ""]
    for label, key in (
        ("目标", "goal"),
        ("参考实体及产品指纹", "topic"),
        ("必须具备", "must"),
        ("最好具备", "nice"),
        ("排除", "exclude"),
        ("用户约束", "constraints"),
        ("质量偏好", "quality_preference"),
    ):
        value = brief.get(key)
        if isinstance(value, (list, tuple)):
            value = "、".join(str(item) for item in value)
        lines.append(f"- {label}：{value or '—'}")
    lines.append("")
    (directory / "brief.md").write_text("\n".join(lines), encoding="utf-8")
    return path


def _read_json_rows(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        rows = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(item)
        return rows
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _add_evidence(record: dict[str, Any], evidence: dict[str, Any]) -> None:
    existing = {str(item.get("id")) for item in record.get("evidence") or []}
    if evidence["id"] not in existing:
        record.setdefault("evidence", []).append(evidence)


# -- 子命令 -------------------------------------------------------------------


def cmd_init(args: argparse.Namespace) -> int:
    directory = session_dir(args.slug)
    directory.mkdir(parents=True, exist_ok=True)
    brief = load_brief(args.slug)
    brief.update(
        {
            "slug": slugify(args.slug),
            "topic": args.topic or brief.get("topic") or args.slug,
            "goal": args.goal or brief.get("goal") or "",
            "must": _split_list(args.must) or brief.get("must") or [],
            "nice": _split_list(args.nice) or brief.get("nice") or [],
            "exclude": _split_list(args.exclude) or brief.get("exclude") or [],
            "constraints": args.constraints or brief.get("constraints") or "",
            "quality_preference": args.quality_preference or brief.get("quality_preference") or "",
            "created_at": brief.get("created_at") or utc_now(),
        }
    )
    write_brief(args.slug, brief)
    path = candidates_path(args.slug)
    if not path.is_file():
        save_candidates(path, {})
    _emit({"status": "ok", "session_dir": str(directory), "candidates": str(path)})
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    path = candidates_path(args.slug)
    if not path.parent.is_dir():
        _emit({"error": f"会话不存在，请先 init：{args.slug}"})
        return 2
    records = load_candidates(path)
    if args.from_json:
        incoming = []
        for row in _read_json_rows(Path(args.from_json)):
            repo_id = str(row.get("repo_id") or row.get("full_name") or "")
            if not repo_id:
                continue
            record = new_record(repo_id, args.query)
            for field in ("description", "stars", "forks", "language", "license", "url"):
                if field in row:
                    record[field] = row[field]
            incoming.append(record)
        status = "ok"
    else:
        incoming, status = search_repos(args.query, limit=args.limit, sort=args.sort)
    added = 0
    for record in incoming:
        record.setdefault("source_queries", [])
        if args.intent:
            record["intent"] = args.intent
        key = record["repo_id"]
        if key in records:
            records[key] = merge_record(records[key], record)
        else:
            records[key] = record
            added += 1
    save_candidates(path, records)
    _emit(
        {
            "status": status,
            "query": args.query,
            "intent": args.intent or "",
            "fetched": len(incoming),
            "added": added,
            "total": len(records),
            "candidates": str(path),
        }
    )
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    path = candidates_path(args.slug)
    if not path.is_file():
        _emit({"error": f"候选库不存在，请先 init：{args.slug}"})
        return 2
    records = load_candidates(path)
    repo_ids = [item.strip().lower() for item in args.repos] if args.repos else sorted(records)
    fresh, status = fetch_metadata(repo_ids)
    stamp = today()
    for repo_id, record in fresh.items():
        record["verified_at"] = stamp
        _add_evidence(
            record,
            make_evidence("E3", "gh api repos", "仓库元数据实时核验", repo_id, stamp),
        )
        records[repo_id] = merge_record(records[repo_id], record) if repo_id in records else record
    save_candidates(path, records)
    missing = [item for item in repo_ids if item not in fresh]
    _emit(
        {
            "status": status,
            "verified": len(fresh),
            "missing": missing,
            "checked_at": stamp,
            "candidates": str(path),
        }
    )
    return 0


def cmd_readme(args: argparse.Namespace) -> int:
    path = candidates_path(args.slug)
    if not path.is_file():
        _emit({"error": f"候选库不存在，请先 init：{args.slug}"})
        return 2
    records = load_candidates(path)
    repo_ids = [item.strip().lower() for item in args.repos] if args.repos else sorted(records)
    stamp = today()
    fetched = 0
    evidence_dir = session_dir(args.slug) / "evidence"
    for index, repo_id in enumerate(repo_ids):
        payload = fetch_readme(repo_id, max_chars=args.max_chars)
        if payload is None:
            continue
        fetched += 1
        record = records.get(repo_id) or new_record(repo_id, "readme")
        record["readme_text"] = payload["readme_text"]
        record["readme_length"] = payload["readme_length"]
        record["readme_truncated"] = payload["truncated"]
        record["verified_at"] = stamp
        _add_evidence(
            record,
            make_evidence(
                "E2",
                "gh api readme",
                f"README 已读取（{payload['readme_length']} 字符"
                + ("，已截断）" if payload["truncated"] else "）"),
                f"{repo_id}/README",
                stamp,
            ),
        )
        records[repo_id] = record
        evidence_dir.mkdir(parents=True, exist_ok=True)
        safe_name = repo_id.replace("/", "__")
        (evidence_dir / f"{safe_name}.readme.md").write_text(
            payload["readme_text"], encoding="utf-8"
        )
        if index < len(repo_ids) - 1:
            time.sleep(0.4)
    save_candidates(path, records)
    _emit(
        {
            "status": "ok" if fetched else "degraded",
            "fetched": fetched,
            "requested": len(repo_ids),
            "checked_at": stamp,
        }
    )
    return 0


def cmd_code_search(args: argparse.Namespace) -> int:
    path = candidates_path(args.slug)
    if not path.is_file():
        _emit({"error": f"候选库不存在，请先 init：{args.slug}"})
        return 2
    records = load_candidates(path)
    hits = search_code(args.query, limit=args.limit)
    stamp = today()
    attached = 0
    for hit in hits:
        repo_id = hit["repo_id"]
        if args.repos and repo_id not in {item.strip().lower() for item in args.repos}:
            continue
        record = records.get(repo_id)
        if record is None:
            if not args.allow_new:
                continue
            record = new_record(repo_id, args.query)
            records[repo_id] = record
        evidence = make_evidence(
            "E1", "gh api search/code", f"代码命中：{args.query}", hit["path"], stamp
        )
        evidence["url"] = hit["url"]
        _add_evidence(record, evidence)
        if args.capability:
            capability = record.setdefault("capabilities", {}).setdefault(
                args.capability, {"required": True, "evidence": []}
            )
            if evidence["id"] not in capability["evidence"]:
                capability["evidence"].append(evidence["id"])
        record["verified_at"] = stamp
        attached += 1
    save_candidates(path, records)
    _emit(
        {
            "status": "ok" if hits else "degraded",
            "hits": len(hits),
            "attached": attached,
            "capability": args.capability or "",
            "checked_at": stamp,
        }
    )
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    path = candidates_path(args.slug)
    if not path.is_file():
        _emit({"error": f"候选库不存在，请先 init：{args.slug}"})
        return 2
    records = load_candidates(path)
    rejected: list[dict[str, Any]] = []
    accepted = 0
    for row in _read_json_rows(Path(args.from_json)):
        repo_id = str(row.get("repo_id") or "").strip().lower()
        if repo_id not in records:
            rejected.append({"repo_id": repo_id, "problems": ["候选库中没有该仓库"]})
            continue
        candidate = dict(records[repo_id])
        # 改分必须重新声明证据；不允许沿用旧链接为新分数背书。
        if "scores" in row:
            candidate["scores"] = row["scores"]
            candidate["score_evidence"] = row.get("score_evidence") or {}
        for field in ("notes", "star_trend", "capabilities"):
            if field in row:
                candidate[field] = row[field]
        problems = validate_scores(candidate)
        if problems:
            rejected.append({"repo_id": repo_id, "problems": problems})
            continue
        for field in ("scores", "score_evidence", "notes", "star_trend", "capabilities"):
            if field in candidate:
                records[repo_id][field] = candidate[field]
        value = composite(records[repo_id].get("scores") or {})
        records[repo_id]["grade"] = grade_of(value) if value is not None else ""
        records[repo_id]["composite"] = value
        accepted += 1
    if rejected:
        _emit({"status": "rejected", "accepted": accepted, "rejected": rejected})
        return 1
    save_candidates(path, records)
    _emit({"status": "ok", "accepted": accepted, "candidates": str(path)})
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    directory = session_dir(args.slug)
    path = candidates_path(args.slug)
    if not path.is_file():
        _emit({"error": f"候选库不存在，请先 init：{args.slug}"})
        return 2
    render = _load_renderer()
    brief = load_brief(args.slug) or {"slug": slugify(args.slug), "topic": args.slug}
    records = list(load_candidates(path).values())
    generated = utc_now()
    markdown_path = directory / "report.md"
    html_path = directory / "report.html"
    markdown_path.write_text(render.render_markdown(brief, records, generated), encoding="utf-8")
    html_path.write_text(render.render_html(brief, records, generated), encoding="utf-8")
    _emit(
        {
            "status": "ok",
            "records": len(records),
            "markdown": str(markdown_path),
            "html": str(html_path),
            "generated_at": generated,
        }
    )
    return 0


def _load_renderer():
    import importlib.util

    target = Path(__file__).resolve().with_name("render_report.py")
    spec = importlib.util.spec_from_file_location("gh_research_render", target)
    module = importlib.util.module_from_spec(spec)
    sys.modules["gh_research_render"] = module
    spec.loader.exec_module(module)
    return module


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="取证式 GitHub 项目调研")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="建立会话目录与搜索简报")
    p.add_argument("--slug", required=True)
    p.add_argument("--topic", default="")
    p.add_argument("--goal", default="")
    p.add_argument("--must", default="")
    p.add_argument("--nice", default="")
    p.add_argument("--exclude", default="")
    p.add_argument("--constraints", default="")
    p.add_argument("--quality-preference", dest="quality_preference", default="")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("search", help="多路发现候选并写库")
    p.add_argument("--slug", required=True)
    p.add_argument("--query", required=True)
    p.add_argument("--intent", default="")
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("--sort", default="stars", choices=["stars", "updated", "best-match"])
    p.add_argument("--from-json", dest="from_json", default="")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("verify", help="核验仓库元数据")
    p.add_argument("--slug", required=True)
    p.add_argument("--repos", nargs="*", default=None)
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("readme", help="读取 README，记 E2 文档级证据")
    p.add_argument("--slug", required=True)
    p.add_argument("--repos", nargs="*", default=None)
    p.add_argument("--max-chars", dest="max_chars", type=int, default=6000)
    p.set_defaults(func=cmd_readme)

    p = sub.add_parser("code-search", help="代码搜索，记 E1 代码级证据")
    p.add_argument("--slug", required=True)
    p.add_argument("--query", required=True)
    p.add_argument("--capability", default="")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--repos", nargs="*", default=None)
    p.add_argument("--allow-new", dest="allow_new", action="store_true")
    p.set_defaults(func=cmd_code_search)

    p = sub.add_parser("score", help="写入三维分数并执行证据闸门校验")
    p.add_argument("--slug", required=True)
    p.add_argument("--from-json", dest="from_json", required=True)
    p.set_defaults(func=cmd_score)

    p = sub.add_parser("report", help="生成 Markdown 与自包含 HTML 报告")
    p.add_argument("--slug", required=True)
    p.set_defaults(func=cmd_report)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (ValueError, OSError) as exc:
        _emit({"error": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
