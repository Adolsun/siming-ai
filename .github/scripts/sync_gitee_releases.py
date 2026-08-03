"""Mirror published GitHub Releases and their uploaded assets to Gitee."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from urllib.parse import quote

import requests


GITHUB_API = "https://api.github.com"
GITEE_API = "https://gitee.com/api/v5"
TIMEOUT = 60


def required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


github_repository = required_env("GITHUB_REPOSITORY")
github_token = required_env("GITHUB_TOKEN")
gitee_token = required_env("GITEE_TOKEN")
gitee_owner = required_env("GITEE_OWNER")
gitee_repo = required_env("GITEE_REPO")

github = requests.Session()
github.headers.update(
    {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {github_token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "siming-ai-gitee-mirror",
    }
)

gitee = requests.Session()
gitee.headers.update({"User-Agent": "siming-ai-gitee-mirror"})


def checked(response: requests.Response) -> requests.Response:
    if not response.ok:
        detail = response.text[:1000]
        raise RuntimeError(
            f"API request failed: {response.request.method} {response.url} "
            f"returned {response.status_code}: {detail}"
        )
    return response


def gitee_request(method: str, path: str, **kwargs) -> requests.Response:
    params = dict(kwargs.pop("params", {}))
    params["access_token"] = gitee_token
    response = gitee.request(
        method,
        f"{GITEE_API}{path}",
        params=params,
        timeout=TIMEOUT,
        **kwargs,
    )
    return checked(response)


def github_releases() -> list[dict]:
    releases: list[dict] = []
    page = 1
    while True:
        response = checked(
            github.get(
                f"{GITHUB_API}/repos/{github_repository}/releases",
                params={"per_page": 100, "page": page},
                timeout=TIMEOUT,
            )
        )
        batch = response.json()
        releases.extend(batch)
        if len(batch) < 100:
            return releases
        page += 1


def find_gitee_release(tag_name: str) -> dict | None:
    response = gitee.get(
        f"{GITEE_API}/repos/{gitee_owner}/{gitee_repo}/releases/tags/{quote(tag_name, safe='')}",
        params={"access_token": gitee_token},
        timeout=TIMEOUT,
    )
    if response.status_code == 404:
        return None
    return checked(response).json()


def upsert_gitee_release(release: dict) -> dict:
    payload = {
        "tag_name": release["tag_name"],
        "name": release["name"] or release["tag_name"],
        "body": release["body"] or "",
        "prerelease": bool(release["prerelease"]),
        "target_commitish": release["target_commitish"],
    }
    existing = find_gitee_release(release["tag_name"])
    base_path = f"/repos/{gitee_owner}/{gitee_repo}/releases"
    if existing is None:
        print(f"Creating Gitee release {release['tag_name']}")
        return gitee_request("POST", base_path, json=payload).json()

    print(f"Updating Gitee release {release['tag_name']}")
    update_payload = {
        key: payload[key] for key in ("tag_name", "name", "body", "prerelease")
    }
    return gitee_request(
        "PATCH", f"{base_path}/{existing['id']}", json=update_payload
    ).json()


def sync_assets(github_release: dict, gitee_release: dict) -> None:
    base_path = (
        f"/repos/{gitee_owner}/{gitee_repo}/releases/{gitee_release['id']}/attach_files"
    )
    existing_assets = {
        item["name"]: item for item in gitee_request("GET", base_path).json()
    }

    for asset in github_release.get("assets", []):
        existing = existing_assets.get(asset["name"])
        if existing and int(existing.get("size", -1)) == int(asset["size"]):
            print(f"Asset already current: {github_release['tag_name']}/{asset['name']}")
            continue
        if existing:
            print(f"Replacing changed asset: {github_release['tag_name']}/{asset['name']}")
            gitee_request("DELETE", f"{base_path}/{existing['id']}")

        print(f"Uploading asset: {github_release['tag_name']}/{asset['name']}")
        with tempfile.TemporaryDirectory() as temp_dir:
            asset_path = Path(temp_dir) / asset["name"]
            with checked(
                github.get(asset["url"], stream=True, timeout=TIMEOUT)
            ) as download:
                with asset_path.open("wb") as output:
                    for chunk in download.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            output.write(chunk)
            with asset_path.open("rb") as upload:
                gitee_request(
                    "POST",
                    base_path,
                    files={"file": (asset["name"], upload, "application/octet-stream")},
                )


def main() -> None:
    releases = github_releases()
    published = [release for release in releases if not release["draft"]]
    print(f"Found {len(published)} published GitHub releases")
    for release in reversed(published):
        gitee_release = upsert_gitee_release(release)
        sync_assets(release, gitee_release)


if __name__ == "__main__":
    main()
