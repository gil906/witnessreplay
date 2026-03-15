"""
Gemini API account manager with prioritized key rotation and passive quota tracking.

This module keeps Primary → Secondary → Tertiary ordering, tracks per-account /
per-model cooldowns, parses rate-limit headers from functional responses, and
exposes a drop-in rotating client wrapper for the SDK surfaces this app uses.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple
from zoneinfo import ZoneInfo

from google import genai

from app.config import settings

logger = logging.getLogger(__name__)

PACIFIC_TZ = ZoneInfo("America/Los_Angeles")

_HEADER_ALIASES = {
    "remaining_requests": (
        "x-ratelimit-remaining-requests",
        "x-goog-ratelimit-remaining-requests",
        "x-ratelimit-remaining-request",
        "x-ratelimit-remaining-rpm",
    ),
    "remaining_tokens": (
        "x-ratelimit-remaining-tokens",
        "x-goog-ratelimit-remaining-tokens",
        "x-ratelimit-remaining-tpm",
    ),
    "remaining_daily_requests": (
        "x-ratelimit-remaining-daily-requests",
        "x-goog-ratelimit-remaining-daily-requests",
        "x-ratelimit-remaining-rpd",
        "x-ratelimit-remaining-day-requests",
    ),
    "limit_requests": (
        "x-ratelimit-limit-requests",
        "x-goog-ratelimit-limit-requests",
        "x-ratelimit-limit-rpm",
    ),
    "limit_tokens": (
        "x-ratelimit-limit-tokens",
        "x-goog-ratelimit-limit-tokens",
        "x-ratelimit-limit-tpm",
    ),
    "limit_daily_requests": (
        "x-ratelimit-limit-daily-requests",
        "x-goog-ratelimit-limit-daily-requests",
        "x-ratelimit-limit-rpd",
        "x-ratelimit-limit-day-requests",
    ),
    "retry_after": (
        "retry-after",
        "x-ratelimit-retry-after",
        "x-goog-ratelimit-retry-after",
    ),
}

_MODEL_QUOTA_ALIASES = {
    "gemini-flash-latest": "gemini-2.5-flash",
    "gemini-2.5-flash-exp-native-audio-thinking": "gemini-2.5-flash-native-audio-latest",
    "imagen-4-fast-generate": "imagen-4.0-fast-generate-001",
    "imagen-4-generate": "imagen-4.0-generate-001",
    "imagen-4-ultra-generate": "imagen-4.0-ultra-generate-001",
}


@dataclass(frozen=True)
class GeminiAccountConfig:
    account_id: str
    label: str
    priority: int
    api_key: str
    email: str = ""
    project_id: str = ""


@dataclass(frozen=True)
class GeminiAccountSelection:
    account_id: str
    label: str
    priority: int
    api_key: str


class RotatingModels:
    """SDK-compatible models surface with account failover."""

    def __init__(self, manager: "APIKeyManager"):
        self._manager = manager

    def generate_content(self, *, model: str, contents: Any, config: Any = None) -> Any:
        last_error: Optional[Exception] = None
        attempted = False
        for account in self._manager.get_account_candidates(model):
            attempted = True
            client = self._manager.get_raw_client(account.account_id)
            self._manager.note_selection(account.account_id, model)
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=config,
                )
                self._manager.record_success(account.account_id, model, response=response)
                return response
            except Exception as exc:
                last_error = exc
                self._manager.record_failure(account.account_id, model, exc)
                if self._manager.should_failover(exc):
                    continue
                raise

        if last_error:
            raise last_error
        if not attempted:
            raise RuntimeError(f"No Gemini accounts are configured for model '{model}'")
        raise RuntimeError(f"No Gemini accounts are currently available for model '{model}'")

    def embed_content(self, *, model: str, contents: Any, config: Any = None) -> Any:
        last_error: Optional[Exception] = None
        attempted = False
        for account in self._manager.get_account_candidates(model):
            attempted = True
            client = self._manager.get_raw_client(account.account_id)
            self._manager.note_selection(account.account_id, model)
            try:
                response = client.models.embed_content(
                    model=model,
                    contents=contents,
                    config=config,
                )
                self._manager.record_success(account.account_id, model, response=response)
                return response
            except Exception as exc:
                last_error = exc
                self._manager.record_failure(account.account_id, model, exc)
                if self._manager.should_failover(exc):
                    continue
                raise

        if last_error:
            raise last_error
        if not attempted:
            raise RuntimeError(f"No Gemini accounts are configured for model '{model}'")
        raise RuntimeError(f"No Gemini accounts are currently available for model '{model}'")

    def list(self, *args: Any, **kwargs: Any) -> Any:
        client = self._manager.get_raw_client()
        return client.models.list(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._manager.get_raw_client().models, name)


class RotatingChatSession:
    """Chat wrapper that can recreate the underlying SDK chat on another account."""

    def __init__(self, manager: "APIKeyManager", model: str, config: Any = None, history: Optional[List[Any]] = None):
        self._manager = manager
        self._model = model
        self.model = model
        self._config = config
        self._history = list(history or [])
        self._chat = None
        self._account_id: Optional[str] = None

    def _current_history(self) -> List[Any]:
        if self._chat is not None:
            curated = getattr(self._chat, "_curated_history", None)
            if curated is not None:
                return list(curated)
        return list(self._history)

    def _ensure_chat(self, account_id: str):
        if self._chat is not None and self._account_id == account_id:
            return
        client = self._manager.get_raw_client(account_id)
        self._chat = client.chats.create(
            model=self._model,
            config=self._config,
            history=self._current_history(),
        )
        self._account_id = account_id

    def send_message(self, message: Any, config: Any = None) -> Any:
        last_error: Optional[Exception] = None
        attempted = False
        for account in self._manager.get_account_candidates(self._model):
            attempted = True
            self._manager.note_selection(account.account_id, self._model)
            self._ensure_chat(account.account_id)
            try:
                response = self._chat.send_message(message, config=config)
                self._history = self._current_history()
                self._manager.record_success(account.account_id, self._model, response=response)
                return response
            except Exception as exc:
                last_error = exc
                self._manager.record_failure(account.account_id, self._model, exc)
                self._chat = None
                self._account_id = None
                if self._manager.should_failover(exc):
                    continue
                raise

        if last_error:
            raise last_error
        if not attempted:
            raise RuntimeError(f"No Gemini accounts are configured for model '{self._model}'")
        raise RuntimeError(f"No Gemini accounts are currently available for model '{self._model}'")

    def send_message_stream(self, message: Any, config: Any = None) -> Iterator[Any]:
        last_error: Optional[Exception] = None
        attempted = False
        for account in self._manager.get_account_candidates(self._model):
            attempted = True
            self._manager.note_selection(account.account_id, self._model)
            self._ensure_chat(account.account_id)
            yielded_any = False
            try:
                stream = self._chat.send_message_stream(message, config=config)
                for chunk in stream:
                    yielded_any = True
                    yield chunk
                self._history = self._current_history()
                self._manager.record_success(account.account_id, self._model)
                return
            except Exception as exc:
                last_error = exc
                self._manager.record_failure(account.account_id, self._model, exc)
                self._chat = None
                self._account_id = None
                if not yielded_any and self._manager.should_failover(exc):
                    continue
                raise

        if last_error:
            raise last_error
        if not attempted:
            raise RuntimeError(f"No Gemini accounts are configured for model '{self._model}'")
        raise RuntimeError(f"No Gemini accounts are currently available for model '{self._model}'")


class RotatingChats:
    def __init__(self, manager: "APIKeyManager"):
        self._manager = manager

    def create(self, *, model: str, config: Any = None, history: Optional[List[Any]] = None) -> RotatingChatSession:
        return RotatingChatSession(self._manager, model=model, config=config, history=history)


class RotatingLiveConnectionContext:
    """Async context manager that selects the best available account for Live API."""

    def __init__(self, manager: "APIKeyManager", model: str, config: Any = None):
        self._manager = manager
        self._model = model
        self._config = config
        self._context = None
        self._session = None
        self._account_id: Optional[str] = None

    async def __aenter__(self):
        last_error: Optional[Exception] = None
        attempted = False
        for account in self._manager.get_account_candidates(self._model):
            attempted = True
            client = self._manager.get_raw_client(account.account_id)
            self._manager.note_selection(account.account_id, self._model)
            try:
                self._context = client.aio.live.connect(model=self._model, config=self._config)
                self._session = await self._context.__aenter__()
                self._account_id = account.account_id
                return self._session
            except Exception as exc:
                last_error = exc
                self._manager.record_failure(account.account_id, self._model, exc)
                self._context = None
                self._session = None
                self._account_id = None
                if self._manager.should_failover(exc):
                    continue
                raise

        if last_error:
            raise last_error
        if not attempted:
            raise RuntimeError(f"No Gemini accounts are configured for model '{self._model}'")
        raise RuntimeError(f"No Gemini accounts are currently available for model '{self._model}'")

    async def __aexit__(self, exc_type, exc, tb):
        if self._account_id:
            if exc is None:
                self._manager.record_success(self._account_id, self._model)
            elif exc_type is not None:
                self._manager.record_failure(self._account_id, self._model, exc or RuntimeError(str(exc_type)))
        if self._context is None:
            return False
        return await self._context.__aexit__(exc_type, exc, tb)


class RotatingAsyncLive:
    def __init__(self, manager: "APIKeyManager"):
        self._manager = manager

    def connect(self, *, model: str, config: Any = None) -> RotatingLiveConnectionContext:
        return RotatingLiveConnectionContext(self._manager, model=model, config=config)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._manager.get_raw_client().aio.live, name)


class RotatingAio:
    def __init__(self, manager: "APIKeyManager"):
        self.live = RotatingAsyncLive(manager)


class RotatingGenAIClient:
    """Drop-in client wrapper that routes requests through APIKeyManager."""

    def __init__(self, manager: "APIKeyManager"):
        self._manager = manager
        self.models = RotatingModels(manager)
        self.chats = RotatingChats(manager)
        self.aio = RotatingAio(manager)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._manager.get_raw_client(), name)


class APIKeyManager:
    """Prioritized multi-account Gemini key router with persistent cooldown state."""

    def __init__(self, accounts: List[GeminiAccountConfig]):
        self.accounts = sorted(accounts, key=lambda item: item.priority)
        self._account_lookup = {account.account_id: account for account in self.accounts}
        self._lock = threading.RLock()
        self._clients: Dict[str, genai.Client] = {}
        self._rotating_client = RotatingGenAIClient(self)
        self._state_path = _state_path()
        self._last_reset_date = ""
        self._rotation_count = 0
        self._last_rotation_at: Optional[datetime] = None
        self._account_state: Dict[str, Dict[str, Any]] = {
            account.account_id: {
                "healthy": True,
                "auth_failed": False,
                "cooldown_until": None,
                "error_count": 0,
                "last_error": None,
                "last_http_status": None,
                "last_used_at": None,
            }
            for account in self.accounts
        }
        self._model_state: Dict[str, Dict[str, Any]] = {}
        self._load_state()
        self._reset_if_new_day()

        if not self.accounts:
            logger.warning("APIKeyManager initialized with no Gemini accounts")
        else:
            logger.info("APIKeyManager initialized with %s Gemini account(s)", len(self.accounts))

    @property
    def total_accounts(self) -> int:
        return len(self.accounts)

    @property
    def rotation_count(self) -> int:
        return self._rotation_count

    def is_enabled(self) -> bool:
        return bool(self.accounts)

    def has_multi_account_rotation(self) -> bool:
        return len(self.accounts) > 1

    def get_rotating_client(self) -> RotatingGenAIClient:
        return self._rotating_client

    def get_default_selection(self, model_name: Optional[str] = None) -> Optional[GeminiAccountSelection]:
        account = self.get_preferred_account(model_name)
        if not account:
            return None
        return GeminiAccountSelection(
            account_id=account.account_id,
            label=account.label,
            priority=account.priority,
            api_key=account.api_key,
        )

    def get_preferred_account(self, model_name: Optional[str] = None) -> Optional[GeminiAccountConfig]:
        candidates = self.get_account_candidates(model_name)
        return candidates[0] if candidates else (self.accounts[0] if self.accounts else None)

    def get_account_candidates(self, model_name: Optional[str] = None) -> List[GeminiAccountConfig]:
        with self._lock:
            self._reset_if_new_day()
            available: List[GeminiAccountConfig] = []
            constrained: List[GeminiAccountConfig] = []
            for account in self.accounts:
                if self._is_account_available(account.account_id, model_name):
                    available.append(account)
                else:
                    constrained.append(account)
            return available + constrained

    def has_available_account(self, model_name: Optional[str] = None) -> bool:
        with self._lock:
            self._reset_if_new_day()
            return any(self._is_account_available(account.account_id, model_name) for account in self.accounts)

    def get_available_account_count(self, model_name: Optional[str] = None) -> int:
        with self._lock:
            self._reset_if_new_day()
            return sum(1 for account in self.accounts if self._is_account_available(account.account_id, model_name))

    def get_capacity_multiplier(self, model_name: Optional[str] = None) -> int:
        with self._lock:
            healthy = sum(1 for account in self.accounts if not self._account_state[account.account_id].get("auth_failed"))
            return max(1, healthy)

    def get_model_status(self, model_name: str) -> Dict[str, Any]:
        with self._lock:
            self._reset_if_new_day()
            accounts = []
            for account in self.accounts:
                state = self._get_model_state(account.account_id, model_name)
                accounts.append({
                    "account_id": account.account_id,
                    "label": account.label,
                    "available": self._is_account_available(account.account_id, model_name),
                    "cooldown_expires": _iso_or_none(state.get("cooldown_until")),
                    "remaining_requests": state.get("remaining_requests"),
                    "remaining_tokens": state.get("remaining_tokens"),
                    "remaining_daily_requests": state.get("remaining_daily_requests"),
                    "daily_requests": state.get("daily_requests", 0),
                    "daily_tokens": state.get("daily_tokens", 0),
                    "minute_requests": len(state.get("minute_requests", [])),
                    "last_http_status": state.get("last_http_status"),
                })
            return {
                "model": model_name,
                "available_accounts": sum(1 for item in accounts if item["available"]),
                "accounts": accounts,
            }

    def get_raw_client(self, account_id: Optional[str] = None) -> genai.Client:
        with self._lock:
            if not self.accounts:
                raise RuntimeError("No Gemini accounts are configured")
            account = self._account_lookup.get(account_id) if account_id else self.accounts[0]
            if account is None:
                raise RuntimeError(f"Unknown Gemini account '{account_id}'")
            if account.account_id not in self._clients:
                self._clients[account.account_id] = genai.Client(api_key=account.api_key)
            return self._clients[account.account_id]

    def get_key(self, model_name: Optional[str] = None) -> Optional[str]:
        account = self.get_preferred_account(model_name)
        return account.api_key if account else None

    def note_selection(self, account_id: str, model_name: Optional[str] = None):
        with self._lock:
            state = self._account_state.get(account_id)
            if state is None:
                return
            state["last_used_at"] = datetime.now(timezone.utc)
            account = self._account_lookup.get(account_id)
            if account and account.priority > 1:
                self._rotation_count += 1
                self._last_rotation_at = datetime.now(timezone.utc)
            self._save_state()

    def record_success(self, account_id: str, model_name: Optional[str], *, response: Any = None):
        with self._lock:
            self._reset_if_new_day()
            account_state = self._account_state.get(account_id)
            if account_state is None:
                return
            account_state["healthy"] = True
            account_state["auth_failed"] = False
            account_state["last_error"] = None
            account_state["last_used_at"] = datetime.now(timezone.utc)
            if account_state.get("cooldown_until") and account_state["cooldown_until"] <= datetime.now(timezone.utc):
                account_state["cooldown_until"] = None

            if model_name:
                state = self._get_model_state(account_id, model_name)
                state["minute_requests"].append(datetime.now(timezone.utc))
                state["daily_requests"] = int(state.get("daily_requests", 0)) + 1
                state["daily_tokens"] = int(state.get("daily_tokens", 0)) + _extract_tokens_used(response)
                state["last_error"] = None
                state["last_updated_at"] = datetime.now(timezone.utc)
                self._prune_minute_window(state)
                headers = _extract_headers_from_response(response)
                if headers:
                    self._apply_headers(account_id, model_name, headers, status_code=200)
                elif state.get("cooldown_until") and state["cooldown_until"] <= datetime.now(timezone.utc):
                    state["cooldown_until"] = None
            self._save_state()

    def record_failure(self, account_id: str, model_name: Optional[str], error: Exception):
        with self._lock:
            self._reset_if_new_day()
            account_state = self._account_state.get(account_id)
            if account_state is None:
                return

            message = str(error)
            status_code = _extract_status_code(error)
            account_state["error_count"] = int(account_state.get("error_count", 0)) + 1
            account_state["last_error"] = message[:500]
            account_state["last_http_status"] = status_code
            response_headers = _extract_headers_from_error(error)

            if model_name and response_headers:
                self._apply_headers(account_id, model_name, response_headers, status_code=status_code)

            lowered = message.lower()
            if status_code == 401 or (
                status_code == 403 and any(token in lowered for token in ("api key", "permission", "forbidden", "access denied", "not enabled"))
            ):
                account_state["healthy"] = False
                account_state["auth_failed"] = True
                account_state["cooldown_until"] = None
                logger.error("Gemini account %s marked auth-failed after %s", account_id, status_code)
                self._save_state()
                return

            if model_name and (
                status_code == 429
                or any(token in lowered for token in ("quota", "rate limit", "resource_exhausted", "resource has been exhausted", "too many requests"))
            ):
                self._mark_model_cooldown(
                    account_id,
                    model_name,
                    seconds=self._cooldown_seconds_for_error(model_name, lowered, response_headers),
                    reason=message,
                    status_code=status_code,
                )
                self._save_state()
                return

            if status_code and 500 <= status_code < 600:
                cooldown_seconds = self._parse_retry_after_seconds(response_headers) or 30
                account_state["cooldown_until"] = datetime.now(timezone.utc) + timedelta(seconds=cooldown_seconds)
                logger.warning("Gemini account %s cooling down globally for %ss after upstream error %s", account_id, cooldown_seconds, status_code)

            self._save_state()

    def should_failover(self, error: Exception) -> bool:
        status_code = _extract_status_code(error)
        if status_code in {401, 403, 429}:
            return True
        message = str(error).lower()
        return any(token in message for token in (
            "quota",
            "rate limit",
            "resource_exhausted",
            "resource has been exhausted",
            "too many requests",
            "api key",
            "forbidden",
            "permission",
        ))

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            self._reset_if_new_day()
            now = datetime.now(timezone.utc)
            accounts_payload = []
            healthy = 0
            rate_limited = 0
            failed = 0

            for account in self.accounts:
                account_state = self._account_state[account.account_id]
                global_cooldown = account_state.get("cooldown_until")
                in_global_cooldown = bool(global_cooldown and global_cooldown > now)
                if account_state.get("auth_failed"):
                    failed += 1
                elif in_global_cooldown:
                    rate_limited += 1
                else:
                    healthy += 1

                model_cooldowns = 0
                model_status = {}
                for key, state in self._model_state.items():
                    acc_id, model_name = key.split(":", 1)
                    if acc_id != account.account_id:
                        continue
                    cooldown_until = state.get("cooldown_until")
                    if cooldown_until and cooldown_until > now:
                        model_cooldowns += 1
                    model_status[model_name] = {
                        "available": self._is_account_available(account.account_id, model_name),
                        "cooldown_expires": _iso_or_none(cooldown_until),
                        "remaining_requests": state.get("remaining_requests"),
                        "remaining_tokens": state.get("remaining_tokens"),
                        "remaining_daily_requests": state.get("remaining_daily_requests"),
                        "daily_requests": state.get("daily_requests", 0),
                        "daily_tokens": state.get("daily_tokens", 0),
                        "minute_requests": len(state.get("minute_requests", [])),
                        "last_http_status": state.get("last_http_status"),
                    }

                accounts_payload.append({
                    "account_id": account.account_id,
                    "label": account.label,
                    "priority": account.priority,
                    "email": account.email or None,
                    "project_id": account.project_id or None,
                    "masked_key": _mask_key(account.api_key),
                    "healthy": bool(account_state.get("healthy")) and not bool(account_state.get("auth_failed")),
                    "auth_failed": bool(account_state.get("auth_failed")),
                    "in_cooldown": in_global_cooldown,
                    "cooldown_expires": _iso_or_none(global_cooldown),
                    "error_count": account_state.get("error_count", 0),
                    "last_http_status": account_state.get("last_http_status"),
                    "last_error": account_state.get("last_error"),
                    "last_used_at": _iso_or_none(account_state.get("last_used_at")),
                    "model_cooldowns_active": model_cooldowns,
                    "models": model_status,
                })

            return {
                "enabled": self.has_multi_account_rotation(),
                "total_keys": len(self.accounts),
                "total_accounts": len(self.accounts),
                "healthy_keys": healthy,
                "rate_limited_keys": rate_limited,
                "failed_keys": failed,
                "rotation_count": self._rotation_count,
                "last_rotated": _iso_or_none(self._last_rotation_at),
                "accounts": accounts_payload,
            }

    def _is_account_available(self, account_id: str, model_name: Optional[str]) -> bool:
        account_state = self._account_state.get(account_id)
        if account_state is None:
            return False
        now = datetime.now(timezone.utc)
        cooldown_until = account_state.get("cooldown_until")
        if account_state.get("auth_failed"):
            return False
        if cooldown_until and cooldown_until > now:
            return False
        if cooldown_until and cooldown_until <= now:
            account_state["cooldown_until"] = None
            account_state["healthy"] = True

        if not model_name:
            return True

        state = self._get_model_state(account_id, model_name)
        model_cooldown = state.get("cooldown_until")
        if model_cooldown and model_cooldown > now:
            return False
        if model_cooldown and model_cooldown <= now:
            state["cooldown_until"] = None

        limit_reason = self._evaluate_local_limit_state(state, model_name)
        return limit_reason is None

    def _evaluate_local_limit_state(self, state: Dict[str, Any], model_name: str) -> Optional[str]:
        now = datetime.now(timezone.utc)
        self._prune_minute_window(state)
        limits = self._get_model_limits(model_name)
        rpm_limit = int(limits.get("rpm", 0) or 0)
        tpm_limit = int(limits.get("tpm", 0) or 0)
        rpd_limit = int(limits.get("rpd", 0) or 0)

        if state.get("remaining_daily_requests") is not None and state["remaining_daily_requests"] <= 0:
            if not state.get("cooldown_until") or state["cooldown_until"] <= now:
                state["cooldown_until"] = self._next_daily_reset_utc()
            return "header_rpd"
        if state.get("remaining_requests") is not None and state["remaining_requests"] <= 0:
            if not state.get("cooldown_until") or state["cooldown_until"] <= now:
                state["cooldown_until"] = now + timedelta(seconds=60)
            return "header_rpm"
        if state.get("remaining_tokens") is not None and state["remaining_tokens"] <= 0:
            if not state.get("cooldown_until") or state["cooldown_until"] <= now:
                state["cooldown_until"] = now + timedelta(seconds=60)
            return "header_tpm"

        if rpm_limit and len(state.get("minute_requests", [])) >= rpm_limit:
            state["cooldown_until"] = max(state.get("cooldown_until") or now, now + timedelta(seconds=60))
            return "local_rpm"
        if tpm_limit and int(state.get("daily_tokens", 0)) >= tpm_limit:
            state["cooldown_until"] = max(state.get("cooldown_until") or now, now + timedelta(seconds=60))
            return "local_tpm"
        if rpd_limit and int(state.get("daily_requests", 0)) >= rpd_limit:
            state["cooldown_until"] = max(state.get("cooldown_until") or now, self._next_daily_reset_utc())
            return "local_rpd"
        return None

    def _get_model_state(self, account_id: str, model_name: str) -> Dict[str, Any]:
        key = f"{account_id}:{model_name}"
        state = self._model_state.get(key)
        if state is None:
            state = {
                "minute_requests": [],
                "daily_requests": 0,
                "daily_tokens": 0,
                "cooldown_until": None,
                "remaining_requests": None,
                "remaining_tokens": None,
                "remaining_daily_requests": None,
                "last_http_status": None,
                "last_error": None,
                "last_updated_at": None,
            }
            self._model_state[key] = state
        self._prune_minute_window(state)
        return state

    def _prune_minute_window(self, state: Dict[str, Any]):
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=60)
        state["minute_requests"] = [
            ts for ts in state.get("minute_requests", [])
            if isinstance(ts, datetime) and ts > cutoff
        ]

    def _apply_headers(self, account_id: str, model_name: str, headers: Dict[str, str], status_code: Optional[int] = None):
        state = self._get_model_state(account_id, model_name)
        normalized = {str(key).lower(): str(value) for key, value in (headers or {}).items()}
        snapshot = _parse_rate_limit_headers(normalized)
        for key in (
            "remaining_requests",
            "remaining_tokens",
            "remaining_daily_requests",
            "limit_requests",
            "limit_tokens",
            "limit_daily_requests",
        ):
            value = snapshot.get(key)
            if value is not None:
                state[key] = value
        if status_code is not None:
            state["last_http_status"] = status_code
        state["last_updated_at"] = datetime.now(timezone.utc)

        retry_after_seconds = snapshot.get("retry_after_seconds")
        if retry_after_seconds:
            state["cooldown_until"] = datetime.now(timezone.utc) + timedelta(seconds=retry_after_seconds)
        elif snapshot.get("remaining_daily_requests") is not None and snapshot["remaining_daily_requests"] <= 0:
            state["cooldown_until"] = self._next_daily_reset_utc()
        elif (
            (snapshot.get("remaining_requests") is not None and snapshot["remaining_requests"] <= 0)
            or (snapshot.get("remaining_tokens") is not None and snapshot["remaining_tokens"] <= 0)
        ):
            state["cooldown_until"] = datetime.now(timezone.utc) + timedelta(seconds=60)
        elif status_code == 200 and state.get("cooldown_until") and state["cooldown_until"] <= datetime.now(timezone.utc):
            state["cooldown_until"] = None

    def _mark_model_cooldown(
        self,
        account_id: str,
        model_name: str,
        *,
        seconds: int,
        reason: str,
        status_code: Optional[int] = None,
    ):
        state = self._get_model_state(account_id, model_name)
        state["cooldown_until"] = datetime.now(timezone.utc) + timedelta(seconds=max(1, seconds))
        state["last_error"] = reason[:500]
        state["last_http_status"] = status_code
        state["last_updated_at"] = datetime.now(timezone.utc)
        logger.warning(
            "Gemini account %s cooling down for model %s for %ss",
            account_id,
            model_name,
            seconds,
        )

    def _cooldown_seconds_for_error(self, model_name: str, lowered_error: str, headers: Optional[Dict[str, str]]) -> int:
        retry_after_seconds = self._parse_retry_after_seconds(headers)
        if retry_after_seconds:
            return retry_after_seconds
        if any(token in lowered_error for token in ("requests per day", "request per day", "daily limit", "rpd", "per day")):
            delta = self._next_daily_reset_utc() - datetime.now(timezone.utc)
            return max(300, int(delta.total_seconds()))
        if any(token in lowered_error for token in ("tokens per minute", "requests per minute", "rpm", "tpm", "per minute")):
            return 10 * 60
        if any(token in lowered_error for token in ("resource_exhausted", "resource has been exhausted", "quota", "rate limit", "too many requests")):
            return 5 * 60
        return 60

    def _parse_retry_after_seconds(self, headers: Optional[Dict[str, str]]) -> Optional[int]:
        normalized = {str(key).lower(): str(value) for key, value in (headers or {}).items()}
        return _parse_rate_limit_headers(normalized).get("retry_after_seconds")

    def _reset_if_new_day(self):
        today = datetime.now(PACIFIC_TZ).strftime("%Y-%m-%d")
        if today == self._last_reset_date:
            return
        self._last_reset_date = today
        for state in self._model_state.values():
            state["daily_requests"] = 0
            state["daily_tokens"] = 0
            state["remaining_daily_requests"] = None
        self._save_state()

    def _next_daily_reset_utc(self) -> datetime:
        pacific_now = datetime.now(PACIFIC_TZ)
        next_reset = (pacific_now + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
        return next_reset.astimezone(timezone.utc)

    def _load_state(self):
        try:
            if not self._state_path.exists():
                return
            payload = json.loads(self._state_path.read_text())
            self._last_reset_date = str(payload.get("last_reset_date", "") or "")
            self._rotation_count = int(payload.get("rotation_count", 0) or 0)
            self._last_rotation_at = _parse_datetime(payload.get("last_rotation_at"))

            restored_account_state = payload.get("account_state") or {}
            for account_id, state in restored_account_state.items():
                if account_id not in self._account_state:
                    continue
                self._account_state[account_id].update({
                    "healthy": bool(state.get("healthy", True)),
                    "auth_failed": bool(state.get("auth_failed", False)),
                    "cooldown_until": _parse_datetime(state.get("cooldown_until")),
                    "error_count": int(state.get("error_count", 0) or 0),
                    "last_error": state.get("last_error"),
                    "last_http_status": state.get("last_http_status"),
                    "last_used_at": _parse_datetime(state.get("last_used_at")),
                })

            restored_model_state = payload.get("model_state") or {}
            for key, state in restored_model_state.items():
                self._model_state[key] = {
                    "minute_requests": [
                        dt for dt in (_parse_datetime(value) for value in state.get("minute_requests", []))
                        if dt is not None
                    ],
                    "daily_requests": int(state.get("daily_requests", 0) or 0),
                    "daily_tokens": int(state.get("daily_tokens", 0) or 0),
                    "cooldown_until": _parse_datetime(state.get("cooldown_until")),
                    "remaining_requests": _coerce_int(state.get("remaining_requests")),
                    "remaining_tokens": _coerce_int(state.get("remaining_tokens")),
                    "remaining_daily_requests": _coerce_int(state.get("remaining_daily_requests")),
                    "limit_requests": _coerce_int(state.get("limit_requests")),
                    "limit_tokens": _coerce_int(state.get("limit_tokens")),
                    "limit_daily_requests": _coerce_int(state.get("limit_daily_requests")),
                    "last_http_status": state.get("last_http_status"),
                    "last_error": state.get("last_error"),
                    "last_updated_at": _parse_datetime(state.get("last_updated_at")),
                }
                self._prune_minute_window(self._model_state[key])
        except Exception as exc:
            logger.warning("APIKeyManager: could not load state: %s", exc)

    def _save_state(self):
        try:
            payload = {
                "last_reset_date": self._last_reset_date,
                "rotation_count": self._rotation_count,
                "last_rotation_at": _iso_or_none(self._last_rotation_at),
                "account_state": {
                    account_id: {
                        **state,
                        "cooldown_until": _iso_or_none(state.get("cooldown_until")),
                        "last_used_at": _iso_or_none(state.get("last_used_at")),
                    }
                    for account_id, state in self._account_state.items()
                },
                "model_state": {
                    key: {
                        **state,
                        "minute_requests": [_iso_or_none(ts) for ts in state.get("minute_requests", []) if ts],
                        "cooldown_until": _iso_or_none(state.get("cooldown_until")),
                        "last_updated_at": _iso_or_none(state.get("last_updated_at")),
                    }
                    for key, state in self._model_state.items()
                },
            }
            self._state_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
        except Exception as exc:
            logger.warning("APIKeyManager: could not save state: %s", exc)

    def _get_model_limits(self, model_name: str) -> Dict[str, int]:
        try:
            from app.services.model_selector import MODEL_QUOTAS
        except Exception:
            MODEL_QUOTAS = {}

        normalized = _MODEL_QUOTA_ALIASES.get(model_name, model_name)
        quota = MODEL_QUOTAS.get(normalized)
        if quota:
            return quota

        lowered = normalized.lower()
        if "embedding" in lowered:
            return {"rpm": 100, "tpm": 30_000, "rpd": 1_000}
        if "native-audio" in lowered:
            return {"rpm": 0, "tpm": 1_000_000, "rpd": 0}
        if "tts" in lowered:
            return {"rpm": 3, "tpm": 10_000, "rpd": 10}
        if "imagen" in lowered or lowered.endswith("-image") or "image-preview" in lowered:
            return {"rpd": 25}
        if "flash-lite" in lowered:
            return {"rpm": 10, "tpm": 250_000, "rpd": 20}
        if "flash" in lowered:
            return {"rpm": 5, "tpm": 250_000, "rpd": 20}
        if "gemma" in lowered:
            return {"rpm": 30, "tpm": 15_000, "rpd": 14_400}
        return {}


_key_manager: Optional[APIKeyManager] = None


def initialize_key_manager(api_keys: Optional[List[str]] = None, force: bool = False) -> Optional[APIKeyManager]:
    """Initialize the global key manager from settings or an explicit key list."""
    global _key_manager
    if _key_manager is not None and not force:
        return _key_manager

    accounts = _load_accounts_from_settings(api_keys)
    if not accounts:
        _key_manager = None
        return None

    _key_manager = APIKeyManager(accounts)
    return _key_manager


def get_key_manager() -> Optional[APIKeyManager]:
    """Get the global API key manager, initializing lazily if needed."""
    global _key_manager
    if _key_manager is None:
        _key_manager = initialize_key_manager()
    return _key_manager


def get_genai_client() -> Optional[Any]:
    """Return a rotating Gemini client when available, else a single-key client."""
    manager = get_key_manager()
    if manager is not None:
        return manager.get_rotating_client()
    if settings.google_api_key:
        return genai.Client(api_key=settings.google_api_key)
    return None


def _persistent_state_dir() -> Path:
    configured_path = Path(settings.database_path).expanduser()
    candidate = configured_path.resolve().parent
    try:
        candidate.mkdir(parents=True, exist_ok=True)
        return candidate
    except OSError:
        fallback = Path("/tmp/witnessreplay_data")
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def _state_path() -> Path:
    return _persistent_state_dir() / "api_key_manager_state.json"


def _load_accounts_from_settings(api_keys: Optional[List[str]] = None) -> List[GeminiAccountConfig]:
    ordered: List[GeminiAccountConfig] = []
    seen_keys: set[str] = set()

    def add_account(account_id: str, label: str, priority: int, api_key: str, email: str = "", project_id: str = ""):
        key = (api_key or "").strip()
        if not key or key in seen_keys:
            return
        seen_keys.add(key)
        ordered.append(GeminiAccountConfig(
            account_id=account_id,
            label=label,
            priority=priority,
            api_key=key,
            email=(email or "").strip(),
            project_id=(project_id or "").strip(),
        ))

    if settings.google_api_accounts_json:
        try:
            raw_payload = json.loads(settings.google_api_accounts_json)
            if isinstance(raw_payload, dict):
                raw_payload = [raw_payload]
            for index, entry in enumerate(raw_payload or [], start=1):
                if not isinstance(entry, dict):
                    continue
                add_account(
                    account_id=str(entry.get("account_id") or entry.get("id") or f"account-{index}"),
                    label=str(entry.get("label") or entry.get("name") or f"Account {index}"),
                    priority=int(entry.get("priority") or index),
                    api_key=str(entry.get("api_key") or entry.get("key") or ""),
                    email=str(entry.get("email") or ""),
                    project_id=str(entry.get("project_id") or entry.get("project") or ""),
                )
        except Exception as exc:
            logger.warning("Failed to parse GOOGLE_API_ACCOUNTS_JSON: %s", exc)

    add_account(
        "primary",
        "Primary",
        1,
        settings.google_api_primary_key,
        settings.google_api_primary_email,
        settings.google_api_primary_project_id,
    )
    add_account(
        "secondary",
        "Secondary",
        2,
        settings.google_api_secondary_key,
        settings.google_api_secondary_email,
        settings.google_api_secondary_project_id,
    )
    add_account(
        "tertiary",
        "Tertiary",
        3,
        settings.google_api_tertiary_key,
        settings.google_api_tertiary_email,
        settings.google_api_tertiary_project_id,
    )

    if api_keys:
        labels = ["Primary", "Secondary", "Tertiary"]
        ids = ["primary", "secondary", "tertiary"]
        for index, api_key in enumerate(api_keys, start=1):
            label = labels[index - 1] if index <= len(labels) else f"Account {index}"
            account_id = ids[index - 1] if index <= len(ids) else f"account-{index}"
            add_account(account_id, label, index, api_key)

    if settings.google_api_keys:
        labels = ["Primary", "Secondary", "Tertiary"]
        ids = ["primary", "secondary", "tertiary"]
        for index, api_key in enumerate(settings.google_api_keys.split(","), start=1):
            key = api_key.strip()
            if not key:
                continue
            label = labels[index - 1] if index <= len(labels) else f"Account {index}"
            account_id = ids[index - 1] if index <= len(ids) else f"account-{index}"
            add_account(account_id, label, index, key)

    add_account(
        "primary",
        "Primary",
        1,
        settings.google_api_key,
        settings.google_api_primary_email,
        settings.google_api_primary_project_id,
    )

    ordered.sort(key=lambda account: account.priority)
    return ordered


def _mask_key(api_key: str) -> str:
    key = (api_key or "").strip()
    if len(key) <= 10:
        return "***" if key else "(missing)"
    return f"{key[:8]}...{key[-4:]}"


def _parse_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _iso_or_none(value: Any) -> Optional[str]:
    if not isinstance(value, datetime):
        return None
    return value.astimezone(timezone.utc).isoformat()


def _coerce_int(value: Any) -> Optional[int]:
    if value in (None, "", "None"):
        return None
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _extract_status_code(error: Exception) -> Optional[int]:
    code = getattr(error, "code", None)
    if isinstance(code, int):
        return code
    response = getattr(error, "response", None)
    for attr in ("status_code", "status"):
        value = getattr(response, attr, None)
        if isinstance(value, int):
            return value
    return None


def _extract_headers_from_response(response: Any) -> Optional[Dict[str, str]]:
    sdk_response = getattr(response, "sdk_http_response", None)
    headers = getattr(sdk_response, "headers", None)
    if isinstance(headers, dict):
        return headers
    return None


def _extract_headers_from_error(error: Exception) -> Optional[Dict[str, str]]:
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    if isinstance(headers, dict):
        return headers
    try:
        if headers is not None:
            return dict(headers)
    except Exception:
        return None
    return None


def _extract_tokens_used(response: Any) -> int:
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return 0
    prompt_tokens = getattr(usage, "prompt_token_count", 0) or 0
    output_tokens = getattr(usage, "candidates_token_count", 0) or 0
    return int(prompt_tokens) + int(output_tokens)


def _parse_rate_limit_headers(headers: Dict[str, str]) -> Dict[str, Optional[int]]:
    parsed: Dict[str, Optional[int]] = {
        "remaining_requests": None,
        "remaining_tokens": None,
        "remaining_daily_requests": None,
        "limit_requests": None,
        "limit_tokens": None,
        "limit_daily_requests": None,
        "retry_after_seconds": None,
    }
    if not headers:
        return parsed

    for key, aliases in _HEADER_ALIASES.items():
        for alias in aliases:
            if alias not in headers:
                continue
            raw_value = headers.get(alias)
            if key == "retry_after":
                parsed["retry_after_seconds"] = _parse_retry_after(raw_value)
            else:
                parsed[key] = _coerce_int(raw_value)
            break
    return parsed


def _parse_retry_after(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    text = str(value).strip()
    direct = _coerce_int(text)
    if direct is not None:
        return max(1, direct)
    try:
        parsed = parsedate_to_datetime(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        delta = parsed.astimezone(timezone.utc) - datetime.now(timezone.utc)
        return max(1, int(delta.total_seconds()))
    except Exception:
        return None
