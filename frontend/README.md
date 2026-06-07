# Frontend — Local Development

The Vite dev server proxies `/api/*` and `/review/*` to the local Flask backend.

## Startup

**Terminal 1 — Backend:**

```bash
cd ..
python api.py            # requires .venv: .venv/bin/python api.py
```

**Terminal 2 — Frontend:**

```bash
cd frontend
npm install
npm run dev              # Vite on http://localhost:5173
```

Open http://localhost:5173 in your browser.

## Troubleshooting

If Vite shows:

```
[vite] http proxy error: /api/dashboard/summary
AggregateError [ECONNREFUSED]
```

The Flask backend is not running. Check port 5001:

```bash
lsof -iTCP:5001 -sTCP:LISTEN
```

If nothing is listening, start the backend first (see above).

> The current `vite.config.ts` uses `http://127.0.0.1:5001` (not `localhost`) to avoid macOS/Node IPv4/IPv6 resolution issues that cause `AggregateError`.
