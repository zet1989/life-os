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

    async def update_goals_dashboard(self, goals: list[dict]) -> None:
        """Полная перегенерация 03-Dashboards/Goals.md из списка целей (9.2.6)."""
        if not self.enabled:
            return
        path = self.vault / "03-Dashboards" / "Goals.md"
        self._ensure_dir(path)

        now = datetime.now(MSK).strftime("%Y-%m-%d %H:%M")
        type_emoji = {"dream": "🌟", "yearly_goal": "🎯", "habit_target": "✅"}
        type_label = {"dream": "Мечта", "yearly_goal": "Годовая цель", "habit_target": "Привычка"}

        lines: list[str] = [
            "---",
            f"updated: {now}",
            "---",
            "",
            "# 🎯 Цели и Мечты",
            "",
        ]

        if not goals:
            lines.append("_Нет активных целей._")
        else:
            # Таблица для Dataview
            lines.append("| Статус | Тип | Цель | Прогресс | Дедлайн |")
            lines.append("|--------|-----|------|----------|---------|")
            for g in goals:
                gtype = g.get("type", "yearly_goal")
                emoji = type_emoji.get(gtype, "📌")
                label = type_label.get(gtype, gtype)
                pct = g.get("progress_pct", 0)
                title = g.get("title", "")
                status = g.get("status", "active")
                target = g.get("target_date")
                target_str = str(target) if target else "—"
                bar_filled = round(pct / 10)
                bar = "▓" * bar_filled + "░" * (10 - bar_filled)
                status_icon = "✅" if status == "achieved" else "⏳"
                lines.append(
                    f"| {status_icon} | {emoji} {label} | {title} | {bar} {pct}% | {target_str} |"
                )

            lines.append("")

            # Детальные карточки
            for g in goals:
                gtype = g.get("type", "yearly_goal")
                emoji = type_emoji.get(gtype, "📌")
                title = g.get("title", "")
                desc = g.get("description", "")
                pct = g.get("progress_pct", 0)
                gid = g.get("id", "")

                lines.append(f"## {emoji} {title}")
                lines.append("")
                lines.append(f"- **ID:** {gid}")
                lines.append(f"- **Тип:** {type_label.get(gtype, gtype)}")
                lines.append(f"- **Прогресс:** {pct}%")
                if desc:
                    lines.append(f"- **Описание:** {desc}")
                target = g.get("target_date")
                if target:
                    lines.append(f"- **Дедлайн:** {target}")
                achieved = g.get("achieved_at")
                if achieved:
                    lines.append(f"- **Достигнуто:** {achieved}")
                lines.append("")

        path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("obsidian.goals_dashboard", count=len(goals))

    async def update_project_readme(
        self,
        project: dict,
        finance_rows: list[dict],
        recent_events: list[dict] | None = None,
    ) -> None:
        """Обновить 05-Projects/{name}/README.md с метаданными и финсводкой (9.2.7)."""
        if not self.enabled:
            return
        name = project.get("name", "Unknown")
        safe_name = re.sub(r"[^\w\s-]", "", name).strip().replace(" ", "-")
        path = self.vault / "05-Projects" / safe_name / "README.md"
        self._ensure_dir(path)

        now = datetime.now(MSK).strftime("%Y-%m-%d %H:%M")
        ptype = project.get("type", "solo")
        status = project.get("status", "active")
        collabs = project.get("collaborators", [])
        created = project.get("created_at", "")

        # Финансовая сводка из SQL-данных
        income = sum(r["total"] for r in finance_rows if r.get("transaction_type") == "income")
        expense = sum(r["total"] for r in finance_rows if r.get("transaction_type") == "expense")
        balance = income - expense

        lines: list[str] = [
            "---",
            f"project: {name}",
            f"type: {ptype}",
            f"status: {status}",
            f"updated: {now}",
            "---",
            "",
            f"# 📁 {name}",
            "",
            "## Метаданные",
            "",
            f"- **Тип:** {ptype}",
            f"- **Статус:** {status}",
            f"- **Создан:** {created}",
        ]
        if collabs:
            lines.append(f"- **Collaborators:** {', '.join(str(c) for c in collabs)}")
        lines.append("")

        # Финансы
        lines.append("## 💰 Финансы")
        lines.append("")
        bal_emoji = "✅" if balance >= 0 else "🔴"
        lines.append(f"| Показатель | Сумма |")
        lines.append(f"|-----------|-------|")
        lines.append(f"| 💵 Доход | {income:,.0f} ₽ |")
        lines.append(f"| 💰 Расход | {expense:,.0f} ₽ |")
        lines.append(f"| {bal_emoji} Баланс | {balance:,.0f} ₽ |")
        lines.append("")

        # Расходы по категориям
        expense_cats = [r for r in finance_rows if r.get("transaction_type") == "expense"]
        if expense_cats:
            lines.append("### Расходы по категориям")
            lines.append("")
            lines.append("| Категория | Сумма |")
            lines.append("|-----------|-------|")
            for r in expense_cats:
                lines.append(f"| {r.get('category', '—')} | {r['total']:,.0f} ₽ |")
            lines.append("")

        # Последние события
        if recent_events:
            lines.append("## 📋 Последние события")
            lines.append("")
            for ev in recent_events[:10]:
                ts = ev.get("created_at", "")
                if hasattr(ts, "strftime"):
                    ts = ts.strftime("%d.%m.%Y")
                etype = ev.get("event_type", "")
                raw = (ev.get("raw_text") or "")[:80]
                lines.append(f"- **{ts}** [{etype}] {raw}")
            lines.append("")

        path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("obsidian.project_readme", project=name)

    async def log_meeting_note(
        self,
        project_name: str,
        transcript: str,
        analysis: str,
    ) -> None:
        """Создать Meeting Note в 05-Projects/{project}/Meeting-YYYY-MM-DD.md."""
        if not self.enabled:
            return
        safe_name = re.sub(r"[^\w\s-]", "", project_name).strip().replace(" ", "-")
        now = datetime.now(MSK)
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M")
        filename = f"Meeting-{date_str}.md"
        path = self.vault / "05-Projects" / safe_name / filename

        # Если файл с такой датой уже есть — добавляем номер
        counter = 2
        while path.exists():
            filename = f"Meeting-{date_str}-{counter}.md"
            path = self.vault / "05-Projects" / safe_name / filename
            counter += 1

        self._ensure_dir(path)

        lines = [
            "---",
            f"type: meeting",
            f"project: {project_name}",
            f"date: {date_str}",
            f"time: {time_str}",
            "---",
            "",
            f"# 🎙 Meeting — {date_str}",
            "",
            f"**Проект:** {project_name}",
            f"**Дата:** {date_str} {time_str}",
            "",
            "---",
            "",
            "## 📝 Анализ",
            "",
            analysis,
            "",
            "---",
            "",
            "## 🎤 Транскрипция",
            "",
            transcript[:5000],
            "",
        ]

        path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("obsidian.meeting_note", project=project_name, path=str(path))

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

    # ---------------------------------------------------------------
    # Weekly Notes (сводка недели)
    # ---------------------------------------------------------------

    def _weekly_path(self, date: datetime | None = None) -> Path:
        d = date or datetime.now(MSK)
        year, week, _ = d.isocalendar()
        return self.vault / "04-Daily" / f"Week-{year}-W{week:02d}.md"

    async def generate_weekly_note(self, summary: dict, events_by_type: dict, goals: list[dict]) -> None:
        """Создать/обновить Weekly Note в 04-Daily/Week-YYYY-WNN.md."""
        if not self.enabled:
            return

        now = datetime.now(MSK)
        path = self._weekly_path(now)
        self._ensure_dir(path)

        year, week, _ = now.isocalendar()
        type_emoji = {"dream": "🌟", "yearly_goal": "🎯", "habit_target": "✅"}

        lines: list[str] = [
            "---",
            f"type: weekly",
            f"week: {year}-W{week:02d}",
            f"generated: {now.strftime('%Y-%m-%d %H:%M')}",
            "---",
            "",
            f"# 📋 Неделя {week}, {year}",
            "",
            "## ✅ Задачи",
            "",
            f"- Выполнено: **{summary.get('completed', 0)}**",
            f"- Создано: **{summary.get('created', 0)}**",
            "",
            "## 💰 Финансы",
            "",
            f"- 💵 Доход: **{summary.get('week_income', 0):,.0f} ₽**",
            f"- 💸 Расход: **{summary.get('week_expense', 0):,.0f} ₽**",
        ]
        balance = summary.get("week_income", 0) - summary.get("week_expense", 0)
        b_emoji = "✅" if balance >= 0 else "🔴"
        lines.append(f"- {b_emoji} Баланс: **{balance:,.0f} ₽**")
        lines.append("")

        # Активность по типам событий
        if events_by_type:
            lines.append("## 📊 Активность")
            lines.append("")
            type_labels = {
                "meal": "🍽 Приёмы пищи",
                "workout": "🏋️ Тренировки",
                "diary": "📝 Дневник",
                "habit": "✅ Привычки",
                "finance": "💰 Финансы",
                "gratitude": "🙏 Благодарности",
                "focus": "🎯 Фокус дня",
                "weight": "⚖️ Вес",
                "water": "💧 Вода",
                "doctor": "👨‍⚕️ Доктор",
                "mood": "😊 Настроение",
            }
            for etype, cnt in sorted(events_by_type.items(), key=lambda x: -x[1]):
                label = type_labels.get(etype, etype)
                lines.append(f"- {label}: **{cnt}**")
            lines.append("")

        # Цели
        if goals:
            lines.append("## 🎯 Цели")
            lines.append("")
            for g in goals:
                gtype = g.get("type", "yearly_goal")
                emoji = type_emoji.get(gtype, "📌")
                pct = g.get("progress_pct", 0)
                bar_filled = round(pct / 10)
                bar = "▓" * bar_filled + "░" * (10 - bar_filled)
                lines.append(f"- {emoji} {g.get('title', '')} {bar} {pct}%")
            lines.append("")

        path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("obsidian.weekly_note", file=str(path), week=f"{year}-W{week:02d}")

    # ---------------------------------------------------------------
    # Kanban Board (плагин Obsidian Kanban)
    # ---------------------------------------------------------------

    async def generate_kanban_board(self, kanban_data: dict[str, list[dict]]) -> None:
        """Перегенерировать 03-Dashboards/Kanban.md в формате плагина Obsidian Kanban."""
        if not self.enabled:
            return

        path = self.vault / "03-Dashboards" / "Kanban.md"
        self._ensure_dir(path)

        now = datetime.now(MSK).strftime("%Y-%m-%d %H:%M")

        COLUMNS = [
            ("backlog", "📥 Backlog"),
            ("todo", "📋 Todo"),
            ("in_progress", "🔄 In Progress"),
            ("done", "✅ Done"),
        ]

        lines: list[str] = [
            "---",
            "",
            "kanban-plugin: basic",
            "",
            "---",
            "",
        ]

        for col_key, col_title in COLUMNS:
            lines.append(f"## {col_title}")
            lines.append("")

            tasks = kanban_data.get(col_key, [])
            for t in tasks:
                is_done = t.get("is_done", False)
                checkbox = "[x]" if is_done else "[ ]"
                text = t.get("task_text", "")
                task_id = t.get("id", "")

                # Метаданные в строку задачи
                parts = [f"- {checkbox} {text}"]

                # Приоритет
                prio = t.get("priority", "normal")
                prio_emoji = {"urgent": "🔴", "high": "🟠", "normal": "", "low": "🔵"}.get(prio, "")
                if prio_emoji:
                    parts[0] = f"- {checkbox} {prio_emoji} {text}"

                # Дедлайн
                due = t.get("due_date")
                if due:
                    due_str = due.strftime("%Y-%m-%d") if hasattr(due, "strftime") else str(due)
                    parts[0] += f" 📅 {due_str}"

                # Время
                due_time = t.get("due_time")
                if due_time:
                    time_str = due_time.strftime("%H:%M") if hasattr(due_time, "strftime") else str(due_time)
                    parts[0] += f" ⏰ {time_str}"

                # Цель
                goal_title = t.get("goal_title")
                if goal_title:
                    parts[0] += f" [🎯 {goal_title}]"

                # Тэги
                tags = t.get("tags") or []
                if tags:
                    parts[0] += " " + " ".join(f"#{tg}" for tg in tags)

                # ID задачи в комментарии (для обратной синхронизации)
                parts[0] += f" ^task-{task_id}"

                lines.append(parts[0])

            lines.append("")
            lines.append("")

        path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("obsidian.kanban_generated", tasks=sum(len(v) for v in kanban_data.values()))


# Синглтон
obsidian = ObsidianWriter()
