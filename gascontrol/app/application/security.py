"""Hash de senha (scrypt, stdlib), JWT e proteção contra força bruta."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone

import jwt

from app.domain.errors import ValidationFailed

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P, _DKLEN = 2**15, 8, 1, 64
_MAXMEM = 64 * 1024 * 1024


def hash_password(password: str) -> str:
    validate_password_strength(password)
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P,
                        dklen=_DKLEN, maxmem=_MAXMEM)
    return "scrypt${}${}${}${}${}".format(
        _SCRYPT_N, _SCRYPT_R, _SCRYPT_P,
        base64.b64encode(salt).decode(), base64.b64encode(dk).decode(),
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_b64, dk_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        expected = base64.b64decode(dk_b64)
        dk = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64), n=int(n), r=int(r),
                            p=int(p), dklen=len(expected), maxmem=_MAXMEM)
        return hmac.compare_digest(dk, expected)
    except (ValueError, TypeError):
        return False


def validate_password_strength(password: str) -> None:
    if len(password) < 10 or len(password) > 128:
        raise ValidationFailed("Senha deve ter entre 10 e 128 caracteres")
    classes = sum([any(c.islower() for c in password), any(c.isupper() for c in password),
                   any(c.isdigit() for c in password), any(not c.isalnum() for c in password)])
    if classes < 3:
        raise ValidationFailed("Senha deve combinar ao menos 3 de: minúscula, maiúscula, dígito, símbolo")


# Hash fixo para equalizar o tempo de resposta quando o e-mail não existe (anti-enumeração).
DUMMY_HASH = hash_password("dummy-Password-123!")


class TokenService:
    ALGO = "HS256"

    def __init__(self, secret: str, ttl_minutes: int) -> None:
        self._secret = secret
        self._ttl = timedelta(minutes=ttl_minutes)

    def issue(self, user_id: int, role: str) -> tuple[str, int]:
        now = datetime.now(timezone.utc)
        payload = {"sub": str(user_id), "role": role, "iat": now, "nbf": now,
                   "exp": now + self._ttl, "jti": secrets.token_hex(8), "iss": "gascontrol"}
        return jwt.encode(payload, self._secret, algorithm=self.ALGO), int(self._ttl.total_seconds())

    def decode(self, token: str) -> dict[str, object]:
        return jwt.decode(token, self._secret, algorithms=[self.ALGO], issuer="gascontrol",
                          options={"require": ["exp", "sub", "iat", "iss"]})


class LoginThrottle:
    """Bloqueio por chave (e-mail+IP) após N falhas. Em multi-réplica, troque por Redis."""

    def __init__(self, max_attempts: int, lockout_seconds: int) -> None:
        self._max = max_attempts
        self._lock_s = lockout_seconds
        self._failures: dict[str, tuple[int, float]] = {}
        self._mutex = threading.Lock()

    def is_locked(self, key: str) -> bool:
        with self._mutex:
            count, since = self._failures.get(key, (0, 0.0))
            if count >= self._max and time.monotonic() - since < self._lock_s:
                return True
            if count >= self._max:
                self._failures.pop(key, None)
            return False

    def fail(self, key: str) -> None:
        with self._mutex:
            count, _ = self._failures.get(key, (0, 0.0))
            self._failures[key] = (count + 1, time.monotonic())
            if len(self._failures) > 100_000:  # limite de memória
                self._failures.clear()

    def success(self, key: str) -> None:
        with self._mutex:
            self._failures.pop(key, None)
