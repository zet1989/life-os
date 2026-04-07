"""Парсер задач из Obsidian .md файлов (формат Tasks-плагина).

Поддерживаемые форматы:
  - [ ] Текст задачи 📅 2026-04-10 ⏰ 14:30
  - [ ] Текст задачи 📅 2026-04-10
  - [x] Выполненная задача ✅ 2026-04-09
  - [ ] 🔴 Срочная задача 📅 2026-04-10
"""

import re
from dataclasses import dataclass, field


@dataclass
class ObsidianTask:
    text: str
    is_done: bool
    due_date: str | None = None   # YYYY-MM-DD
    due_time: str | None = None   # HH:MM
    priority: str = "normal"      # urgent/high/normal/low
    source_file: str = ""
    line_number: int = 0

# Regex для парсинга строки задачи
_TASK_RE = re.compile(
    r"^-\s+\[([ xX])\]\s+(.+)$",
    re.MULTILINE,
)

_DATE_RE = re.compile(r"📅\s*(\d{4}-\d{2}-\d{2})")
_TIME_RE = re.compile(r"⏰\s*(\d{1,2}:\d{2})")
_DONE_DATE_RE = re.compile(r"✅\s*(\d{4}-\d{2}-\d{2})")

_PRIORITY_MAP = {
    "🔴": "urgent",
    "🟡": "high",
    "🟢": "normal",
    "⚪": "low",
    "⏫": "urgent",
    "🔼": "high",
    "🔽": "low",
}


def parse_tasks(content: str, source_file: str = "") -> list[ObsidianTask]:
    """Извлечь все задачи из текста .md файла."""
    tasks = []
    lines = content.split("\n")

    for i, line in enumerate(lines):
        m = _TASK_RE.match(line.strip())
        if not m:
            continue

        checkbox = m.group(1)
        body = m.group(2).strip()
        is_done = checkbox.lower() == "x"

        # Извлекаем дату
        due_date = None
        dm = _DATE_RE.search(body)
        if dm:
            due_date = dm.group(1)
            body = _DATE_RE.sub("", body).strip()

        # Время
        due_time = None
        tm = _TIME_RE.search(body)
        if tm:
            due_time = tm.group(1)
            body = _TIME_RE.sub("", body).strip()

        # Дата выполнения
        body = _DONE_DATE_RE.sub("", body).strip()

        # Приоритет
        priority = "normal"
        for emoji, prio in _PRIORITY_MAP.items():
            if emoji in body:
                priority = prio
                body = body.replace(emoji, "").strip()
                break

        # Чистим текст
        text = re.sub(r"\s+", " ", body).strip()
        if not text:
            continue

        tasks.append(ObsidianTask(
            text=text,
            is_done=is_done,
            due_date=due_date,
            due_time=due_time,
            priority=priority,
            source_file=source_file,
            line_number=i + 1,
        ))

    return tasks
