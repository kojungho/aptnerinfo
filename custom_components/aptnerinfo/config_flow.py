from __future__ import annotations

import logging
from typing import Any
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .aptner_auth import AptnerAuth
from .const import DOMAIN, CONF_ID, CONF_PASSWORD, CONF_APT_NAME

_LOGGER = logging.getLogger(__name__)

class AptnerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> AptnerOptionsFlowHandler:
        return AptnerOptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors = {}
        if user_input is not None:
            apt_name = user_input.get(CONF_APT_NAME)
            user_id = user_input[CONF_ID]
            password = user_input[CONF_PASSWORD]
            
            # [치명적 버그 선제 교정] 변경된 AptnerAuth 규격에 맞춰 config_flow에서도 전역 세션(Session) 주입
            session = async_get_clientsession(self.hass)
            auth = AptnerAuth(user_id, password, session)
            
            try:
                await auth.login()
                # 전역 세션을 사용하므로 강제 닫기(close) 대신 로그인 인증 성공 여부만 확인하고 넘어갑니다.
                
                return self.async_create_entry(
                    title=f"{apt_name} ({user_id})",
                    data={
                        CONF_APT_NAME: apt_name,
                        CONF_ID: user_id,
                        CONF_PASSWORD: password,
                    }
                )
            except Exception as e:
                _LOGGER.error("통합구성요소 초기 등록 로그인 실패: %s", e)
                errors["base"] = "invalid_auth"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_APT_NAME): str,
                vol.Required(CONF_ID): str,
                vol.Required(CONF_PASSWORD): str,
            }),
            errors=errors,
        )

class AptnerOptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="아파트너 가변 설정", data=user_input)

        options = self._config_entry.options
        refresh_interval = options.get("refresh_interval_seconds", 30)
        idle_interval = options.get("idle_refresh_interval", 300)
        fee_hours = options.get("fee_refresh_hours", 24)
        reset_minutes = options.get("form_reset_minutes", 5)
        
        # [교정] 개별 제어 스위치 엔티티 신설에 따라 컴팩트한 오리지널 주정차 스케줄 팩만 연동 유지
        data_schema = vol.Schema({
            vol.Required("refresh_interval_seconds", default=refresh_interval): selector.NumberSelector(
                selector.NumberSelectorConfig(min=30, max=600, mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Required("idle_refresh_interval", default=idle_interval): selector.NumberSelector(
                selector.NumberSelectorConfig(min=300, max=3600, mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Required("fee_refresh_hours", default=fee_hours): selector.NumberSelector(
                selector.NumberSelectorConfig(min=24, max=720, mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Required("form_reset_minutes", default=reset_minutes): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=60, mode=selector.NumberSelectorMode.BOX)
            ),
        })

        return self.async_show_form(
            step_id="init",
            data_schema=data_schema
        )
