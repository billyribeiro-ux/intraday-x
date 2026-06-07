import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

// Dev proxy to the FastAPI backend (Phase 5). With this, the browser only ever
// talks to the Vite origin, so there's no CORS config needed in dev and the
// websocket upgrade is proxied too.
export default defineConfig({
	plugins: [sveltekit()],
	server: {
		proxy: {
			'/api': { target: 'http://localhost:8000', changeOrigin: true },
			'/ws': { target: 'ws://localhost:8000', ws: true, changeOrigin: true }
		}
	}
});
