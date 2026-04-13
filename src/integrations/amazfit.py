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
    # Температура тела (новый датчик)
    if "body_temperature" in payload:
        data["body_temperature"] = round(float(payload["body_temperature"]), 1)
    # Жиросжигание (минуты)
    if "fat_burning_min" in payload:
        data["fat_burning_min"] = int(payload["fat_burning_min"])
    # PAI (Physical Activity Intelligence)
    if "pai" in payload:
        p = payload["pai"]
        if isinstance(p, dict):
            data["pai"] = {"total": int(p.get("total", 0)), "today": int(p.get("today", 0))}
        elif isinstance(p, (int, float)):
            data["pai"] = {"total": int(p)}
    # Часы стоя
    if "standing_hours" in payload:
        data["standing_hours"] = int(payload["standing_hours"])
    # Тренировка: VO2 Max, Training Load, Recovery Time
    if "workout" in payload:
        w = payload["workout"]
        if isinstance(w, dict):
            workout = {}
            if w.get("vo2_max"): workout["vo2_max"] = round(float(w["vo2_max"]), 1)
            if w.get("training_load"): workout["training_load"] = round(float(w["training_load"]))
            if w.get("recovery_hours"): workout["recovery_hours"] = round(float(w["recovery_hours"]))
            if workout:
                data["workout"] = workout

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
        hr_parts = []
        if hr.get("avg"): hr_parts.append(f"ср {hr['avg']}")
        if hr.get("min"): hr_parts.append(f"мин {hr['min']}")
        if hr.get("max"): hr_parts.append(f"макс {hr['max']}")
        if hr.get("resting"): hr_parts.append(f"покой {hr['resting']}")
        parts.append(f"Пульс: {', '.join(hr_parts)}" if hr_parts else f"Пульс: {hr.get('last', '?')}")
    if "spo2" in data:
        sp = data["spo2"]
        val = sp.get("avg", sp) if isinstance(sp, dict) else sp
        parts.append(f"SpO2: {val}%")
    if "stress" in data:
        st = data["stress"]
        if isinstance(st, dict):
            parts.append(f"Стресс: {st.get('avg', st.get('last', '?'))}/100")
        else:
            parts.append(f"Стресс: {st}/100")
    if "sleep" in data:
        sl = data["sleep"]
        sleep_parts = [f"{sl.get('total_hours', '?')}ч"]
        if sl.get("score"): sleep_parts.append(f"оценка {sl['score']}")
        if sl.get("deep_min"): sleep_parts.append(f"глубокий {sl['deep_min']} мин")
        if sl.get("rem_min"): sleep_parts.append(f"REM {sl['rem_min']} мин")
        if sl.get("light_min"): sleep_parts.append(f"лёгкий {sl['light_min']} мин")
        if sl.get("nap_min"): sleep_parts.append(f"дневной сон {sl['nap_min']} мин")
        parts.append(f"Сон: {', '.join(sleep_parts)}")
    if "skin_temperature" in data:
        parts.append(f"Температура кожи: {data['skin_temperature']}°C")
    if "body_temperature" in data:
        parts.append(f"Температура тела: {data['body_temperature']}°C")
    if "fat_burning_min" in data:
        parts.append(f"Жиросжигание: {data['fat_burning_min']} мин")
    if "pai" in data:
        p = data["pai"]
        parts.append(f"PAI: {p.get('total', 0)} (сегодня +{p.get('today', 0)})")
    if "standing_hours" in data:
        parts.append(f"Стоя: {data['standing_hours']} ч")
    if "workout" in data:
        w = data["workout"]
        w_parts = []
        if w.get("vo2_max"): w_parts.append(f"VO₂max {w['vo2_max']}")
        if w.get("training_load"): w_parts.append(f"нагрузка {w['training_load']}")
        if w.get("recovery_hours"): w_parts.append(f"восстановление {w['recovery_hours']}ч")
        if w_parts: parts.append(f"Тренировка: {', '.join(w_parts)}")
    return "⌚ Данные часов: " + " | ".join(parts) if parts else "⌚ Нет данных"
