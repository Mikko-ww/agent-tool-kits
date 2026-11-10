"""Platform registry, path expansion, and physical-target resolution."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any

_VALID_OS = {"darwin", "linux", "windows"}
_VALID_ROLES = {"primary", "shared", "compatibility"}


class PlatformError(ValueError):
    """Raised for invalid platform definitions or requests."""


@dataclass(frozen=True)
class PathSpec:
    id: str
    template: str
    role: str
    os: tuple[str, ...] | None = None
    precedence: int | None = None


@dataclass(frozen=True)
class PlatformDefinition:
    id: str
    display_name: str
    project_paths: tuple[PathSpec, ...]
    global_paths: tuple[PathSpec, ...]
    detect: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True)
class PhysicalTarget:
    target_id: str
    path: Path
    consumers: tuple[str, ...]
    strategy: str
    role: str
    shared: bool


# Compatibility model used by the legacy engine until the new CLI lands.
@dataclass(frozen=True)
class Platform:
    id: str
    label: str
    project_skills_dir: str
    _global_skills_dir: str
    _global_plugins_dir: str | None = None

    def global_skills_dir(self) -> Path:
        return _expand(self._global_skills_dir)

    def skills_dir(self, project: Path | None = None) -> Path:
        if project is None:
            return self.global_skills_dir()
        return project / self.project_skills_dir

    @property
    def supports_plugins(self) -> bool:
        return self._global_plugins_dir is not None

    def plugins_dir(self) -> Path:
        if self._global_plugins_dir is None:
            raise KeyError(f"platform '{self.id}' has no local plugins directory")
        return _expand(self._global_plugins_dir)


_PLATFORMS: tuple[Platform, ...] = (
    Platform("claude-code", "Claude Code", ".claude/skills", "$CLAUDE_HOME/skills"),
    Platform("codex", "Codex", ".agents/skills", "$CODEX_HOME/skills"),
    Platform(
        "cursor",
        "Cursor",
        ".agents/skills",
        "$HOME/.cursor/skills",
        _global_plugins_dir="$HOME/.cursor/plugins/local",
    ),
    Platform("opencode", "OpenCode", ".agents/skills", "$XDG_CONFIG_HOME/opencode/skills"),
    Platform("pi", "pi", ".pi/skills", "$HOME/.pi/agent/skills"),
    Platform("gemini-cli", "Gemini CLI", ".agents/skills", "$HOME/.gemini/skills"),
    Platform("antigravity", "Antigravity", ".agents/skills", "$HOME/.gemini/antigravity/skills"),
    Platform("github-copilot", "GitHub Copilot", ".agents/skills", "$HOME/.copilot/skills"),
    Platform("universal", "Universal (.agents)", ".agents/skills", "$HOME/.agents/skills"),
)

PLATFORMS: dict[str, Platform] = {platform.id: platform for platform in _PLATFORMS}


def get(platform_id: str) -> Platform:
    try:
        return PLATFORMS[platform_id]
    except KeyError as exc:
        known = ", ".join(PLATFORMS)
        raise KeyError(f"unknown platform '{platform_id}' (known: {known})") from exc


def detect_from_path(path: Path) -> Platform | None:
    resolved = path.expanduser().absolute()
    for platform in _PLATFORMS:
        base = platform.global_skills_dir().absolute()
        try:
            resolved.relative_to(base)
        except ValueError:
            continue
        return platform
    return None


def load_registry(path: Path | None = None) -> dict[str, PlatformDefinition]:
    registry_path = path or _registry_path()
    try:
        raw = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlatformError(f"invalid platform registry: {registry_path}") from exc
    if raw.get("schema_version") != 1:
        raise PlatformError("unsupported platform registry schema_version")
    platforms = raw.get("platforms")
    if not isinstance(platforms, list):
        raise PlatformError("platform registry must contain a platforms list")
    definitions: dict[str, PlatformDefinition] = {}
    for item in platforms:
        definition = _parse_platform(item)
        if definition.id in definitions:
            raise PlatformError(f"duplicate platform definition: {definition.id}")
        definitions[definition.id] = definition
    return definitions


def resolve_targets(
    scope: str,
    platform_ids: list[str],
    cwd: Path,
    os_name: str,
    env: Mapping[str, str],
) -> tuple[PhysicalTarget, ...]:
    if scope not in {"project", "global"}:
        raise PlatformError(f"unsupported scope {scope!r}")
    if os_name not in _VALID_OS:
        raise PlatformError(f"unsupported OS {os_name!r}")
    registry = load_registry()
    cwd = cwd.expanduser().resolve()
    home = _home_from_env(env)
    groups: dict[str, dict[str, Any]] = {}
    for platform_id in platform_ids:
        definition = registry.get(platform_id)
        if definition is None:
            raise PlatformError(f"unknown platform {platform_id!r}")
        specs = definition.project_paths if scope == "project" else definition.global_paths
        for spec in specs:
            if spec.os is not None and os_name not in spec.os:
                continue
            path = _resolve_template(spec.template, scope, cwd, home, env)
            key = _path_key(path)
            group = groups.setdefault(
                key,
                {
                    "target_id": spec.id,
                    "path": path,
                    "consumers": set(),
                    "roles": set(),
                },
            )
            group["consumers"].add(platform_id)
            group["roles"].add(spec.role)
    targets: list[PhysicalTarget] = []
    for group in groups.values():
        roles = group["roles"]
        if roles == {"primary"}:
            role = "primary"
        elif "shared" in roles or "primary" in roles:
            role = "shared"
        else:
            role = "compatibility"
        consumers = tuple(sorted(group["consumers"]))
        shared = len(consumers) > 1 or role in {"shared", "compatibility"}
        targets.append(
            PhysicalTarget(
                target_id=group["target_id"],
                path=group["path"],
                consumers=consumers,
                strategy="symlink",
                role=role,
                shared=shared,
            )
        )
    return tuple(sorted(targets, key=lambda target: (target.target_id, str(target.path))))


def detect_platforms(os_name: str, env: Mapping[str, str], home: Path) -> set[str]:
    if os_name not in _VALID_OS:
        raise PlatformError(f"unsupported OS {os_name!r}")
    registry = load_registry()
    detected: set[str] = set()
    for definition in registry.values():
        for entry in definition.detect:
            if entry.get("type") != "path":
                continue
            template = entry.get("template")
            if not isinstance(template, str):
                continue
            path = _resolve_template(template, "global", home, home, env)
            if path.exists():
                detected.add(definition.id)
                break
    return detected


def project_id(project_root: Path) -> str:
    resolved = project_root.expanduser().resolve()
    normalized = os.path.normcase(str(resolved))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def same_physical_path(left: Path, right: Path) -> bool:
    return _path_key(left) == _path_key(right)


def _registry_path() -> Path:
    configured = os.environ.get("ATKITS_PLATFORM_REGISTRY")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).with_name("platform_registry.json")


def _parse_platform(item: object) -> PlatformDefinition:
    if not isinstance(item, dict):
        raise PlatformError("platform definition must be an object")
    platform_id = item.get("id")
    display_name = item.get("display_name")
    if not isinstance(platform_id, str) or not platform_id:
        raise PlatformError("platform id must be a non-empty string")
    if not isinstance(display_name, str) or not display_name:
        raise PlatformError(f"platform {platform_id}: display_name must be a string")
    project_paths = _parse_paths(item.get("project_paths"), platform_id, "project_paths")
    global_paths = _parse_paths(item.get("global_paths"), platform_id, "global_paths")
    detect = item.get("detect", [])
    if not isinstance(detect, list):
        raise PlatformError(f"platform {platform_id}: detect must be a list")
    for entry in detect:
        if not isinstance(entry, dict):
            raise PlatformError(f"platform {platform_id}: detect entries must be objects")
    return PlatformDefinition(
        id=platform_id,
        display_name=display_name,
        project_paths=project_paths,
        global_paths=global_paths,
        detect=tuple(detect),
    )


def _parse_paths(raw: object, platform_id: str, field_name: str) -> tuple[PathSpec, ...]:
    if not isinstance(raw, list) or not raw:
        raise PlatformError(f"platform {platform_id}: {field_name} must be a non-empty list")
    specs: list[PathSpec] = []
    for item in raw:
        if not isinstance(item, dict):
            raise PlatformError(f"platform {platform_id}: path specs must be objects")
        spec_id = item.get("id")
        template = item.get("template")
        role = item.get("role")
        if not isinstance(spec_id, str) or not spec_id:
            raise PlatformError(f"platform {platform_id}: path id must be a non-empty string")
        if not isinstance(template, str) or not template:
            raise PlatformError(f"platform {platform_id}: path template must be non-empty")
        if role not in _VALID_ROLES:
            raise PlatformError(f"platform {platform_id}: invalid path role {role!r}")
        os_value = item.get("os")
        if os_value is not None:
            if not isinstance(os_value, list) or not os_value:
                raise PlatformError(f"platform {platform_id}: os must be a non-empty list")
            if any(value not in _VALID_OS for value in os_value):
                raise PlatformError(f"platform {platform_id}: invalid OS in path spec")
            os_names = tuple(os_value)
        else:
            os_names = None
        precedence = item.get("precedence")
        if precedence is not None and not isinstance(precedence, int):
            raise PlatformError(f"platform {platform_id}: precedence must be an integer")
        specs.append(
            PathSpec(
                id=spec_id,
                template=template,
                role=role,
                os=os_names,
                precedence=precedence,
            )
        )
    return tuple(specs)


def _resolve_template(
    template: str, scope: str, cwd: Path, home: Path, env: Mapping[str, str]
) -> Path:
    expanded = _expand_template(template, env, home)
    path = Path(expanded)
    if scope == "project":
        if path.is_absolute():
            raise PlatformError(f"project path must be relative: {template!r}")
        return (cwd / path).resolve()
    if not path.is_absolute():
        path = home / path
    return path.resolve()


def _expand_template(template: str, env: Mapping[str, str], home: Path) -> str:
    home_value = str(home)
    replacements = {
        "$HOME": env.get("HOME", home_value),
        "$USERPROFILE": env.get("USERPROFILE", home_value),
        "$XDG_CONFIG_HOME": env.get("XDG_CONFIG_HOME", str(home / ".config")),
        "$XDG_DATA_HOME": env.get("XDG_DATA_HOME", str(home / ".local/share")),
        "$CODEX_HOME": env.get("CODEX_HOME", str(home / ".codex")),
        "$CLAUDE_CONFIG_DIR": env.get("CLAUDE_CONFIG_DIR", str(home / ".claude")),
        "$APPDATA": env.get("APPDATA", str(home / "AppData/Roaming")),
        "$LOCALAPPDATA": env.get("LOCALAPPDATA", str(home / "AppData/Local")),
    }
    value = template
    for key, replacement in replacements.items():
        value = value.replace(key, replacement)
    if value.startswith("~"):
        value = home_value + value[1:]
    if "$" in value:
        raise PlatformError(f"unresolved variable in path template: {template!r}")
    return value


def _home_from_env(env: Mapping[str, str]) -> Path:
    home = env.get("HOME") or env.get("USERPROFILE")
    if home:
        return Path(home).expanduser().resolve()
    return Path.home().resolve()


def _path_key(path: Path) -> str:
    text = str(path.expanduser())
    if _is_windows_style_path(text):
        return str(PureWindowsPath(text)).lower()
    resolved = path.resolve()
    return os.path.normcase(str(resolved))


def _is_windows_style_path(text: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", text))


def _expand(template: str) -> Path:
    home = Path.home()
    xdg_config = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    claude_home = Path(os.environ.get("CLAUDE_CONFIG_DIR") or home / ".claude")
    codex_home = Path(os.environ.get("CODEX_HOME") or home / ".codex")
    value = (
        template.replace("$HOME", str(home))
        .replace("$XDG_CONFIG_HOME", str(xdg_config))
        .replace("$CLAUDE_HOME", str(claude_home))
        .replace("$CODEX_HOME", str(codex_home))
    )
    return Path(value)
