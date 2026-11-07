import { createApp } from 'vue';
import AdminApp from './AdminApp.vue';
const root = document.getElementById('admin')!;
// Clickjacking guard: never start the token UI inside another page's frame.
if (window.top !== window.self) root.textContent = '관리 화면은 다른 페이지 안에서는 열 수 없습니다. 주소창에서 직접 여세요.';
else createApp(AdminApp).mount(root);
