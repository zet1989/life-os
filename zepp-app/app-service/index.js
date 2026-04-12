/**
 * Life OS Sync — Background App Service (Zepp OS)
 *
 * Периодически собирает метрики здоровья с датчиков и сохраняет в LocalStorage.
 * Данные отправляются на сервер через Side Service при открытии приложения.
 */

import { HeartRate, Step, Calorie, Distance, Sleep, BloodOxygen, Stress } from '@zos/sensor';
import { LocalStorage } from '@zos/storage';
import { set as setAlarm } from '@zos/alarm';
import { INTERVAL_MINUTES } from '../config';

const localStorage = new LocalStorage();

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

AppService({
  onInit() {
    const interval = parseInt(INTERVAL_MINUTES || '15');

    const data = collectHealthData();
    const keys = Object.keys(data);

    if (keys.length > 0) {
      localStorage.setItem('pending_data', JSON.stringify(data));
      localStorage.setItem('pending_keys', keys.join(','));
      console.log('Life OS Service: collected', keys.join(', '));
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
