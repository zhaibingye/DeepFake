# Backend Streamline And Hardening Design

## Goal
Refactor the backend around a stream-only chat flow while fixing the current high-priority correctness and security issues. The system must remove hard-coded default admin creation, eliminate redundant non-stream chat code, and make persistence rules easier to reason about.

## Scope
This change covers five tightly related items:

1. Remove all non-stream chat code paths from both backend and frontend chat execution.
2. Replace default admin auto-creation with explicit first-run admin bootstrap endpoints.
3. Fix the registration response bug that currently returns a server error after successful insert.
4. Enforce a single rule for “must keep at least one enabled admin”.
5. Make unfinished streamed chats non-persistent: if a stream errors or is aborted, that round must not be saved.

This change allows small structural cleanup, but does not include a full product redesign, account recovery flow, or new setup UI.

## Architecture
The current `backend/app/main.py` is carrying database setup, auth, admin bootstrap, admin rules, provider orchestration, and chat persistence in one file. The refactor will split only the parts needed for these fixes:

- `backend/app/main.py`
  App setup, middleware, and route wiring only.
- `backend/app/db.py`
  Database paths, connections, and schema initialization.
- `backend/app/auth.py`
  Password hashing, sessions, token parsing, current-user/admin guards, and shared user-loading helpers.
- `backend/app/admin_setup.py`
  First-run admin bootstrap state and creation logic.
- `backend/app/chat_service.py`
  Stream-only chat preparation, provider invocation, and final commit rules.

Other existing logic may stay where it is unless it directly blocks the new boundaries.

## Chat Flow Decision
Streaming becomes the only supported chat execution path. The backend `POST /api/chat` endpoint is removed. The frontend should also remove any remaining `sendMessage` non-stream path and keep only `streamMessage`.

Persistence rules change as follows:

- A successful completed stream saves both the user message and the assistant reply.
- A failed or aborted stream saves neither side of that round.
- In-progress streamed output may still appear in the current page state, but it must disappear after refresh because it was never committed to history.

This keeps conversation history semantically clean: only completed rounds are part of durable state.

## Admin Bootstrap
Startup keeps schema initialization but must not create a default admin.

Add two public setup endpoints:

- `GET /api/setup/status`
  Returns `{ "needs_admin_setup": boolean }`.
- `POST /api/setup/admin`
  Creates the first admin only when no admin exists, then returns `{ token, user }`.

If any admin already exists, including a disabled one, bootstrap is considered complete and the endpoint returns `409`.

## Admin Safety Rule
The system should have one authoritative rule: at least one enabled admin must remain. Both “disable admin” and “delete admin” operations must use the same check. This removes the current mismatch where one path counts enabled admins and the other counts total admins.

## Registration Fix
User creation and user serialization must go through shared helpers so registration, login, and admin bootstrap all return a full user payload with the fields expected by the frontend. This removes the current partial-row bug.

## Task Ordering
Implementation order:

0. Remove backend and frontend non-stream chat code and dead compatibility branches.
1. Extract `db.py` and `auth.py`.
2. Add `admin_setup.py` and remove default admin seeding.
3. Centralize the enabled-admin safety rule.
4. Move stream-only chat commit logic into `chat_service.py`.
5. Add/expand backend tests and update `README.md`.

## Testing
Add focused backend tests for:

- first-run admin bootstrap
- successful registration response shape
- preventing deletion or disablement of the last enabled admin
- commit-on-success and no-commit-on-abort/error for streamed chat rounds

Repository verification remains:

- `cd frontend && npm run lint`
- `cd frontend && npm run build`
- `cd backend && python -m compileall app`

## Risks And Constraints
Because the repository has very limited automated coverage today, this refactor must stay narrow and validation-heavy. The goal is not “perfect layering”, but a cleaner and safer backend with fewer contradictory code paths.
