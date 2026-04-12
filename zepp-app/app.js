import { BaseApp } from '@zeppos/zml/base-app';

App(
  BaseApp({
    globalData: {},

    onCreate() {
      console.log('Life OS Sync: App started');
    },

    onDestroy() {
      console.log('Life OS Sync: App destroyed');
    },
  })
);
