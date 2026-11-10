#!/usr/bin/env bash
set -euo pipefail

if ! command -v uv >/dev/null 2>&1; then
  echo "未找到 uv。请先安装 uv：https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi

TOKEN="${ATKITS_GITHUB_TOKEN:-${GITHUB_TOKEN:-${GH_TOKEN:-}}}"
if [[ -z "$TOKEN" ]]; then
  echo "缺少 GitHub token。请设置 ATKITS_GITHUB_TOKEN、GITHUB_TOKEN 或 GH_TOKEN。" >&2
  exit 1
fi

REPO="${ATKITS_REGISTRY_REPO:-Mikko-ww/agent-tool-kits}"

WHEEL="$(python3 - "$TOKEN" "$REPO" <<'PY'
import hashlib
import json
import re
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

token = sys.argv[1]
repo = sys.argv[2]
headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "atkits-installer",
}
url = f"https://api.github.com/repos/{repo}/releases?per_page=100"
request = urllib.request.Request(url, headers=headers)
try:
    with urllib.request.urlopen(request, timeout=30) as response:
        releases = json.load(response)
except urllib.error.HTTPError as exc:
    raise SystemExit(f"无法读取 GitHub Releases：HTTP {exc.code}") from exc

cli_releases = []
for release in releases:
    tag = release.get("tag_name", "")
    if tag.startswith("cli-v"):
        cli_releases.append((tag.removeprefix("cli-v"), release))
if not cli_releases:
    raise SystemExit("没有找到 CLI Release")


def version_key(value: str):
    numbers = [int(part) for part in re.findall(r"\d+", value)[:3]]
    while len(numbers) < 3:
        numbers.append(0)
    return tuple(numbers)


version, release = max(cli_releases, key=lambda item: version_key(item[0]))
assets = release.get("assets", [])
wheel_asset = next((asset for asset in assets if asset.get("name", "").endswith(".whl")), None)
if wheel_asset is None:
    raise SystemExit(f"Release {release.get('tag_name')} 没有 wheel 资产")

asset_id = wheel_asset["id"]
asset_url = f"https://api.github.com/repos/{repo}/releases/assets/{asset_id}"
request = urllib.request.Request(
    asset_url,
    headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/octet-stream",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "atkits-installer",
    },
)
try:
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read()
except urllib.error.HTTPError as exc:
    raise SystemExit(f"无法下载 CLI wheel：HTTP {exc.code}") from exc

digest = wheel_asset.get("sha256") or wheel_asset.get("digest")
if isinstance(digest, str) and digest.startswith("sha256:"):
    digest = digest.removeprefix("sha256:")
if not isinstance(digest, str) or not digest:
    raise SystemExit("GitHub Release 资产缺少 sha256/digest，拒绝安装")
actual_hash = hashlib.sha256(data).hexdigest()
if actual_hash != digest:
    raise SystemExit(
        f"CLI wheel 校验失败：expected {digest}, got {actual_hash}"
    )

with tempfile.NamedTemporaryFile(
    prefix=f"atkits-{version}-", suffix=".whl", delete=False
) as file_handle:
    file_handle.write(data)
    destination = Path(file_handle.name)
print(destination)
PY
)"

uv tool install --force "$WHEEL"
rm -f "$WHEEL"
atkits --version
