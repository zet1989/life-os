"""Watcher — мониторинг .md файлов в Obsidian Vault.

Использует watchdog для отслеживания изменений в папке Vault.
При изменении файла — парсит задачи → upsert в БД.
Файлы из Knowledge/Sources/Inbox → embedding → RAG-поиск.
"""

import asyncio
from pathlib import Path

import structlog
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent

from src.config import settings
from src.integrations.obsidian.task_parser import parse_tasks

logger = structlog.get_logger()

# Папки, файлы из которых индексируются для RAG
_RAG_FOLDERS = {"00-Inbox", "01-Sources", "02-Knowledge", "03-Dashboards", "05-Projects"}


class _VaultHandler(FileSystemEventHandler):
    """Обработчик событий файловой системы в Vault."""

    def __init__(self, loop: asyncio.AbstractEventLoop, user_id: int) -> None:
        self.loop = loop
        self.user_id = user_id

    def on_modified(self, event: FileModifiedEvent) -> None:  # type: ignore[override]
        if event.is_directory or not str(event.src_path).endswith(".md"):
            return
        self.loop.call_soon_threadsafe(
            asyncio.ensure_future,
            _process_file(event.src_path, self.user_id),
        )

    def on_created(self, event: FileCreatedEvent) -> None:  # type: ignore[override]
        if event.is_directory or not str(event.src_path).endswith(".md"):
            return
        self.loop.call_soon_threadsafe(
            asyncio.ensure_future,
            _process_file(event.src_path, self.user_id),
        )


async def _process_file(filepath: str, user_id: int) -> None:
    """Прочитать файл, распарсить задачи, обновить БД. Для Knowledge-папок — индекс для RAG."""
    from src.db.queries import upsert_obsidian_task

    path = Path(filepath)
    vault = Path(settings.obsidian_vault_path)
    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("obsidian.read_error", file=filepath, error=str(e))
        return

    relative = str(path.relative_to(vault))

    # Kanban board — отдельная обработка
    if relative.replace("\\", "/") == "03-Dashboards/Kanban.md":
        await _process_kanban_changes(content, user_id)
        return

    tasks = parse_tasks(content, source_file=relative)

    for task in tasks:
        await upsert_obsidian_task(
            user_id=user_id,
            task_text=task.text,
            source_file=task.source_file,
            due_date=task.due_date,
            due_time=task.due_time,
            is_done=task.is_done,
        )

    if tasks:
        logger.info("obsidian.tasks_synced", file=relative, count=len(tasks))

    # RAG-индексация для файлов из Knowledge-папок
    top_folder = relative.split("/")[0] if "/" in relative else relative.split("\\")[0] if "\\" in relative else ""
    if top_folder in _RAG_FOLDERS and len(content.strip()) > 50:
        await _index_note_for_rag(user_id, relative, content)


# Маппинг заголовков Kanban → статусы в БД
_KANBAN_HEADER_MAP = {
    "backlog": "backlog",
    "todo": "todo",
    "in progress": "in_progress",
    "in_progress": "in_progress",
    "done": "done",
}


async def _process_kanban_changes(content: str, user_id: int) -> None:
    """Парсить Kanban.md и синхронизировать kanban_status и is_done в БД."""
    import re
    from src.db.queries import update_kanban_status, complete_task, uncomplete_task

    # Парсим колонки: ## Заголовок → задачи
    current_status: str | None = None
    task_re = re.compile(r"^-\s+\[([ xX])\].*?\^task-(\d+)\s*$")
    header_re = re.compile(r"^##\s+(.+)$")

    for line in content.split("\n"):
        line = line.strip()

        hm = header_re.match(line)
        if hm:
            header_text = hm.group(1).strip().lower()
            # Убираем эмодзи в начале
            header_clean = re.sub(r"^[^\w]+", "", header_text).strip()
            current_status = _KANBAN_HEADER_MAP.get(header_clean)
            continue

        if current_status is None:
            continue

        tm = task_re.match(line)
        if not tm:
            continue

        checkbox = tm.group(1)
        task_id = int(tm.group(2))
        is_done_in_md = checkbox.lower() == "x"

        # Обновляем kanban_status
        await update_kanban_status(task_id, user_id, current_status)

        # Синхронизируем is_done
        if current_status == "done" and not is_done_in_md:
            # Перемещено в done → отмечаем выполненной
            await complete_task(task_id, user_id)
        elif is_done_in_md and current_status != "done":
            # Чекбокс отмечен, но не в done → снимаем
            await uncomplete_task(task_id, user_id)

    logger.info("obsidian.kanban_synced", user_id=user_id)


async def _index_note_for_rag(user_id: int, relative_path: str, content: str) -> None:
    """Создать/обновить event с embedding для Obsidian-заметки (RAG)."""
    from src.db.queries import create_event, get_obsidian_note_event, update_event_raw_text
    from src.ai.rag import store_event_embedding
    import re

    # Убираем frontmatter и sync-маркеры для чистого текста
    text = re.sub(r"^---\n.*?\n---\n", "", content, flags=re.DOTALL)
    text = re.sub(r"<!--.*?-->", "", text)
    text = text.strip()

    if len(text) < 30:
        return

    # Ограничиваем длину для embedding (max ~8000 токенов ≈ 6000 символов)
    embed_text = f"[Obsidian: {relative_path}]\n{text[:6000]}"

    try:
        # Проверяем, есть ли уже event для этого файла
        existing = await get_obsidian_note_event(user_id, relative_path)

        if existing:
            # Обновляем текст и пересчитываем embedding
            if existing.get("raw_text") != text[:4000]:
                await update_event_raw_text(existing["id"], text[:4000])
                await store_event_embedding(existing["id"], embed_text, user_id=user_id, bot_source="obsidian")
                logger.info("obsidian.note_reindexed", file=relative_path)
        else:
            # Создаём новый event
            event = await create_event(
                user_id=user_id,
                event_type="obsidian_note",
                bot_source="obsidian",
                raw_text=text[:4000],
                json_data={"source_file": relative_path},
            )
            await store_event_embedding(event["id"], embed_text, user_id=user_id, bot_source="obsidian")
            logger.info("obsidian.note_indexed", file=relative_path, event_id=event["id"])

    except Exception:
        logger.exception("obsidian.index_error", file=relative_path)


_observer: Observer | None = None


async def start_watcher(user_id: int) -> None:
    """Запустить мониторинг Vault, если включён."""
    global _observer

    if not settings.obsidian_watch_enabled:
        logger.info("obsidian.watcher_disabled")
        return

    vault_path = Path(settings.obsidian_vault_path)
    if not vault_path.exists():
        logger.warning("obsidian.vault_not_found", path=str(vault_path))
        return

    loop = asyncio.get_running_loop()
    handler = _VaultHandler(loop, user_id)

    _observer = Observer()
    _observer.schedule(handler, str(vault_path), recursive=True)
    _observer.daemon = True
    _observer.start()
    logger.info("obsidian.watcher_started", path=str(vault_path))


async def stop_watcher() -> None:
    """Остановить мониторинг."""
    global _observer
    if _observer:
        _observer.stop()
        _observer.join(timeout=5)
        _observer = None
        logger.info("obsidian.watcher_stopped")
