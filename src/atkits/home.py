"""Layout and configuration for the per-user atkits data directory."""

from __future__ import annotations

import json
import os
import tomllib
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any


class AtkitsHome:
    """The root directory that contains all atkits-owned local state."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def discover(
        cls,
        env: Mapping[str, str] | None = None,
        cwd: Path | None = None,  # noqa: ARG003 - reserved for project-aware discovery
    ) -> "AtkitsHome":
        environment = os.environ if env is None else env
        configured = environment.get("ATKITS_HOME")
        root = Path(configured).expanduser() if configured else Path.home() / ".atkits"
        return cls(root.resolve())

    @property
    def config_path(self) -> Path:
        return self.path / "config.toml"

    @property
    def state_path(self) -> Path:
        return self.path / "state.json"

    @property
    def registry_path(self) -> Path:
        return self.path / "registry"

    @property
    def catalog_path(self) -> Path:
        return self.registry_path / "catalog.json"

    @property
    def packages_path(self) -> Path:
        return self.path / "packages"

    @property
    def downloads_path(self) -> Path:
        return self.path / "downloads"

    @property
    def backup_path(self) -> Path:
        return self.path / "backup"

    @property
    def locks_path(self) -> Path:
        return self.path / "locks"

    @property
    def logs_path(self) -> Path:
        return self.path / "logs"

    @property
    def tmp_path(self) -> Path:
        return self.path / "tmp"

    def ensure_layout(self) -> None:
        directories = (
            self.path,
            self.registry_path,
            self.packages_path / "skills",
            self.packages_path / "plugins",
            self.downloads_path,
            self.backup_path,
            self.locks_path,
            self.logs_path,
            self.tmp_path,
        )
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)

    def load_config(self) -> dict[str, Any]:
        if not self.config_path.is_file():
            return {}
        with self.config_path.open("rb") as file_handle:
            data = tomllib.load(file_handle)
        if not isinstance(data, dict):
            raise ValueError("atkits config must be a TOML table")
        _reject_token_keys(data)
        return data

    def save_config(self, config: Mapping[str, Any]) -> None:
        if not isinstance(config, Mapping):
            raise ValueError("atkits config must be a mapping")
        _reject_token_keys(config)
        text = _dump_config(config)
        _atomic_write_text(self.config_path, text)

    def lock_path(self, name: str) -> Path:
        return self.locks_path / name


def _reject_token_keys(config: Mapping[str, Any]) -> None:
    for key in config:
        if "token" in str(key).lower():
            raise ValueError("tokens must not be stored in atkits config")


def _dump_config(config: Mapping[str, Any]) -> str:
    lines: list[str] = []
    for key, value in config.items():
        if not isinstance(key, str) or not key or any(char in key for char in "=\n#"):
            raise ValueError(f"invalid config key {key!r}")
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        elif isinstance(value, int | float) and not isinstance(value, bool):
            rendered = str(value)
        elif isinstance(value, str):
            rendered = json.dumps(value, ensure_ascii=False)
        elif isinstance(value, list) and all(isinstance(item, str) for item in value):
            if not value:
                rendered = "[]"
            else:
                rendered = "[" + ", ".join(json.dumps(item) for item in value) + "]"
        else:
            raise ValueError(f"unsupported config value for {key!r}: {value!r}")
        lines.append(f"{key} = {rendered}")
    return "\n".join(lines) + "\n"


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}")
    try:
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
