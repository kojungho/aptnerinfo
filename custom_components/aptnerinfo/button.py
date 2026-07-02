from __future__ import annotations

import asyncio
from datetime import date, timedelta
import logging
import aiohttp

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN, CONF_APT_NAME

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    auth = hass.data[DOMAIN][entry.entry_id]["auth"]
    ctx = hass.data[DOMAIN][entry.entry_id]["reserve_ctx"]
    # [명칭 교정]
    apt_name = entry.data.get(CONF_APT_NAME, "아파트명")
    
    coordinators = hass.data[DOMAIN].get(entry.entry_id, {}).get("coordinators", {})
    car_coord = coordinators.get("reserve") or coordinators.get("car")
    
    if not car_coord:
        await asyncio.sleep(1.0)
        coordinators = hass.data[DOMAIN].get(entry.entry_id, {}).get("coordinators", {})
        car_coord = coordinators.get("reserve") or coordinators.get("car")

    hass.data[DOMAIN].setdefault("del_btn_array", [])
    hass.data[DOMAIN]["del_btn_array"].clear()
    hass.data[DOMAIN].setdefault("preset_btn_array", [])
    hass.data[DOMAIN]["preset_btn_array"].clear()

    entities = [AptnerReserveButton(hass, entry.entry_id, auth, ctx, apt_name)]
    
    for idx in range(10):
        btn = AptnerDeleteCarArrayButton(hass, entry.entry_id, auth, ctx, car_coord, idx, apt_name)
        entities.append(btn)
        hass.data[DOMAIN]["del_btn_array"].append(btn)
    
    for idx in range(9):
        preset_btn = AptnerDynamicPresetButton(hass, entry.entry_id, auth, ctx, idx, apt_name)
        entities.append(preset_btn)
        hass.data[DOMAIN]["preset_btn_array"].append(preset_btn)
        
    async_add_entities(entities)


def _format_display_phone(raw_phone: str) -> str:
    digits = "".join(filter(str.isdigit, raw_phone))
    if len(digits) == 11 and digits.startswith("010"):
        return f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"
    return raw_phone


class AptnerDeleteCarArrayButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_icon = "mdi:car-remove"

    def __init__(self, hass, entry_id: str, auth, ctx: dict, coordinator, index: int, apt_name: str):
        self.hass = hass
        self._entry_id = entry_id
        self.auth = auth
        self.ctx = ctx
        self.coordinator = coordinator
        self._index = index
        self._apt_name = apt_name
        self._attr_unique_id = f"{entry_id}_del_car_{index + 1}"
        self.entity_id = f"button.del_car_{index + 1}"

    def _get_preset_label_map(self) -> dict[str, str]:
        label_map = {}
        master_entity_id = self.ctx.get("master_presets")
        if not master_entity_id: return label_map
        state_obj = self.hass.states.get(master_entity_id)
        if not state_obj or state_obj.state in ("unknown", "unavailable", ""): return label_map
            
        try:
            raw_chunks = state_obj.state.split(";")
            for chunk in raw_chunks:
                chunk = chunk.strip()
                if not chunk: continue
                parts = chunk.split("-")
                if len(parts) >= 2:
                    label = "-".join(parts[:-2]).strip() if len(parts) >= 3 else parts[0].strip()
                    carno = parts[-2].strip().replace(" ", "").replace("-", "") if len(parts) >= 3 else parts[1].strip().replace(" ", "").replace("-", "")
                    if carno: label_map[carno] = label
        except: pass
        return label_map

    def _get_target_reserve_info(self) -> dict | None:
        if not self.coordinator:
            coordinators = self.hass.data[DOMAIN].get(self._entry_id, {}).get("coordinators", {})
            self.coordinator = coordinators.get("reserve") or coordinators.get("car")
        if not self.coordinator or not hasattr(self.coordinator, "data_reserve"): return None
        reserves = self.coordinator.data_reserve.get("attrs", [])
        if len(reserves) > self._index:
            item = reserves[self._index]
            if isinstance(item, dict):
                carno = item.get("carNo") or item.get("car_no") or ""
                vdate = item.get("visitDate") or item.get("visit_date") or ""
                norm_date = vdate.replace("-", ".")
                display_date = norm_date[5:] if len(norm_date) >= 10 else norm_date
                reserve_id = item.get("visitReserveIdx") or item.get("idx") or item.get("reserveIdx")
                return {"carno": carno, "date": display_date, "id": reserve_id}
        return None

    @property
    def name(self) -> str:
        info = self._get_target_reserve_info()
        if info:
            clean_carno = info["carno"].replace(" ", "").replace("-", "")
            preset_map = self._get_preset_label_map()
            if clean_carno in preset_map:
                label = preset_map[clean_carno]
                return f"삭제 {self._index + 1}: {info['carno']} | {label} | {info['date']}"
            else:
                return f"삭제 {self._index + 1}: {info['carno']} | {info['date']}"
        return f"삭제 {self._index + 1}: 예약 없음"

    @property
    def available(self) -> bool:
        return self._get_target_reserve_info() is not None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._entry_id)}, name=f"{self._apt_name} 주차", manufacturer="Aptner Custom")

    async def async_press(self) -> None:
        info = self._get_target_reserve_info()
        if not info or not info.get("id"): raise HomeAssistantError("삭제할 데이터가 없는 빈 예약 슬롯입니다.")
        target_id = info["id"]
        try: await self.auth.request("DELETE", f"/pc/reserve/{target_id}")
        except Exception as e: raise HomeAssistantError(f"서버 삭제 통신 실패: {e}")
        if self.coordinator:
            self.coordinator._last_api_call_time = None
            await self.coordinator.update()
            for btn in self.hass.data[DOMAIN].get("del_btn_array", []):
                try: 
                    if hasattr(btn, "async_write_ha_state"): btn.async_write_ha_state()
                except: pass
            for sensor in self.hass.data[DOMAIN].get("sensor_entities", []):
                try:
                    if hasattr(sensor, "async_write_ha_state"): sensor.async_write_ha_state()
                except: pass

class AptnerReserveButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_name = "방문차량 예약 실행"
    _attr_icon = "mdi:car-clock"

    def __init__(self, hass, entry_id: str, auth, ctx: dict, apt_name: str):
        self.hass = hass
        self._entry_id = entry_id
        self.auth = auth
        self.ctx = ctx
        self._apt_name = apt_name
        self._attr_unique_id = f"{entry_id}_reserve_button"

    def _get_state(self, entity_id: str) -> str | None:
        if not entity_id: return None
        st = self.hass.states.get(entity_id)
        if not st or st.state in ("unknown", "unavailable", ""): return None
        return st.state

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._entry_id)}, name=f"{self._apt_name} 주차", manufacturer="Aptner Custom")

    async def async_press(self) -> None:
        purpose_e = self.ctx.get("purpose")
        carno_e = self.ctx.get("carno")
        phone_e = self.ctx.get("phone")
        fallback_phone_e = self.ctx.get("fallback_phone")

        purpose = self._get_state(purpose_e)
        carno = self._get_state(carno_e)
        phone = self._get_state(phone_e)
        fallback_phone = self._get_state(fallback_phone_e)

        if not carno or str(carno).strip() == "": raise HomeAssistantError("차량번호가 입력되지 않았습니다.")
        if not phone or str(phone).strip() == "": phone = fallback_phone
        if not phone or str(phone).strip() == "": raise HomeAssistantError("연락처를 입력해 주세요.")
        if not purpose: purpose = "기타"

        date_entities = self.hass.data[DOMAIN].get("date_entities", {})
        start_entity_obj = date_entities.get(f"{self._entry_id}_start")
        end_entity_obj = date_entities.get(f"{self._entry_id}_end")

        start_date = start_entity_obj.native_value if start_entity_obj and start_entity_obj.native_value else date.today()
        end_date = end_entity_obj.native_value if end_entity_obj and end_entity_obj.native_value else date.today()

        if end_date < start_date: raise HomeAssistantError("날짜 범위를 교정해 주세요.")

        clean_number = carno.replace(" ", "").replace("-", "")
        clean_phone = phone.replace("-", "").strip()

        delta = end_date - start_date
        for i in range(delta.days + 1):
            target_date = start_date + timedelta(days=i)
            target_str = target_date.strftime("%Y.%m.%d")
            payload = {"visitDate": target_str, "endDate": target_str, "purpose": purpose, "carNo": clean_number, "phone": clean_phone}
            
            try: 
                await self.auth.request("POST", "/pc/reserve", json=payload)
            except aiohttp.ClientResponseError as e:
                if e.status == 409: 
                    pass 
                elif e.status == 400:
                    raise HomeAssistantError(f"예약 거절(400): 아파트너 서버에서 예약을 거부했습니다. (사유: 잘못된 차량번호 형식 또는 예약불가 시간)")
                else: 
                    raise HomeAssistantError(f"서버 통신 에러({e.status}): {e.message}")
            except Exception as e: 
                _LOGGER.error(f"프리셋 예약 전송 중 에러: {e}")
                
            await asyncio.sleep(0.5)

        coordinators = self.hass.data[DOMAIN].get(self._entry_id, {}).get("coordinators", {})
        car_coord = coordinators.get("reserve") or coordinators.get("car")
        
        if car_coord:
            car_coord._last_api_call_time = None
            await car_coord.update()
            for btn in self.hass.data[DOMAIN].get("del_btn_array", []):
                try: 
                    if hasattr(btn, "async_write_ha_state"): btn.async_write_ha_state()
                except: pass
            for sensor in self.hass.data[DOMAIN].get("sensor_entities", []):
                try:
                    if hasattr(sensor, "async_write_ha_state"): sensor.async_write_ha_state()
                except: pass

        await asyncio.sleep(0.5)
        if start_entity_obj: start_entity_obj.set_value_internal(date.today())
        if end_entity_obj: end_entity_obj.set_value_internal(date.today())

        text_entities = self.hass.data[DOMAIN].get("text_entities", {})
        carno_obj = text_entities.get(f"{self._entry_id}_carno")
        if carno_obj: await carno_obj.async_set_value("")
        phone_obj = text_entities.get(f"{self._entry_id}_phone")
        if phone_obj: await phone_obj.async_set_value("")
        if purpose_e: await self.hass.services.async_call("select", "select_option", {"entity_id": purpose_e, "option": "기타"}, blocking=False)


class AptnerDynamicPresetButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_icon = "mdi:car-side"

    def __init__(self, hass, entry_id: str, auth, ctx: dict, index: int, apt_name: str):
        self.hass = hass
        self._entry_id = entry_id
        self.auth = auth
        self.ctx = ctx
        self._index = index
        self._apt_name = apt_name
        self._attr_unique_id = f"{entry_id}_dynamic_car_slot_{index}"
        self.entity_id = f"button.dynamic_car_slot_{index + 1}"

    def _get_current_car_info(self) -> dict | None:
        master_entity_id = self.ctx.get("master_presets")
        if not master_entity_id: return None
        state_obj = self.hass.states.get(master_entity_id)
        if not state_obj or state_obj.state in ("unknown", "unavailable", ""): return None
        try:
            raw_chunks = state_obj.state.split(";")
            car_tokens = [chunk.strip() for chunk in raw_chunks if chunk.strip()]
            if len(car_tokens) > self._index:
                target_token = car_tokens[self._index]
                parts = target_token.split("-")
                if len(parts) >= 3:
                    return {"name": "-".join(parts[:-2]).strip(), "number": parts[-2].strip(), "phone": parts[-1].strip()}
                elif len(parts) == 2:
                    return {"name": parts[0].strip(), "number": parts[1].strip(), "phone": ""}
        except: pass
        return None

    @property
    def name(self) -> str:
        info = self._get_current_car_info()
        if info and "name" in info and "number" in info: return f"차량 {self._index + 1}: {info['name']} ({info['number']})"
        return f"차량 프리셋 슬롯 {self._index + 1} (미설정)"

    @property
    def available(self) -> bool:
        return self._get_current_car_info() is not None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._entry_id)}, name=f"{self._apt_name} 주차", manufacturer="Aptner Custom")

    async def async_press(self) -> None:
        info = self._get_current_car_info()
        if not info: raise HomeAssistantError(f"슬롯 {self._index + 1}번에 바인딩된 올바른 형식이 없습니다.")

        date_entities = self.hass.data[DOMAIN].get("date_entities", {})
        preset_start_entity_obj = date_entities.get(f"{self._entry_id}_preset_start")
        preset_end_entity_obj = date_entities.get(f"{self._entry_id}_preset_end")

        start_date = preset_start_entity_obj.native_value if preset_start_entity_obj and preset_start_entity_obj.native_value else date.today()
        end_date = preset_end_entity_obj.native_value if preset_end_entity_obj and preset_end_entity_obj.native_value else date.today()

        if end_date < start_date: raise HomeAssistantError("예약 종료일이 시작일보다 빠를 수 없습니다.")

        raw_phone = info.get("phone", "")
        if not raw_phone:
            fallback_phone_e = self.ctx.get("fallback_phone")
            if fallback_phone_e:
                st = self.hass.states.get(fallback_phone_e)
                if st and st.state not in ("unknown", "unavailable", ""): raw_phone = st.state

        if not raw_phone: raise HomeAssistantError("프리셋에 연락처가 없고 기본 연락처도 설정되어 있지 않습니다.")

        clean_number = info["number"].replace(" ", "").replace("-", "")
        clean_phone = raw_phone.replace("-", "").strip()

        delta = end_date - start_date
        for i in range(delta.days + 1):
            target_date = start_date + timedelta(days=i)
            target_str = target_date.strftime("%Y.%m.%d")
            payload = {"visitDate": target_str, "endDate": target_str, "purpose": "지인/가족방문", "carNo": clean_number, "phone": clean_phone}
            
            try: 
                await self.auth.request("POST", "/pc/reserve", json=payload)
            except aiohttp.ClientResponseError as e:
                if e.status == 409: 
                    pass 
                elif e.status == 400:
                    raise HomeAssistantError(f"예약 거절(400): 아파트너 서버에서 예약을 거부했습니다. (사유: 잘못된 차량번호 형식 또는 예약불가 시간)")
                else: 
                    raise HomeAssistantError(f"서버 통신 에러({e.status}): {e.message}")
            except Exception as e: 
                _LOGGER.error(f"프리셋 예약 전송 중 에러: {e}")
                
            await asyncio.sleep(0.5)

        coordinators = self.hass.data[DOMAIN].get(self._entry_id, {}).get("coordinators", {})
        car_coord = coordinators.get("reserve") or coordinators.get("car")
        
        if car_coord:
            car_coord._last_api_call_time = None
            await car_coord.update()
            for btn in self.hass.data[DOMAIN].get("del_btn_array", []):
                try: 
                    if hasattr(btn, "async_write_ha_state"): btn.async_write_ha_state()
                except: pass
            for sensor in self.hass.data[DOMAIN].get("sensor_entities", []):
                try:
                    if hasattr(sensor, "async_write_ha_state"): sensor.async_write_ha_state()
                except: pass

        await asyncio.sleep(0.5)
        if preset_start_entity_obj: preset_start_entity_obj.set_value_internal(date.today())
        if preset_end_entity_obj: preset_end_entity_obj.set_value_internal(date.today())