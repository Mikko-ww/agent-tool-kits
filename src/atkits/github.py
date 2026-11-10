"""Minimal GitHub Releases client with cross-host Authorization protection."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlsplit


class GitHubError(RuntimeError):
    """Base error for GitHub API requests."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class GitHubAuthenticationError(GitHubError):
    pass


class GitHubPermissionError(GitHubError):
    pass


class GitHubNotFoundError(GitHubError):
    pass


class GitHubRateLimitError(GitHubError):
    pass


class GitHubNetworkError(GitHubError):
    pass


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        request = super().redirect_request(req, fp, code, msg, headers, newurl)
        if request is None:
            return None
        old_host = urlsplit(req.full_url).netloc
        new_host = urlsplit(newurl).netloc
        if old_host != new_host:
            for header_map in (request.headers, request.unredirected_hdrs):
                header_map.pop("Authorization", None)
        return request


class GitHubReleaseClient:
    """A small GitHub Releases REST client used by atkits."""

    def __init__(
        self,
        repo: str,
        *,
        token: str | None = None,
        base_url: str = "https://api.github.com",
        timeout: float = 20,
    ) -> None:
        self.repo = repo
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.opener = urllib.request.build_opener(_SafeRedirectHandler)

    def get_release_by_tag(self, tag: str) -> dict[str, object]:
        data = self._request_json(f"/repos/{self.repo}/releases/tags/{tag}")
        if not isinstance(data, dict):
            raise GitHubError("GitHub release response must be an object")
        return data

    def download_asset(self, asset_id: int, destination: Path) -> None:
        data = self._request_bytes(
            f"/repos/{self.repo}/releases/assets/{asset_id}",
            accept="application/octet-stream",
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(
            f".{destination.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}"
        )
        try:
            temporary.write_bytes(data)
            os.replace(temporary, destination)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _request_json(self, path: str) -> object:
        data = self._request_bytes(path, accept="application/vnd.github+json")
        try:
            return json.loads(data)
        except json.JSONDecodeError as exc:
            raise GitHubError("GitHub response is not valid JSON") from exc

    def _request_bytes(self, path: str, *, accept: str) -> bytes:
        request = urllib.request.Request(
            self.base_url + path,
            headers={
                "Accept": accept,
                "User-Agent": "atkits",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            method="GET",
        )
        if self.token is not None:
            request.add_header("Authorization", f"Bearer {self.token}")
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            raise self._map_http_error(exc) from exc
        except urllib.error.URLError as exc:
            raise GitHubNetworkError(f"GitHub request failed: {exc.reason}") from exc

    def _map_http_error(self, exc: urllib.error.HTTPError) -> GitHubError:
        status = exc.code
        reason = exc.reason
        if status == 401:
            return GitHubAuthenticationError(
                f"GitHub authentication failed: {reason}", status=status
            )
        if status == 403:
            return GitHubPermissionError(f"GitHub permission denied: {reason}", status=status)
        if status == 404:
            return GitHubNotFoundError(f"GitHub resource not found: {reason}", status=status)
        if status == 429:
            return GitHubRateLimitError(f"GitHub rate limit exceeded: {reason}", status=status)
        return GitHubError(f"GitHub request failed: {reason}", status=status)
