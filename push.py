from __future__ import annotations

import base64
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from config import TARGET_REPOSITORY, TARGET_REPOSITORY_SLUG, Settings


def _run_git(settings: Settings, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if settings.github_token:
        token = base64.b64encode(f"x-access-token:{settings.github_token}".encode()).decode()
        env.update({
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.extraHeader",
            "GIT_CONFIG_VALUE_0": f"Authorization: Basic {token}",
        })
    return subprocess.run(
        ["git", "-C", str(settings.root), *args],
        env=env,
        text=True,
        capture_output=True,
        check=check,
    )


def _verify_remote(settings: Settings) -> None:
    remote = _run_git(settings, ["config", "--get", "remote.origin.url"]).stdout.strip()
    normalised = remote.removesuffix("/").removesuffix(".git").lower()
    expected = TARGET_REPOSITORY.removesuffix(".git").lower()
    if normalised != expected:
        raise RuntimeError(f"Refusing to push: origin is {remote!r}, expected {TARGET_REPOSITORY!r}")


def prepare_repository(settings: Settings) -> None:
    _verify_remote(settings)
    result = _run_git(settings, ["pull", "--rebase", "origin", "main"], check=False)
    if result.returncode:
        raise RuntimeError(f"git pull failed: {result.stderr.strip()}")


def commit_and_push(settings: Settings) -> bool:
    _verify_remote(settings)
    _run_git(settings, ["config", "user.name", "github-actions[bot]"])
    _run_git(settings, ["config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"])
    _run_git(settings, ["add", "--", "data/sxbet"])
    staged = _run_git(settings, ["diff", "--cached", "--quiet"], check=False)
    if staged.returncode == 0:
        print(f"No data changes for {TARGET_REPOSITORY_SLUG}")
        return False
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    _run_git(settings, ["commit", "-m", f"Update soccer trades {timestamp}"])
    result = _run_git(settings, ["push", "origin", "main"], check=False)
    if result.returncode:
        raise RuntimeError(f"git push failed: {result.stderr.strip()}")
    print(f"Pushed data to {TARGET_REPOSITORY_SLUG}")
    return True
