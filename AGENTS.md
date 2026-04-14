# AGENTS.md

## Structure
- This repo has two standalone apps: `frontend/` (Vite + React + TypeScript) and `backend/` (FastAPI in a single `app/main.py`). There is no monorepo tool, task runner, or CI config.
- Backend state is local SQLite at `backend/data/app.db`. The file and schema are created on startup in `backend/app/main.py`.
- The default admin user is auto-created on backend startup if no admin exists: `admin` / `admin123`.

## Run And Verify
- Frontend dev server: `npm run dev` in `frontend/`. Verified host/port is `http://127.0.0.1:5173`.
- Frontend checks: `npm run lint` and `npm run build` in `frontend/`.
- Backend lightweight check: `python -m compileall app` in `backend/`.
- There is no test suite in the repo right now.

## Known Verification State
- `npm run lint` currently passes with 1 existing warning in `frontend/src/App.tsx`: `react-hooks/exhaustive-deps` for `bootstrap`. Do not assume lint is clean before your change.
- `npm run build` succeeds, but Vite warns that the main JS chunk is larger than 500 kB.

## Wiring That Agents Commonly Miss
- Frontend API base is hardcoded in `frontend/src/api.ts` as `http://127.0.0.1:8000/api`. There is no Vite proxy or env-based API URL. If backend moves, this file must change.
- Backend CORS only allows `http://localhost:5173` and `http://127.0.0.1:5173`.
- Provider `api_url` should be the Anthropic-compatible base URL; backend appends `/messages` automatically unless it is already present.
- Streaming chat uses `POST /api/chat/stream` with `application/x-ndjson`. Frontend parses newline-delimited JSON chunks in `frontend/src/api.ts`; this is not SSE.

## Code Layout
- `backend/app/main.py` contains almost all backend behavior: schema creation, auth, admin/provider CRUD, conversation CRUD, Anthropic request building, and streaming.
- `frontend/src/App.tsx` contains most UI state and flows: auth, admin screens, provider management, conversation management, and chat streaming.
- Markdown and LaTeX rendering live in `frontend/src/components/MarkdownView.tsx` using `react-markdown` + `remark-math` + `rehype-katex`.

## Repo-Specific Gotchas
- Editing a provider currently requires sending a non-empty `api_key`. `ProviderPayload` requires it, and the edit form intentionally resets `api_key` to `''` before submit.
- Conversation messages persist both plain text and JSON content blocks; image uploads are stored as base64-backed Anthropic content blocks.
- When working on chat UI, preserve the distinction between the currently selected provider and the provider attached to the active conversation. The app already had a bug where historical assistant labels changed when the dropdown changed.
