# Search Tools And Stream UI Design

## Goal
Fix the current streamed chat failure, restore search as a deliberate tool layer, and make the chat UI clearly separate thinking, tool execution, and final answer output.

## Scope
This change covers four connected areas:

1. Make streamed chats succeed when the upstream provider finishes without emitting a literal `[DONE]`.
2. Add two fixed search tools, `exa_search` and `tavily_search`, behind a user-controlled chat toggle.
3. Restore minimal admin-side search configuration for `Tavily` only.
4. Update the chat UI so thinking and tool activity have explicit, compact, inspectable containers.

This change does not implement a generic MCP client, dynamic tool registration, automatic provider selection, or persistent storage for search results outside the message stream.

## Root Cause
The current backend stream path treats a round as successful only when it receives `[DONE]`. The active provider already streams valid `thinking_delta`, `text_delta`, and `usage` data, but the stream ends without that sentinel, so the backend emits an error and rolls the round back. The failure is therefore in completion detection, not in frontend rendering.

## Backend Design
Add a small stream normalization layer around provider streaming. It should accept provider-specific termination patterns and convert them into one internal rule: commit when the stream reached a valid natural completion, not only when `[DONE]` appears.

Keep the existing stream-only persistence rule:

- success commits user and assistant messages
- provider error, tool error, malformed completion, or user abort commits nothing

Add a fixed search-tool orchestration layer with exactly two tools:

- `exa_search`
- `tavily_search`

The chat request adds:

- `enable_search: boolean`
- `search_provider?: "exa" | "tavily"`

When search is enabled, the backend injects only the selected tool into the model request. `Exa` is always available without local credentials. `Tavily` requires an admin-configured API key. If the selected search provider is unavailable, the round fails immediately with a clear error.

## Search Configuration
Restore a narrow admin surface instead of generic MCP management.

Add:

- `GET /api/search-providers`
  Returns public availability for `exa` and `tavily`.
- `GET /api/admin/search-providers`
  Returns admin-visible status, including whether `tavily` is configured.
- `PUT /api/admin/search-providers/tavily`
  Updates the Tavily API key and enabled state.

No create/delete/search-provider registry is needed. The system always knows only these two providers.

## Stream Event Contract
The frontend should consume only normalized events:

- `conversation`
- `thinking_delta`
- `text_delta`
- `activity`
- `usage`
- `done`
- `error`

`activity` is the only tool-execution event. It carries:

- stable `id`
- `kind: "tool"`
- `label`
- `status: "running" | "done" | "error"`
- optional `detail`
- optional `duration_ms`
- optional `output`

This keeps the frontend independent from whether the backend used HTTP calls, provider-native tools, or another internal adapter.

## Frontend UX
Restore a compact chat-side search control:

- one `联网搜索` toggle
- when enabled, one source selector with `Exa` and `Tavily`

Message rendering becomes explicitly layered:

- thinking panel
  default open while only thinking is streaming; auto-collapse when the first `text_delta` arrives; if the user reopens it manually, do not force-close it again
- tool activity cards
  default collapsed; show live running state during search; expanded view shows the returned result text
- assistant answer bubble
  final answer only

The thinking panel must use its own bordered container so it is visually distinct from the final answer bubble.

## Error Handling
- Search enabled with no provider selected: frontend blocks send
- `Tavily` selected but not configured: backend returns a clear error, and the round is not saved
- Tool timeout or upstream search error: backend emits tool error activity and then terminates the round with `error`
- User abort during thinking, tool use, or answer generation: rollback the round completely

## Testing
Add backend tests for:

- stream commits on natural completion without `[DONE]`
- stream rolls back on malformed completion
- successful `exa_search` tool flow commits the round
- `tavily` selected without configured key fails and does not commit
- tool failure emits error and does not commit

Add frontend verification for:

- thinking opens by default while streaming
- thinking auto-collapses when answer text begins
- tool cards render collapsed by default
- failed rounds do not leave fabricated assistant messages in history

## Risks And Constraints
The main risk is mixing provider completion semantics and tool execution semantics inside one route. To keep the change controlled, all new logic should be isolated behind small helpers instead of adding more branching to `backend/app/main.py` and `frontend/src/App.tsx`.
