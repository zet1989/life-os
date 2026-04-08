"""HUAWEI Health Kit — интеграция со смарт-часами HUAWEI WATCH FIT 4 Pro.

Получает данные через HUAWEI Health Kit REST API:
- Шаги, дистанция, калории
- Пульс (средний, min, max)
- SpO2 (кислород в крови)
- Сон (фазы, продолжительность)
- Стресс
- Тренировки

Поток:
1. Пользователь авторизуется через OAuth2 (HUAWEI ID) — бот отдаёт ссылку.
2. Callback-endpoint получает code → обменивает на access_token + refresh_token.
3. Планировщик каждые 30 мин pull'ит данные и сохраняет в events.
4. Health-бот AI видит данные часов в контексте.
"""

import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import structlog

from src.config import settings
from src.db.queries import create_event

logger = structlog.get_logger()
MSK = ZoneInfo("Europe/Moscow")

# ── HUAWEI Health Kit endpoints ─────────────────────────

TOKEN_URL = "https://oauth-login.cloud.huawei.com/oauth2/v3/token"
HEALTH_API = "https://health-api.cloud.huawei.com/healthkit/v1"

# Data type constants (HUAWEI Health Kit)
DT_STEPS = "com.huawei.continuous.steps.delta"
DT_DISTANCE = "com.huawei.continuous.distance.delta"
DT_CALORIES = "com.huawei.continuous.calories.burnt"
DT_HEART_RATE = "com.huawei.instantaneous.heart_rate"
DT_SPO2 = "com.huawei.instantaneous.blood_oxygen"
DT_STRESS = "com.huawei.instantaneous.stress"
DT_SLEEP = "com.huawei.continuous.sleep.fragment"
DT_ACTIVITY = "com.huawei.activity.segment"
DT_SKIN_TEMP = "com.huawei.instantaneous.skin_temperature"


class HuaweiHealthClient:
    """Клиент HUAWEI Health Kit REST API."""

    def __init__(self) -> None:
        self.client_id = settings.huawei_client_id
        self.client_secret = settings.huawei_client_secret
        self._http = httpx.AsyncClient(timeout=30)

    # ── OAuth2 ──────────────────────────────────────────

    def get_auth_url(self, redirect_uri: str) -> str:
        """Сгенерировать URL авторизации для пользователя."""
        scopes = (
            "https://www.huawei.com/healthkit/step.read "
            "https://www.huawei.com/healthkit/heartrate.read "
            "https://www.huawei.com/healthkit/oxygensaturation.read "
            "https://www.huawei.com/healthkit/sleep.read "
            "https://www.huawei.com/healthkit/stress.read "
            "https://www.huawei.com/healthkit/calories.read "
            "https://www.huawei.com/healthkit/activity.read "
            "https://www.huawei.com/healthkit/distance.read "
            "https://www.huawei.com/healthkit/bodytemperature.read"
        )
        return (
            f"https://oauth-login.cloud.huawei.com/oauth2/v3/authorize?"
            f"response_type=code"
            f"&client_id={self.client_id}"
            f"&redirect_uri={redirect_uri}"
            f"&scope={scopes}"
            f"&access_type=offline"
        )

    async def exchange_code(self, code: str, redirect_uri: str) -> dict:
        """Обменять authorization code на токены."""
        resp = await self._http.post(TOKEN_URL, data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": redirect_uri,
        })
        resp.raise_for_status()
        return resp.json()

    async def refresh_access_token(self, refresh_token: str) -> dict:
        """Обновить access_token по refresh_token."""
        resp = await self._http.post(TOKEN_URL, data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        })
        resp.raise_for_status()
        return resp.json()

    # ── Data fetch ──────────────────────────────────────

    async def _read_data(
        self,
        access_token: str,
        data_type: str,
        start_ms: int,
        end_ms: int,
    ) -> list[dict]:
        """Прочитать данные из Health Kit."""
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        body = {
            "dataTypeName": data_type,
            "startTime": start_ms,
            "endTime": end_ms,
        }
        try:
            resp = await self._http.post(
                f"{HEALTH_API}/data/read",
                headers=headers,
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("group", [])
        except httpx.HTTPStatusError as e:
            logger.warning("huawei_api_error", status=e.response.status_code, data_type=data_type)
            return []
        except Exception:
            logger.exception("huawei_read_failed", data_type=data_type)
            return []

    # ── High-level data getters ─────────────────────────

    async def get_steps(self, access_token: str, start: datetime, end: datetime) -> int:
        """Получить шаги за период."""
        groups = await self._read_data(
            access_token, DT_STEPS,
            _to_ms(start), _to_ms(end),
        )
        total = 0
        for g in groups:
            for point in g.get("dataPoints", []):
                for field in point.get("fields", []):
                    if field.get("fieldName") == "steps":
                        total += int(field.get("intValue", 0))
        return total

    async def get_heart_rate(self, access_token: str, start: datetime, end: datetime) -> dict:
        """Получить данные пульса: min, max, avg, last."""
        groups = await self._read_data(
            access_token, DT_HEART_RATE,
            _to_ms(start), _to_ms(end),
        )
        values = []
        for g in groups:
            for point in g.get("dataPoints", []):
                for field in point.get("fields", []):
                    if field.get("fieldName") == "heart_rate":
                        values.append(float(field.get("floatValue", 0)))
        if not values:
            return {}
        return {
            "min": int(min(values)),
            "max": int(max(values)),
            "avg": int(sum(values) / len(values)),
            "last": int(values[-1]),
            "readings": len(values),
        }

    async def get_spo2(self, access_token: str, start: datetime, end: datetime) -> dict:
        """Получить SpO2 (кислород в крови)."""
        groups = await self._read_data(
            access_token, DT_SPO2,
            _to_ms(start), _to_ms(end),
        )
        values = []
        for g in groups:
            for point in g.get("dataPoints", []):
                for field in point.get("fields", []):
                    if field.get("fieldName") == "blood_oxygen":
                        values.append(float(field.get("floatValue", 0)))
        if not values:
            return {}
        return {
            "min": int(min(values)),
            "max": int(max(values)),
            "avg": int(sum(values) / len(values)),
            "last": int(values[-1]),
        }

    async def get_stress(self, access_token: str, start: datetime, end: datetime) -> dict:
        """Получить уровень стресса."""
        groups = await self._read_data(
            access_token, DT_STRESS,
            _to_ms(start), _to_ms(end),
        )
        values = []
        for g in groups:
            for point in g.get("dataPoints", []):
                for field in point.get("fields", []):
                    if field.get("fieldName") == "stress":
                        values.append(int(field.get("intValue", 0)))
        if not values:
            return {}
        return {
            "min": min(values),
            "max": max(values),
            "avg": round(sum(values) / len(values)),
            "last": values[-1],
        }

    async def get_sleep(self, access_token: str, start: datetime, end: datetime) -> dict:
        """Получить данные сна: фазы + общая продолжительность."""
        groups = await self._read_data(
            access_token, DT_SLEEP,
            _to_ms(start), _to_ms(end),
        )
        phases: dict[str, float] = {"awake": 0, "light": 0, "deep": 0, "rem": 0}
        total_min = 0
        for g in groups:
            for point in g.get("dataPoints", []):
                start_ms = int(point.get("startTime", 0))
                end_ms = int(point.get("endTime", 0))
                duration_min = max(0, (end_ms - start_ms) / 60000)
                sleep_type = None
                for field in point.get("fields", []):
                    if field.get("fieldName") == "sleep_state":
                        sleep_type = int(field.get("intValue", 0))
                # HUAWEI sleep states: 1=awake, 2=light, 3=deep, 4=REM
                if sleep_type == 1:
                    phases["awake"] += duration_min
                elif sleep_type == 2:
                    phases["light"] += duration_min
                    total_min += duration_min
                elif sleep_type == 3:
                    phases["deep"] += duration_min
                    total_min += duration_min
                elif sleep_type == 4:
                    phases["rem"] += duration_min
                    total_min += duration_min

        if total_min == 0:
            return {}
        return {
            "total_hours": round(total_min / 60, 1),
            "deep_min": round(phases["deep"]),
            "light_min": round(phases["light"]),
            "rem_min": round(phases["rem"]),
            "awake_min": round(phases["awake"]),
            "quality_pct": round((phases["deep"] + phases["rem"]) / total_min * 100) if total_min else 0,
        }

    async def get_calories(self, access_token: str, start: datetime, end: datetime) -> int:
        """Получить сожжённые калории за период."""
        groups = await self._read_data(
            access_token, DT_CALORIES,
            _to_ms(start), _to_ms(end),
        )
        total = 0.0
        for g in groups:
            for point in g.get("dataPoints", []):
                for field in point.get("fields", []):
                    if field.get("fieldName") == "calories":
                        total += float(field.get("floatValue", 0))
        return round(total)

    async def get_distance(self, access_token: str, start: datetime, end: datetime) -> float:
        """Получить дистанцию в км."""
        groups = await self._read_data(
            access_token, DT_DISTANCE,
            _to_ms(start), _to_ms(end),
        )
        total = 0.0
        for g in groups:
            for point in g.get("dataPoints", []):
                for field in point.get("fields", []):
                    if field.get("fieldName") == "distance":
                        total += float(field.get("floatValue", 0))
        return round(total / 1000, 2)  # meters → km

    # ── Aggregate: pull all data and save ───────────────

    async def pull_and_save(self, user_id: int, access_token: str) -> dict:
        """Запросить все метрики за последние 30 мин и сохранить в events.

        Returns:
            dict со всеми собранными данными (или пустой при ошибке).
        """
        now = datetime.now(MSK)
        start = now - timedelta(minutes=30)

        steps = await self.get_steps(access_token, start, now)
        heart_rate = await self.get_heart_rate(access_token, start, now)
        spo2 = await self.get_spo2(access_token, start, now)
        stress = await self.get_stress(access_token, start, now)
        calories = await self.get_calories(access_token, start, now)
        distance = await self.get_distance(access_token, start, now)

        # Сон — берём за последние 12 часов (может включать ночь)
        sleep_start = now - timedelta(hours=12)
        sleep = await self.get_sleep(access_token, sleep_start, now)

        data: dict[str, Any] = {
            "source": "huawei_watch_fit4_pro",
            "period_start": start.isoformat(),
            "period_end": now.isoformat(),
        }
        if steps:
            data["steps"] = steps
        if heart_rate:
            data["heart_rate"] = heart_rate
        if spo2:
            data["spo2"] = spo2
        if stress:
            data["stress"] = stress
        if calories:
            data["calories_burned"] = calories
        if distance:
            data["distance_km"] = distance
        if sleep:
            data["sleep"] = sleep

        # Сохраняем только если есть реальные данные
        has_data = any(k not in ("source", "period_start", "period_end") for k in data)
        if has_data:
            await create_event(
                user_id=user_id,
                event_type="watch_metrics",
                bot_source="health",
                raw_text=_format_summary(data),
                json_data=data,
            )
            logger.info("huawei_data_saved", user_id=user_id, keys=list(data.keys()))

        return data

    async def pull_daily_summary(self, user_id: int, access_token: str) -> dict:
        """Собрать полную дневную сводку с часов (за сегодня)."""
        now = datetime.now(MSK)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        steps = await self.get_steps(access_token, start, now)
        heart_rate = await self.get_heart_rate(access_token, start, now)
        spo2 = await self.get_spo2(access_token, start, now)
        stress = await self.get_stress(access_token, start, now)
        calories = await self.get_calories(access_token, start, now)
        distance = await self.get_distance(access_token, start, now)

        # Сон за прошлую ночь
        sleep_start = now - timedelta(hours=14)
        sleep = await self.get_sleep(access_token, sleep_start, start + timedelta(hours=12))

        return {
            "steps": steps,
            "distance_km": distance,
            "calories_burned": calories,
            "heart_rate": heart_rate,
            "spo2": spo2,
            "stress": stress,
            "sleep": sleep,
        }

    async def close(self) -> None:
        await self._http.aclose()


# ── Helpers ─────────────────────────────────────────────

def _to_ms(dt: datetime) -> int:
    """datetime → milliseconds since epoch."""
    return int(dt.timestamp() * 1000)


def _format_summary(data: dict) -> str:
    """Форматировать данные в читаемый текст для RAG."""
    parts = []
    if "steps" in data:
        parts.append(f"Шаги: {data['steps']}")
    if "distance_km" in data:
        parts.append(f"Дистанция: {data['distance_km']} км")
    if "calories_burned" in data:
        parts.append(f"Сожжено: {data['calories_burned']} ккал")
    if "heart_rate" in data:
        hr = data["heart_rate"]
        parts.append(f"Пульс: {hr.get('avg', '?')} (мин {hr.get('min', '?')}, макс {hr.get('max', '?')})")
    if "spo2" in data:
        sp = data["spo2"]
        parts.append(f"SpO2: {sp.get('avg', '?')}%")
    if "stress" in data:
        st = data["stress"]
        parts.append(f"Стресс: {st.get('avg', '?')}/100")
    if "sleep" in data:
        sl = data["sleep"]
        parts.append(f"Сон: {sl.get('total_hours', '?')}ч (глубокий {sl.get('deep_min', 0)} мин, REM {sl.get('rem_min', 0)} мин)")
    return "⌚ Данные часов: " + " | ".join(parts) if parts else "⌚ Нет данных"


# Синглтон (инициализируется только если настроен)
huawei_health: HuaweiHealthClient | None = None


def get_huawei_client() -> HuaweiHealthClient | None:
    """Ленивая инициализация клиента (только если задан client_id)."""
    global huawei_health
    if huawei_health is None and settings.huawei_client_id:
        huawei_health = HuaweiHealthClient()
    return huawei_health
