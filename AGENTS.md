# Repository Guidelines

## Project Structure & Module Organization
This repository is split into `frontend/` and `backend/`. The React + TypeScript client lives in `frontend/src`, with static assets in `frontend/public` and build output in `frontend/dist`. Shared frontend API/types are in `frontend/src/api.ts` and `frontend/src/types.ts`. The FastAPI server lives in `backend/app`, with most backend logic currently centered in `backend/app/main.py`. Local runtime data is stored in `backend/data/app.db`; treat that database as machine-local state, not source.

## Build, Test, and Development Commands
Run the frontend and backend in separate terminals.

- `cd frontend && npm install`: install frontend dependencies.
- `cd frontend && npm run dev -- --host 127.0.0.1 --port 5173`: start the Vite dev server.
- `cd frontend && npm run lint`: run ESLint checks for the TypeScript codebase.
- `cd frontend && npm run build`: type-check and build the production frontend.
- `cd backend && python -m pip install -r requirements.txt`: install backend dependencies.
- `cd backend && python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`: start the FastAPI API locally.
- `cd backend && python -m compileall app`: perform a quick Python syntax check.

## Coding Style & Naming Conventions
Match the surrounding code instead of introducing a new style. Use 2-space indentation in `*.ts` and `*.tsx`, and 4 spaces in Python. Keep React components in PascalCase, hooks and utilities in camelCase, and Python functions in snake_case. Reuse shared definitions in `frontend/src/types.ts` and API helpers in `frontend/src/api.ts`. Frontend linting is handled by ESLint; there is no separate formatter configured.

## Testing Guidelines
There is no dedicated automated test suite yet. Before submitting changes, run `npm run lint`, `npm run build`, and `python -m compileall app`. Manually verify affected flows in the browser, especially login, chat streaming, provider management, and admin user actions. If you add tests, prefer names like `*.test.ts` or `*.test.tsx` near the feature they cover.

## Commit & Pull Request Guidelines
Recent commits use short, imperative subjects such as `Update README.md` and `Initial project setup`. Keep commit messages focused and descriptive, ideally one logical change per commit. Pull requests should include a short summary, linked issues when relevant, manual verification notes, and screenshots for UI changes.

## Security & Configuration Tips
Do not commit `backend/data/app.db`, generated logs, or real API keys. Change any default admin credentials before deployment. If the backend URL changes, update the frontend API base in `frontend/src/api.ts`.
