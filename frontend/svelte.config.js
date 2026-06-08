import adapter from '@sveltejs/adapter-static';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	compilerOptions: {
		// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
		runes: ({ filename }) => (filename.split(/[/\\]/).includes('node_modules') ? undefined : true)
	},
	kit: {
		// Tauri serves a static, client-rendered SPA (no Node server). `fallback`
		// makes every route boot from index.html and hydrate client-side, which
		// matches our client-only data loading (ssr = false in +layout.ts).
		adapter: adapter({ fallback: 'index.html' })
	}
};

export default config;
