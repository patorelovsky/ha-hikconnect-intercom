"""The Hik-Connect Intercom (Cloud) integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant

from .const import BASE_RTSP_PORT, CONF_CHANNEL, CONF_MEDIA_KEY, CONF_SERIAL, DOMAIN
from .relay import HikConnectRelay

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.CAMERA]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Hik-Connect Intercom from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Each config entry gets its own local RTSP listen port so multiple
    # intercoms/channels can run side by side without colliding.
    used_ports = {data.rtsp_port for data in hass.data[DOMAIN].values()}
    port = BASE_RTSP_PORT
    while port in used_ports:
        port += 1

    relay = HikConnectRelay(
        email=entry.data[CONF_EMAIL],
        password=entry.data[CONF_PASSWORD],
        serial=entry.data[CONF_SERIAL],
        channel=entry.data[CONF_CHANNEL],
        media_key=entry.data[CONF_MEDIA_KEY],
        rtsp_port=port,
    )
    await hass.async_add_executor_job(relay.start)

    hass.data[DOMAIN][entry.entry_id] = relay
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        relay: HikConnectRelay = hass.data[DOMAIN].pop(entry.entry_id)
        await hass.async_add_executor_job(relay.stop)
    return unload_ok
