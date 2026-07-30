# Hik-Connect Intercom (Cloud) — unofficial Home Assistant integration

A custom Home Assistant integration that provides **live video from a
Hikvision Hik-Connect intercom/outdoor station entirely over the Hik-Connect
cloud** — no local network access to the device required.

This exists because some Hikvision video intercoms (e.g. the
`DS-KH7300EY-WTE2`) expose **zero local network services** (no RTSP, no
web UI, no ONVIF — confirmed via a full 65535-port scan) and can only be
viewed through the Hik-Connect mobile app, which streams via Hikvision's
cloud VTM (Video Transfer Module) relay.

This integration reverse-engineers that same cloud relay:

1. Logs in to the Hik-Connect regional API (`apiieu.hik-connect.com`) using
   your account email/password.
2. Fetches the VTM cloud relay assignment and a VTDU stream auth token via
   `euauth.ezvizlife.com` (the account's own reported auth address is
   broken; this is a known, empirically-discovered workaround).
3. Opens the cloud stream and receives it as **RTP-encapsulated H.264**.
4. Depacketizes RTP (RFC 6184: single NAL / STAP-A / FU-A) into a raw
   Annex-B H.264 elementary stream.
5. Decrypts it using Hikvision's AES-ECB-based NAL-body encryption scheme,
   keyed with the device's Hik-Connect **verification code**.
6. Feeds the clear H.264 into `ffmpeg`, which acts as its own tiny local
   RTSP server (`-rtsp_flags listen`) — no external RTSP server binary
   needed, since `ffmpeg` already ships with Home Assistant.
7. Exposes a standard HA `camera` entity whose `stream_source()` points at
   that local RTSP URL, so HA's built-in `stream` component (HLS,
   thumbnails, Lovelace picture/glance cards, etc.) handles the rest.

## ⚠️ Disclaimer

This is a fully **unofficial, reverse-engineered** use of undocumented
Hik-Connect/EZVIZ cloud endpoints and Hikvision's proprietary VTM/RTP
protocol. It is not supported by Hikvision, may violate their terms of
service, and **can break at any time** if they change their backend. Use
at your own risk, on your own device/account only.

## Installation (via HACS)

1. In Home Assistant, open **HACS → the "⋮" menu (top right) → Custom
   repositories**.
2. Add this repository's URL: `https://github.com/patorelovsky/ha-hikconnect-intercom`
   with category **Integration**.
3. Find **"Hik-Connect Intercom (Cloud, unofficial)"** in HACS and click
   **Download**.
4. **Restart Home Assistant.**
5. Go to **Settings → Devices & Services → Add Integration**, search for
   **"Hik-Connect Intercom"**, and fill in the form:
   - Hik-Connect account email/password
   - Device serial (e.g. `A1B2C34567`)
   - Channel (`1` is typically the outdoor station)
   - Verification code — found on the device itself: touchscreen →
     Settings → Hik-Connect server settings → "Overovací kód" /
     "Verification Code" field.

That's it — a new camera entity will appear with a live stream.

## Manual installation (without HACS)

Copy `custom_components/hikconnect_intercom` into your Home Assistant
`config/custom_components/` directory, restart HA, then follow step 5
above.

## Notes / limitations

- Requires the intercom account to have a device linked to the Hik-Connect
  cloud (confirmed via the app already showing live video).
- Each configured device/channel gets its own local RTSP port
  (auto-assigned starting at 8554) so multiple cameras can run side by
  side.
- Reconnects automatically on stream drops and re-logs in periodically on
  repeated failures.
- Tested against a `DS-KH7300EY-WTE2` indoor station / outdoor station
  pair. Other Hikvision/EZVIZ devices using the same cloud VTM relay may
  or may not work unmodified — the RTP/H.264 assumption in particular may
  not hold for HEVC-only devices (untested).
