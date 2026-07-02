from __future__ import annotations

from datetime import date
import logging
import time

from homeassistant.components.date import DateEntity
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN, CONF_APT_NAME

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    ctx = hass.data[DOMAIN][entry.entry_id]["reserve_ctx"]
    apt_name = entry.data.get(CONF_APT_NAME, "아파트명")
    
    start_entity = AptnerReserveStartDate(entry.entry_id, ctx, apt_name)
    end_entity = AptnerReserveEndDate(entry.entry_id, ctx, apt_name)
    
    preset_start_entity = AptnerPresetStartDate(entry.entry_id, ctx, apt_name)
    preset_end_entity = AptnerPresetEndDate(entry.entry_id, ctx, apt_name)
    
    ctx["start"] = f"date.apateuneo_jeongbo_bangmun_sijagil"
    ctx["end"] = f"date.apateuneo_jeongbo_bangmun_jongryoil"
    ctx["preset_start"] = f"date.apateuneo_jeongbo_preset_bangmun_sijagil"
    ctx["preset_end"] = f"date.apateuneo_jeongbo_preset_bangmun_jongryoil"
    
    hass.data[DOMAIN].setdefault("date_entities", {})
    hass.data[DOMAIN]["date_entities"][f"{entry.entry_id}_start"] = start_entity
    hass.data[DOMAIN]["date_entities"][f"{entry.entry_id}_end"] = end_entity
    hass.data[DOMAIN]["date_entities"][f"{entry.entry_id}_preset_start"] = preset_start_entity
    hass.data[DOMAIN]["date_entities"][f"{entry.entry_id}_preset_end"] = preset_end_entity

    async_add_entities([start_entity, end_entity, preset_start_entity, preset_end_entity])

class _BaseReserveDate(DateEntity):
    _attr_has_entity_name = True

    def __init__(self, entry_id: str, ctx: dict, apt_name: str, key: str, name: str):
        self._entry_id = entry_id
        self._ctx = ctx
        self._apt_name = apt_name
        self._key = key
        self._attr_name = name
        
        if key == "start": uid = "bangmun_sijagil"
        elif key == "end": uid = "bangmun_jongryoil"
        elif key == "preset_start": uid = "preset_bangmun_sijagil"
        elif key == "preset_end": uid = "preset_bangmun_jongryoil"
        else: uid = key
        
        self._attr_unique_id = f"{entry_id}_{uid}"
        self._value: date = date.today()
        self.last_changed_time: float | None = None

    async def async_added_to_hass(self):
        self._value = date.today()
        self.last_changed_time = None
        self.async_write_ha_state()

    @property
    def native_value(self) -> date:
        return self._value

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            name=f"{self._apt_name} 주차",
            manufacturer="Aptner Custom",
        )

    def set_value_internal(self, value: date) -> None:
        self._value = value
        if self._value != date.today():
            self.last_changed_time = time.time()
        else:
            self.last_changed_time = None
        self.async_write_ha_state()

class AptnerReserveStartDate(_BaseReserveDate):
    def __init__(self, entry_id: str, ctx: dict, apt_name: str):
        super().__init__(entry_id, ctx, apt_name, key="start", name="방문 시작일")
        self._attr_icon = "mdi:calendar-import"
        self.entity_id = "date.apateuneo_jeongbo_bangmun_sijagil"

    async def async_set_value(self, value: date) -> None:
        today = date.today()
        target_value = value
        # [교정] 과거 날짜 선택 시 에러 팝업 발생 및 차단
        if target_value < today:
            raise ValueError("과거 날짜는 선택할 수 없습니다.")
        self.set_value_internal(target_value)

        date_entities = self.hass.data[DOMAIN].get("date_entities", {})
        end_entity = date_entities.get(f"{self._entry_id}_end")
        if end_entity and end_entity.native_value < target_value:
            end_entity.set_value_internal(target_value)
        self.async_write_ha_state()

class AptnerReserveEndDate(_BaseReserveDate):
    def __init__(self, entry_id: str, ctx: dict, apt_name: str):
        super().__init__(entry_id, ctx, apt_name, key="end", name="방문 종료일")
        self._attr_icon = "mdi:calendar-export"
        self.entity_id = "date.apateuneo_jeongbo_bangmun_jongryoil"

    async def async_set_value(self, value: date) -> None:
        today = date.today()
        target_value = value
        # [교정] 과거 날짜 선택 시 에러 팝업 발생 및 차단
        if target_value < today:
            raise ValueError("과거 날짜는 선택할 수 없습니다.")
        self.set_value_internal(target_value)

        date_entities = self.hass.data[DOMAIN].get("date_entities", {})
        start_entity = date_entities.get(f"{self._entry_id}_start")
        if start_entity and start_entity.native_value > target_value:
            start_entity.set_value_internal(target_value)
        self.async_write_ha_state()

class AptnerPresetStartDate(_BaseReserveDate):
    def __init__(self, entry_id: str, ctx: dict, apt_name: str):
        super().__init__(entry_id, ctx, apt_name, key="preset_start", name="프리셋 방문 시작일")
        self._attr_icon = "mdi:calendar-import"
        self.entity_id = "date.apateuneo_jeongbo_preset_bangmun_sijagil"

    async def async_set_value(self, value: date) -> None:
        today = date.today()
        target_value = value
        # [교정] 과거 날짜 선택 시 에러 팝업 발생 및 차단
        if target_value < today:
            raise ValueError("과거 날짜는 선택할 수 없습니다.")
        self.set_value_internal(target_value)

        date_entities = self.hass.data[DOMAIN].get("date_entities", {})
        end_entity = date_entities.get(f"{self._entry_id}_preset_end")
        if end_entity and end_entity.native_value < target_value:
            end_entity.set_value_internal(target_value)
        self.async_write_ha_state()

class AptnerPresetEndDate(_BaseReserveDate):
    def __init__(self, entry_id: str, ctx: dict, apt_name: str):
        super().__init__(entry_id, ctx, apt_name, key="preset_end", name="프리셋 방문 종료일")
        self._attr_icon = "mdi:calendar-export"
        self.entity_id = "date.apateuneo_jeongbo_preset_bangmun_jongryoil"

    async def async_set_value(self, value: date) -> None:
        today = date.today()
        target_value = value
        # [교정] 과거 날짜 선택 시 에러 팝업 발생 및 차단
        if target_value < today:
            raise ValueError("과거 날짜는 선택할 수 없습니다.")
        self.set_value_internal(target_value)

        date_entities = self.hass.data[DOMAIN].get("date_entities", {})
        start_entity = date_entities.get(f"{self._entry_id}_preset_start")
        if start_entity and start_entity.native_value > target_value:
            start_entity.set_value_internal(target_value)
        self.async_write_ha_state()
