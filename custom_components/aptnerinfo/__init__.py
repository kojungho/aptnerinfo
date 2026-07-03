from __future__ import annotations

import asyncio
import datetime
from datetime import timedelta
import logging
import time

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .aptner_auth import AptnerAuth
from .const import DOMAIN, CONF_ID, CONF_PASSWORD

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR, 
    Platform.SELECT, 
    Platform.DATE, 
    Platform.TEXT, 
    Platform.BUTTON,
    Platform.SWITCH
]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """통합구성요소 진입점에서 완벽한 양식 전체 자동 초기화 삼원 스케줄러를 가동합니다."""
    hass.data.setdefault(DOMAIN, {})
    
    entry_data = hass.data[DOMAIN].setdefault(entry.entry_id, {})
    entry_data["reserve_ctx"] = {}
    entry_data["coordinators"] = {}
    
    user_id = entry.data.get(CONF_ID)
    password = entry.data.get(CONF_PASSWORD)
    
    session = async_get_clientsession(hass)
    entry_data["auth"] = AptnerAuth(user_id, password, session)
    
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    refresh_seconds = entry.options.get("refresh_interval_seconds", 10)
    fee_hours = entry.options.get("fee_refresh_hours", 12)
    fee_seconds_threshold = fee_hours * 3600
    
    reset_minutes = entry.options.get("form_reset_minutes", 5)
    reset_seconds_threshold = reset_minutes * 60
    
    _LOGGER.info(
        "아파트너 올인원 클렌징 스케줄러 기동: [관리비: %d시간] / [차량폴링: %d초] / [양식초기화: %d분 후 그룹별 독립 삭제]", 
        fee_hours, refresh_seconds, reset_minutes
    )

    # =====================================================================
    # [태스크 A] 관리비 및 연락처 데이터 전용 가변 스케줄러 루프
    # =====================================================================
    async def _async_maintenance_fee_refresh_loop(now):
        coordinators = hass.data[DOMAIN].get(entry.entry_id, {}).get("coordinators", {})
        
        for name, coord in coordinators.items():
            if name != "reserve" and name != "contact":
                try:
                    await coord.update()
                except Exception as e:
                    _LOGGER.error(f"관리비 계열 백그라운드 데이터 갱신 실패 ({name}): {e}")
                    
        contact_coord = coordinators.get("contact")
        if contact_coord:
            try:
                await contact_coord.update()
            except Exception as e:
                _LOGGER.error(f"연락처 데이터 백그라운드 갱신 실패: {e}")
                    
        for entity in hass.data[DOMAIN].get("sensor_entities", []):
            if hasattr(entity, "async_write_ha_state") and not str(entity.entity_id).endswith("reserve"):
                entity.async_write_ha_state()

    # =====================================================================
    # [태스크 B] 차량 실시간 조회 및 자정 경과 / 폼 타이머 자동 초기화 루프
    # =====================================================================
    async def _async_car_and_timer_refresh_loop(now):
        coordinators = hass.data[DOMAIN].get(entry.entry_id, {}).get("coordinators", {})
        reserve_coord = coordinators.get("reserve")
        
        if reserve_coord:
            try:
                await reserve_coord.update()
                
                for entity in hass.data[DOMAIN].get("sensor_entities", []):
                    if hasattr(entity, "async_write_ha_state"):
                        entity.async_write_ha_state()
                        
                for btn in hass.data[DOMAIN].get("del_btn_array", []):
                    try:
                        if hasattr(btn, "async_write_ha_state"): btn.async_write_ha_state()
                    except Exception: pass
                    
                for btn in hass.data[DOMAIN].get("preset_btn_array", []):
                    try:
                        if hasattr(btn, "async_write_ha_state"): btn.async_write_ha_state()
                    except Exception: pass
                    
            except Exception as e:
                _LOGGER.error("실시간 차량 데이터 갱신 장애: %s", e)

        text_entities = hass.data[DOMAIN].get("text_entities", {})
        date_entities = hass.data[DOMAIN].get("date_entities", {})
        
        carno_obj = text_entities.get(f"{entry.entry_id}_carno")
        phone_obj = text_entities.get(f"{entry.entry_id}_phone")
        start_obj = date_entities.get(f"{entry.entry_id}_start")
        end_obj = date_entities.get(f"{entry.entry_id}_end")
        
        preset_start_obj = date_entities.get(f"{entry.entry_id}_preset_start")
        preset_end_obj = date_entities.get(f"{entry.entry_id}_preset_end")
        
        current_time = time.time()
        today = datetime.date.today()

        # =====================================================================
        # [핵심 교정 패치] 자정 경과 실시간 감시 및 강제 당일 동기화 가드
        # =====================================================================
        # 사용자의 폼 조작이나 5분 타이머 만료 여부와 무관하게, 자정이 지나 시스템 날짜와 
        # UI 달력창 엔티티의 실제 내부 값이 불일치하는 순간 즉시 당일 날짜로 연동 갱신합니다.
        if start_obj and getattr(start_obj, "native_value", None) != today:
            _LOGGER.info("자정 경과 포착: 일반 방문 시작일을 당일 날짜로 자동 보정합니다.")
            await start_obj.async_set_value(today)
        if end_obj and getattr(end_obj, "native_value", None) != today:
            await end_obj.async_set_value(today)
            
        if preset_start_obj and getattr(preset_start_obj, "native_value", None) != today:
            _LOGGER.info("자정 경과 포착: 프리셋 방문 시작일을 당일 날짜로 자동 보정합니다.")
            await preset_start_obj.async_set_value(today)
        if preset_end_obj and getattr(preset_end_obj, "native_value", None) != today:
            await preset_end_obj.async_set_value(today)

        # 1. 일반 예약 폼 만료 조건 판단
        general_objects = [carno_obj, phone_obj, start_obj, end_obj]
        general_should_reset = False
        if reset_minutes > 0:
            for obj in general_objects:
                if obj and hasattr(obj, "last_changed_time") and obj.last_changed_time is not None:
                    if current_time - obj.last_changed_time >= reset_seconds_threshold:
                        general_should_reset = True
                        break

        # 2. 프리셋 날짜 만료 조건 판단
        preset_objects = [preset_start_obj, preset_end_obj]
        preset_should_reset = False
        if reset_minutes > 0:
            for obj in preset_objects:
                if obj and hasattr(obj, "last_changed_time") and obj.last_changed_time is not None:
                    if current_time - obj.last_changed_time >= reset_seconds_threshold:
                        preset_should_reset = True
                        break

        # --- A. 일반 폼 초기화 독립 실행 ---
        if general_should_reset:
            _LOGGER.info("일반 폼 설정 시간(%d분) 만료 도달 -> 독립 초기화 가동", reset_minutes)
            if carno_obj: await carno_obj.async_set_value("")
            if phone_obj: await phone_obj.async_set_value("")
            if start_obj: await start_obj.async_set_value(today)
            if end_obj: await end_obj.async_set_value(today)
            
            ctx = hass.data[DOMAIN].get(entry.entry_id, {}).get("reserve_ctx", {})
            purpose_entity_id = ctx.get("purpose")
            if purpose_entity_id:
                select_component = hass.data.get("entity_components", {}).get("select")
                if select_component:
                    purpose_obj = select_component.get_entity(purpose_entity_id)
                    if purpose_obj: await purpose_obj.async_select_option("기타")
            
            for obj in general_objects:
                if obj and hasattr(obj, "last_changed_time"): obj.last_changed_time = None

        # --- B. 프리셋 폼 초기화 독립 실행 ---
        if preset_should_reset:
            _LOGGER.info("프리셋 날짜 폼 설정 시간(%d분) 만료 도달 -> 독립 초기화 가동", reset_minutes)
            if preset_start_obj: await preset_start_obj.async_set_value(today)
            if preset_end_obj: await preset_end_obj.async_set_value(today)
            
            for obj in preset_objects:
                if obj and hasattr(obj, "last_changed_time"): obj.last_changed_time = None

    if "fee_unsub" in entry_data and entry_data["fee_unsub"]: entry_data["fee_unsub"]()
    if "car_unsub" in entry_data and entry_data["car_unsub"]: entry_data["car_unsub"]()

    entry_data["fee_unsub"] = async_track_time_interval(hass, _async_maintenance_fee_refresh_loop, timedelta(seconds=fee_seconds_threshold))
    entry_data["car_unsub"] = async_track_time_interval(hass, _async_car_and_timer_refresh_loop, timedelta(seconds=refresh_seconds))

    entry.add_update_listener(async_reload_entry)
    return True

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    entry_data = hass.data[DOMAIN].get(entry.entry_id, {})
    if "fee_unsub" in entry_data and entry_data["fee_unsub"]: entry_data["fee_unsub"]()
    if "car_unsub" in entry_data and entry_data["car_unsub"]: entry_data["car_unsub"]()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok: hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
