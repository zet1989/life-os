"""Text-to-Speech через edge-tts (бесплатный Microsoft Edge TTS).

Поддерживает русские голоса:
- ru-RU-SvetlanaNeural (женский, по умолчанию)
- ru-RU-DmitryNeural (мужской)
"""

import asyncio
import re
import tempfile
from pathlib import Path

import structlog

logger = structlog.get_logger()

# Женский голос по умолчанию (тёплый, приятный)
DEFAULT_VOICE = "ru-RU-SvetlanaNeural"

# Максимальная длина текста для озвучки (edge-tts ограничение ~5000 символов)
MAX_TTS_LENGTH = 4500

# In-memory toggle: user_id → True/False
_voice_mode: dict[int, bool] = {}


def is_voice_mode(user_id: int) -> bool:
    """Проверить, включён ли голосовой режим у пользователя."""
    return _voice_mode.get(user_id, False)


def toggle_voice_mode(user_id: int) -> bool:
    """Переключить голосовой режим. Возвращает новое состояние."""
    current = _voice_mode.get(user_id, False)
    _voice_mode[user_id] = not current
    return not current


def _clean_for_tts(text: str) -> str:
    """Убрать HTML-теги и форматирование для TTS."""
    # Убираем HTML-теги
    text = re.sub(r"<[^>]+>", "", text)
    # Убираем markdown-символы
    text = re.sub(r"[*_`#]", "", text)
    # Убираем эмодзи (оставляем текст вокруг)
    text = re.sub(
        r"[\U0001f300-\U0001f9ff\U0001fa00-\U0001fa6f\U0001fa70-\U0001faff"
        r"\u2600-\u27bf\u2b50\u2934\u2935\u25aa-\u25fe\u2700-\u27bf]+",
        " ", text,
    )
    # Множественные пробелы → один
    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_TTS_LENGTH]


async def text_to_voice(
    text: str,
    voice: str = DEFAULT_VOICE,
) -> Path | None:
    """Синтезировать речь из текста. Возвращает путь к OGG-файлу или None."""
    try:
        import edge_tts

        clean = _clean_for_tts(text)
        if not clean or len(clean) < 5:
            return None

        tmp = Path(tempfile.mktemp(suffix=".mp3"))

        communicate = edge_tts.Communicate(clean, voice)
        await communicate.save(str(tmp))

        if not tmp.exists() or tmp.stat().st_size < 100:
            tmp.unlink(missing_ok=True)
            return None

        logger.info("tts_generated", chars=len(clean), voice=voice, size=tmp.stat().st_size)
        return tmp

    except Exception:
        logger.exception("tts_failed")
        return None
