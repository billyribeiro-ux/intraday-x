import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

// Tauri expects Vite on a fixed port (matches `devUrl` in tauri.conf.json) and
// quiet output. In dev (browser OR `tauri dev`) the webview loads from this Vite
// server, so the proxy below forwards /api + /ws to the FastAPI backend on :8000
// — no CORS needed. In the bundled .app there is no proxy; the frontend resolves
// the engine's dynamic port via src/lib/api/backend.ts instead.
export default defineConfig({
	plugins: [sveltekit()],
	clearScreen: false,
	server: {
		port: 5173,
		strictPort: true,
		proxy: {
			'/api': { target: 'http://localhost:8000', changeOrigin: true },
			'/ws': { target: 'ws://localhost:8000', ws: true, changeOrigin: true }
		}
	}
});
