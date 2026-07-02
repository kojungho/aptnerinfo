import aiohttp
import asyncio
import logging
import time
from datetime import datetime

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://v2.aptner.com"
TOKEN_URL = f"{BASE_URL}/auth/token"
REFRESH_URL = f"{BASE_URL}/auth/refresh"

class AptnerAuth:
    def __init__(self, user_id: str, password: str, session: aiohttp.ClientSession):
        self.user_id = user_id
        self.password = password
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self.token_expiry_timestamp: float = 0.0
        # [핵심 교정] 단독 생성되던 소켓 루프를 전면 중단하고 주입받은 핵심 전역 세션에 결합 바인딩
        self.session = session
        self._login_lock = asyncio.Lock()

    def _get_default_headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "User-Agent": "Home Assistant",
            "x-app-version": "2.2.0",
            "x-device-model": "Home Assistant",
            "x-os-version": "Home Assistant"
        }

    def _is_access_token_valid(self) -> bool:
        if not self.access_token or self.token_expiry_timestamp == 0.0:
            return False
        return time.time() < (self.token_expiry_timestamp - 30)

    def _extract_expiry_from_jwt(self, token: str) -> float:
        try:
            import base64
            import json
            payload_b64 = token.split(".")[1]
            payload_b64 += "=" * ((4 - len(payload_b64) % 4) % 4)
            payload_json = base64.urlsafe_b64decode(payload_b64).decode("utf-8")
            payload = json.loads(payload_json)
            return float(payload.get("exp", time.time() + 300))
        except Exception:
            return time.time() + 300

    async def _execute_auth_request(self, url: str, json_payload: dict, attempt: int, max_attempts: int, delay: int) -> dict | None:
        try:
            async with self.session.post(url, json=json_payload, headers=self._get_default_headers(), timeout=10) as resp:
                if resp.status == 429:
                    # [핵심 교정] 429 감지 시 백오프 비동기 대기 처리를 상위 레이어로 이관하여 언클로즈 세션 소거
                    _LOGGER.warning("인증 서버의 트래픽 과부하 방어막(429) 작동 포착 -> 강제 예외 반환")
                    raise Exception("429 Too Many Requests (Auth)")
                resp.raise_for_status()
                return await resp.json()
        except Exception as e:
            if "429" in str(e): raise
            _LOGGER.error("인증 엔드포인트 통신 실패: %s", e)
            if attempt == max_attempts: raise
            await asyncio.sleep(0.1)
            return None

    async def login(self, force: bool = False) -> str:
        async with self._login_lock:
            if not force and self._is_access_token_valid(): return self.access_token
            backoffs = [1, 2, 3]
            
            if self.refresh_token:
                headers = self._get_default_headers()
                headers["Authorization"] = f"Bearer {self.refresh_token}"
                try:
                    async with self.session.post(REFRESH_URL, headers=headers, timeout=10) as resp:
                        if resp.status == 429: raise Exception("429 Too Many Requests (Refresh)")
                        if resp.status == 200:
                            data = await resp.json()
                            self.access_token = data.get("accessToken")
                            self.refresh_token = data.get("refreshToken")
                            self.token_expiry_timestamp = self._extract_expiry_from_jwt(self.access_token)
                            return self.access_token
                except Exception as e:
                    if "429" in str(e): raise

            for attempt, delay in enumerate(backoffs, start=1):
                payload = {"id": self.user_id, "password": self.password, "isShowUpdateTerms": False}
                try:
                    data = await self._execute_auth_request(TOKEN_URL, payload, attempt, len(backoffs), delay)
                    if data:
                        self.access_token = data.get("accessToken")
                        self.refresh_token = data.get("refreshToken")
                        self.token_expiry_timestamp = self._extract_expiry_from_jwt(self.access_token)
                        return self.access_token
                except Exception as e:
                    if "429" in str(e): raise
                    if attempt == len(backoffs): raise

            raise Exception("아파트너 인증 토큰 획득 실패")

    async def request(self, method: str, path: str, **kwargs) -> dict:
        if not self._is_access_token_valid(): await self.login()
        token = self.access_token
        
        headers = kwargs.pop("headers", self._get_default_headers())
        headers["Authorization"] = f"Bearer {token}"
        headers["Content-Type"] = "application/json"
        url = f"{BASE_URL}{path}" if not path.startswith("http") else path
        
        async with self.session.request(method, url, headers=headers, **kwargs) as resp:
            if resp.status == 401:
                token = await self.login(force=True)
                headers["Authorization"] = f"Bearer {token}"
                async with self.session.request(method, url, headers=headers, **kwargs) as resp2:
                    resp2.raise_for_status()
                    return await resp2.json()
            elif resp.status == 429:
                _LOGGER.warning("데이터 동기화 트래픽 429 차단벽 임계치 도달. 세션을 즉시 안전 회수합니다.")
                raise Exception("429 Too Many Requests")
            resp.raise_for_status()
            return await resp.json()

    async def close(self):
        # 이제 전역 코어 통합 세션을 관리하므로, 개별 플러그인 폐쇄 수동 호출 절차를 패스 처리합니다.
        pass
