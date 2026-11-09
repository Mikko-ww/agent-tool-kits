"""平台注册表：每个 agent 平台从哪里读取技能。

id 刻意与 vercel `skills` CLI 的 `--agent` 名称保持一致，委托外部安装时可直接透传。
路径来源：https://github.com/vercel-labs/skills（src/agents.ts）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Platform:
    id: str
    label: str
    project_skills_dir: str  # relative to a project root
    _global_skills_dir: str  # may contain ${VAR:-default} style tokens, expanded at runtime
    # 本地插件目录（机器级）。None = 该平台没有“放一个目录就能被发现”的插件机制，
    # 例如 Claude Code / Codex 只认 marketplace，交给后续阶段。
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


_PLATFORMS: tuple[Platform, ...] = (
    Platform("claude-code", "Claude Code", ".claude/skills", "$CLAUDE_HOME/skills"),
    Platform("codex", "Codex", ".agents/skills", "$CODEX_HOME/skills"),
    # Cursor 的本地插件目录会拒绝指向目录外的 symlink（realpath 校验），只能放真实拷贝。
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
    # Canonical dir used by the vercel `skills` CLI and read by amp/cline/zed/...
    Platform("universal", "Universal (.agents)", ".agents/skills", "$HOME/.agents/skills"),
)

PLATFORMS: dict[str, Platform] = {p.id: p for p in _PLATFORMS}


def get(platform_id: str) -> Platform:
    try:
        return PLATFORMS[platform_id]
    except KeyError:
        known = ", ".join(PLATFORMS)
        raise KeyError(f"unknown platform '{platform_id}' (known: {known})") from None


def detect_from_path(path: Path) -> Platform | None:
    """Return the platform whose *global* skills dir contains `path`, if any."""
    resolved = path.expanduser().absolute()
    for platform in _PLATFORMS:
        base = platform.global_skills_dir().absolute()
        try:
            resolved.relative_to(base)
        except ValueError:
            continue
        return platform
    return None
