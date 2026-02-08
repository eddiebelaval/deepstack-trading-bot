import hmac
import json
import os
from datetime import datetime, timedelta, timezone
from hashlib import sha256

from kalshi_trader.command_auth import NonceCache, verify_signed_command


def _canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sign(envelope: dict, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), _canonical_json(envelope).encode("utf-8"), sha256).hexdigest()


def test_verify_signed_command_ok(monkeypatch):
    monkeypatch.setenv("BOT_COMMAND_HMAC_SECRET", "test_secret")

    now = datetime.now(timezone.utc)
    env = {
        "schema_version": 1,
        "command_id": "11111111-1111-1111-1111-111111111111",
        "command": "toggle_strategy",
        "params": {"strategy": "momentum", "enabled": True},
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=60)).isoformat(),
        "nonce": "abcd" * 8,
    }
    sig = _sign(env, "test_secret")

    params = {**env["params"], **{k: env[k] for k in ("schema_version", "command_id", "created_at", "expires_at", "nonce")}, "signature": sig}

    cache = NonceCache()
    res = verify_signed_command(
        command=env["command"],
        params=params,
        fallback_command_id="fallback",
        nonce_cache=cache,
        now=now,
    )
    assert res.ok


def test_verify_signed_command_expired(monkeypatch):
    monkeypatch.setenv("BOT_COMMAND_HMAC_SECRET", "test_secret")

    now = datetime.now(timezone.utc)
    env = {
        "schema_version": 1,
        "command_id": "11111111-1111-1111-1111-111111111111",
        "command": "pause",
        "params": {},
        "created_at": (now - timedelta(seconds=120)).isoformat(),
        "expires_at": (now - timedelta(seconds=60)).isoformat(),
        "nonce": "ffff" * 8,
    }
    sig = _sign(env, "test_secret")
    params = {**env["params"], **{k: env[k] for k in ("schema_version", "command_id", "created_at", "expires_at", "nonce")}, "signature": sig}

    cache = NonceCache()
    res = verify_signed_command(
        command=env["command"],
        params=params,
        fallback_command_id="fallback",
        nonce_cache=cache,
        now=now,
    )
    assert not res.ok
    assert "expired" in res.error


def test_verify_signed_command_replay(monkeypatch):
    monkeypatch.setenv("BOT_COMMAND_HMAC_SECRET", "test_secret")

    now = datetime.now(timezone.utc)
    env = {
        "schema_version": 1,
        "command_id": "11111111-1111-1111-1111-111111111111",
        "command": "scan_now",
        "params": {},
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=60)).isoformat(),
        "nonce": "9999" * 8,
    }
    sig = _sign(env, "test_secret")
    params = {**env["params"], **{k: env[k] for k in ("schema_version", "command_id", "created_at", "expires_at", "nonce")}, "signature": sig}

    cache = NonceCache()
    r1 = verify_signed_command(
        command=env["command"],
        params=params,
        fallback_command_id="fallback",
        nonce_cache=cache,
        now=now,
    )
    assert r1.ok

    r2 = verify_signed_command(
        command=env["command"],
        params=params,
        fallback_command_id="fallback",
        nonce_cache=cache,
        now=now,
    )
    assert not r2.ok
    assert "replayed" in r2.error

