from __future__ import annotations

import logging
from homeassistant.components.select import SelectEntity
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN, CONF_APT_NAME

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    ctx = hass.data[DOMAIN][entry.entry_id]["reserve_ctx"]
    # [명칭 교정]
    apt_name = entry.data.get(CONF_APT_NAME, "아파트명")
    async_add_entities([AptnerReserveSelectPurpose(entry.entry_id, ctx, apt_name)])

class AptnerReserveSelectPurpose(SelectEntity):
    _attr_has_entity_name = True
    _attr_name = "방문 목적"
    _attr_icon = "mdi:format-list-bulleted"

    def __init__(self, entry_id: str, ctx: dict, apt_name: str):
        self._entry_id = entry_id
        self._ctx = ctx
        self._apt_name = apt_name
        self._attr_unique_id = f"{entry_id}_purpose_select"
        self._attr_options = ["지인/가족방문", "기타", "과외/수업", "돌봄도우미(청소)"]
        self._current_option: str | None = "기타"

    async def async_added_to_hass(self):
        self._ctx["purpose"] = self.entity_id
        self._current_option = "기타"
        self.async_write_ha_state()

    @property
    def current_option(self) -> str | None:
        return self._current_option

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            name=f"{self._apt_name} 주차",
            manufacturer="Aptner Custom",
        )

    async def async_select_option(self, option: str) -> None:
        if option not in self._attr_options: return
        self._current_option = option
        self.async_write_ha_state()
