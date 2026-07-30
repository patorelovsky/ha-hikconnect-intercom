"""Download and cache a MediaMTX (https://github.com/bluenviron/mediamtx)
binary matching the current host OS/architecture.

MediaMTX is a small, dependency-free, MIT-licensed RTSP/RTP server. It is
used here instead of relying on ffmpeg's own "-rtsp_flags listen" muxer
option, which turned out to be decode-only (input/demuxer side) in modern
ffmpeg builds and does not actually make ffmpeg act as an RTSP server for
output. MediaMTX is a proven, minimal RTSP server: ffmpeg *pushes*
(publishes) the decrypted stream into it as a regular RTSP client, and
Home Assistant's camera then *pulls* (plays) it back from MediaMTX as a
regular RTSP client too.

The binary is downloaded once from MediaMTX's GitHub releases and cached
under Home Assistant's own persistent storage directory, so it survives
integration updates/restarts and does not need to be bundled in the HACS
repository (keeping the git repo small and avoiding multi-arch binary
bloat).
"""

from __future__ import annotations

import logging
import platform
import stat
import tarfile
import zipfile
from pathlib import Path

import requests

_LOGGER = logging.getLogger(__name__)

MEDIAMTX_VERSION = "v1.19.3"
_RELEASES_BASE = f"https://github.com/bluenviron/mediamtx/releases/download/{MEDIAMTX_VERSION}"


def _os_name() -> str:
    system = platform.system().lower()
    if system == "darwin":
        return "darwin"
    if system == "windows":
        return "windows"
    return "linux"


def _arch_name() -> str:
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "amd64"
    if machine in ("aarch64", "arm64"):
        return "arm64"
    if machine.startswith("armv7") or machine == "armv7l":
        return "armv7"
    if machine.startswith("armv6") or machine == "armv6l":
        return "armv6"
    if machine in ("i386", "i686", "x86"):
        return "386"
    raise RuntimeError(f"Unsupported architecture for MediaMTX: {machine}")


def _asset_name() -> str:
    os_name = _os_name()
    arch = _arch_name()
    ext = "zip" if os_name == "windows" else "tar.gz"
    return f"mediamtx_{MEDIAMTX_VERSION}_{os_name}_{arch}.{ext}"


def ensure_mediamtx(storage_dir: Path) -> Path:
    """Return a path to a working MediaMTX executable, downloading it into
    ``storage_dir`` if it isn't already cached there. Safe to call from a
    worker thread (blocking I/O)."""
    storage_dir.mkdir(parents=True, exist_ok=True)
    exe_name = "mediamtx.exe" if _os_name() == "windows" else "mediamtx"
    exe_path = storage_dir / exe_name
    if exe_path.exists():
        return exe_path

    asset = _asset_name()
    url = f"{_RELEASES_BASE}/{asset}"
    _LOGGER.info("Downloading MediaMTX (%s) from %s", asset, url)
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()

    archive_path = storage_dir / asset
    archive_path.write_bytes(resp.content)
    try:
        if asset.endswith(".zip"):
            with zipfile.ZipFile(archive_path) as zf:
                zf.extractall(storage_dir)
        else:
            with tarfile.open(archive_path, "r:gz") as tf:
                tf.extractall(storage_dir)  # noqa: S202 - trusted, pinned release asset
    finally:
        archive_path.unlink(missing_ok=True)

    if not exe_path.exists():
        raise RuntimeError(f"MediaMTX archive did not contain expected {exe_name}")
    if _os_name() != "windows":
        exe_path.chmod(exe_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    _LOGGER.info("MediaMTX ready at %s", exe_path)
    return exe_path
