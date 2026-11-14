import { defineConfig } from '@playwright/test';
import {fileURLToPath} from 'node:url';
const port=Number(process.env.BENEFIT_TEST_PORT||4173);
if(!Number.isInteger(port)||port<1024||port>65535)throw new Error('Invalid test port');
export default defineConfig({
 testDir:'./tests/e2e',fullyParallel:false,workers:1,retries:0,
 use:{baseURL:`http://127.0.0.1:${port}/benefit-monitor/`,browserName:'chromium',...(process.env.BENEFIT_TEST_BROWSER_CHANNEL?{channel:process.env.BENEFIT_TEST_BROWSER_CHANNEL}:{}),trace:'off'},
 reporter:[['list'],['html',{open:'never',outputFolder:fileURLToPath(new URL('./playwright-report',import.meta.url))}]],
 webServer:{command:`npm run preview -- --port ${port} --strictPort`,url:`http://127.0.0.1:${port}/benefit-monitor/`,reuseExistingServer:false},
});
