"""Credential hashing / verification for Smart Attendance (Phase 0).

Security references (cited in the code comments where each decision is made):
- OWASP Password Storage Cheat Sheet:
  https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html
- OWASP Authentication Cheat Sheet:
  https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html

Rules enforced here:
- Argon2id is the only hash produced for new credentials. Legacy bcrypt
  hashes are *verified* (so existing accounts keep working) but never
  produced, and ``verify_credential`` flags them with ``needs_rehash=True``
  so callers can transparently upgrade them on the next successful login.
- Plaintext credentials are never logged or stored by this module. There is
  no logging call anywhere in this file, by design.
- Verification fails closed: empty / missing / malformed stored hashes
  return ``(False, False)`` and never raise, so a corrupt row cannot be
  treated as a successful login.

New dependency (NOT added to requirements.txt in this change -- another
agent owns that file): ``argon2-cffi``. ``bcrypt`` is still needed only to
verify legacy hashes; it is no longer used to create hashes.
"""

from __future__ import annotations

import hashlib
import re

try:  # argon2-cffi is a declared Phase 0 dependency; import lazily-guarded
    # so this module can still be imported (and fail closed at call time)
    # in environments where it has not been installed yet.
    from argon2 import PasswordHasher
    from argon2.exceptions import VerificationError, InvalidHashError

    _ARGON2_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only without argon2-cffi
    PasswordHasher = None  # type: ignore[assignment]
    VerificationError = Exception  # type: ignore[assignment]
    InvalidHashError = Exception  # type: ignore[assignment]
    _ARGON2_ERROR = exc

try:
    import bcrypt as _bcrypt
except Exception:  # pragma: no cover - bcrypt is legacy-only; absence fails closed
    _bcrypt = None

# --- Argon2id parameters -------------------------------------------------
# OWASP Password Storage Cheat Sheet (Argon2id, first choice):
#   memory 19 MiB, iterations 2, parallelism 1
# https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html
ARGON2_TIME_COST = 2
ARGON2_MEMORY_COST_KIB = 19 * 1024  # 19 MiB
ARGON2_PARALLELISM = 1
ARGON2_HASH_LEN = 32
ARGON2_SALT_LEN = 16

# --- PIN policy -----------------------------------------------------------
# OWASP Authentication Cheat Sheet: short numeric PINs have very low
# entropy (10_000-1_000_000 combinations) and are only acceptable as one
# factor combined with a biometric / device factor and strict rate limiting
# (see src/database/rate_limit.py). They must never be the sole credential.
# https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html
PIN_MIN_LENGTH = 4
PIN_MAX_LENGTH = 6
_PIN_RE = re.compile(r"^[0-9]{4,6}$")

# --- bcrypt legacy limit --------------------------------------------------
# bcrypt silently truncates inputs longer than 72 bytes, so two different
# long passwords sharing a 72-byte prefix would verify against the same
# legacy hash. New passwords are therefore SHA-256 pre-hashed (hex digest)
# whenever their UTF-8 form exceeds 72 bytes, before Argon2id hashing, so
# the full password always influences the hash. Short passwords are hashed
# unchanged. Verification applies the identical transform, so this is
# deterministic. See OWASP Password Storage Cheat Sheet, "maximum password
# length" discussion.
# https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html
BCRYPT_MAX_BYTES = 72


def _get_hasher() -> "PasswordHasher":
    if PasswordHasher is None:
        raise RuntimeError(
            "argon2-cffi is required for credential hashing but is not "
            f"installed: {_ARGON2_ERROR}"
        )
    return PasswordHasher(
        time_cost=ARGON2_TIME_COST,
        memory_cost=ARGON2_MEMORY_COST_KIB,
        parallelism=ARGON2_PARALLELISM,
        hash_len=ARGON2_HASH_LEN,
        salt_len=ARGON2_SALT_LEN,
    )


def validate_pin(pin: str) -> str:
    """Validate a student PIN and return its canonical form.

    Policy: 4-6 ASCII digits only. Anything else raises ``ValueError``.
    Surrounding whitespace is stripped; interior whitespace / letters /
    symbols are rejected. The returned value is the stripped digit string.
    """
    if not isinstance(pin, str):
        raise ValueError("PIN must be a string of 4-6 digits")
    candidate = pin.strip()
    if not _PIN_RE.match(candidate):
        raise ValueError("PIN must be 4-6 digits only")
    return candidate


def hash_pin(pin: str) -> str:
    """Hash a validated PIN with Argon2id. Raises ``ValueError`` for bad PINs."""
    return _get_hasher().hash(validate_pin(pin))


def _prepare_password(pwd: str) -> str:
    """Return the exact string to feed to Argon2id for ``pwd``.

    Passwords whose UTF-8 encoding exceeds bcrypt's 72-byte limit are
    SHA-256 pre-hashed (hex digest) first; shorter passwords pass through
    unchanged. Documented in the module docstring / ``BCRYPT_MAX_BYTES``.
    """
    if len(pwd.encode("utf-8")) > BCRYPT_MAX_BYTES:
        return hashlib.sha256(pwd.encode("utf-8")).hexdigest()
    return pwd


def hash_password(pwd: str) -> str:
    """Hash a teacher password with Argon2id.

    The password is NOT stripped or truncated: leading/trailing spaces are
    part of the password (cf. OWASP Authentication Cheat Sheet -- do not
    silently alter the credential the user typed).
    Raises ``ValueError`` for an empty / non-string password.
    """
    if not isinstance(pwd, str) or not pwd:
        raise ValueError("Password cannot be empty")
    return _get_hasher().hash(_prepare_password(pwd))


def is_argon2_hash(stored: str | None) -> bool:
    """True only for Argon2id hashes (``$argon2id$...``)."""
    return isinstance(stored, str) and stored.startswith("$argon2id$")


def is_bcrypt_hash(stored: str | None) -> bool:
    """True for legacy bcrypt hashes (``$2a$`` / ``$2b$`` / ``$2y$``)."""
    return isinstance(stored, str) and stored.startswith(("$2a$", "$2b$", "$2y$"))


def _verify_bcrypt(plain: str, stored: str) -> bool:
    """Verify ``plain`` against a legacy bcrypt hash. Fail closed."""
    if _bcrypt is None:
        return False
    try:
        raw = plain.encode("utf-8")
        # bcrypt itself truncates >72 bytes, which is exactly how legacy
        # hashes were created, so the raw form must be tried first.
        if _bcrypt.checkpw(raw, stored.encode("utf-8")):
            return True
        # Also try the Phase 0 pre-hash form, in case a long password was
        # ever stored as bcrypt after SHA-256 pre-hashing.
        if len(raw) > BCRYPT_MAX_BYTES:
            pre = hashlib.sha256(raw).hexdigest().encode("utf-8")
            return bool(_bcrypt.checkpw(pre, stored.encode("utf-8")))
        return False
    except Exception:
        return False


def verify_credential(plain: str, stored: str | None) -> tuple[bool, bool]:
    """Verify a plaintext credential against a stored hash.

    Returns ``(ok, needs_rehash)``:
    - ``ok`` is True only if the credential matches.
    - ``needs_rehash`` describes the *stored hash*, independent of whether
      the credential matched: True for legacy bcrypt (migrate on next
      successful login) and for Argon2id hashes whose parameters no longer
      match the current OWASP parameters (``PasswordHasher.check_needs_rehash``).
      Callers should re-hash with :func:`hash_password` / :func:`hash_pin`
      when ``ok`` is True and ``needs_rehash`` is True.
    - Fail closed: empty / missing / non-string / unrecognised stored hashes
      return ``(False, False)`` and never raise. The plaintext is never
      logged. Comparison of the bcrypt path uses ``bcrypt.checkpw`` (constant
      time internally); the Argon2id path uses argon2-cffi verification.
    """
    if not isinstance(plain, str) or not plain:
        return False, False
    if not isinstance(stored, str) or not stored:
        return False, False

    if is_argon2_hash(stored):
        try:
            hasher = _get_hasher()
            hasher.verify(stored, _prepare_password(plain))
            return True, bool(hasher.check_needs_rehash(stored))
        except InvalidHashError:
            return False, False
        except VerificationError:
            try:
                return False, bool(_get_hasher().check_needs_rehash(stored))
            except Exception:
                return False, False
        except Exception:
            return False, False

    if is_bcrypt_hash(stored):
        # Legacy bcrypt: always needs migration to Argon2id, whether or not
        # this attempt matched. See OWASP Password Storage Cheat Sheet.
        return _verify_bcrypt(plain, stored), True

    # Unrecognised hash format: fail closed, do not guess.
    return False, False


# Backwards-compatible alias used by older callers/tests.
verify_password = verify_credential


def needs_rehash(stored: str | None) -> bool:
    """Convenience: True if ``stored`` is a legacy / outdated hash."""
    if is_bcrypt_hash(stored):
        return True
    if is_argon2_hash(stored):
        try:
            return bool(_get_hasher().check_needs_rehash(stored))
        except Exception:
            return False
    return False
