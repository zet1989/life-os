/**
 * Life OS Sync — Background App Service (Zepp OS 4.x)
 *
 * Периодически собирает метрики здоровья с датчиков и сохраняет в localStorage.
 * Данные отправляются на сервер при открытии Page (через ZML BLE → Side Service → fetch).
 *
 * ОГРАНИЧЕНИЕ Zepp OS: AppService в режиме Single Execution (setAlarm) имеет
 * лимит 600мс. Сетевые запросы (async BLE messaging) НЕ могут завершиться за это время.
 * Поэтому AppService ТОЛЬКО собирает данные, а Page отправляет.
 */

import { HeartRate, Step, Calorie, Distance, Sleep, BloodOxygen, Stress, FatBurning, Stand, BodyTemperature, Pai, Workout } from '@zos/sensor';
import { LocalStorage } from '@zos/storage';
import { set as setAlarm } from '@zos/alarm';
import { INTERVAL_MINUTES } from '../config';

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

AppService({
  onInit() {
    const interval = parseInt(INTERVAL_MINUTES || '15');

    // ПЕРВЫМ делом ставим следующий alarm — даже если сбор данных упадёт, цепочка не разорвётся
    try {
      setAlarm({
        delay: interval * 60,
        url: 'app-service/index',
      });
    } catch (e) {
      console.log('Life OS BG: alarm error', e);
    }

    // Собираем данные с датчиков
    try {
      const data = collectHealthData();
      const keys = Object.keys(data);

      if (keys.length > 0) {
        // Сохраняем в pending — Page заберёт при открытии
        localStorage.setItem('pending_data', JSON.stringify(data));
        localStorage.setItem('pending_keys', keys.join(','));
        localStorage.setItem('last_collect_time', Date.now().toString());
        localStorage.setItem('collect_count',
          (parseInt(localStorage.getItem('collect_count') || '0') + 1).toString()
        );
        console.log('Life OS BG: collected', keys.length, 'metrics');
      } else {
        console.log('Life OS BG: no sensor data');
      }
    } catch (e) {
      console.log('Life OS BG: collect error', e);
    }
  },

  onDestroy() {},
});
