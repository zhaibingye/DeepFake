from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class RegisterPayload(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=6, max_length=128)


class LoginPayload(RegisterPayload):
    pass


class SetupAdminPayload(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=6, max_length=128)


class AdminProfilePayload(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    current_password: str = Field(min_length=6, max_length=128)
    new_password: str = Field(min_length=6, max_length=128)


class RegistrationSettingsPayload(BaseModel):
    allow_registration: bool


class AdminUserCreatePayload(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=6, max_length=128)
    role: str = Field(default="user", pattern="^(admin|user)$")
    is_enabled: bool = True


class AdminUserUpdatePayload(BaseModel):
    is_enabled: bool


class AdminUserPasswordResetPayload(BaseModel):
    new_password: str = Field(min_length=6, max_length=128)


class ProviderBasePayload(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    api_format: str = Field(default="anthropic_messages", pattern="^(anthropic_messages|openai_chat|openai_responses|gemini)$")
    model_name: str = Field(min_length=1, max_length=128)
    supports_thinking: bool = True
    supports_vision: bool = False
    supports_tool_calling: bool = False
    thinking_effort: str = "high"
    max_context_window: int = 256000
    max_output_tokens: int = 32000
    is_enabled: bool = True


class ProviderPayload(ProviderBasePayload):
    api_url: str = Field(min_length=1, max_length=500)
    api_key: str = Field(min_length=1, max_length=500)


class ProviderUpdatePayload(ProviderBasePayload):
    api_url: str = Field(max_length=500)
    api_key: str = Field(max_length=500)


class SearchProviderSelection(str, Enum):
    exa = "exa"
    tavily = "tavily"


class ChatAttachment(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    media_type: str
    data: str


class SearchProviderConfigPayload(BaseModel):
    api_key: str = Field(max_length=500)
    is_enabled: bool


class ChatPayload(BaseModel):
    provider_id: int
    conversation_id: int | None = None
    text: str = Field(default="", max_length=20000)
    enable_thinking: bool = False
    enable_search: bool = False
    search_provider: SearchProviderSelection | None = None
    effort: str = "high"
    attachments: list[ChatAttachment] = Field(default_factory=list)


class ConversationTitlePayload(BaseModel):
    title: str = Field(min_length=1, max_length=80)
