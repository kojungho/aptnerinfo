from __future__ import annotations

import logging
import re
import time
from typing import Any

from homeassistant.components.text import TextEntity
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN, CONF_APT_NAME

_LOGGER = logging.getLogger(__name__)
CARNO_PATTERN = re.compile(r"^(?:\d{2}|\d{3})[가-힣]\d{4}$")
PHONE_DIGIT_PATTERN = re.compile(r"\d+")

DEFAULT_PRESETS_TEXT = "홍길동-123가4567-01012345678; 김미영-12호1004-01011112222;"

async def async_setup_entry(hass, entry, async_add_entities):
    ctx = hass.data[DOMAIN][entry.entry_id]["reserve_ctx"]
    # [명칭 교정]
    apt_name = entry.data.get(CONF_APT_NAME, "아파트명")
    
    carno_entity = AptnerReserveCarNo(entry.entry_id, ctx, apt_name)
    phone_entity = AptnerReservePhone(entry.entry_id, ctx, apt_name)
    fallback_phone_entity = AptnerFallbackPhone(entry.entry_id, ctx, apt_name)
    master_presets_entity = AptnerCarPresetsMaster(entry.entry_id, ctx, apt_name)
    
    hass.data[DOMAIN].setdefault("text_entities", {})
    hass.data[DOMAIN]["text_entities"][f"{entry.entry_id}_carno"] = carno_entity
    hass.data[DOMAIN]["text_entities"][f"{entry.entry_id}_phone"] = phone_entity
    hass.data[DOMAIN]["text_entities"][f"{entry.entry_id}_fallback_phone"] = fallback_phone_entity
    hass.data[DOMAIN]["text_entities"][f"{entry.entry_id}_master_presets"] = master_presets_entity

    async_add_entities([carno_entity, phone_entity, fallback_phone_entity, master_presets_entity])


class _BaseReserveText(TextEntity):
    _attr_has_entity_name = True
    _attr_mode = "text"

    def __init__(self, entry_id: str, ctx: dict, apt_name: str, key: str, name: str, max_len: int = 64):
        self._entry_id = entry_id
        self._ctx = ctx
        self._apt_name = apt_name
        self._key = key
        self._attr_name = name
        self._attr_unique_id = f"{entry_id}_{key}_text_field"
        self._attr_native_max = max_len
        self._value: str = ""
        self.last_changed_time: float | None = None

    async def async_added_to_hass(self):
        self._ctx[self._key] = self.entity_id
        self._value = ""
        self.last_changed_time = None
        self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        return self._value

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            name=f"{self._apt_name} 주차",
            manufacturer="Aptner Custom",
        )

    async def async_set_value(self, value: str) -> None:
        self._value = value.strip() if value is not None else ""
        self.last_changed_time = time.time() if self._value else None
        self.async_write_ha_state()


class AptnerCarPresetsMaster(TextEntity, RestoreEntity):
    _attr_has_entity_name = True
    _attr_name = "차량 프리셋 마스터 데이터"
    _attr_icon = "mdi:database-edit"
    _attr_mode = "text"

    def __init__(self, entry_id: str, ctx: dict, apt_name: str):
        self._entry_id = entry_id
        self._ctx = ctx
        self._apt_name = apt_name
        self._attr_unique_id = f"{entry_id}_car_presets_master_field"
        self._attr_native_max = 1024
        
        self._attr_placeholder = "작성 규칙: 별명-차량번호-연락처; (각 차량은 세미콜론으로 구분)"
        self._value: str = DEFAULT_PRESETS_TEXT

    async def async_added_to_hass(self):
        self._ctx["master_presets"] = self.entity_id
        last = await self.async_get_last_state()
        if last and last.state not in (None, "unknown", "unavailable", ""):
            self._value = last.state
        else:
            self._value = DEFAULT_PRESETS_TEXT
        self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        return self._value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "작성 가이드": "이름(차종)-차량번호-연락처; 형태로 작성하세요.",
            "구분자": "각 차량의 끝에는 반드시 세미콜론(;)을 붙여야 합니다.",
            "예시": "아빠-12가3456-01012345678;"
        }

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            name=f"{self._apt_name} 주차",
            manufacturer="Aptner Custom",
        )

    async def async_set_value(self, value: str) -> None:
        self._value = value if value is not None else ""
        self.async_write_ha_state()
        
        for btn in self.hass.data.get(DOMAIN, {}).get("preset_btn_array", []):
            try:
                if hasattr(btn, "async_write_ha_state"):
                    btn.async_write_ha_state()
            except Exception:
                pass


class AptnerReserveCarNo(_BaseReserveText):
    def __init__(self, entry_id: str, ctx: dict, apt_name: str):
        super().__init__(entry_id, ctx, apt_name, key="carno", name="예약 차량번호 입력", max_len=16)
        self._attr_placeholder = "12가3456 또는 123가4567"

    async def async_set_value(self, value: str) -> None:
        v = (value or "").strip()
        if not v:
            self._value = ""
            self.last_changed_time = None
            self.async_write_ha_state()
            return
        clean_v = v.replace(" ", "").replace("-", "")
        if clean_v and not CARNO_PATTERN.match(clean_v):
            raise ValueError("차량번호 형식이 맞지 않습니다.")
        self._value = clean_v
        self.last_changed_time = time.time()
        self.async_write_ha_state()


class AptnerReservePhone(_BaseReserveText):
    def __init__(self, entry_id: str, ctx: dict, apt_name: str):
        super().__init__(entry_id, ctx, apt_name, key="phone", name="방문차량 연락처 입력", max_len=32)
        self._attr_placeholder = "미입력 시 기본 연락처로 대체됩니다"

    async def async_set_value(self, value: str) -> None:
        v = (value or "").strip()
        if not v:
            self._value = ""
            self.last_changed_time = None
            self.async_write_ha_state()
            return
        digits = "".join(PHONE_DIGIT_PATTERN.findall(v))
        if len(digits) == 8: digits = "010" + digits
        if len(digits) == 11 and digits.startswith("010"): formatted = f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"
        elif len(digits) == 10 and not digits.startswith("02"): formatted = f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
        else: formatted = v
        self._value = formatted
        self.last_changed_time = time.time()
        self.async_write_ha_state()

class AptnerFallbackPhone(_BaseReserveText, RestoreEntity):
    def __init__(self, entry_id: str, ctx: dict, apt_name: str):
        super().__init__(entry_id, ctx, apt_name, key="fallback_phone", name="미입력 시 대체 기본 연락처", max_len=32)
        self._attr_placeholder = "010-1234-5678 (예약 시 빈칸이면 이 번호 사용)"

    async def async_added_to_hass(self):
        self._ctx[self._key] = self.entity_id
        last = await self.async_get_last_state()
        if last and last.state not in (None, "unknown", "unavailable", ""):
            self._value = last.state
        else:
            self._value = ""
        self.last_changed_time = None
        self.async_write_ha_state()

    async def async_set_value(self, value: str) -> None:
        v = (value or "").strip()
        if not v:
            self._value = ""
            self.last_changed_time = None
            self.async_write_ha_state()
            return
        digits = "".join(PHONE_DIGIT_PATTERN.findall(v))
        if len(digits) == 8: digits = "010" + digits
        if len(digits) == 11 and digits.startswith("010"): formatted = f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"
        elif len(digits) == 10 and not digits.startswith("02"): formatted = f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
        else: formatted = v
        self._value = formatted
        self.last_changed_time = time.time()
        self.async_write_ha_state()