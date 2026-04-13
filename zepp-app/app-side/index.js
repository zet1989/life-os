/**
 * Life OS Sync — Side Service (runs on phone via Zepp App)
 *
 * Принимает данные от устройства и часов:
 * 1. ZML автоматически проксирует httpRequest из BasePage (Page) через BLE.
 * 2. onRequest обрабатывает push_health_data из AppService (фоновая отправка).
 */

import { BaseSideService } from '@zeppos/zml/base-side';

AppSideService(
  BaseSideService({
    onInit() {
      console.log('Life OS Side Service: started');
    },

    onRequest(req, res) {
      if (req.method === 'push_health_data') {
        const { data, api_key, server_url } = req.params || {};
        if (!data || !api_key || !server_url) {
          console.log('Life OS Side: missing params');
          res('missing params');
          return;
        }

        console.log('Life OS Side: pushing data to server...');
        fetch({
          url: server_url,
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + api_key,
          },
          body: JSON.stringify(data),
        })
          .then((result) => {
            console.log('Life OS Side: push OK, status', result.status);
            res(null, { status: 'ok' });
          })
          .catch((err) => {
            console.log('Life OS Side: push error', String(err));
            res(String(err));
          });
      }
    },

    onDestroy() {
      console.log('Life OS Side Service: stopped');
    },
  })
);
