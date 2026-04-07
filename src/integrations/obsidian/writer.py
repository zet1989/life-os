"""Obsidian writer — генерация/обновление .md файлов из данных ботов.

Все записи идемпотентны: если контент уже есть, не дублируется.
При obsidian_sync_enabled=False все вызовы — no-op.
"""

import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import structlog

from src.config import settings

logger = structlog.get_logger()
MSK = ZoneInfo("Europe/Moscow")


class ObsidianWriter:
    """Записывает данные из Telegram-ботов в .md файлы Obsidian Vault."""

    def __init__(self) -> None:
        self.vault = Path(settings.obsidian_vault_path)
        self.enabled = settings.obsidian_sync_enabled

    def _ensure_dir(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------
    # Inbox Notes
    # ---------------------------------------------------------------

    async def write_inbox_note(
        self,
        title: str,
        content: str,
        tags: list[str] | None = None,
        note_type: str = "note",
    ) -> None:
        """Создать заметку в 00-Inbox/."""
        if not self.enabled:
            return
        ts = datetime.now(MSK).strftime("%Y%m%d-%H%M%S")
        slug = re.sub(r"[^\w\s-]", "", title)[:60].strip().replace(" ", "-")
        filename = f"{note_type}-{ts}-{slug}.md"
        path = self.vault / "00-Inbox" / filename

        tag_str = " ".join(f"#{t}" for t in (tags or []))
        frontmatter = (
            f"---\n"
            f"type: {note_type}\n"
            f"created: {datetime.now(MSK).isoformat()}\n"
            f"tags: [{', '.join(tags or [])}]\n"
            f"---\n\n"
        )
        body = f"# {title}\n\n{content}\n\n{tag_str}\n"

        self._ensure_dir(path)
        path.write_text(frontmatter + body, encoding="utf-8")
        logger.info("obsidian.inbox", file=str(path))

    # ---------------------------------------------------------------
    # Daily Note
    # ---------------------------------------------------------------

    def _daily_path(self, date: datetime | None = None) -> Path:
        d = date or datetime.now(MSK)
        return self.vault / "04-Daily" / f"{d.strftime('%Y-%m-%d')}.md"

    def _ensure_daily(self, path: Path) -> None:
        """Создать Daily Note из шаблона, если не существует."""
        if path.exists():
            return
        self._ensure_dir(path)
        date_str = path.stem  # 2026-04-07
        template = self.vault / "07-Templates" / "Daily.md"
        if template.exists():
            content = template.read_text(encoding="utf-8")
            content = content.replace("{{date:YYYY-MM-DD}}", date_str)
            # weekday name
            from datetime import date as dt_date
            d = dt_date.fromisoformat(date_str)
            days_ru = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
            content = content.replace("{{date:dddd}}", days_ru[d.weekday()])
        else:
            content = f"# {date_str}\n\n## 📋 Задачи\n\n## 📝 Заметки\n\n"
            content += "## 🍽 Питание\n<!-- sync:health -->\n\n"
            content += "## 🏋️ Тренировки\n<!-- sync:workout -->\n\n"
            content += "## 💰 Финансы\n<!-- sync:finances -->\n\n"
            content += "## 🧠 Рефлексия\n\n"
        path.write_text(content, encoding="utf-8")
        logger.info("obsidian.daily_created", file=str(path))

    async def append_to_daily(
        self,
        section: str,
        content: str,
        date: datetime | None = None,
    ) -> None:
        """Вставить контент в секцию Daily Note (после <!-- sync:section -->)."""
        if not self.enabled:
            return
        path = self._daily_path(date)
        self._ensure_daily(path)

        marker = f"<!-- sync:{section} -->"
        text = path.read_text(encoding="utf-8")

        if content.strip() in text:
            return  # уже есть — идемпотентность

        if marker in text:
            text = text.replace(marker, f"{marker}\n{content.strip()}")
        else:
            text += f"\n## {section}\n{marker}\n{content.strip()}\n"

        path.write_text(text, encoding="utf-8")
        logger.info("obsidian.daily_append", section=section, file=str(path))

    # ---------------------------------------------------------------
    # Специализированные экспорты
    # ---------------------------------------------------------------

    async def log_meal(self, json_data: dict, raw_text: str = "") -> None:
        """Записать приём пищи в Daily Note."""
        if not self.enabled:
            return
        desc = json_data.get("description", raw_text[:60] or "Приём пищи")
        cal = json_data.get("calories", "?")
        prot = json_data.get("protein", "?")
        fat = json_data.get("fat", "?")
        carbs = json_data.get("carbs", "?")
        now = datetime.now(MSK).strftime("%H:%M")
        line = f"- {now} | **{desc}** — {cal} ккал (Б:{prot} Ж:{fat} У:{carbs})"
        await self.append_to_daily("health", line)

    async def log_workout(self, json_data: dict, raw_text: str = "") -> None:
        """Записать тренировку в Daily Note."""
        if not self.enabled:
            return
        wtype = json_data.get("type", "Тренировка")
        dur = json_data.get("duration_min", "?")
        exercises = json_data.get("exercises", [])
        now = datetime.now(MSK).strftime("%H:%M")
        line = f"- {now} | **{wtype}** ({dur} мин)"
        if exercises:
            for ex in exercises[:5]:
                name = ex.get("name", "")
                sets = ex.get("sets", "")
                reps = ex.get("reps", "")
                weight = ex.get("weight", "")
                detail = f"  - {name}"
                if sets and reps:
                    detail += f" {sets}×{reps}"
                if weight:
                    detail += f" @ {weight} кг"
                line += f"\n{detail}"
        await self.append_to_daily("workout", line)

    async def log_finance(self, json_data: dict) -> None:
        """Записать финансовую операцию в Daily Note."""
        if not self.enabled:
            return
        ftype = json_data.get("type", "expense")
        amount = json_data.get("amount", 0)
        cat = json_data.get("category", "")
        desc = json_data.get("description", "")
        emoji = "🔴" if ftype == "expense" else "🟢"
        now = datetime.now(MSK).strftime("%H:%M")
        line = f"- {now} | {emoji} {amount:,.0f} ₽ — {cat}: {desc}"
        await self.append_to_daily("finances", line)

    async def log_diary(self, text: str) -> None:
        """Записать дневниковую запись в Inbox."""
        if not self.enabled:
            return
        date_str = datetime.now(MSK).strftime("%Y-%m-%d")
        await self.write_inbox_note(
            title=f"Дневник {date_str}",
            content=text,
            tags=["diary", "psychology"],
            note_type="diary",
        )

    async def log_idea(self, text: str, project: str = "", source: str = "business") -> None:
        """Записать бизнес-идею в Inbox."""
        if not self.enabled:
            return
        tags = ["idea", source]
        if project:
            tags.append(project.lower().replace(" ", "-"))
        await self.write_inbox_note(
            title=f"Идея: {text[:80]}",
            content=text,
            tags=tags,
            note_type="idea",
        )

    async def log_goal_update(self, goal_title: str, progress: int, note: str = "") -> None:
        """Обновить прогресс цели в дашборде."""
        if not self.enabled:
            return
        path = self.vault / "03-Dashboards" / "Dashboard — Цели.md"
        if not path.exists():
            return
        content = path.read_text(encoding="utf-8")
        now = datetime.now(MSK).strftime("%d.%m.%Y")
        update_line = f"\n- {now}: {goal_title} — {progress}%"
        if note:
            update_line += f" ({note})"
        content += update_line
        path.write_text(content, encoding="utf-8")
        logger.info("obsidian.goal_update", goal=goal_title, progress=progress)

    async def log_task_to_daily(self, task_text: str, due_time: str = "", priority: str = "") -> None:
        """Добавить задачу в Daily Note (формат Tasks-плагина)."""
        if not self.enabled:
            return
        date_str = datetime.now(MSK).strftime("%Y-%m-%d")
        line = f"- [ ] {task_text}"
        if due_time:
            line += f" ⏰ {due_time}"
        line += f" 📅 {date_str}"
        if priority:
            prio_map = {"urgent": "🔴", "high": "🟡", "normal": "🟢", "low": "⚪"}
            line = f"- [ ] {prio_map.get(priority, '')} {task_text}"
            if due_time:
                line += f" ⏰ {due_time}"
            line += f" 📅 {date_str}"

        path = self._daily_path()
        self._ensure_daily(path)
        text = path.read_text(encoding="utf-8")
        # Вставляем после ## 📋 Задачи или ## Задачи
        task_header = re.search(r"(## .*[Зз]адачи.*)\n", text)
        if task_header and line.strip() not in text:
            pos = task_header.end()
            text = text[:pos] + line + "\n" + text[pos:]
            path.write_text(text, encoding="utf-8")
            logger.info("obsidian.task_added", task=task_text)

    # ---------------------------------------------------------------
    # Двусторонняя синхронизация задач (9.4)
    # ---------------------------------------------------------------

    async def complete_task_in_md(self, task_text: str, due_date: str | None = None) -> None:
        """Пометить задачу выполненной в .md файле: - [ ] → - [x] ✅ дата."""
        if not self.enabled:
            return
        done_date = datetime.now(MSK).strftime("%Y-%m-%d")
        # Ищем в Daily Note соответствующей даты или сегодняшнем
        paths_to_check = []
        if due_date:
            try:
                from datetime import date as dt_date
                d = dt_date.fromisoformat(due_date)
                paths_to_check.append(self.vault / "04-Daily" / f"{d.isoformat()}.md")
            except ValueError:
                pass
        paths_to_check.append(self._daily_path())
        # Также проверяем все .md в 04-Daily за последнюю неделю
        daily_dir = self.vault / "04-Daily"
        if daily_dir.exists():
            for md_file in sorted(daily_dir.glob("*.md"), reverse=True)[:7]:
                if md_file not in paths_to_check:
                    paths_to_check.append(md_file)

        for path in paths_to_check:
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            # Ищем незакрытую задачу с этим текстом
            pattern = re.compile(
                r"^(- \[ \]\s+.*?" + re.escape(task_text) + r".*?)$",
                re.MULTILINE,
            )
            m = pattern.search(text)
            if m:
                old_line = m.group(1)
                new_line = old_line.replace("- [ ]", f"- [x]", 1) + f" ✅ {done_date}"
                text = text.replace(old_line, new_line, 1)
                path.write_text(text, encoding="utf-8")
                logger.info("obsidian.task_completed", task=task_text, file=str(path))
                return

    async def uncomplete_task_in_md(self, task_text: str, due_date: str | None = None) -> None:
        """Снять отметку выполненной: - [x] → - [ ], убрать ✅ дату."""
        if not self.enabled:
            return
        paths_to_check = []
        if due_date:
            try:
                from datetime import date as dt_date
                d = dt_date.fromisoformat(due_date)
                paths_to_check.append(self.vault / "04-Daily" / f"{d.isoformat()}.md")
            except ValueError:
                pass
        paths_to_check.append(self._daily_path())
        daily_dir = self.vault / "04-Daily"
        if daily_dir.exists():
            for md_file in sorted(daily_dir.glob("*.md"), reverse=True)[:7]:
                if md_file not in paths_to_check:
                    paths_to_check.append(md_file)

        for path in paths_to_check:
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            pattern = re.compile(
                r"^(- \[x\]\s+.*?" + re.escape(task_text) + r".*?)$",
                re.MULTILINE | re.IGNORECASE,
            )
            m = pattern.search(text)
            if m:
                old_line = m.group(1)
                # Убираем [x] → [ ] и ✅ дату
                new_line = re.sub(r"- \[[xX]\]", "- [ ]", old_line, count=1)
                new_line = re.sub(r"\s*✅\s*\d{4}-\d{2}-\d{2}", "", new_line)
                text = text.replace(old_line, new_line, 1)
                path.write_text(text, encoding="utf-8")
                logger.info("obsidian.task_uncompleted", task=task_text, file=str(path))
                return


# Синглтон
obsidian = ObsidianWriter()
