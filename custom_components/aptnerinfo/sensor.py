from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, date
import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.util import dt as dt_util
from .const import DOMAIN, CONF_APT_NAME

_LOGGER = logging.getLogger(__name__)

ICON_MAPPING = {
    "일반관리비": "mdi:office-building", "청소비": "mdi:broom", "경비비": "mdi:security",
    "소독비": "mdi:bacteria", "승강기유지비": "mdi:elevator", "수선유지비": "mdi:wrench",
    "장기수선충당금": "mdi:piggy-bank", "위탁관리수수료": "mdi:handshake", "건물보험료": "mdi:shield-home",
    "관리비차감": "mdi:cash-minus", "대표회의운영비": "mdi:account-group", "선거관리운영비": "mdi:vote",
    "가 수 금": "mdi:receipt-text-outline", "세대전기료": "mdi:flash", "공동전기료": "mdi:flash-outline",
    "승강기전기": "mdi:elevator-passenger", "TV수신료": "mdi:television", "주차위반": "mdi:alert",
    "세대수도료": "mdi:water", "공동수도료": "mdi:water-outline", "하수도료": "mdi:water-pump",
    "세대난방비": "mdi:fire", "기본난방비": "mdi:fire-circle", "공동난방비": "mdi:fire-hydrant",
    "세대급탕비": "mdi:water-boiler", "전기차충전료": "mdi:ev-station", "홈네트워크유지": "mdi:lan",
    "커뮤니티차감": "mdi:storefront-minus", "주차비": "mdi:parking", "커뮤니티사용료": "mdi:google-circles-communities",
    "커뮤니티기본료": "mdi:storefront", "병렬주차비": "mdi:car-multiple", "15일이상주차비": "mdi:calendar-clock",
    "일자리지원차감": "mdi:briefcase-minus", "개별사용료": "mdi:receipt-text-outline", "납기내": "mdi:cash-check",
    "납기후": "mdi:cash-clock", "관리비소계": "mdi:calculator", "징수대행소계": "mdi:calculator-variant",
    "당월후연체료": "mdi:cash-marker", "전기할인요금": "mdi:percent", "수도할인요금": "mdi:percent-outline"
}

FEE_MAIN_FIELDS = {
    "currentLateFee": {"name": "관리비 당월 연체료", "icon": "mdi:cash-marker", "unit": "원", "cls": SensorDeviceClass.MONETARY, "st": SensorStateClass.TOTAL},
    "delinquentFee": {"name": "관리비 미납 연체금", "icon": "mdi:cash-alert", "unit": "원", "cls": SensorDeviceClass.MONETARY, "st": SensorStateClass.TOTAL},
    "delinquentLateFee": {"name": "관리비 미납 연체료", "icon": "mdi:cash-minus", "unit": "원", "cls": SensorDeviceClass.MONETARY, "st": SensorStateClass.TOTAL},
    "beforeDayFee": {"name": "관리비 납기내 금액", "icon": "mdi:cash-check", "unit": "원", "cls": SensorDeviceClass.MONETARY, "st": SensorStateClass.TOTAL},
    "afterDayFee": {"name": "관리비 납기후 금액", "icon": "mdi:cash-clock", "unit": "원", "cls": SensorDeviceClass.MONETARY, "st": SensorStateClass.TOTAL},
    "prevFee": {"name": "관리비 전월 총액", "icon": "mdi:calendar-arrow-left", "unit": "원", "cls": SensorDeviceClass.MONETARY, "st": SensorStateClass.TOTAL},
    "prevFeeContrast": {"name": "관리비 전월대비 증감", "icon": "mdi:chart-timeline-variant", "unit": "원", "cls": SensorDeviceClass.MONETARY, "st": None},
    "avgFee": {"name": "관리비 동일평형 평균", "icon": "mdi:calculator-variant", "unit": "원", "cls": SensorDeviceClass.MONETARY, "st": SensorStateClass.TOTAL},
    "avgFeeContrast": {"name": "관리비 평균대비 증감", "icon": "mdi:chart-bell-curve", "unit": "원", "cls": SensorDeviceClass.MONETARY, "st": None},
    "area": {"name": "세대 전용면적", "icon": "mdi:ruler-square", "unit": "㎡", "cls": None, "st": SensorStateClass.MEASUREMENT},
}

META_FIELDS = {
    "item_count": {"name": "관리비 세부 항목 수", "icon": "mdi:format-list-numbered", "unit": "건"},
}

async def async_setup_entry(hass, entry, async_add_entities):
    auth = hass.data[DOMAIN][entry.entry_id]["auth"]
    apt_name = entry.data.get(CONF_APT_NAME, "아파트명")

    class FeeCoordinator:
        def __init__(self, auth):
            self.auth = auth
            self.data = {}
            self.last_updated: Any | None = None
            self._lock = asyncio.Lock()

        async def update(self):
            if self._lock.locked(): return 
            async with self._lock:
                try:
                    data = await self.auth.request("GET", "/fee/detail")
                    fee = data.get("fee", {})
                    fee_list = data.get("feeList", [])
                    
                    details_list = fee.get("details", [])
                    parsed = {}
                    if isinstance(details_list, list):
                        for item in details_list:
                            if isinstance(item, dict) and "name" in item:
                                parsed[item["name"]] = item.get("value", 0)
                    fee["parsed_details"] = parsed
                    
                    self.data = {"fee": fee, "feeList": fee_list}
                    self.last_updated = dt_util.utcnow()
                except Exception as e: 
                    _LOGGER.error("fee update err: %s", e)

    class CarHubCoordinator:
        def __init__(self, auth, entry): 
            self.auth = auth
            self.entry = entry 
            self.data_car = {}
            self.data_reserve = {}
            self.last_updated: Any | None = None
            self._last_api_call_time: datetime | None = None
            self.current_mode: str = "초기화 중"
            self._lock = asyncio.Lock()

        @property
        def data(self):
            return self.data_reserve

        @data.setter
        def data(self, value):
            self.data_reserve = value

        def _has_today_reservation(self) -> bool:
            today = date.today()
            attrs = self.data_reserve.get("attrs", [])
            for item in attrs:
                visit_date_str = item.get("visitDate") or item.get("visit_date")
                if not visit_date_str: continue
                try:
                    norm_date = visit_date_str.replace(".", "-")
                    y, m, d = map(int, norm_date.split("-")[:3])
                    if date(y, m, d) == today:
                        return True
                except Exception: continue
            return False

        async def _fetch_car(self):
            history = await self.auth.request("GET", "/pc/monthly-access-history")
            access_list = history.get("monthlyParkingHistoryList", [])
            
            if access_list:
                latest_month = access_list[0]
                car_list = latest_month.get("visitCarUseHistoryReportList", [])
                
                latest_event_dt = None
                latest_event_str = "알 수 없음"
                
                for car in car_list:
                    car_no = car.get("carNo", "")
                    is_exit = car.get("isExit") in (True, "true", "True")
                    is_resident = car.get("isResident") in (True, "true", "True")
                    
                    dt_str = car.get("outDatetime") if is_exit else car.get("inDatetime")
                    
                    if dt_str:
                        try:
                            event_dt = datetime.strptime(dt_str, "%Y.%m.%d %H:%M")
                            if latest_event_dt is None or event_dt > latest_event_dt:
                                latest_event_dt = event_dt
                                action_str = "출차" if is_exit else "입차"
                                
                                formatted_time = latest_event_dt.strftime("%m.%d %H:%M")
                                if is_resident:
                                    latest_event_str = f"{formatted_time} | {car_no} | 입주민 | {action_str}"
                                else:
                                    latest_event_str = f"{formatted_time} | {car_no} | {action_str}"
                        except Exception:
                            pass
                
                self.data_car = {"native": latest_event_str, "attrs": latest_month}

        async def _fetch_reserve(self):
            res = await self.auth.request("GET", "/pc/reserves?pg=1")
            reserve_list = res.get("reserveList", [])
            
            today = date.today()
            filtered_reserves = []
            for item in reserve_list:
                visit_date_str = item.get("visitDate") or item.get("visit_date")
                if not visit_date_str: continue
                try:
                    norm_date = visit_date_str.replace(".", "-")
                    y, m, d = map(int, norm_date.split("-")[:3])
                    if date(y, m, d) >= today:
                        filtered_reserves.append(item)
                except Exception: continue
            
            try:
                filtered_reserves.sort(key=lambda x: (x.get("visitDate") or x.get("visit_date") or ""))
            except Exception:
                pass
            
            self.data_reserve = {"native": len(filtered_reserves), "attrs": filtered_reserves, "raw_root": res}

        async def update(self):
            if self._lock.locked(): return
            async with self._lock:
                try:
                    now = datetime.now()
                    
                    has_today = self._has_today_reservation()
                    idle_interval = self.entry.options.get("idle_refresh_interval", 300)

                    if not has_today and self._last_api_call_time is not None:
                        elapsed = (now - self._last_api_call_time).total_seconds()
                        if elapsed < idle_interval:
                            self.current_mode = f"스마트 절전 ({int(idle_interval)}초 주기 잠금 가동 중)"
                            return

                    if has_today:
                        self.current_mode = "실시간 감시 (당일 예약 포착 - 인터벌 주기 가동)"
                    else:
                        self.current_mode = f"스마트 절전 ({int(idle_interval)}초 주기 도달 - 데이터 갱신 시점)"

                    await asyncio.gather(self._fetch_car(), self._fetch_reserve())
                    
                    self._last_api_call_time = now
                    self.last_updated = dt_util.utcnow()
                except Exception as e: 
                    _LOGGER.error("CarHub 동기화 업데이트 에러 발생: %s", e)

    class ContactCoordinator:
        def __init__(self, auth):
            self.auth = auth
            self.data = []
            self.kapt_code = None
            self.last_updated: Any | None = None
            self._lock = asyncio.Lock()

        async def update(self):
            if self._lock.locked(): return
            async with self._lock:
                try:
                    if not self.kapt_code:
                        try:
                            user_data = await self.auth.request("GET", "/user/me")
                            self.kapt_code = user_data.get("kaptCode", "C41480117")
                        except Exception:
                            self.kapt_code = "C41480117"
                    
                    res = await self.auth.request("GET", f"/apt/contacts/{self.kapt_code}")
                    self.data = res.get("contactList", [])
                    self.last_updated = dt_util.utcnow()
                except Exception as e: 
                    _LOGGER.error("아파트 연락처 업데이트 에러 발생: %s", e)

    fc = FeeCoordinator(auth)
    chc = CarHubCoordinator(auth, entry) 
    cc = ContactCoordinator(auth)

    await asyncio.gather(fc.update(), chc.update(), cc.update())

    hass.data[DOMAIN][entry.entry_id]["coordinators"] = {"fee": fc, "car": chc, "reserve": chc, "contact": cc}

    # [교정 완료] 잡다한 보조 센서들을 전면 숙청하고 딱 1개의 핵심 주차 센서만 연동 유지
    entities = [
        AptnerFeeSensor(fc, entry.entry_id, f"{entry.entry_id}_fee_original", apt_name),
        AptnerFeePeriodSensor(fc, entry.entry_id, f"{entry.entry_id}_fee_period", apt_name),
        AptnerFeeDongHoSensor(fc, entry.entry_id, f"{entry.entry_id}_fee_dongho", apt_name),
        AptnerFeeHistorySensor(fc, entry.entry_id, f"{entry.entry_id}_fee_history", apt_name),
        AptnerCarSensor(chc, entry.entry_id, f"{entry.entry_id}_car_original", apt_name),
        AptnerReserveSensor(chc, entry.entry_id, f"{entry.entry_id}_reserve_original", apt_name),
        AptnerAvailableHouseholdLimitSensor(chc, entry.entry_id, f"{entry.entry_id}_available_household_limit", apt_name), # [유지 대상]
        AptnerFeeTimestampSensor(fc, entry.entry_id, f"{entry.entry_id}_fee_refresh_time", apt_name),
        AptnerCarTimestampSensor(chc, entry.entry_id, f"{entry.entry_id}_car_refresh_time", apt_name),
    ]

    for field_key, info in FEE_MAIN_FIELDS.items():
        entities.append(AptnerFeeMainExtendedSensor(fc, entry.entry_id, f"{entry.entry_id}_fee_main_{field_key}", apt_name, field_key, info))

    for key, info in META_FIELDS.items():
        entities.append(AptnerFeeMetaSensor(fc, entry.entry_id, f"{entry.entry_id}_fee_meta_{key}", apt_name, key, info))

    api_keys = list(fc.data.get("fee", {}).get("parsed_details", {}).keys())
    master_keys = list(ICON_MAPPING.keys())
    all_keys = sorted(list(set(api_keys + master_keys)))

    for field_key in all_keys:
        icon = ICON_MAPPING.get(field_key, "mdi:cash")
        entities.append(AptnerFeeDetailSensor(fc, entry.entry_id, f"{entry.entry_id}_fee_detail_{field_key}", apt_name, field_key, icon))

    for idx, item in enumerate(cc.data):
        title = item.get("title", f"연락처 {idx+1}")
        entities.append(AptnerContactSensor(cc, entry.entry_id, f"{entry.entry_id}_contact_{idx}", apt_name, idx, title))

    hass.data[DOMAIN].setdefault("sensor_entities", [])
    hass.data[DOMAIN]["sensor_entities"].clear()
    hass.data[DOMAIN]["sensor_entities"].extend(entities)

    async_add_entities(entities)


class _BaseAptnerSensor(SensorEntity):
    _attr_should_poll = False 

    def __init__(self, coordinator, entry_id: str, unique_id: str, apt_name: str):
        self.coordinator = coordinator
        self._entry_id = entry_id
        self._attr_unique_id = unique_id
        self._apt_name = apt_name

class AptnerContactSensor(_BaseAptnerSensor):
    def __init__(self, coordinator, entry_id: str, unique_id: str, apt_name: str, index: int, title: str):
        super().__init__(coordinator, entry_id, unique_id, apt_name)
        self._index = index
        self._attr_name = title
        self._attr_icon = "mdi:phone-classic"

    @property
    def native_value(self):
        if len(self.coordinator.data) > self._index:
            val = self.coordinator.data[self._index].get("tel")
            return val if val else "번호 없음"
        return "정보 없음"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if len(self.coordinator.data) > self._index:
            item = self.coordinator.data[self._index]
            return {
                "타이틀": item.get("title", ""),
                "전화번호": item.get("tel", ""),
                "운영시간": item.get("times", "")
            }
        return {}

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry_id}_contacts")},
            name=f"{self._apt_name} 연락처",
            manufacturer="Aptner Custom"
        )

class AptnerFeePeriodSensor(_BaseAptnerSensor):
    _attr_name = "관리비 기준월"
    _attr_icon = "mdi:calendar-month"

    @property
    def native_value(self):
        fee = self.coordinator.data.get("fee", {})
        year = fee.get("year")
        month = fee.get("month")
        if year and month:
            return f"{str(year)[-2:]}년 {month:02d}월"
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        fee = self.coordinator.data.get("fee", {})
        return {
            "year": fee.get("year", ""),
            "month": fee.get("month", "")
        }

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, f"{self._entry_id}_fee_center")}, name=f"{self._apt_name} 관리비", manufacturer="Aptner Custom")

class AptnerFeeDongHoSensor(_BaseAptnerSensor):
    _attr_name = "관리비 대상 세대"
    _attr_icon = "mdi:home-city"

    @property
    def native_value(self):
        fee = self.coordinator.data.get("fee", {})
        dong = fee.get("dong")
        host = fee.get("ho")
        if dong and host:
            return f"{dong}동 {host}호"
        return "정보 없음"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        fee = self.coordinator.data.get("fee", {})
        return {
            "dong": fee.get("dong", ""),
            "ho": fee.get("ho", "")
        }

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, f"{self._entry_id}_fee_center")}, name=f"{self._apt_name} 관리비", manufacturer="Aptner Custom")

class AptnerFeeHistorySensor(_BaseAptnerSensor):
    _attr_name = "관리비 과거 이력"
    _attr_icon = "mdi:history"
    _attr_native_unit_of_measurement = "건"

    @property
    def native_value(self):
        fee_list = self.coordinator.data.get("feeList", [])
        return len(fee_list)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        fee_list = self.coordinator.data.get("feeList", [])
        history_dict = {}
        for item in fee_list:
            y = str(item.get("year"))
            m = item.get("month")
            f = item.get("currentFee", 0)
            if y and m is not None:
                if y not in history_dict: history_dict[y] = {}
                history_dict[y][f"{m}월"] = f"{f:,} 원" if isinstance(f, int) else f"{f} 원"
        return history_dict

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, f"{self._entry_id}_fee_center")}, name=f"{self._apt_name} 관리비", manufacturer="Aptner Custom")

class AptnerFeeSensor(_BaseAptnerSensor):
    _attr_name = "관리비 총액"
    _attr_native_unit_of_measurement = "원"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL

    @property
    def native_value(self):
        return self.coordinator.data.get("fee", {}).get("currentFee")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        fee = self.coordinator.data.get("fee", {})
        return {
            "dong": fee.get("dong", ""),
            "ho": fee.get("ho", ""),
            "year": fee.get("year", ""),
            "month": fee.get("month", "")
        }

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, f"{self._entry_id}_fee_center")}, name=f"{self._apt_name} 관리비", manufacturer="Aptner Custom")

class AptnerFeeMainExtendedSensor(_BaseAptnerSensor):
    def __init__(self, coordinator, entry_id: str, unique_id: str, apt_name: str, field_key: str, info: dict):
        super().__init__(coordinator, entry_id, unique_id, apt_name)
        self._field_key = field_key
        self._attr_name = info["name"]
        self._attr_icon = info["icon"]
        if info["unit"]: self._attr_native_unit_of_measurement = info["unit"]
        if info["cls"]: self._attr_device_class = info["cls"]
        if info.get("st"): self._attr_state_class = info["st"]

    @property
    def native_value(self):
        val = self.coordinator.data.get("fee", {}).get(self._field_key)
        if val is None: return None
        if self._field_key == "area":
            try: return float(val)
            except ValueError: return val
        return val

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, f"{self._entry_id}_fee_center")}, name=f"{self._apt_name} 관리비", manufacturer="Aptner Custom")

class AptnerFeeTimestampSensor(_BaseAptnerSensor):
    _attr_name = "관리비 조회 갱신 시간"
    _attr_icon = "mdi:clock-check-outline"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.last_updated

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, f"{self._entry_id}_fee_center")}, name=f"{self._apt_name} 관리비", manufacturer="Aptner Custom")

class AptnerFeeMetaSensor(_BaseAptnerSensor):
    def __init__(self, coordinator, entry_id: str, unique_id: str, apt_name: str, field_key: str, info: dict):
        super().__init__(coordinator, entry_id, unique_id, apt_name)
        self._field_key = field_key
        self._attr_name = info["name"]
        self._attr_icon = info["icon"]
        if info["unit"]: self._attr_native_unit_of_measurement = info["unit"]

    @property
    def native_value(self):
        fee_data = self.coordinator.data.get("fee", {})
        if self._field_key == "item_count":
            return len(fee_data.get("parsed_details", {}))
        return None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, f"{self._entry_id}_fee_center")}, name=f"{self._apt_name} 관리비", manufacturer="Aptner Custom")

class AptnerFeeDetailSensor(_BaseAptnerSensor):
    _attr_native_unit_of_measurement = "원"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    
    def __init__(self, coordinator, entry_id: str, unique_id: str, apt_name: str, field_key: str, icon: str):
        super().__init__(coordinator, entry_id, unique_id, apt_name)
        self._field_key = field_key
        self._attr_name = field_key
        self._attr_icon = icon

    @property
    def native_value(self):
        return self.coordinator.data.get("fee", {}).get("parsed_details", {}).get(self._field_key, 0)

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, f"{self._entry_id}_fee_center")}, name=f"{self._apt_name} 관리비", manufacturer="Aptner Custom")

class AptnerCarSensor(_BaseAptnerSensor):
    _attr_name = "최근 입출차 차량"
    _attr_icon = "mdi:car-arrow-right"

    @property
    def native_value(self):
        return self.coordinator.data_car.get("native")

    @property
    def extra_state_attributes(self):
        return self.coordinator.data_car.get("attrs", {})

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._entry_id)}, name=f"{self._apt_name} 주차", manufacturer="Aptner Custom")

class AptnerCarTimestampSensor(_BaseAptnerSensor):
    _attr_name = "차량 조회 갱신 시간"
    _attr_icon = "mdi:clock-digital"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.last_updated

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"현재_동작_모드": getattr(self.coordinator, "current_mode", "알 수 없음")}

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._entry_id)}, name=f"{self._apt_name} 주차", manufacturer="Aptner Custom")

class AptnerReserveSensor(_BaseAptnerSensor):
    _attr_name = "방문차량 예약현황"
    _attr_icon = "mdi:car-key"
    _attr_native_unit_of_measurement = "건"
    
    @property
    def native_value(self) -> int:
        return self.coordinator.data_reserve.get("native", 0)
        
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        filtered = self.coordinator.data_reserve.get("attrs", [])
        attrs = {"total_valid_count": len(filtered)}
        for idx, item in enumerate(filtered, start=1):
            reserve_id = item.get("visitReserveIdx") or item.get("idx") or item.get("reserveIdx") or ""
            attrs[f"예약{idx}"] = {
                "차량번호": item.get("carNo") or item.get("car_no"),
                "예약일자": item.get("visitDate") or item.get("visit_date"),
                "목적": item.get("purpose") or item.get("visit_purpose"),
                "예약번호": reserve_id
            }
        return attrs

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._entry_id)}, name=f"{self._apt_name} 주차", manufacturer="Aptner Custom")


# =====================================================================
# [독립 수령 및 개명 완료] 세대 한도 수집 단일 파서 (이름 변경 반영)
# =====================================================================
class AptnerAvailableHouseholdLimitSensor(_BaseAptnerSensor):
    # [교정] 직관성을 위해 요청하신 명칭으로 완벽하게 엔티티 이름 수정 적용
    _attr_name = "방문차량 주차 남은시간"
    _attr_icon = "mdi:clock-outline"
    _attr_native_unit_of_measurement = "분"
    _attr_state_class = SensorStateClass.TOTAL

    @property
    def native_value(self) -> int | None:
        """추가 트래픽 발송 없이, 예약 동기화 시점에 받아둔 최상위 visitConfig 트리 노드를 안전하게 리딩"""
        raw_root = getattr(self.coordinator, "data_reserve", {}).get("raw_root", {})
        if not raw_root:
            return None
        return raw_root.get("visitConfig", {}).get("availableHouseHoldLimit")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        raw_root = getattr(self.coordinator, "data_reserve", {}).get("raw_root", {})
        config = raw_root.get("visitConfig", {})
        return {
            "주차_예약_세대_한도_시간": config.get("availableLimitText", "정보 없음"),
            "최대_예약_가능_일수": config.get("parkingReserveHouseholdLimit", "정보 없음"),
            "동일_차량_월간_제한_일수": config.get("parkingReserveCarLimit", "정보 없음"),
            "예약_가능_시작시간": config.get("visitReserveStartTime", "정보 없음"),
            "예약_가능_종료시간": config.get("visitReserveEndTime", "정보 없음")
        }

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._entry_id)}, name=f"{self._apt_name} 주차", manufacturer="Aptner Custom")
