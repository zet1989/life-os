/**
 * Life OS Sync — Status Page (Zepp OS 4.x)
 *
 * Экран приложения: статус синхронизации, кнопка «Синхр. сейчас».
 * Сбор данных с датчиков → отправка через Side Service (BLE → fetch).
 */

import { createWidget, widget, prop, align, text_style } from '@zos/ui';
import { LocalStorage } from '@zos/storage';
import { px } from '@zos/utils';
import { HeartRate, Step, Calorie, Distance, Sleep, BloodOxygen, Stress } from '@zos/sensor';

import { BasePage } from '@zeppos/zml/base-page';
import { API_KEY, SERVER_URL, INTERVAL_MINUTES } from '../config';

const localStorage = new LocalStorage();

const COLOR_PRIMARY = 0x179dde;
const COLOR_SUCCESS = 0x00d68f;
const COLOR_ERROR   = 0xff6b6b;
const COLOR_MUTED   = 0x666666;
const W = 480;

function collectHealthData() {
  const data = {};
  try { const s = new Step();        const v = s.getCurrent();        if (v > 0) data.steps = v;        } catch (e) {}
  try { const c = new Calorie();     const v = c.getCurrent();        if (v > 0) data.calories = v;     } catch (e) {}
  try { const d = new Distance();    const v = d.getCurrent();        if (v > 0) data.distance = v;     } catch (e) {}
  try { const h = new HeartRate();   const v = h.getLast();            if (v > 0) data.heart_rate = v;   } catch (e) {}
  try { const b = new BloodOxygen(); const r = b.getCurrent();        if (r && r.value > 0) data.spo2 = r.value; } catch (e) {}
  try { const st = new Stress();     const r = st.getCurrent();       if (r && r.value > 0) data.stress = r.value; } catch (e) {}
  try {
    const sl = new Sleep();
    const info = sl.getInfo();
    if (info && info.totalTime > 0) {
      data.sleep = { total_min: info.totalTime, deep_min: info.deepTime || 0 };
    }
  } catch (e) {}
  return data;
}

function formatTime(tsStr) {
  if (!tsStr) return '--:--';
  const ts = parseInt(tsStr);
  if (isNaN(ts)) return '--:--';
  const d = new Date(ts);
  return d.getHours().toString().padStart(2, '0') + ':' + d.getMinutes().toString().padStart(2, '0');
}

Page(
  BasePage({
    state: { statusWidget: null, hintWidget: null, autoSyncTimer: null },

    build() {
      const lastStatus = localStorage.getItem('last_sync_status') || 'none';
      const lastTime = localStorage.getItem('last_sync_time');
      const lastKeys = localStorage.getItem('last_sync_keys') || '';

      let statusText = 'Ожидание';
      let statusColor = COLOR_MUTED;
      if (lastStatus === 'ok')    { statusText = '✓ OK';     statusColor = COLOR_SUCCESS; }
      if (lastStatus === 'error') { statusText = '✗ Ошибка'; statusColor = COLOR_ERROR; }

      // Title
      createWidget(widget.TEXT, {
        x: 0, y: px(18), w: W, h: px(44),
        text: 'Life OS Sync', text_size: px(34), color: COLOR_PRIMARY, align_h: align.CENTER_H,
      });

      // Status
      this.state.statusWidget = createWidget(widget.TEXT, {
        x: 0, y: px(80), w: W, h: px(40),
        text: statusText, text_size: px(28), color: statusColor, align_h: align.CENTER_H,
      });

      // Last sync time
      createWidget(widget.TEXT, {
        x: 0, y: px(126), w: W, h: px(30),
        text: 'Последняя: ' + formatTime(lastTime),
        text_size: px(22), color: COLOR_MUTED, align_h: align.CENTER_H,
      });

      // Metrics
      createWidget(widget.TEXT, {
        x: px(20), y: px(164), w: W - px(40), h: px(48),
        text: lastKeys ? lastKeys.split(',').join(' · ') : '',
        text_size: px(20), color: COLOR_MUTED, align_h: align.CENTER_H, text_style: text_style.WRAP,
      });

      // Interval
      createWidget(widget.TEXT, {
        x: 0, y: px(220), w: W, h: px(30),
        text: 'Интервал: ' + (INTERVAL_MINUTES || 15) + ' мин',
        text_size: px(22), color: COLOR_MUTED, align_h: align.CENTER_H,
      });

      // Sync button
      const self = this;
      createWidget(widget.BUTTON, {
        x: px(40), y: px(280), w: W - px(80), h: px(70),
        text: 'Синхр. сейчас', text_size: px(26),
        normal_color: COLOR_PRIMARY, press_color: 0x0d6fa8,
        click_func: () => { self.syncNow(); },
      });

      // Hint line
      this.state.hintWidget = createWidget(widget.TEXT, {
        x: px(20), y: px(370), w: W - px(40), h: px(60),
        text: '', text_size: px(20), color: COLOR_MUTED,
        align_h: align.CENTER_H, text_style: text_style.WRAP,
      });

      // Авто-синхронизация каждые INTERVAL_MINUTES
      const intervalMs = (INTERVAL_MINUTES || 15) * 60 * 1000;
      this.state.autoSyncTimer = setInterval(() => {
        this.syncNow();
      }, intervalMs);

      // Первая автосинхронизация через 10 секунд после запуска
      setTimeout(() => { this.syncNow(); }, 10000);
    },

    onDestroy() {
      if (this.state.autoSyncTimer) {
        clearInterval(this.state.autoSyncTimer);
        this.state.autoSyncTimer = null;
      }
    },

    syncNow() {
      const data = collectHealthData();
      const keys = Object.keys(data);

      if (keys.length === 0) {
        this.setHint('Нет данных с датчиков');
        return;
      }

      this.setHint('Отправка ' + keys.length + ' метрик...');

      this.httpRequest({
        method: 'post',
        url: SERVER_URL,
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer ' + API_KEY,
        },
        body: data,
      })
        .then((result) => {
          localStorage.setItem('last_sync_status', 'ok');
          localStorage.setItem('last_sync_time', Date.now().toString());
          localStorage.setItem('last_sync_keys', keys.join(','));
          this.state.statusWidget.setProperty(prop.MORE, { text: '✓ OK', color: COLOR_SUCCESS });
          this.setHint(keys.join(' · '));
        })
        .catch((err) => {
          localStorage.setItem('last_sync_status', 'error');
          this.state.statusWidget.setProperty(prop.MORE, { text: '✗ Ошибка', color: COLOR_ERROR });
          this.setHint(String(err).slice(0, 80));
        });
    },

    setHint(text) {
      if (this.state.hintWidget) {
        this.state.hintWidget.setProperty(prop.MORE, { text: text });
      }
    },
  })
);
