import dataclasses
import hashlib
import io
import json
import tarfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from collections.abc import Callable
from types import SimpleNamespace
from typing import Iterator

import pytest

from atkits.home import AtkitsHome
from atkits.github import GitHubNetworkError
from atkits.models import AssetVersion, Catalog, InstallTarget
from atkits.packages import PackageStore
from atkits.registry import RegistryClient


def _create_archive(path: Path, entries: dict[str, bytes]) -> Path:
    with tarfile.open(path, "w:gz") as archive:
        for name, data in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return path


@pytest.fixture
def catalog_data() -> dict[str, object]:
    return {
        "schema_version": 1,
        "skills": {
            "foo": {
                "latest": "1.1.0",
                "versions": {
                    "1.0.0": {
                        "asset_id": 10001,
                        "archive": "foo-1.0.0.tar.gz",
                        "sha256": "0" * 64,
                    },
                    "1.1.0": {
                        "asset_id": 10002,
                        "archive": "foo-1.1.0.tar.gz",
                        "sha256": "1" * 64,
                    },
                    "1.2.0-beta.1": {
                        "asset_id": 10003,
                        "archive": "foo-1.2.0-beta.1.tar.gz",
                        "sha256": "2" * 64,
                    },
                },
            }
        },
    }


@pytest.fixture
def catalog(catalog_data: dict[str, object]) -> Catalog:
    return Catalog(catalog_data)


@pytest.fixture
def install_target() -> InstallTarget:
    return InstallTarget(
        kind="skill",
        name="foo",
        scope="global",
        project_id=None,
        version="1.1.0",
        target_id="agents",
        path=Path("/home/user/.agents/skills/foo"),
        strategy="symlink",
        consumers=("codex",),
        package_path=Path("packages/skills/foo/1.1.0"),
        artifact_sha256="1" * 64,
        content_sha256="2" * 64,
    )


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AtkitsHome:
    root = tmp_path / "atkits"
    monkeypatch.setenv("ATKITS_HOME", str(root))
    result = AtkitsHome.discover()
    result.ensure_layout()
    return result


@pytest.fixture
def project_install_target(install_target: InstallTarget) -> InstallTarget:
    return dataclasses.replace(
        install_target,
        scope="project",
        project_id="a" * 64,
        path=Path("/tmp/project-a/.agents/skills/foo"),
    )


@pytest.fixture
def other_project_install_target(install_target: InstallTarget) -> InstallTarget:
    return dataclasses.replace(
        install_target,
        scope="project",
        project_id="b" * 64,
        path=Path("/tmp/project-b/.agents/skills/foo"),
    )


class FakeHTTPServer:
    def __init__(self) -> None:
        self.routes: dict[str, tuple[int, bytes, dict[str, str]]] = {}
        self.requests: list[dict[str, object]] = []
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeHTTPHandler)
        self._server.fake = self  # type: ignore[attr-defined]
        self._thread = Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def set_route(
        self, path: str, status: int, body: bytes, headers: dict[str, str] | None = None
    ) -> None:
        self.routes[path] = (status, body, headers or {})

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)


class _FakeHTTPHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        server = self.server.fake  # type: ignore[attr-defined]
        headers = {key: value for key, value in self.headers.items()}
        server.requests.append(
            SimpleNamespace(method=self.command, path=self.path, headers=headers)
        )
        route = server.routes.get(self.path)
        if route is None:
            self.send_response(404)
            self.end_headers()
            return
        status, body, extra_headers = route
        self.send_response(status)
        for key, value in extra_headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


@pytest.fixture
def http_server(catalog_data: dict[str, object]) -> Iterator[FakeHTTPServer]:
    server = FakeHTTPServer()
    server.set_route(
        "/repos/owner/repo/releases/assets/42",
        302,
        b"",
        {"Location": f"http://localhost:{server._server.server_address[1]}/asset-download"},
    )
    server.set_route("/asset-download", 200, b"asset-content")
    server.set_route(
        "/repos/owner/repo/releases/assets/52",
        200,
        json.dumps(catalog_data).encode(),
        {"Content-Type": "application/json"},
    )
    server.set_route(
        "/repos/owner/repo/releases/tags/registry",
        200,
        json.dumps({"assets": [{"id": 52, "name": "catalog.json"}]}).encode(),
        {"Content-Type": "application/json"},
    )
    server.start()
    try:
        yield server
    finally:
        server.stop()


class FakeGitHubClient:
    def __init__(self, release: dict[str, object], catalog_text: str) -> None:
        self.release = release
        self.catalog_text = catalog_text
        self.offline = False

    def set_offline(self, value: bool) -> None:
        self.offline = value

    def get_release_by_tag(self, tag: str) -> dict[str, object]:
        if self.offline:
            raise GitHubNetworkError("offline")
        return self.release

    def download_asset(self, asset_id: int, destination: Path) -> None:
        if self.offline:
            raise GitHubNetworkError("offline")
        destination.write_text(self.catalog_text, encoding="utf-8")


class FakeRegistryClient(RegistryClient):
    def set_offline(self, value: bool) -> None:
        self.github.offline = value


@pytest.fixture
def fake_registry(home: AtkitsHome, catalog_data: dict[str, object]) -> FakeRegistryClient:
    catalog_text = json.dumps(catalog_data)
    home.catalog_path.parent.mkdir(parents=True, exist_ok=True)
    home.catalog_path.write_text(catalog_text, encoding="utf-8")
    release = {"assets": [{"id": 42, "name": "catalog.json"}]}
    return FakeRegistryClient(home, FakeGitHubClient(release, catalog_text))


@pytest.fixture
def package_store(home: AtkitsHome) -> PackageStore:
    return PackageStore(home)


@pytest.fixture
def valid_archive(tmp_path: Path) -> Path:
    return _create_archive(
        tmp_path / "foo-1.1.0.tar.gz",
        {
            "foo/SKILL.md": (
                b"---\n"
                b"name: foo\n"
                b"description: test skill\n"
                b"metadata:\n"
                b"  version: 1.1.0\n"
                b"---\n"
                b"# foo\n"
            )
        },
    )


@pytest.fixture
def asset(valid_archive: Path) -> AssetVersion:
    digest = hashlib.sha256(valid_archive.read_bytes()).hexdigest()
    return AssetVersion(
        kind="skill",
        name="foo",
        version="1.1.0",
        asset_id=10002,
        archive="foo-1.1.0.tar.gz",
        sha256=digest,
    )


@pytest.fixture
def write_valid_archive(valid_archive: Path) -> Callable[[AssetVersion], Path]:
    return lambda _asset: valid_archive


@pytest.fixture
def write_corrupted_archive(tmp_path: Path) -> Callable[[AssetVersion], Path]:
    path = tmp_path / "corrupted.tar.gz"
    path.write_bytes(b"not really a tarball")
    return lambda _asset: path


@pytest.fixture
def malicious_archive(tmp_path: Path) -> Path:
    return _create_archive(tmp_path / "malicious.tar.gz", {"../evil.txt": b"bad"})


@pytest.fixture
def symlink_archive(tmp_path: Path) -> Path:
    path = tmp_path / "symlink.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        info = tarfile.TarInfo("foo/link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        archive.addfile(info)
    return path


@pytest.fixture
def wrong_version_archive(tmp_path: Path) -> Path:
    return _create_archive(
        tmp_path / "wrong.tar.gz",
        {
            "foo/SKILL.md": (
                b"---\nname: foo\ndescription: test skill\nmetadata:\n  version: 1.0.0\n---\n"
            )
        },
    )


@pytest.fixture
def wrong_asset(valid_archive: Path) -> AssetVersion:
    digest = hashlib.sha256(valid_archive.read_bytes()).hexdigest()
    return AssetVersion(
        kind="skill",
        name="foo",
        version="9.9.9",
        asset_id=10099,
        archive="foo-9.9.9.tar.gz",
        sha256=digest,
    )


@pytest.fixture
def platform_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / "home"
    cwd = tmp_path / "project"
    xdg_config = tmp_path / "xdg"
    home.mkdir()
    cwd.mkdir()
    xdg_config.mkdir()
    env = {
        "HOME": str(home),
        "USERPROFILE": str(home),
        "XDG_CONFIG_HOME": str(xdg_config),
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "CODEX_HOME": str(home / ".codex"),
        "CLAUDE_CONFIG_DIR": str(home / ".claude"),
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    registry = {
        "schema_version": 1,
        "platforms": [
            {
                "id": "codex",
                "display_name": "Codex",
                "project_paths": [
                    {"id": "agents", "template": ".agents/skills", "role": "primary"}
                ],
                "global_paths": [
                    {"id": "agents", "template": "$HOME/.agents/skills", "role": "primary"}
                ],
                "detect": [{"type": "path", "template": "$HOME/.codex"}],
            },
            {
                "id": "cursor",
                "display_name": "Cursor",
                "project_paths": [
                    {"id": "agents", "template": ".agents/skills", "role": "shared"},
                    {"id": "cursor", "template": ".cursor/skills", "role": "primary"},
                ],
                "global_paths": [
                    {"id": "agents", "template": "$HOME/.agents/skills", "role": "shared"},
                    {"id": "cursor", "template": "$HOME/.cursor/skills", "role": "primary"},
                ],
                "detect": [{"type": "path", "template": "$HOME/.cursor"}],
            },
            {
                "id": "opencode",
                "display_name": "OpenCode",
                "project_paths": [
                    {"id": "agents", "template": ".agents/skills", "role": "shared"},
                    {"id": "opencode", "template": ".opencode/skills", "role": "primary"},
                ],
                "global_paths": [
                    {
                        "id": "agents",
                        "template": "$HOME/.agents/skills",
                        "role": "compatibility",
                    },
                    {
                        "id": "opencode",
                        "template": "$XDG_CONFIG_HOME/opencode/skills",
                        "role": "primary",
                    },
                ],
                "detect": [{"type": "path", "template": "$XDG_CONFIG_HOME/opencode"}],
            },
            {
                "id": "example-windows-only",
                "display_name": "Example Windows Only",
                "project_paths": [
                    {"id": "example", "template": ".example/skills", "role": "primary"}
                ],
                "global_paths": [
                    {
                        "id": "example",
                        "template": "$APPDATA/example/skills",
                        "role": "primary",
                        "os": ["windows"],
                    }
                ],
                "detect": [],
            },
        ],
    }
    registry_path = tmp_path / "platform_registry.json"
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    monkeypatch.setenv("ATKITS_PLATFORM_REGISTRY", str(registry_path))
    return SimpleNamespace(
        home=home,
        cwd=cwd,
        env=env,
        xdg_config=xdg_config,
        registry_path=registry_path,
    )
