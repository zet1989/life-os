"""Amazfit Balance 2 — интеграция со смарт-часами через Zepp OS push API.

Amazfit Balance 2 работает на Zepp OS. Вместо pull-модели (OAuth2 + polling)
используется push-модель: мини-приложение на часах периодически отправляет
данные на наш сервер через HTTP POST.

Метрики:
- Шаги, дистанция, калории
- Пульс (средний, min, max)
- SpO2 (кислород в крови)
- Сон (фазы, продолжительность)
- Стресс
- Температура кожи

Поток:
1. Пользователь генерирует API-ключ через /watch_connect.
2. Ключ вводится в Zepp OS мини-приложение на часах.
3. Мини-приложение каждые N минут POST-ит данные на /api/watch/push.
4. Сервер валидирует ключ, сохраняет данные в events.
5. Health-бот AI видит данные часов в контексте.
"""

import secrets
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import structlog

from src.db.queries import create_event

logger = structlog.get_logger()
MSK = ZoneInfo("Europe/Moscow")


def generate_watch_api_key() -> str:
    """Сгенерировать API-ключ для авторизации push-запросов с часов."""
    return f"wk_{secrets.token_urlsafe(32)}"


async def process_watch_push(user_id: int, payload: dict[str, Any]) -> dict:
    """Обработать push-данные от Amazfit Balance 2 и сохранить в events.

    Args:
        user_id: Telegram ID пользователя (определяется по API-ключу).
        payload: JSON от часов с метриками.

    Returns:
        dict с сохранёнными данными.
    """
    now = datetime.now(MSK)

    data: dict[str, Any] = {
        "source": "amazfit_balance_2",
        "pushed_at": now.isoformat(),
    }

    # Шаги
    if "steps" in payload:
        data["steps"] = int(payload["steps"])
    # Дистанция (метры → км)
    if "distance" in payload:
        data["distance_km"] = round(float(payload["distance"]) / 1000, 2)
    if "distance_km" in payload:
        data["distance_km"] = round(float(payload["distance_km"]), 2)
    # Калории
    if "calories" in payload:
        data["calories_burned"] = round(float(payload["calories"]))
    # Пульс
    if "heart_rate" in payload:
        hr = payload["heart_rate"]
        if isinstance(hr, dict):
            data["heart_rate"] = {
                "min": int(hr.get("min", 0)),
                "max": int(hr.get("max", 0)),
                "avg": int(hr.get("avg", 0)),
                "last": int(hr.get("last", hr.get("avg", 0))),
            }
        elif isinstance(hr, (int, float)):
            data["heart_rate"] = {"last": int(hr), "avg": int(hr)}
    # SpO2
    if "spo2" in payload:
        sp = payload["spo2"]
        if isinstance(sp, dict):
            data["spo2"] = {
                "min": int(sp.get("min", 0)),
                "max": int(sp.get("max", 0)),
                "avg": int(sp.get("avg", 0)),
                "last": int(sp.get("last", sp.get("avg", 0))),
            }
        elif isinstance(sp, (int, float)):
            data["spo2"] = {"last": int(sp), "avg": int(sp)}
    # Стресс
    if "stress" in payload:
        st = payload["stress"]
        if isinstance(st, dict):
            data["stress"] = {
                "min": int(st.get("min", 0)),
                "max": int(st.get("max", 0)),
                "avg": int(st.get("avg", 0)),
                "last": int(st.get("last", st.get("avg", 0))),
            }
        elif isinstance(st, (int, float)):
            data["stress"] = {"last": int(st), "avg": int(st)}
    # Сон
    if "sleep" in payload:
        sl = payload["sleep"]
        if isinstance(sl, dict):
            total_min = float(sl.get("total_min", 0))
            data["sleep"] = {
                "total_hours": round(total_min / 60, 1) if total_min else sl.get("total_hours", 0),
                "deep_min": round(float(sl.get("deep_min", 0))),
                "light_min": round(float(sl.get("light_min", 0))),
                "rem_min": round(float(sl.get("rem_min", 0))),
                "awake_min": round(float(sl.get("awake_min", 0))),
            }
            total = data["sleep"]["deep_min"] + data["sleep"]["rem_min"] + data["sleep"]["light_min"]
            if total > 0:
                data["sleep"]["quality_pct"] = round(
                    (data["sleep"]["deep_min"] + data["sleep"]["rem_min"]) / total * 100
                )
    # Температура кожи
    if "skin_temperature" in payload:
        data["skin_temperature"] = round(float(payload["skin_temperature"]), 1)

    # Сохраняем только если есть реальные данные
    has_data = any(k not in ("source", "pushed_at") for k in data)
    if has_data:
        await create_event(
            user_id=user_id,
            event_type="watch_metrics",
            bot_source="health",
            raw_text=format_summary(data),
            json_data=data,
        )
        logger.info("amazfit_data_saved", user_id=user_id, keys=list(data.keys()))

    return data


def format_summary(data: dict) -> str:
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
        parts.append(
            f"Сон: {sl.get('total_hours', '?')}ч "
            f"(глубокий {sl.get('deep_min', 0)} мин, REM {sl.get('rem_min', 0)} мин)"
        )
    if "skin_temperature" in data:
        parts.append(f"Температура кожи: {data['skin_temperature']}°C")
    return "⌚ Данные часов: " + " | ".join(parts) if parts else "⌚ Нет данных"
