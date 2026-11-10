"""Atomic, file-locked storage for physical install targets."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import replace
from pathlib import Path

from filelock import FileLock

from atkits.home import AtkitsHome
from atkits.models import InstallTarget

_STATE_SCHEMA_VERSION = 1


class StateError(ValueError):
    """Raised when the on-disk installation state is invalid."""


class StateStore:
    """Persist InstallTarget records in ``~/.atkits/state.json``."""

    def __init__(self, home: AtkitsHome) -> None:
        self.home = home
        self.path = home.state_path
        home.locks_path.mkdir(parents=True, exist_ok=True)
        self.lock = FileLock(home.lock_path("state.lock"))

    def all(self) -> list[InstallTarget]:
        with self.lock:
            data = self._load()
        records = [_decode_target(raw) for raw in data["installs"].values()]
        return sorted(records, key=lambda record: record.key())

    def get_target(
        self, kind: str, name: str, scope: str, project_id: str | None, target_id: str
    ) -> InstallTarget | None:
        key = _state_key(kind, name, scope, project_id, target_id)
        with self.lock:
            data = self._load()
        raw = data["installs"].get(key)
        return _decode_target(raw) if raw is not None else None

    def put(self, record: InstallTarget) -> None:
        with self.lock:
            data = self._load()
            data["installs"][record.key()] = _encode_target(record)
            self._save(data)

    def remove(
        self, kind: str, name: str, scope: str, project_id: str | None, target_id: str
    ) -> None:
        key = _state_key(kind, name, scope, project_id, target_id)
        with self.lock:
            data = self._load()
            if key not in data["installs"]:
                raise KeyError(key)
            del data["installs"][key]
            self._save(data)

    def remove_consumer(
        self,
        kind: str,
        name: str,
        scope: str,
        project_id: str | None,
        target_id: str,
        consumer: str,
    ) -> InstallTarget:
        key = _state_key(kind, name, scope, project_id, target_id)
        with self.lock:
            data = self._load()
            raw = data["installs"].get(key)
            if raw is None:
                raise KeyError(key)
            record = _decode_target(raw)
            if consumer not in record.consumers:
                raise ValueError(f"{consumer} is not a consumer of {key}")
            remaining = tuple(item for item in record.consumers if item != consumer)
            updated = replace(record, consumers=remaining)
            data["installs"][key] = _encode_target(updated)
            self._save(data)
            return updated

    def _load(self) -> dict[str, object]:
        if not self.path.is_file():
            return {"schema_version": _STATE_SCHEMA_VERSION, "installs": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise StateError(f"invalid state JSON: {exc}") from exc
        if data.get("schema_version") != _STATE_SCHEMA_VERSION:
            raise StateError(f"unsupported state schema_version {data.get('schema_version')!r}")
        installs = data.get("installs")
        if not isinstance(installs, dict):
            raise StateError("state 'installs' must be an object")
        return data

    def _save(self, data: dict[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}")
        try:
            temporary.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            os.replace(temporary, self.path)
        finally:
            if temporary.exists():
                temporary.unlink()


def _state_key(kind: str, name: str, scope: str, project_id: str | None, target_id: str) -> str:
    if scope == "project":
        return f"{kind}:{name}:project:{project_id}:{target_id}"
    return f"{kind}:{name}:{scope}:{target_id}"


def _encode_target(record: InstallTarget) -> dict[str, object]:
    return {
        "kind": record.kind,
        "name": record.name,
        "scope": record.scope,
        "project_id": record.project_id,
        "version": record.version,
        "target_id": record.target_id,
        "path": str(record.path),
        "strategy": record.strategy,
        "consumers": list(record.consumers),
        "package_path": None if record.package_path is None else str(record.package_path),
        "source_path": None if record.source_path is None else str(record.source_path),
        "artifact_sha256": record.artifact_sha256,
        "content_sha256": record.content_sha256,
    }


def _decode_target(raw: object) -> InstallTarget:
    if not isinstance(raw, dict):
        raise StateError("install target must be an object")
    try:
        return InstallTarget(
            kind=raw["kind"],
            name=raw["name"],
            scope=raw["scope"],
            project_id=raw["project_id"],
            version=raw["version"],
            target_id=raw["target_id"],
            path=Path(raw["path"]),
            strategy=raw["strategy"],
            consumers=tuple(raw["consumers"]),
            package_path=None if raw.get("package_path") is None else Path(raw["package_path"]),
            source_path=None if raw.get("source_path") is None else Path(raw["source_path"]),
            artifact_sha256=raw.get("artifact_sha256"),
            content_sha256=raw.get("content_sha256"),
        )
    except KeyError as exc:
        raise StateError(f"install target is missing {exc.args[0]}") from exc
