/**
 * Life OS Sync — Background App Service (Zepp OS)
 *
 * Периодически собирает метрики здоровья с датчиков часов
 * и отправляет их на сервер Life OS через HTTP POST.
 *
 * Цикл работы:
 *   1. AppService стартует (по расписанию alarm или вручную)
 *   2. Собирает данные с датчиков (шаги, пульс, SpO2, стресс, сон, калории, дистанция)
 *   3. Отправляет POST-запрос на SERVER_URL с Bearer-токеном
 *   4. Записывает результат в LocalStorage (для отображения в UI)
 *   5. Выставляет следующий alarm через INTERVAL_MINUTES минут → завершается
 */

import { HeartRate, Sleep, StepCounter, SpO2, Stress, Calorie, Distance, SkinTemperature } from '@zos/health';
import { request } from '@zos/network';
import { storage } from '@zos/storage';
import { set as setAlarm } from '@zos/alarm';
import { API_KEY, SERVER_URL, INTERVAL_MINUTES } from '../config';

// ─────────────────────────────────────────────────────────────────────────────
//  Сбор метрик
// ─────────────────────────────────────────────────────────────────────────────

function collectHealthData() {
  const data = {};

  // Шаги (за сегодня)
  try {
    const sc = new StepCounter();
    const info = sc.getInfo();
    if (info && info.current > 0) {
      data.steps = info.current;
    }
  } catch (e) {
    console.log('Life OS: StepCounter error', e);
  }

  // Калории (за сегодня)
  try {
    const cal = new Calorie();
    const info = cal.getInfo();
    if (info && info.current > 0) {
      data.calories = info.current;
    }
  } catch (e) {
    console.log('Life OS: Calorie error', e);
  }

  // Дистанция (метры → сервер конвертирует в км сам)
  try {
    const dist = new Distance();
    const info = dist.getInfo();
    if (info && info.current > 0) {
      data.distance = info.current;
    }
  } catch (e) {
    console.log('Life OS: Distance error', e);
  }

  // Пульс (последнее измерение)
  try {
    const hr = new HeartRate();
    const last = hr.getLast();
    if (last > 0) {
      data.heart_rate = { last: last, avg: last };
    }
  } catch (e) {
    console.log('Life OS: HeartRate error', e);
  }

  // SpO2 (последнее измерение)
  try {
    const spo2 = new SpO2();
    const last = spo2.getLast();
    if (last > 0) {
      data.spo2 = { last: last, avg: last };
    }
  } catch (e) {
    console.log('Life OS: SpO2 error', e);
  }

  // Стресс (последнее измерение)
  try {
    const stress = new Stress();
    const last = stress.getLast();
    if (last > 0) {
      data.stress = { last: last, avg: last };
    }
  } catch (e) {
    console.log('Life OS: Stress error', e);
  }

  // Сон (данные за последнюю ночь)
  try {
    const sleep = new Sleep();
    const info = sleep.getInfo();
    if (info && (info.totalTime > 0 || info.deepTime > 0)) {
      data.sleep = {
        total_min:  info.totalTime  || 0,
        deep_min:   info.deepTime   || 0,
        light_min:  info.lightTime  || 0,
        rem_min:    info.remTime    || 0,
        awake_min:  info.awakeTime  || 0,
      };
    }
  } catch (e) {
    console.log('Life OS: Sleep error', e);
  }

  // Температура кожи (Amazfit Balance 2 поддерживает)
  try {
    const skin = new SkinTemperature();
    const last = skin.getLast();
    if (last > 0) {
      data.skin_temperature = last;
    }
  } catch (e) {
    // Датчик недоступен в данный момент — игнорируем
  }

  return data;
}

// ─────────────────────────────────────────────────────────────────────────────
//  AppService
// ─────────────────────────────────────────────────────────────────────────────

AppService({
  onInit() {
    const apiKey    = API_KEY    || storage.getItem('api_key_override');
    const serverUrl = SERVER_URL || storage.getItem('server_url_override');
    const interval  = parseInt(INTERVAL_MINUTES || storage.getItem('interval_min') || '15');

    if (!apiKey || !serverUrl) {
      console.log('Life OS: API key or Server URL not configured');
      storage.setItem('last_sync_status', 'not_configured');
      this._scheduleNext(interval);
      return;
    }

    const data = collectHealthData();
    const keys = Object.keys(data);

    if (keys.length === 0) {
      console.log('Life OS: No health data available from sensors');
      storage.setItem('last_sync_status', 'no_data');
      this._scheduleNext(interval);
      return;
    }

    console.log('Life OS: Sending', keys.join(', '));

    request({
      url:    serverUrl,
      method: 'POST',
      headers: {
        'Content-Type':  'application/json',
        'Authorization': 'Bearer ' + apiKey,
      },
      body: JSON.stringify(data),
      success: (result) => {
        console.log('Life OS: Push OK, status', result.status);
        storage.setItem('last_sync_time',   Date.now().toString());
        storage.setItem('last_sync_status', 'ok');
        storage.setItem('last_sync_keys',   keys.join(','));
        this._scheduleNext(interval);
      },
      fail: (error) => {
        console.log('Life OS: Push FAILED', JSON.stringify(error));
        storage.setItem('last_sync_status', 'error');
        storage.setItem('last_sync_error',  JSON.stringify(error).slice(0, 100));
        this._scheduleNext(interval);
      },
    });
  },

  // Запланировать следующий запуск через setAlarm
  _scheduleNext(intervalMinutes) {
    setAlarm({
      delay: intervalMinutes * 60,      // секунды
      file:  'app-service/index.js',
      args:  {},
    });
    console.log('Life OS: Next sync in', intervalMinutes, 'min');
  },

  onDestroy() {
    console.log('Life OS Sync: AppService stopped');
  },
});
