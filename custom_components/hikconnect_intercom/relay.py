"""Core Hik-Connect cloud video relay logic.

Reverse-engineered, unofficial use of the Hik-Connect cloud VTM (Video
Transfer Module) relay - the same mechanism the Hik-Connect mobile app
uses for live view. This bypasses devices that expose zero local network
services by pulling video via the cloud instead.

This module is intentionally synchronous/blocking; it is always driven
from a dedicated background thread (see HikConnectRelay.start()), never
directly from Home Assistant's asyncio event loop.
"""

from __future__ import annotations

import hashlib
import logging
import subprocess
import threading
import time
from typing import Any

import requests

from pyezvizapi.client import EzvizClient
from pyezvizapi.cloud_stream import open_cloud_stream
from pyezvizapi.stream import decrypt_hikvision_ps_video

from .const import AUTH_BASE, FEATURE_CODE, LOGIN_URL

_LOGGER = logging.getLogger(__name__)


def hik_connect_login(email: str, password: str) -> str:
    """Log in to the Hik-Connect regional API and return a session id (JWT)."""
    pwd_md5 = hashlib.md5(password.encode()).hexdigest()  # noqa: S324 - required by Hik-Connect's own API
    headers = {
        "clientType": "55",
        "lang": "en-US",
        "featureCode": FEATURE_CODE,
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {"account": email, "password": pwd_md5}
    resp = requests.post(LOGIN_URL, headers=headers, data=data, timeout=15)
    resp.raise_for_status()
    body = resp.json()
    code = body.get("meta", {}).get("code")
    if code == 200:
        return body["loginSession"]["sessionId"]
    raise RuntimeError(f"Hik-Connect login failed (code={code}): {body}")


def build_ezviz_client(session_id: str, email: str) -> EzvizClient:
    """Build a pyezvizapi client bound to the Hik-Connect Slovakia region.

    The account's own /v3/configurations/system/info reports a broken
    "https://null" authAddr, so the auth/token base URL is pre-populated
    manually with the working euauth.ezvizlife.com endpoint.
    """
    token = {
        "session_id": session_id,
        "rf_session_id": None,
        "username": email,
        "api_url": "apiieu.hik-connect.com",
        "feature_code": FEATURE_CODE,
        "service_urls": {"authAddr": AUTH_BASE},
    }
    return EzvizClient(token=token)


def _rtp_payload(body: bytes) -> tuple[int | None, bytes | None]:
    """Strip a 12+ byte RTP header from a VTM STREAM-channel packet body."""
    if len(body) < 12:
        return None, None
    b0 = body[0]
    if b0 >> 6 != 2:  # RTP version 2
        return None, None
    csrc_count = b0 & 0x0F
    has_ext = (b0 >> 4) & 0x01
    seq = int.from_bytes(body[2:4], "big")
    off = 12 + 4 * csrc_count
    if has_ext:
        if off + 4 > len(body):
            return seq, None
        ext_len_words = int.from_bytes(body[off + 2 : off + 4], "big")
        off += 4 + 4 * ext_len_words
    if off > len(body):
        return seq, None
    return seq, body[off:]


class _H264Depacketizer:
    """Incremental RFC 6184 depacketizer.

    Feed RTP payloads in sequence order, get back complete Annex-B NAL
    units as soon as they finish (single NAL, STAP-A aggregation, or
    FU-A fragmentation).
    """

    def __init__(self) -> None:
        self._fu: bytearray | None = None

    def feed(self, payload: bytes) -> list[bytes]:
        if not payload:
            return []
        nal_type = payload[0] & 0x1F
        out: list[bytes] = []
        if 1 <= nal_type <= 23:
            out.append(payload)
        elif nal_type == 24:  # STAP-A
            p = payload[1:]
            while len(p) > 2:
                sz = int.from_bytes(p[0:2], "big")
                nal = p[2 : 2 + sz]
                if len(nal) == sz:
                    out.append(nal)
                p = p[2 + sz :]
        elif nal_type == 28:  # FU-A
            fu_header = payload[1]
            start_bit = (fu_header >> 7) & 1
            end_bit = (fu_header >> 6) & 1
            orig_type = fu_header & 0x1F
            if start_bit:
                nal_header_byte = (payload[0] & 0xE0) | orig_type
                self._fu = bytearray([nal_header_byte]) + bytearray(payload[2:])
            elif self._fu is not None:
                self._fu += payload[2:]
            if end_bit and self._fu is not None:
                out.append(bytes(self._fu))
                self._fu = None
        return out


class _FfmpegRtspServerSink:
    """Feeds a raw Annex-B H.264 stream into an ffmpeg subprocess that acts
    as its own tiny RTSP server (``-rtsp_flags listen``), so no separate
    RTSP server binary (e.g. MediaMTX) is required. ffmpeg already ships
    with Home Assistant.
    """

    def __init__(self, rtsp_url: str, ffmpeg_path: str = "ffmpeg") -> None:
        self._rtsp_url = rtsp_url
        self._ffmpeg_path = ffmpeg_path
        self._proc: subprocess.Popen | None = None

    def _ensure_started(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return
        if self._proc is not None:
            _LOGGER.warning("ffmpeg exited (code %s); restarting", self._proc.returncode)
        self._proc = subprocess.Popen(  # noqa: S603 - fixed argv, no shell, no user-controlled binary path
            [
                self._ffmpeg_path, "-y", "-loglevel", "warning",
                "-f", "h264", "-i", "-",
                "-c", "copy", "-f", "rtsp", "-rtsp_flags", "listen",
                self._rtsp_url,
            ],
            stdin=subprocess.PIPE,
        )
        _LOGGER.info("ffmpeg RTSP server started (pid %s) at %s", self._proc.pid, self._rtsp_url)

    def write(self, data: bytes) -> None:
        self._ensure_started()
        assert self._proc is not None and self._proc.stdin is not None
        try:
            self._proc.stdin.write(data)
        except (BrokenPipeError, OSError):
            _LOGGER.warning("ffmpeg pipe broke; will restart on next write")
            self._proc = None

    def flush(self) -> None:
        if self._proc is not None and self._proc.stdin is not None:
            try:
                self._proc.stdin.flush()
            except (BrokenPipeError, OSError):
                self._proc = None

    def stop(self) -> None:
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None


class HikConnectRelay:
    """Manages the full cloud-pull-decrypt-republish pipeline for one
    intercom channel, running in a dedicated background thread.
    """

    def __init__(
        self,
        email: str,
        password: str,
        serial: str,
        channel: int,
        media_key: str,
        rtsp_port: int,
    ) -> None:
        self._email = email
        self._password = password
        self._serial = serial
        self._channel = channel
        self._media_key = media_key
        self.rtsp_port = rtsp_port
        self.rtsp_url = f"rtsp://127.0.0.1:{rtsp_port}/{serial}_{channel}"
        self._sink = _FfmpegRtspServerSink(self.rtsp_url)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name=f"hikconnect_relay_{self._serial}_{self._channel}", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._sink.stop()
        if self._thread is not None:
            self._thread.join(timeout=10)
            self._thread = None

    def test_login(self) -> None:
        """Raise if credentials are invalid. Used by the config flow."""
        hik_connect_login(self._email, self._password)

    def _run(self) -> None:
        session_id = hik_connect_login(self._email, self._password)
        client = build_ezviz_client(session_id, self._email)
        _LOGGER.info("Hik-Connect login OK for %s", self._serial)

        consecutive_failures = 0
        while not self._stop_event.is_set():
            try:
                depk = _H264Depacketizer()
                with open_cloud_stream(client, self._serial, channel=self._channel, timeout=30) as stream:
                    stream.start()
                    _LOGGER.info("Stream connected for %s/%s", self._serial, self._channel)
                    consecutive_failures = 0
                    for packet in stream.iter_packets(max_packets=None):
                        if self._stop_event.is_set():
                            break
                        if packet.channel != 1:  # VtmChannel.STREAM
                            continue
                        _seq, payload = _rtp_payload(packet.body)
                        if payload is None:
                            continue
                        for nal in depk.feed(payload):
                            annexb_nal = b"\x00\x00\x00\x01" + nal
                            clear_nal = decrypt_hikvision_ps_video(
                                annexb_nal, self._media_key, nalu_header_size=1
                            )
                            self._sink.write(clear_nal)
                        self._sink.flush()
            except Exception as exc:  # noqa: BLE001 - reconnect on any stream error
                if self._stop_event.is_set():
                    break
                consecutive_failures += 1
                _LOGGER.warning(
                    "Hik-Connect stream error (%r); reconnecting in 2s (failure #%s)",
                    exc, consecutive_failures,
                )
                if consecutive_failures % 5 == 0:
                    try:
                        session_id = hik_connect_login(self._email, self._password)
                        client = build_ezviz_client(session_id, self._email)
                        _LOGGER.info("Re-logged in to Hik-Connect")
                    except Exception:  # noqa: BLE001
                        _LOGGER.exception("Hik-Connect re-login failed")
                self._stop_event.wait(2)
