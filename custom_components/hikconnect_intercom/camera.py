"""Camera platform for the Hik-Connect Intercom (Cloud) integration."""

from __future__ import annotations

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_CHANNEL, CONF_SERIAL, DOMAIN
from .relay import HikConnectRelay


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the camera entity for a config entry."""
    relay: HikConnectRelay = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([HikConnectCamera(relay, entry)])


class HikConnectCamera(Camera):
    """Camera entity backed by the local RTSP URL fed by HikConnectRelay."""

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, relay: HikConnectRelay, entry: ConfigEntry) -> None:
        super().__init__()
        self._relay = relay
        self._attr_unique_id = entry.unique_id or entry.entry_id
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.unique_id or entry.entry_id)},
            "name": (
                f"Hik-Connect Intercom {entry.data[CONF_SERIAL]} "
                f"ch{entry.data[CONF_CHANNEL]}"
            ),
            "manufacturer": "Hikvision",
            "model": "Hik-Connect cloud relay (unofficial)",
        }
        self._attr_extra_state_attributes = {"account": entry.data[CONF_EMAIL]}

    async def stream_source(self) -> str | None:
        """Return the local RTSP URL fed by the cloud relay."""
        return self._relay.rtsp_url
