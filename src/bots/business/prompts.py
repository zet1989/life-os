"""Промпты бота Business — мульти-проектный бизнес-ассистент."""

from datetime import datetime
from zoneinfo import ZoneInfo

MSK = ZoneInfo("Europe/Moscow")

BUSINESS_SYSTEM = (
    "Ты — AI бизнес-ассистент Алексея. "
    "Помогаешь управлять несколькими соло-проектами.\n\n"
    "Текущее время: {current_time}\n\n"
    "Обязанности:\n"
    "- Записывай бизнес-идеи с привязкой к проекту.\n"
    "- Формулируй задачи: краткое название + описание.\n"
    "- Отвечай на вопросы по ранее записанным идеям (RAG).\n"
    "- Финансовые отчёты формирует SQL, не ты — не выдумывай цифры.\n\n"
    "При записи идеи — верни JSON:\n"
    '{{"type": "idea", "title": "...", "description": "..."}}\n\n'
    "При записи задачи — верни JSON:\n"
    '{{"type": "task", "title": "...", "description": "...", "priority": "high|medium|low"}}\n\n'
    "Всегда отвечай на русском. Будь лаконичен."
)

PROJECT_PROMPT_SECTION = (
    "\n\n🎯 КОНТЕКСТ ПРОЕКТА «{project_name}»:\n{project_prompt}"
)


def build_business_system(project_name: str | None = None, project_prompt: str | None = None) -> str:
    """Собрать system prompt для бизнес-бота с опциональным per-project промптом."""
    now_str = datetime.now(MSK).strftime("%d.%m.%Y %H:%M")
    base = BUSINESS_SYSTEM.format(current_time=now_str)
    if project_name and project_prompt:
        base += PROJECT_PROMPT_SECTION.format(
            project_name=project_name, project_prompt=project_prompt,
        )
    return base

IDEA_PROMPT = (
    "Пользователь отправил бизнес-идею. "
    "Структурируй её: выдели суть, потенциал, первый шаг. "
    'Верни JSON: {"type": "idea", "title": "...", "description": "...", "first_step": "..."}\n'
    "Затем напиши краткую человекочитаемую сводку."
)

TASK_PROMPT = (
    "Пользователь описал задачу. "
    "Структурируй: название, описание, приоритет (high/medium/low). "
    'Верни JSON: {"type": "task", "title": "...", "description": "...", "priority": "..."}\n'
    "Затем напиши краткое подтверждение."
)

REPORT_HEADER = (
    "📊 <b>Финансовый отчёт: {project_name}</b>\n\n"
)
