/**
 * Life OS Sync — Background App Service (Zepp OS)
 *
 * Периодически собирает метрики здоровья с датчиков.
 * Отправляет данные через ZML messaging → Side Service → fetch (серверу).
 * Если messaging недоступен, сохраняет в LocalStorage для отправки при открытии Page.
 */

import { HeartRate, Step, Calorie, Distance, Sleep, BloodOxygen, Stress, FatBurning, Stand, BodyTemperature, Pai, Workout } from '@zos/sensor';
import { LocalStorage } from '@zos/storage';
import { set as setAlarm } from '@zos/alarm';
import { getApp } from '@zos/app';
import { INTERVAL_MINUTES, API_KEY, SERVER_URL } from '../config';

const localStorage = new LocalStorage();

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
      // Получаем фазы (REM, light, awake)
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
      // Дневной сон
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

function trySendViaMessaging(data) {
  try {
    const app = getApp();
    const messaging = app && app._options && app._options.globalData && app._options.globalData.messaging;
    if (messaging && typeof messaging.request === 'function') {
      messaging.request({
        method: 'push_health_data',
        params: { data, api_key: API_KEY, server_url: SERVER_URL },
      })
        .then(() => {
          console.log('Life OS Service: sent via messaging OK');
          localStorage.setItem('last_sync_status', 'ok');
          localStorage.setItem('last_sync_time', Date.now().toString());
          // Очищаем pending — данные отправлены
          localStorage.removeItem('pending_data');
          localStorage.removeItem('pending_keys');
        })
        .catch((err) => {
          console.log('Life OS Service: messaging send failed', err);
          savePending(data);
        });
      return true;
    }
  } catch (e) {
    console.log('Life OS Service: messaging unavailable', e);
  }
  return false;
}

function savePending(data) {
  const keys = Object.keys(data);
  if (keys.length > 0) {
    localStorage.setItem('pending_data', JSON.stringify(data));
    localStorage.setItem('pending_keys', keys.join(','));
    console.log('Life OS Service: saved to pending (will sync on page open)');
  }
}

AppService({
  onInit() {
    const interval = parseInt(INTERVAL_MINUTES || '15');

    const data = collectHealthData();
    const keys = Object.keys(data);

    if (keys.length > 0) {
      console.log('Life OS Service: collected', keys.join(', '));
      // Пробуем отправить через messaging (если App и ZML messaging доступны)
      const sent = trySendViaMessaging(data);
      if (!sent) {
        // Fallback: сохраняем в localStorage для отправки при открытии Page
        savePending(data);
      }
    } else {
      console.log('Life OS Service: no data from sensors');
    }

    // Schedule next wake
    setAlarm({
      delay: interval * 60,
      url: 'app-service/index.js',
    });
    console.log('Life OS Service: next in', interval, 'min');
  },

  onDestroy() {
    console.log('Life OS Sync: AppService stopped');
  },
});
