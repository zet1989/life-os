/**
 * Life OS Sync — Конфигурация
 *
 * Заполни перед сборкой:
 * 1. Получи API-ключ: раздел Health → /watch_connect
 * 2. URL сервера — твой VPS с Life OS
 * 3. Интервал — как часто отправлять данные (в минутах)
 */

// API-ключ для авторизации push-запросов (из /watch_connect)
export const API_KEY = '';

// URL эндпоинта push (из /watch_connect)
export const SERVER_URL = '';

// Интервал отправки данных (минуты): 15 / 30 / 60
export const INTERVAL_MINUTES = 15;
