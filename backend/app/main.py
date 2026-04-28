from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.bootstrap import ensure_tables
from app.config import get_allowed_origins
from app.routers import admin, auth, chat, conversations, public


app = FastAPI(title="Anthropic Chat Console")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(public.router)
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(conversations.router)
app.include_router(chat.router)


@app.on_event("startup")
def on_startup() -> None:
    ensure_tables()
