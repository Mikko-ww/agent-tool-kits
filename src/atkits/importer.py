"""`atkits import`：收编散落在各平台目录里的技能。

以 ~/.codex/skills/foo 为例：

* 外部技能（通过 --source、清单已有 source、或 vercel 的 .skill-lock.json 得知来源）：
  文件原地不动，只在清单里记录 `source` + `to`。
* 与金库某技能内容一致：把副本替换为指向金库的 symlink。
* 新技能：移入金库，原位置留 symlink，写入清单。
* 与金库同名但内容不同：报告冲突并跳过。
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import fsutil, platforms
from .profile import Profile, SkillSpec
from .vault import SKILL_FILE, Vault, skill_name_from_frontmatter


@dataclass
class ImportResult:
    path: Path
    name: str
    outcome: str  # moved | linked | external | conflict | skipped
    detail: str = ""


def vercel_lock_sources() -> dict[str, str]:
    """Map skill name -> 'owner/repo' from the vercel skills CLI lock file, if present."""
    lock = Path.home() / ".agents" / ".skill-lock.json"
    if not lock.is_file():
        return {}
    try:
        data = json.loads(lock.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, str] = {}
    for name, entry in (data.get("skills") or {}).items():
        source = entry.get("source")
        if source:
            out[name] = source
    return out


def discover_skill_dirs(path: Path) -> list[Path]:
    """`path` may be one skill dir or a directory of skill dirs."""
    path = path.expanduser()
    if (path / SKILL_FILE).is_file():
        return [path]
    if path.is_dir():
        return sorted(
            p
            for p in path.iterdir()
            if p.is_dir() and not p.name.startswith(".") and (p / SKILL_FILE).is_file()
        )
    return []


def import_skill(
    vault: Vault,
    profile: Profile,
    skill_dir: Path,
    *,
    source: str | None = None,
    to: list[str] | None = None,
    rename: str | None = None,
    dry_run: bool = False,
) -> ImportResult:
    skill_dir = skill_dir.expanduser()
    name = rename or skill_name_from_frontmatter(skill_dir / SKILL_FILE) or skill_dir.name

    detected = platforms.detect_from_path(skill_dir)
    targets = to or ([detected.id] if detected and detected.id in profile.targets else [])
    if not targets:
        return ImportResult(skill_dir, name, "skipped", "无法从路径推断目标平台，请用 --to 指定")
    unknown = [t for t in targets if t not in profile.targets]
    if unknown:
        return ImportResult(skill_dir, name, "skipped", f"{unknown} 不在清单 targets 中")

    if skill_dir.is_symlink() and vault.contains(skill_dir):
        _record(profile, SkillSpec(name, targets), dry_run)
        return ImportResult(skill_dir, name, "skipped", "已经是指向金库的 symlink")

    existing = profile.skills.get(name)
    source = source or (existing.source if existing else None) or vercel_lock_sources().get(name)
    if source:
        _record(profile, SkillSpec(name, targets, source=source), dry_run)
        return ImportResult(skill_dir, name, "external", f"来源={source}，文件原地保留")

    dest = vault.skills_dir / name
    if dest.exists():
        if skill_dir.is_dir() and fsutil.dirs_equal(skill_dir, dest):
            if not dry_run:
                fsutil.backup(skill_dir, f"import/{detected.id if detected else 'misc'}")
                fsutil.make_symlink(skill_dir, dest)
            _record(profile, SkillSpec(name, targets), dry_run)
            return ImportResult(skill_dir, name, "linked", "与金库内容一致，已替换为 symlink")
        return ImportResult(
            skill_dir, name, "conflict", f"与 {dest} 内容不同，请手动处理或用 --rename 另存"
        )

    # Leave the symlink under the *canonical* name so a dir renamed by its frontmatter
    # (e.g. skills-lookup/ with name: skill-lookup) does not turn into an orphan.
    link_at = skill_dir.parent / name
    if not dry_run:
        vault.skills_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(skill_dir), str(dest))
        for junk in dest.rglob(".DS_Store"):
            junk.unlink()
        fsutil.make_symlink(link_at, dest)
    _record(profile, SkillSpec(name, targets), dry_run)
    note = f"已移入 {dest}，原位置留下 symlink {link_at.name}"
    return ImportResult(skill_dir, name, "moved", note)


def _record(profile: Profile, spec: SkillSpec, dry_run: bool) -> None:
    existing = profile.skills.get(spec.name)
    if existing:
        merged = sorted(set(existing.to) | set(spec.to), key=profile.targets.index)
        spec = SkillSpec(spec.name, merged, source=existing.source or spec.source)
        profile.add_skill(spec, replace=True)
    else:
        profile.add_skill(spec)
    if not dry_run:
        profile.save()
