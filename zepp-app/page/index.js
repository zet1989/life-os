/**
 * Life OS Sync — Status Page (Zepp OS 4.x)
 *
 * Экран приложения: статус синхронизации, кнопка «Синхр. сейчас».
 * При открытии МГНОВЕННО отправляет pending данные из фонового сервиса,
 * затем собирает свежие данные с датчиков → отправка через Side Service (BLE → fetch).
 */

import { createWidget, widget, prop, align, text_style } from '@zos/ui';
import { LocalStorage } from '@zos/storage';
import { px } from '@zos/utils';
import { HeartRate, Step, Calorie, Distance, Sleep, BloodOxygen, Stress, FatBurning, Stand, BodyTemperature, Pai, Workout } from '@zos/sensor';

import { BasePage } from '@zeppos/zml/base-page';
import { API_KEY, SERVER_URL, INTERVAL_MINUTES } from '../config';

const localStorage = new LocalStorage();

const COLOR_PRIMARY = 0x179dde;
const COLOR_SUCCESS = 0x00d68f;
const COLOR_ERROR   = 0xff6b6b;
const COLOR_MUTED   = 0x666666;
const COLOR_WARN    = 0xffaa00;
const W = 480;

function collectHealthData() {
  const data = {};

  // Шаги
  try { const s = new Step(); const v = s.getCurrent(); if (v > 0) data.steps = v; } catch (e) {}

  // Калории
  try { const c = new Calorie(); const v = c.getCurrent(); if (v > 0) data.calories = v; } catch (e) {}

  // Дистанция (метры)
  try { const d = new Distance(); const v = d.getCurrent(); if (v > 0) data.distance = v; } catch (e) {}

  // Пульс: last + resting + daily summary (max) + средний за день
  try {
    const h = new HeartRate();
    const hr = {};
    const last = h.getLast(); if (last > 0) hr.last = last;
    try { const rest = h.getResting(); if (rest > 0) hr.resting = rest; } catch (e) {}
    try {
      const summary = h.getDailySummary();
      if (summary && summary.maximum) {
        hr.max = summary.maximum.hr_value;
        hr.max_time = summary.maximum.time;
      }
    } catch (e) {}
    try {
      const today = h.getToday();
      if (today && today.length > 0) {
        const valid = today.filter(v => v > 0);
        if (valid.length > 0) {
          hr.avg = Math.round(valid.reduce((a, b) => a + b, 0) / valid.length);
          hr.min = Math.min(...valid);
          if (!hr.max) hr.max = Math.max(...valid);
        }
      }
    } catch (e) {}
    if (Object.keys(hr).length > 0) data.heart_rate = hr;
  } catch (e) {}

  // SpO2
  try { const b = new BloodOxygen(); const r = b.getCurrent(); if (r && r.value > 0) data.spo2 = r.value; } catch (e) {}

  // Стресс: last + средний за день
  try {
    const st = new Stress();
    const stress = {};
    const cur = st.getCurrent(); if (cur && cur.value > 0) stress.last = cur.value;
    try {
      const today = st.getTodayByHour();
      if (today && today.length > 0) {
        const valid = today.filter(v => v > 0);
        if (valid.length > 0) {
          stress.avg = Math.round(valid.reduce((a, b) => a + b, 0) / valid.length);
        }
      }
    } catch (e) {}
    if (Object.keys(stress).length > 0) data.stress = stress;
  } catch (e) {}

  // Сон: score + фазы + дневной сон
  try {
    const sl = new Sleep();
    sl.updateInfo();
    const info = sl.getInfo();
    if (info && info.totalTime > 0) {
      const sleep = {
        total_min: info.totalTime,
        deep_min: info.deepTime || 0,
        score: info.score || 0,
        start_time: info.startTime,
        end_time: info.endTime,
      };
      try {
        const stageConst = sl.getStageConstantObj();
        const stages = sl.getStage();
        if (stages && stages.length > 0) {
          let rem = 0, light = 0, awake = 0;
          stages.forEach(s => {
            const dur = (s.stop - s.start);
            if (s.model === stageConst.REM_STAGE) rem += dur;
            else if (s.model === stageConst.LIGHT_STAGE) light += dur;
            else if (s.model === stageConst.WAKE_STAGE) awake += dur;
          });
          sleep.rem_min = rem;
          sleep.light_min = light;
          sleep.awake_min = awake;
        }
      } catch (e) {}
      try {
        const naps = sl.getNap();
        if (naps && naps.length > 0) {
          sleep.nap_min = naps.reduce((sum, n) => sum + (n.length || 0), 0);
          sleep.nap_count = naps.length;
        }
      } catch (e) {}
      data.sleep = sleep;
    }
  } catch (e) {}

  // Температура тела
  try {
    const bt = new BodyTemperature();
    const r = bt.getCurrent();
    if (r && r.current > 0 && r.current < 45) data.body_temperature = r.current;
  } catch (e) {}

  // Жиросжигание (минуты)
  try { const fb = new FatBurning(); const v = fb.getCurrent(); if (v > 0) data.fat_burning_min = v; } catch (e) {}

  // PAI (Physical Activity Intelligence)
  try {
    const p = new Pai();
    const total = p.getTotal();
    const today = p.getToday();
    if (total > 0 || today > 0) data.pai = { total: total, today: today };
  } catch (e) {}

  // Часы стоя
  try { const st = new Stand(); const v = st.getCurrent(); if (v > 0) data.standing_hours = v; } catch (e) {}

  // Тренировка: VO2 Max, Training Load, Recovery Time
  try {
    const w = new Workout();
    const status = w.getStatus();
    if (status) {
      const workout = {};
      if (status.vo2Max > 0) workout.vo2_max = status.vo2Max;
      if (status.trainingLoad > 0) workout.training_load = status.trainingLoad;
      if (status.fullRecoveryTime > 0) workout.recovery_hours = status.fullRecoveryTime;
      if (Object.keys(workout).length > 0) data.workout = workout;
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
    state: { statusWidget: null, hintWidget: null, collectWidget: null, autoSyncTimer: null },

    build() {
      const lastStatus = localStorage.getItem('last_sync_status') || 'none';
      const lastTime = localStorage.getItem('last_sync_time');
      const lastCollect = localStorage.getItem('last_collect_time');
      const collectCount = localStorage.getItem('collect_count') || '0';
      const hasPending = !!localStorage.getItem('pending_data');

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
        x: 0, y: px(72), w: W, h: px(36),
        text: statusText, text_size: px(26), color: statusColor, align_h: align.CENTER_H,
      });

      // Last sent time
      createWidget(widget.TEXT, {
        x: 0, y: px(114), w: W, h: px(28),
        text: 'Отправлено: ' + formatTime(lastTime),
        text_size: px(20), color: COLOR_MUTED, align_h: align.CENTER_H,
      });

      // Last background collect time + count
      this.state.collectWidget = createWidget(widget.TEXT, {
        x: 0, y: px(146), w: W, h: px(28),
        text: 'Фон: ' + formatTime(lastCollect) + (hasPending ? ' (ожидает отправки)' : '') + ' [' + collectCount + ']',
        text_size: px(20), color: hasPending ? COLOR_WARN : COLOR_MUTED, align_h: align.CENTER_H,
      });

      // Interval
      createWidget(widget.TEXT, {
        x: 0, y: px(180), w: W, h: px(28),
        text: 'Интервал фона: ' + (INTERVAL_MINUTES || 15) + ' мин',
        text_size: px(20), color: COLOR_MUTED, align_h: align.CENTER_H,
      });

      // Sync button
      const self = this;
      createWidget(widget.BUTTON, {
        x: px(40), y: px(230), w: W - px(80), h: px(70),
        text: 'Синхр. сейчас', text_size: px(26),
        normal_color: COLOR_PRIMARY, press_color: 0x0d6fa8,
        click_func: () => { self.syncNow(); },
      });

      // Hint line
      this.state.hintWidget = createWidget(widget.TEXT, {
        x: px(20), y: px(320), w: W - px(40), h: px(80),
        text: '', text_size: px(20), color: COLOR_MUTED,
        align_h: align.CENTER_H, text_style: text_style.WRAP,
      });

      // МГНОВЕННАЯ отправка pending данных (без задержки!)
      this.flushPending();

      // Свежая синхронизация через 3 секунды
      setTimeout(() => { this.syncNow(); }, 3000);

      // Повторная синхронизация пока приложение открыто
      const intervalMs = (INTERVAL_MINUTES || 15) * 60 * 1000;
      this.state.autoSyncTimer = setInterval(() => {
        this.syncNow();
      }, intervalMs);
    },

    onDestroy() {
      if (this.state.autoSyncTimer) {
        clearInterval(this.state.autoSyncTimer);
        this.state.autoSyncTimer = null;
      }
    },

    flushPending() {
      const pendingRaw = localStorage.getItem('pending_data');
      if (!pendingRaw) return;

      let pending;
      try { pending = JSON.parse(pendingRaw); } catch (e) { return; }
      const keys = Object.keys(pending);
      if (keys.length === 0) return;

      this.setHint('Отправка фоновых данных (' + keys.length + ')...');
      this.httpRequest({
        method: 'post',
        url: SERVER_URL,
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer ' + API_KEY,
        },
        body: pending,
      })
        .then(() => {
          localStorage.removeItem('pending_data');
          localStorage.removeItem('pending_keys');
          localStorage.setItem('last_sync_status', 'ok');
          localStorage.setItem('last_sync_time', Date.now().toString());
          localStorage.setItem('collect_count', '0');
          this.state.statusWidget.setProperty(prop.MORE, { text: '✓ Фон OK', color: COLOR_SUCCESS });
          if (this.state.collectWidget) {
            this.state.collectWidget.setProperty(prop.MORE, {
              text: 'Фон: ' + formatTime(Date.now().toString()) + ' [0]',
              color: COLOR_MUTED,
            });
          }
          this.setHint('Фоновые данные отправлены ✓');
        })
        .catch((err) => {
          this.setHint('Фон: ошибка ' + String(err).slice(0, 60));
        });
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
          localStorage.setItem('collect_count', '0');
          this.state.statusWidget.setProperty(prop.MORE, { text: '✓ OK', color: COLOR_SUCCESS });
          this.setHint(keys.length + ' метрик: ' + keys.join(', '));
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
