/**
 * Life OS Sync — Status Page (Zepp OS)
 *
 * Экран, который открывается при запуске приложения на часах.
 * Показывает: статус последней синхронизации, время, метрики.
 * Кнопка «Синхр. сейчас» запускает AppService немедленно через alarm(delay=1).
 */

import { createWidget, widget, prop, align, text_style } from '@zos/ui';
import { storage } from '@zos/storage';
import { set as setAlarm } from '@zos/alarm';
import { px } from '@zos/utils';
import { INTERVAL_MINUTES } from '../config';

// Цвета
const COLOR_PRIMARY  = 0x179dde;  // Life OS blue
const COLOR_SUCCESS  = 0x00d68f;  // зелёный
const COLOR_WARNING  = 0xff9f43;  // оранжевый
const COLOR_ERROR    = 0xff6b6b;  // красный
const COLOR_MUTED    = 0x666666;  // серый
const COLOR_TEXT     = 0xffffff;  // белый

// Ширина и высота экрана Amazfit Balance 2 (480×520)
const W = 480;

function formatTime(tsStr) {
  if (!tsStr) return 'Никогда';
  const ts = parseInt(tsStr);
  if (isNaN(ts)) return '—';
  const d  = new Date(ts);
  const hh = d.getHours().toString().padStart(2, '0');
  const mm = d.getMinutes().toString().padStart(2, '0');
  return hh + ':' + mm;
}

Page({
  build() {
    const status     = storage.getItem('last_sync_status') || 'none';
    const lastTime   = storage.getItem('last_sync_time');
    const lastKeys   = storage.getItem('last_sync_keys')   || '';
    const errDetail  = storage.getItem('last_sync_error')  || '';
    const interval   = parseInt(INTERVAL_MINUTES || '15');

    // ── Заголовок ──────────────────────────────────────────
    createWidget(widget.TEXT, {
      x: 0, y: px(18), w: W, h: px(44),
      text:       'Life OS Sync',
      text_size:  px(34),
      color:      COLOR_PRIMARY,
      align_h:    align.CENTER_H,
    });

    // ── Статус-строка ──────────────────────────────────────
    let statusIcon  = '⏳';
    let statusColor = COLOR_WARNING;
    let statusText  = 'Ожидание';

    if (status === 'ok') {
      statusIcon  = '✓';
      statusColor = COLOR_SUCCESS;
      statusText  = 'OK';
    } else if (status === 'error') {
      statusIcon  = '✗';
      statusColor = COLOR_ERROR;
      statusText  = 'Ошибка';
    } else if (status === 'not_configured') {
      statusIcon  = '!';
      statusColor = COLOR_WARNING;
      statusText  = 'Не настроено';
    } else if (status === 'no_data') {
      statusIcon  = '?';
      statusColor = COLOR_MUTED;
      statusText  = 'Нет данных';
    }

    createWidget(widget.TEXT, {
      x: 0, y: px(70), w: W, h: px(40),
      text:      statusIcon + ' ' + statusText,
      text_size: px(30),
      color:     statusColor,
      align_h:   align.CENTER_H,
    });

    // ── Время последней синхронизации ──────────────────────
    createWidget(widget.TEXT, {
      x: 0, y: px(116), w: W, h: px(32),
      text:      'Последняя: ' + formatTime(lastTime),
      text_size: px(24),
      color:     COLOR_MUTED,
      align_h:   align.CENTER_H,
    });

    // ── Переданные метрики ─────────────────────────────────
    const metricsLabel = lastKeys
      ? lastKeys.split(',').join(' · ')
      : 'нет данных';

    createWidget(widget.TEXT, {
      x: px(20), y: px(156), w: W - px(40), h: px(48),
      text:       metricsLabel,
      text_size:  px(20),
      color:      COLOR_MUTED,
      align_h:    align.CENTER_H,
      text_style: text_style.WRAP,
    });

    // ── Детали ошибки (если есть) ──────────────────────────
    if (status === 'error' && errDetail) {
      createWidget(widget.TEXT, {
        x: px(20), y: px(210), w: W - px(40), h: px(40),
        text:       errDetail.slice(0, 60),
        text_size:  px(18),
        color:      COLOR_ERROR,
        text_style: text_style.WRAP,
      });
    }

    // ── Интервал ───────────────────────────────────────────
    createWidget(widget.TEXT, {
      x: 0, y: px(260), w: W, h: px(30),
      text:      'Интервал: каждые ' + interval + ' мин',
      text_size: px(22),
      color:     COLOR_MUTED,
      align_h:   align.CENTER_H,
    });

    // ── Кнопка «Синхронизировать сейчас» ──────────────────
    createWidget(widget.BUTTON, {
      x: px(40), y: px(306), w: W - px(80), h: px(70),
      text:        'Синхр. сейчас',
      text_size:   px(26),
      normal_color: COLOR_PRIMARY,
      press_color:  0x0d6fa8,
      func: () => {
        // Запустить AppService немедленно (через 1 сек)
        setAlarm({
          delay: 1,
          file:  'app-service/index.js',
          args:  {},
        });
        // Обновить индикатор
        createWidget(widget.TEXT, {
          x: 0, y: px(386), w: W, h: px(30),
          text:      'Запущено...',
          text_size: px(22),
          color:     COLOR_SUCCESS,
          align_h:   align.CENTER_H,
        });
      },
    });

    // ── Подсказка по настройке ─────────────────────────────
    if (status === 'not_configured' || status === 'none') {
      createWidget(widget.TEXT, {
        x: px(20), y: px(390), w: W - px(40), h: px(66),
        text:       'Настройка: Health → /watch_connect → заполни config.js → пересобери',
        text_size:  px(18),
        color:      COLOR_MUTED,
        text_style: text_style.WRAP,
        align_h:    align.CENTER_H,
      });
    }
  },
});
