# Life OS — План интеграции Obsidian + Планировщик дел

> **Дата:** 07.04.2026  
> **Статус:** Фаза 10 — завершена ✅ | Фаза 9 — ожидает (ручные шаги)  
> **Приоритет:** Новая фаза поверх стабильного ядра

---

## Концепция

Telegram-боты = быстрые агенты для сбора данных «на бегу».  
Obsidian = визуальный командный центр: структурированные знания, планирование, дашборды.

**Поток данных:**
```
Telegram → PostgreSQL → Python-скрипт → .md файлы → Obsidian (чтение)
Obsidian (задачи/заметки) → Syncthing → VPS → Python-парсер → PostgreSQL/reminders → Telegram (напоминания)
```

---

## Фаза 9: Интеграция Obsidian

### 9.0 Подготовка инфраструктуры

- [ ] **9.0.1** Создать Obsidian Vault локально (папка `~/ObsidianVault/LifeOS/`)
- [ ] **9.0.2** Определить структуру папок Zettelkasten в Vault:
  ```
  LifeOS/
  ├── 00-Inbox/              # Fleeting Notes (входящие из Telegram)
  ├── 01-Sources/            # Literature Notes (конспекты, статьи)
  ├── 02-Knowledge/          # Permanent Notes (атомарные заметки)
  ├── 03-Dashboards/         # MOC: дашборды проектов, целей
  ├── 04-Daily/              # Ежедневные заметки (Daily Notes)
  ├── 05-Projects/           # Рабочие заметки по проектам
  │   ├── KDK-GRUPP/
  │   ├── Cleaning/
  │   ├── House/
  │   └── Hyundai/
  ├── 06-People/             # Заметки по людям (партнёры, контакты)
  ├── 07-Templates/          # Шаблоны для Daily Note, проектов, встреч
  └── 08-Archive/            # Архив
  ```
- [ ] **9.0.3** Установить плагины Obsidian: **Tasks**, **Dataview**, **Templater**, **Calendar**, **Periodic Notes**
- [ ] **9.0.4** Создать шаблон Daily Note (`07-Templates/Daily.md`):
  ```markdown
  # {{date:YYYY-MM-DD}} {{date:dddd}}

  ## 📋 Задачи на сегодня
  - [ ] 

  ## 📝 Заметки
  

  ## 🍽 Питание (авто из бота)
  <!-- sync:health -->

  ## 🏋️ Тренировки (авто из бота)
  <!-- sync:workout -->

  ## 💰 Финансы (авто из бота)
  <!-- sync:finances -->

  ## 🧠 Рефлексия
  
  ```
- [ ] **9.0.5** Создать шаблон Meeting Note (`07-Templates/Meeting.md`)
- [ ] **9.0.6** Создать MOC-дашборды: `[[Dashboard — Бизнес]]`, `[[Dashboard — Здоровье]]`, `[[Dashboard — Цели]]`

### 9.1 Синхронизация: Syncthing (VPS ↔ Laptop)

- [ ] **9.1.1** Установить Syncthing на ноутбук (Windows)
- [ ] **9.1.2** Установить Syncthing на VPS (Docker-контейнер либо apt)
- [ ] **9.1.3** Настроить синхронизацию папки Vault: `~/ObsidianVault/LifeOS/` ↔ `/opt/life-os/obsidian-vault/`
- [ ] **9.1.4** Проверить двустороннюю синхронизацию (создать файл локально → появился на VPS, и наоборот)
- [ ] **9.1.5** Добавить `/opt/life-os/obsidian-vault/` в `.gitignore` (не коммитить заметки)
- [ ] **9.1.6** Добавить папку obsidian-vault как volume в `docker-compose.yml`:
  ```yaml
  bot:
    volumes:
      - /opt/life-os/obsidian-vault:/app/obsidian-vault:rw
  ```

### 9.2 Telegram → Obsidian (экспорт данных в .md)

Скрипт на Python, который генерирует/обновляет .md файлы из PostgreSQL.

- [ ] **9.2.1** Создать модуль `src/integrations/obsidian/__init__.py`
- [ ] **9.2.2** Создать `src/integrations/obsidian/config.py` — пути к папкам Vault, настройки
- [ ] **9.2.3** Создать `src/integrations/obsidian/writer.py` — базовый класс записи .md файлов:
  - `write_inbox_note(title, content, tags)` — заметка в `00-Inbox/`
  - `append_to_daily(date, section, content)` — вставка в Daily Note
  - `update_project_dashboard(project_id)` — обновление MOC проекта
- [ ] **9.2.4** Экспорт событий бота → Inbox:
  - Бизнес-идеи (business, mentor) → `00-Inbox/idea-{timestamp}.md`
  - Обсуждения (mentor) → `00-Inbox/meeting-{timestamp}.md` с саммари
  - Дневник (psychology) → `00-Inbox/diary-{date}.md`
- [ ] **9.2.5** Экспорт в Daily Note:
  - КБЖУ из health → секция `<!-- sync:health -->`
  - Тренировки → секция `<!-- sync:workout -->`  
  - Финансовые операции → секция `<!-- sync:finances -->`
- [ ] **9.2.6** Экспорт целей → `03-Dashboards/Goals.md` (Dataview-совместимый YAML frontmatter)
- [ ] **9.2.7** Экспорт проектов → `05-Projects/{name}/README.md` с метаданными и финансовыми итогами
- [ ] **9.2.8** Интегрировать writer в существующие хэндлеры (вызывать после `create_event`):
  - В `src/bots/business/handlers.py` — при создании идеи/задачи
  - В `src/bots/mentor/handlers.py` — при записи идеи/обсуждения
  - В `src/bots/psychology/handlers.py` — при записи в дневник
  - В `src/bots/health/handlers.py` — при записи еды/тренировки
  - В `src/bots/master/handlers.py` — при обновлении цели

### 9.3 Obsidian → Telegram (парсинг задач + напоминания)

Python-демон на VPS, который мониторит .md файлы и отправляет напоминания.

- [ ] **9.3.1** Добавить `watchdog` в `requirements.txt`
- [ ] **9.3.2** Создать `src/integrations/obsidian/task_parser.py`:
  - RegEx парсер формата Tasks-плагина:
    ```
    - [ ] Текст задачи 📅 2026-04-10 ⏰ 14:30
    - [ ] Текст задачи 📅 2026-04-10
    - [x] Выполненная задача ✅ 2026-04-09
    ```
  - Извлечение: `text`, `due_date`, `due_time`, `is_done`, `source_file`
- [ ] **9.3.3** Создать `src/integrations/obsidian/watcher.py`:
  - `watchdog.observers.Observer` мониторит папку Vault
  - При изменении `.md` файла → парсит задачи → upsert в таблицу `obsidian_tasks`
- [ ] **9.3.4** Создать SQL-миграцию — новая таблица `obsidian_tasks`:
  ```sql
  CREATE TABLE obsidian_tasks (
      id SERIAL PRIMARY KEY,
      user_id BIGINT REFERENCES users(user_id),
      task_text TEXT NOT NULL,
      source_file TEXT NOT NULL,           -- путь к .md файлу
      due_date DATE,
      due_time TIME,                       -- NULL если без времени
      is_done BOOLEAN DEFAULT FALSE,
      reminder_sent BOOLEAN DEFAULT FALSE, -- чтобы не дублировать
      created_at TIMESTAMPTZ DEFAULT NOW(),
      updated_at TIMESTAMPTZ DEFAULT NOW(),
      UNIQUE(source_file, task_text)       -- дедупликация
  );
  CREATE INDEX idx_obsidian_tasks_due ON obsidian_tasks(due_date, due_time) 
      WHERE is_done = FALSE AND reminder_sent = FALSE;
  ```
- [ ] **9.3.5** Добавить SQL-запросы в `src/db/queries.py`:
  - `upsert_obsidian_task(...)` 
  - `get_pending_reminders(now)` — задачи, у которых наступило время
  - `mark_reminder_sent(task_id)`
  - `get_today_tasks(user_id)` — все задачи на сегодня
- [ ] **9.3.6** Добавить scheduler-задачу в master-бот (`src/bots/master/scheduler.py`):
  - Каждую минуту: `SELECT * FROM obsidian_tasks WHERE due_date = today AND due_time <= now AND NOT is_done AND NOT reminder_sent`
  - Отправить Telegram-сообщение через master-бот:
    ```
    ⏰ Напоминание: Созвон по поставкам леса
    📂 Файл: Projects/KDK-GRUPP/задачи.md
    ```
  - Пометить `reminder_sent = TRUE`
- [ ] **9.3.7** Утренняя сводка задач на день (APScheduler, 08:00 MSK):
  - SELECT все задачи на сегодня → Telegram:
    ```
    📋 Задачи на 10.04.2026:
    • 09:00 — Утренний разбор Inbox
    • 14:30 — Созвон по поставкам леса
    • 16:00 — Обзвон клиентов клининга
    Всего: 3 задачи
    ```

### 9.4 Двусторонняя синхронизация задач

- [ ] **9.4.1** При выполнении задачи в Obsidian (`- [x]`) → watcher обновляет БД (`is_done = TRUE`)
- [ ] **9.4.2** Telegram-команда `/done <task_id>` → обновить БД + перезаписать в .md файле `- [ ]` → `- [x] ✅ {date}`
- [ ] **9.4.3** Telegram-команда `/task Текст 📅 2026-04-15 ⏰ 10:00` → создать запись в `04-Daily/{today}.md` + БД
- [ ] **9.4.4** Reply-кнопка `📋 Задачи` в master-боте → показать задачи на сегодня из `obsidian_tasks`

### 9.5 RAG-интеграция с Obsidian

Obsidian-заметки как дополнительный источник для RAG-поиска.

- [ ] **9.5.1** При создании/обновлении заметки в `02-Knowledge/` → генерировать embedding → сохранять в `events` (event_type = `obsidian_note`)
- [ ] **9.5.2** Бот Master/Mentor при RAG-поиске учитывает `obsidian_note` события
- [ ] **9.5.3** При RAG-ответе, если источник — заметка Obsidian, добавлять ссылку: `📝 Источник: Knowledge/Скрипт продаж B2B.md`

### 9.6 Конфигурация и Settings

- [x] **9.6.1** Добавить в `src/config.py`:
  ```python
  # --- Obsidian ---
  obsidian_vault_path: str = "/app/obsidian-vault"
  obsidian_sync_enabled: bool = False      # включать только когда Syncthing настроен
  obsidian_watch_enabled: bool = False     # мониторинг задач
  ```
- [ ] **9.6.2** Добавить переменные в `.env.example`
- [x] **9.6.3** Obsidian-интеграция НЕ блокирует работу ботов — если `obsidian_sync_enabled = False`, все вызовы writer пропускаются

---

## Фаза 10: Ежедневный планировщик (Daily Planner)

Расширение master-бота для управления ежедневными делами напрямую из Telegram.

### 10.1 Модель данных

- [x] **10.1.1** Создать таблицу `tasks` (унифицированная для Telegram + Obsidian):
  - `sql/001_init_schema.sql` — добавлена таблица tasks
  - `sql/002_add_tasks.sql` — миграция для существующих БД
- [x] **10.1.2** SQL-запросы в `src/db/queries.py`: `create_task`, `complete_task`, `get_tasks_by_date`, `get_today_tasks`, `get_overdue_tasks`, `get_week_tasks`, `reschedule_task`, `delete_task`, `get_pending_task_reminders`, `mark_reminder_sent`, `get_unclosed_tasks`, `get_completed_today_count`

### 10.2 Telegram-интерфейс (master-бот)

- [x] **10.2.1** Добавить кнопку `📋 Задачи` в reply-клавиатуру master-бота
- [x] **10.2.2** Хэндлер кнопки `📋 Задачи` — показать задачи на сегодня с inline-кнопками:
  ```
  📋 Задачи на 07.04.2026:

  ⬜ 09:00 — Утренний разбор Inbox [🔴 urgent]
  ⬜ 14:30 — Созвон по поставкам леса [📁 КДК]
  ✅ 10:00 — Проверить отчёт клининга

  [➕ Добавить] [📅 Другой день] [🔄 Просрочено]
  ```
- [x] **10.2.3** Inline-кнопка на каждой задаче → отметить выполненной (callback `task_done:{id}`)
- [x] **10.2.4** Хэндлер `➕ Добавить задачу`:
  - Текст → LLM парсит: тема, дата, время, приоритет, проект
  - Голос → Whisper → LLM парсит
  - Inline-кнопки для уточнения проекта и приоритета
- [ ] **10.2.5** Хэндлер `📅 Другой день` — выбор даты через inline-календарь (TODO: `aiogram_calendar`)
- [x] **10.2.6** Хэндлер `🔄 Просрочено` — список задач с прошедшей due_date  
- [x] **10.2.7** Команда `/week` — задачи на текущую неделю
- [x] **10.2.8** Команда `/task` — быстрое добавление задачи
- [x] **10.2.9** Команда `/done` — отметить задачу выполненной по номеру

### 10.3 Автоплан и умные напоминания

- [x] **10.3.1** Утренний брифинг (08:00 MSK, APScheduler):
  ```
  ☀️ Доброе утро, Алексей!

  📋 Задачи на сегодня: 5
  🔴 Срочных: 1
  ⏰ Первая: 09:00 — Утренний разбор Inbox

  💰 Вчера расходы: 12 500 ₽
  🍽 Вчера КБЖУ: 2150 / 2400

  🎯 Фокус: «Выйти из операционки клининга» — 45%
  ```
- [x] **10.3.2** Вечерний обзор (21:00 MSK):
  ```
  🌙 Итоги дня:

  ✅ Выполнено: 4/5 задач
  ❌ Не выполнено: Обзвон клиентов (перенести?)
  
  [📅 Перенести на завтра] [🗑 Удалить]
  ```
- [x] **10.3.3** Напоминание при наступлении времени задачи (каждую минуту проверка pending_task_reminders)
- [x] **10.3.4** Вечерний обзор показывает незакрытые задачи с кнопками переноса/удаления

### 10.4 Синхронизация Planner ↔ Obsidian

- [ ] **10.4.1** Задачи из Telegram → автоматически попадают в `04-Daily/{date}.md`
- [ ] **10.4.2** Задачи из Obsidian → автоматически видны в Telegram через `📋 Задачи`
- [ ] **10.4.3** Отметка `[x]` в любом месте → синхронизация в обе стороны

---

## Зависимости и требования

### Новые Python-пакеты
```
watchdog>=4.0          # мониторинг файловой системы
```

### Новые переменные .env
```
OBSIDIAN_VAULT_PATH=/app/obsidian-vault
OBSIDIAN_SYNC_ENABLED=false
OBSIDIAN_WATCH_ENABLED=false
```

### Влияние на существующий код
| Файл | Изменение |
|------|-----------|
| `src/config.py` | +3 переменные Obsidian |
| `src/main.py` | Запуск watcher (если enabled) |
| `sql/001_init_schema.sql` | +таблица `obsidian_tasks` |
| `src/db/queries.py` | +CRUD для obsidian_tasks |
| `src/bots/master/handlers.py` | +кнопка Tasks, хэндлеры |
| `src/bots/master/keyboard.py` | +Mode.TASKS |
| `src/bots/master/scheduler.py` | +утренний/вечерний брифинг, напоминания |
| `src/bots/*/handlers.py` | +вызов obsidian writer (опционально) |
| `docker-compose.yml` | +volume obsidian-vault |
| `requirements.txt` | +watchdog |

---

## Риски

| Риск | Вероятность | Решение |
|------|-------------|---------|
| Syncthing задержка >30 сек | Низкая | Для напоминаний достаточно, не критично |
| Конфликт при одновременной записи .md | Средняя | Writer использует file-lock; Syncthing conflict resolution |
| Watchdog нагрузка на VPS | Низкая | Debounce 2 сек, мониторит только .md |
| Сложный парсинг Obsidian-формата | Средняя | Строгий RegEx + тесты; не парсить произвольный markdown |
| Obsidian не установлен → боты ломаются | Исключена | `obsidian_sync_enabled=False` по умолчанию |

---

## Порядок внедрения

**Рекомендуемая последовательность:**

1. **Obsidian Vault** — настроить локально, шаблоны, плагины (9.0)
2. **Syncthing** — связать ноутбук ↔ VPS (9.1)
3. **Планировщик в Telegram** — кнопка Tasks в master-боте, без Obsidian (10.1–10.2)
4. **Telegram → Obsidian** — writer для экспорта данных (9.2)
5. **Obsidian → Telegram** — watcher + парсер задач (9.3)
6. **Двусторонняя синхронизация** — полный цикл (9.4, 10.4)
7. **RAG-интеграция** — заметки Obsidian в поиске (9.5)
8. **Умные напоминания** — утренний/вечерний брифинг (10.3)

---

## Обновление implementation_plan.md

После завершения каждого подпункта — отметить `[x]` в этом файле.
