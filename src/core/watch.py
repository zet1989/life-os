"""Общий контекст данных с часов для AI-промптов.

Используется в health, psychology и других ботах.
"""

from src.db.queries import get_today_watch_metrics


async def watch_context(user_id: int) -> str:
    """Собрать контекст данных с часов для AI-промптов."""
    metrics = await get_today_watch_metrics(user_id)
    if not metrics:
        return ""

    last = metrics[0].get("json_data") or {}
    parts = []
    if "steps" in last:
        parts.append(f"Шаги: {last['steps']}")
    if "distance_km" in last:
        parts.append(f"Дистанция: {last['distance_km']} км")
    if "calories_burned" in last:
        parts.append(f"Сожжено: {last['calories_burned']} ккал")
    hr = last.get("heart_rate")
    if hr:
        hr_parts = []
        if hr.get("avg"): hr_parts.append(f"ср {hr['avg']}")
        if hr.get("min"): hr_parts.append(f"мин {hr['min']}")
        if hr.get("max"): hr_parts.append(f"макс {hr['max']}")
        if hr.get("resting"): hr_parts.append(f"покой {hr['resting']}")
        parts.append(f"Пульс: {', '.join(hr_parts)}" if hr_parts else f"Пульс: {hr.get('last', '?')}")
    sp = last.get("spo2")
    if sp:
        val = sp.get("avg", sp) if isinstance(sp, dict) else sp
        parts.append(f"SpO2: {val}%")
    st = last.get("stress")
    if st:
        if isinstance(st, dict):
            parts.append(f"Стресс: {st.get('avg', st.get('last', '?'))}/100")
        else:
            parts.append(f"Стресс: {st}/100")
    sl = last.get("sleep")
    if sl:
        sleep_parts = [f"{sl.get('total_hours', '?')}ч"]
        if sl.get("score"): sleep_parts.append(f"оценка {sl['score']}")
        if sl.get("deep_min"): sleep_parts.append(f"глубокий {sl['deep_min']} мин")
        if sl.get("rem_min"): sleep_parts.append(f"REM {sl['rem_min']} мин")
        if sl.get("light_min"): sleep_parts.append(f"лёгкий {sl['light_min']} мин")
        if sl.get("awake_min"): sleep_parts.append(f"пробуждения {sl['awake_min']} мин")
        if sl.get("nap_min"): sleep_parts.append(f"дневной сон {sl['nap_min']} мин")
        if sl.get("start_time"): sleep_parts.append(f"уснул {sl['start_time']}")
        if sl.get("end_time"): sleep_parts.append(f"проснулся {sl['end_time']}")
        parts.append(f"Сон: {', '.join(sleep_parts)}")
    if "skin_temperature" in last:
        parts.append(f"Температура кожи: {last['skin_temperature']}°C")
    if "body_temperature" in last:
        parts.append(f"Температура тела: {last['body_temperature']}°C")
    if "fat_burning_min" in last:
        parts.append(f"Жиросжигание: {last['fat_burning_min']} мин")
    pai = last.get("pai")
    if pai:
        parts.append(f"PAI: {pai.get('total', 0)} (сегодня +{pai.get('today', 0)})")
    if "standing_hours" in last:
        parts.append(f"Стоя: {last['standing_hours']} ч")
    wo = last.get("workout")
    if wo:
        w_parts = []
        if wo.get("vo2_max"): w_parts.append(f"VO₂max {wo['vo2_max']}")
        if wo.get("training_load"): w_parts.append(f"нагрузка {wo['training_load']}")
        if wo.get("recovery_hours"): w_parts.append(f"восстановление {wo['recovery_hours']}ч")
        if w_parts: parts.append(f"Тренировка: {', '.join(w_parts)}")

    if not parts:
        return ""
    return "⌚ ДАННЫЕ ЧАСОВ СЕГОДНЯ:\n" + "\n".join(f"  {p}" for p in parts)
