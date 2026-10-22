# Musubi Pages

## Run locally

```sh
uv sync
cd web && npm ci && npm run build && cd ..
uv run pages web          # http://127.0.0.1:8000, serves the built app and the /api JSON API
```

While working on the app, run `npm run dev` in `web/` instead of building: Vite serves it with hot reload and proxies `/api` and `/files` to the server on port 8000.

Tests: `uv run pytest`. Type check the app: `cd web && npx tsc -b`.
