/**
 * Life OS Sync — Side Service (runs on phone via Zepp App)
 *
 * ZML автоматически проксирует httpRequest через BLE.
 * Кастомная логика не нужна — BaseSideService делает всё сам.
 */

import { BaseSideService } from '@zeppos/zml/base-side';

AppSideService(
  BaseSideService({
    onInit() {
      console.log('Life OS Side Service: started');
    },

    onDestroy() {
      console.log('Life OS Side Service: stopped');
    },
  })
);
