"""Watcher — мониторинг .md файлов в Obsidian Vault.

Использует watchdog для отслеживания изменений в папке Vault.
При изменении файла — парсит задачи → upsert в БД.
"""

import asyncio
from pathlib import Path

import structlog
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent

from src.config import settings
from src.integrations.obsidian.task_parser import parse_tasks

logger = structlog.get_logger()


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
    """Прочитать файл, распарсить задачи, обновить БД."""
    from src.db.queries import upsert_obsidian_task

    path = Path(filepath)
    vault = Path(settings.obsidian_vault_path)
    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("obsidian.read_error", file=filepath, error=str(e))
        return

    relative = str(path.relative_to(vault))
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
