"""
LLMChatGPT - ChatGPT OAuth LLM provider.

Inherits LLMOpenai and injects ChatGPT OAuth credentials (access_token)
from ~/.alfred/credentials/chatgpt.json before each API call.
Uses standard OpenAI API endpoint (api.openai.com/v1).
"""

import json
import time
from pathlib import Path
from typing import Optional

import requests

from dolphin.core.common.enums import Messages
from dolphin.core.config.global_config import LLMInstanceConfig
from dolphin.core.context.context import Context
from dolphin.core.llm.llm import LLMOpenai
from dolphin.core.logging.logger import get_logger

logger = get_logger("llm.chatgpt")

_CREDENTIALS_PATH = Path.home() / ".alfred" / "credentials" / "chatgpt.json"
_TOKEN_URL = "https://auth.openai.com/oauth/token"
_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
_BASE_URL = "https://api.openai.com/v1"

# Module-level cache to avoid reading disk on every call
_cached_credential = None


def _load_credential():
    global _cached_credential
    if not _CREDENTIALS_PATH.exists():
        raise RuntimeError(
            "No ChatGPT credentials found. Run 'alfred chatgpt login' first."
        )
    data = json.loads(_CREDENTIALS_PATH.read_text())
    _cached_credential = data
    return data


def _refresh_token(refresh_token: str) -> dict:
    """Use refresh_token to get a new access_token."""
    resp = requests.post(
        _TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": _CLIENT_ID,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if not resp.ok:
        raise RuntimeError(
            f"ChatGPT token refresh failed ({resp.status_code}). "
            "Please re-run 'alfred chatgpt login'."
        )
    data = resp.json()

    expires_in = data.get("expires_in", 3600)
    cred = {
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token", refresh_token),
        "expires_at": int(time.time()) + expires_in,
    }

    # Persist refreshed credential
    _CREDENTIALS_PATH.write_text(json.dumps(cred, indent=2))

    global _cached_credential
    _cached_credential = cred
    return cred


def _resolve_credential() -> dict:
    """Return a valid ChatGPT credential, refreshing if expired."""
    global _cached_credential
    cred = _cached_credential
    if cred is None:
        cred = _load_credential()

    # Refresh if expired (with 5min buffer, matching openclaw)
    if time.time() >= cred["expires_at"] - 300:
        refresh = cred.get("refresh_token")
        if not refresh:
            raise RuntimeError(
                "ChatGPT token expired and no refresh_token. "
                "Run 'alfred chatgpt login' again."
            )
        cred = _refresh_token(refresh)

    return cred


class LLMChatGPT(LLMOpenai):
    def __init__(self, context: Context):
        super().__init__(context)

    async def chat(
        self,
        llm_instance_config: LLMInstanceConfig,
        messages: Messages,
        continous_content: Optional[str] = None,
        temperature: Optional[float] = None,
        no_cache: bool = False,
        **kwargs,
    ):
        # Inject ChatGPT OAuth credentials
        cred = _resolve_credential()
        llm_instance_config.set_api_key(cred["access_token"])
        llm_instance_config.cloud_config.api = _BASE_URL

        async for chunk in super().chat(
            llm_instance_config,
            messages,
            continous_content=continous_content,
            temperature=temperature,
            no_cache=no_cache,
            **kwargs,
        ):
            yield chunk
