# Admin Bootstrap Design

## Goal
Remove the hard-coded default admin account and replace it with an explicit first-run bootstrap flow. The system must no longer create `admin / admin123` during startup.

## Scope
This change only covers first-time administrator creation for an uninitialized instance. It does not add account recovery, password reset outside the existing admin flows, or a new frontend setup screen.

## Backend Changes
The backend keeps database initialization through `ensure_tables()` but removes automatic admin creation from startup.

Add two public setup endpoints in `backend/app/main.py`:

- `GET /api/setup/status`
  Returns `{ "needs_admin_setup": boolean }`.
  `true` means there is currently no user with `role = 'admin'`.

- `POST /api/setup/admin`
  Accepts `username` and `password`.
  Behavior:
  1. Normalize and validate the input using the same rules as existing auth flows.
  2. Check whether any admin already exists.
  3. If an admin exists, reject the request with `409`.
  4. If no admin exists, create the first admin user.
  5. Create a session with the existing session logic.
  6. Return `{ token, user }`.

## Security Model
This design removes the deterministic default credential risk, but it intentionally does not protect the setup endpoint with a separate bootstrap token. As a result, the first reachable caller on an uninitialized instance can claim the admin account.

This is acceptable only for local or trusted-network usage. It is not safe for public internet deployment before bootstrap is complete.

## Error Handling
- Invalid input: `400`
- Username already exists: `400`
- Admin already initialized: `409`
- Success: `200`

The setup endpoint should treat any existing admin, enabled or disabled, as initialized state and refuse bootstrap. Recovery for a broken admin state remains out of scope for this change.

## Frontend And Docs
Do not add a setup UI in this iteration. Keep the existing login and registration screens unchanged.

Update `README.md` to replace the default admin section with explicit initialization instructions and note that the setup endpoint is intended for local or trusted-network use.

## Testing
Verify:

- startup no longer creates a default admin
- `GET /api/setup/status` returns `true` on a fresh database
- first `POST /api/setup/admin` succeeds and returns a token
- second `POST /api/setup/admin` returns `409`
- normal login still works for the bootstrapped admin
- `python -m compileall app` still passes
