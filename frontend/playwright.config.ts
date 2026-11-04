import { defineConfig } from '@playwright/test';
export default defineConfig({
 testDir:'./tests/e2e',fullyParallel:false,workers:1,retries:0,
 use:{baseURL:'http://127.0.0.1:4173/benefit-monitor/',browserName:'chromium',trace:'off'},
 reporter:[['list'],['html',{open:'never'}]],
 webServer:{command:'npm run preview -- --port 4173 --strictPort',url:'http://127.0.0.1:4173/benefit-monitor/',reuseExistingServer:false},
});
