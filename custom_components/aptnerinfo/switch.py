from __future__ import annotations

import logging
from typing import Any
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN, CONF_APT_NAME

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    apt_name = entry.data.get(CONF_APT_NAME, "아파트명")
    
    # 런타임 저장소 내 초기값 설정 (기본값 True)
    entry_data = hass.data[DOMAIN][entry.entry_id]
    entry_data.setdefault("switches", {
        "reset_visit_form": True,
        "reset_preset_form": True
    })

    switches = [
        AptnerFormResetSwitch(entry.entry_id, apt_name, "reset_visit_form", "방문차량 예약 후 폼 초기화", "mdi:toggle-switch-outline"),
        AptnerFormResetSwitch(entry.entry_id, apt_name, "reset_preset_form", "프리셋 예약 후 날짜 초기화", "mdi:calendar-sync")
    ]
    async_add_entities(switches)

class AptnerFormResetSwitch(SwitchEntity):
    _attr_has_entity_name = True

    def __init__(self, entry_id: str, apt_name: str, key: str, name: str, icon: str):
        self._entry_id = entry_id
        self._apt_name = apt_name
        self._key = key
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{entry_id}_switch_{key}"
        self.entity_id = f"switch.aptner_{key}"

    @property
    def is_on(self) -> bool:
        """메모리에 저장된 현재 스위치 온/오프 상태 리턴"""
        return self.hass.data[DOMAIN][self._entry_id]["switches"].get(self._key, True)

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            name=f"{self._apt_name} 주차",
            manufacturer="Aptner Custom",
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """스위치 ON 조작 시 상태 반영"""
        self.hass.data[DOMAIN][self._entry_id]["switches"][self._key] = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """스위치 OFF 조작 시 상태 반영"""
        self.hass.data[DOMAIN][self._entry_id]["switches"][self._key] = False
        self.async_write_ha_state()

