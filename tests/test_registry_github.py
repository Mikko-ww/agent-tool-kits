import pytest

from atkits.github import (
    GitHubAuthenticationError,
    GitHubReleaseClient,
    GitHubNotFoundError,
    GitHubPermissionError,
    GitHubRateLimitError,
)
from atkits.registry import RegistryClient


def test_private_asset_download_strips_token_on_cross_host_redirect(http_server, home):
    client = GitHubReleaseClient("owner/repo", token="secret", base_url=http_server.url)
    destination = home.downloads_path / "asset.tar.gz"
    client.download_asset(42, destination)

    assert destination.read_bytes() == b"asset-content"
    assert http_server.requests[0].path == "/repos/owner/repo/releases/assets/42"
    assert http_server.requests[0].headers["Authorization"] == "Bearer secret"
    assert http_server.requests[0].headers["Accept"] == "application/octet-stream"
    assert "Authorization" not in http_server.requests[1].headers


def test_registry_refresh_replaces_catalog_atomically(home, http_server):
    client = GitHubReleaseClient("owner/repo", token="secret", base_url=http_server.url)
    registry = RegistryClient(home, client, release_tag="registry")
    catalog = registry.refresh()

    assert catalog.latest("skill", "foo").version == "1.1.0"
    assert home.catalog_path.is_file()
    assert not list(home.tmp_path.glob("catalog.json.tmp*"))


def test_offline_registry_uses_cached_catalog(fake_registry):
    fake_registry.set_offline(True)
    catalog = fake_registry.cached()
    assert catalog.latest("skill", "foo").version == "1.1.0"


def test_registry_resolve_latest_and_exact_version(fake_registry):
    assert fake_registry.resolve("skill", "foo").version == "1.1.0"
    assert fake_registry.resolve("skill", "foo", "1.0.0").version == "1.0.0"


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, GitHubAuthenticationError),
        (403, GitHubPermissionError),
        (404, GitHubNotFoundError),
        (429, GitHubRateLimitError),
    ],
)
def test_github_errors_are_mapped(http_server, home, status, expected):
    client = GitHubReleaseClient("owner/repo", token="secret", base_url=http_server.url)
    http_server.set_route(
        "/repos/owner/repo/releases/assets/43",
        status,
        b"error",
    )
    with pytest.raises(expected):
        client.download_asset(43, home.downloads_path / "broken")
