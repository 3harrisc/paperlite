"""Check GitHub Releases for a newer version and install it.

Publishing an update = push a tag like ``v0.3.0``. The GitHub Actions workflow
builds the installer and attaches it to a Release. Installed copies see it on
their next start (at most once a day), download the installer and run it
silently; Inno Setup upgrades in place and reopens the app.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass

USER_AGENT = "PaperLite-Updater"


@dataclass
class Update:
    version: str
    notes: str
    download_url: str
    size: int
    page_url: str


def parse_version(v: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", v)
    return tuple(int(n) for n in nums[:4]) or (0,)


def is_newer(latest: str, current: str) -> bool:
    return parse_version(latest) > parse_version(current)


def check(repo: str, current: str, timeout: float = 8) -> Update | None:
    """Return the newer release, or None if up to date. Raises on network errors."""
    if not repo:
        return None
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/releases/latest",
        headers={"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.load(r)
    tag = data.get("tag_name", "")
    if not is_newer(tag, current):
        return None
    asset = next((a for a in data.get("assets", []) if a["name"].lower().endswith(".exe")), None)
    if not asset:
        return None
    return Update(tag.lstrip("v"), data.get("body") or "", asset["browser_download_url"], asset.get("size", 0),
                  data.get("html_url", ""))


def download(update: Update, progress=None) -> str:
    """Download the installer to a temp file and return its path."""
    path = os.path.join(tempfile.gettempdir(), f"PaperLite-PDF-Setup-{update.version}.exe")
    req = urllib.request.Request(update.download_url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r, open(path + ".part", "wb") as f:
        total = int(r.headers.get("Content-Length") or update.size or 0)
        done = 0
        while chunk := r.read(256 * 1024):
            f.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    os.replace(path + ".part", path)
    return path


def launch_installer(path: str) -> None:
    """Start the installer silently. The caller should quit straight after."""
    if sys.platform != "win32":
        raise RuntimeError("Automatic install is only available on Windows.")
    subprocess.Popen([path, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"], close_fds=True)
