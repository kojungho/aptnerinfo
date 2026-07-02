import logging
from datetime import datetime, timedelta
from homeassistant.core import HomeAssistant, SupportsResponse
from .aptner_auth import AptnerAuth
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

def register_services(hass: HomeAssistant, entry):
    """Home Assistant에 서비스 등록"""
    entry_id = entry.entry_id

    # 1 & 3. 서비스 영문 키 사용 및 응답(Response) 지원 추가
    hass.services.async_register(
        DOMAIN, "find_car",
        lambda call: _call_service(hass, entry_id, "find_car", call),
        supports_response=SupportsResponse.OPTIONAL
    )
    hass.services.async_register(
        DOMAIN, "get_fee",
        lambda call: _call_service(hass, entry_id, "get_fee", call),
        supports_response=SupportsResponse.OPTIONAL
    )
    hass.services.async_register(
        DOMAIN, "reserve_car",
        lambda call: _call_service(hass, entry_id, "reserve_car", call),
        supports_response=SupportsResponse.OPTIONAL
    )
    hass.services.async_register(
        DOMAIN, "get_reserve_status",
        lambda call: _call_service(hass, entry_id, "get_reserve_status", call),
        supports_response=SupportsResponse.OPTIONAL
    )


async def _call_service(hass: HomeAssistant, entry_id: str, service_name: str, call):
    auth: AptnerAuth = hass.data[DOMAIN][entry_id]["auth"]

    try:
        if service_name == "find_car":
            carno = call.data.get("carno")
            history = await auth.request("GET", "/pc/monthly-access-history")
            response = {}
            for monthly in history.get("monthlyParkingHistoryList", []):
                for car in monthly.get("visitCarUseHistoryReportList", []):
                    if carno is None or car["carNo"] == carno:
                        status = "입차" if not car.get("isExit") else "출차"
                        response[car["carNo"]] = {"status": status}
            return response

        elif service_name == "get_fee":
            fee = (await auth.request("GET", "/fee/detail"))["fee"]
            return {
                "year": fee["year"],
                "month": fee["month"],
                "fee": fee["currentFee"],
                "details": {item["name"]: item["value"] for item in fee.get("details", [])}
            }

        elif service_name == "reserve_car":
            data = {
                "visitDate": call.data.get("date"),
                "purpose": call.data.get("purpose"),
                "carNo": call.data.get("carno"),
                "days": call.data.get("days"),
                "phone": call.data.get("phone")
            }
            return await auth.request("POST", "/pc/reserve/", json=data)

        elif service_name == "get_reserve_status":
            totalpages = 0
            currentpage = 0
            today = datetime.today().date()
            result = {}

            while True:
                currentpage += 1
                reservedcars = await auth.request("GET", f"/pc/reserves?pg={currentpage}")
                if totalpages == 0:
                    totalpages = reservedcars.get("totalPages", 0)
                for reservedcar in reservedcars.get("reserveList", []):
                    visitdate = datetime.strptime(reservedcar["visitDate"], "%Y.%m.%d").date()
                    # 4. 당일 예약도 포함되도록 조건 변경
                    if today <= visitdate:
                        result.setdefault(reservedcar["carNo"], []).append(visitdate)
                if currentpage >= totalpages:
                    break

            # 4. 최대 10대 제한 유지하되, 배열(List of Dictionaries) 형태로 구조화
            response = []
            idx = 0
            for car, dates in result.items():
                idx += 1
                if idx > 10:
                    break
                dates.sort()
                start = dates[0]
                ranges = []
                for i in range(1, len(dates)):
                    prev, curr = dates[i-1], dates[i]
                    if (curr - prev).days > 1:
                        ranges.append({"from": str(start), "to": str(prev)})
                        start = curr
                ranges.append({"from": str(start), "to": str(dates[-1])})

                # 커스텀 카드 등에서 반복문을 돌리기 쉬운 구조로 변경
                response.append({
                    "car_no": car,
                    "ranges": ranges
                })

            return {
                "count": len(response),
                "cars": response
            }

    except Exception as e:
        _LOGGER.error("서비스 호출 실패(%s): %s", service_name, e)
        return None