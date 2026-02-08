"""
Command authentication for the dashboard -> bot control plane.

We use HMAC-SHA256 signatures over a canonical JSON envelope to ensure:
- the command was produced by the dashboard (shared secret)
- the command hasn't expired
- the command can't be trivially replayed (nonce cache)

This does NOT provide authorization by itself (that's DB permissions + bot-side validation).
"""

from __future__ import annotations

import hmac
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Dict, Optional, Tuple


RESERVED_META_KEYS = {
    "command_id",
    "schema_version",
    "created_at",
    "expires_at",
    "nonce",
    "signature",
}


def _canonical_json(obj: Any) -> str:
    # Match the dashboard stable stringify: sorted keys, no spaces.
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _parse_iso8601(ts: str) -> datetime:
    # Accept both "Z" and "+00:00".
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts).astimezone(timezone.utc)


def get_hmac_secret() -> str:
    return os.getenv("BOT_COMMAND_HMAC_SECRET", "")


def split_user_params(params: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    meta: Dict[str, Any] = {}
    user: Dict[str, Any] = {}
    for k, v in (params or {}).items():
        if k in RESERVED_META_KEYS:
            meta[k] = v
        else:
            user[k] = v
    return user, meta


@dataclass
class VerifyResult:
    ok: bool
    error: str = ""
    command_id: str = ""
    nonce: str = ""


class NonceCache:
    """
    In-memory replay protection.

    Not persisted across restarts. DB uniqueness on command id + short expiries
    are still doing most of the work.
    """

    def __init__(self, max_items: int = 2000):
        self._max_items = max_items
        self._seen: Dict[str, float] = {}

    def seen(self, nonce: str) -> bool:
        return nonce in self._seen

    def add(self, nonce: str, expires_at_epoch: float) -> None:
        self._seen[nonce] = expires_at_epoch
        self._evict()

    def _evict(self) -> None:
        now = time.time()
        # Drop expired first.
        expired = [n for n, exp in self._seen.items() if exp <= now]
        for n in expired:
            self._seen.pop(n, None)

        if len(self._seen) <= self._max_items:
            return

        # If still too big, drop oldest expiries.
        for nonce, _ in sorted(self._seen.items(), key=lambda kv: kv[1])[
            : len(self._seen) - self._max_items
        ]:
            self._seen.pop(nonce, None)


def verify_signed_command(
    *,
    command: str,
    params: Dict[str, Any],
    fallback_command_id: str,
    nonce_cache: NonceCache,
    now: Optional[datetime] = None,
) -> VerifyResult:
    secret = get_hmac_secret()
    if not secret:
        return VerifyResult(False, "BOT_COMMAND_HMAC_SECRET not set (commands disabled)")

    user_params, meta = split_user_params(params or {})

    schema_version = int(meta.get("schema_version") or 0)
    command_id = str(meta.get("command_id") or fallback_command_id or "")
    created_at = meta.get("created_at")
    expires_at = meta.get("expires_at")
    nonce = str(meta.get("nonce") or "")
    signature = str(meta.get("signature") or "")

    if schema_version != 1:
        return VerifyResult(False, "invalid schema_version", command_id=command_id, nonce=nonce)
    if not command_id:
        return VerifyResult(False, "missing command_id", nonce=nonce)
    if not created_at or not expires_at or not nonce or not signature:
        return VerifyResult(False, "missing signature metadata", command_id=command_id, nonce=nonce)

    now_dt = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    try:
        expires_dt = _parse_iso8601(str(expires_at))
    except Exception:
        return VerifyResult(False, "invalid expires_at", command_id=command_id, nonce=nonce)

    if now_dt > expires_dt:
        return VerifyResult(False, "command expired", command_id=command_id, nonce=nonce)

    if nonce_cache.seen(nonce):
        return VerifyResult(False, "replayed nonce", command_id=command_id, nonce=nonce)

    envelope = {
        "schema_version": 1,
        "command_id": command_id,
        "command": command,
        "params": user_params,
        "created_at": str(created_at),
        "expires_at": str(expires_at),
        "nonce": nonce,
    }

    expected = hmac.new(secret.encode("utf-8"), _canonical_json(envelope).encode("utf-8"), sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return VerifyResult(False, "invalid signature", command_id=command_id, nonce=nonce)

    nonce_cache.add(nonce, expires_dt.timestamp())
    return VerifyResult(True, command_id=command_id, nonce=nonce)

