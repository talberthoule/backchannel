"""Encrypted workspace credentials stored in app_settings.

Values are Fernet tokens; the master key lives OUTSIDE the database, either
in the CREDENTIALS_MASTER_KEY env var or auto-generated at DATA_DIR/master.key.

On Windows the desktop launcher additionally asks for the master key file to
be wrapped with DPAPI (CREDENTIALS_MASTER_KEY_PROTECTION=dpapi): the file then
holds a blob only the same Windows user on the same machine can unwrap, so a
copied AppData folder or an offline disk image no longer yields the key that
decrypts every stored credential. A plaintext file from an earlier version is
upgraded in place the first time it is read under that mode; unsetting the
mode leaves a wrapped file readable, so the setting is safe to toggle. If
DPAPI itself fails on a fresh install, the key is stored unwrapped with a
warning rather than not at all - the app must always have a usable key.

A master key that exists but cannot be used (an unwrappable blob after an
admin-forced password reset or a data folder moved to another PC, an empty or
corrupt file) raises MasterKeyUnavailable. Reads treat every stored secret as
unset and log why; writes propagate the error so the save routes can answer
503 with the recovery steps instead of an opaque 500.

Every plaintext secret that passes through here is registered with
``services.redaction`` so it can never appear verbatim in a log line.
"""

import base64
import hashlib
import logging
import os
import sys
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings
from app.services.app_settings import get_app_setting, set_app_setting
from app.services.redaction import register_secret

logger = logging.getLogger(__name__)

# "openai-compatible" is a self-hosted OpenAI-shaped server; its key is
# optional (see llm_endpoint.requires_api_key) but it still gets a credential
# row so proxies that do want a token can store one encrypted.
PROVIDERS = ["google", "openai", "openai-compatible"]

PROTECTION_ENV = "CREDENTIALS_MASTER_KEY_PROTECTION"
DPAPI_MODE = "dpapi"
_DPAPI_PREFIX = b"dpapi:"

_fernet: Fernet | None = None


class MasterKeyUnavailable(RuntimeError):
    """The master key exists but cannot be used by this user, machine, or file."""


def data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", "/app/data"))


def master_key_path() -> Path:
    return data_dir() / "master.key"


def master_key_recovery_message(exc: Exception | None = None) -> str:
    """Operator-facing explanation for a 503 when the master key is unusable."""
    reason = f" ({exc})" if exc else ""
    return (
        f"The credentials master key at {master_key_path()} cannot be used on this "
        f"account or machine{reason}. Provider keys stored with it are unreadable "
        "until it is replaced: stop Backchannel, delete that file, start again, "
        "and re-enter the provider keys in Admin -> Connections."
    )


def protection_mode() -> str:
    return os.environ.get(PROTECTION_ENV, "").strip().lower()


def dpapi_available() -> bool:
    return sys.platform == "win32"


def _dpapi_call(function_name: str, data: bytes) -> bytes:
    """CryptProtectData / CryptUnprotectData through ctypes, current-user scope."""
    import ctypes
    from ctypes import wintypes

    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)  # type: ignore[attr-defined]
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    buffer = ctypes.create_string_buffer(data, len(data))
    blob_in = DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    blob_out = DataBlob()
    function = getattr(crypt32, function_name)
    # description, entropy, reserved, prompt struct, flags (0 = current user)
    ok = function(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    )
    if not ok:
        raise MasterKeyUnavailable(f"{function_name} failed (error {ctypes.get_last_error()})")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def _dpapi_protect(data: bytes) -> bytes:
    return _dpapi_call("CryptProtectData", data)


def _dpapi_unprotect(blob: bytes) -> bytes:
    return _dpapi_call("CryptUnprotectData", blob)


def _wrap_master_key(key: bytes) -> bytes:
    return _DPAPI_PREFIX + base64.b64encode(_dpapi_protect(key))


def _read_master_key_file(key_file: Path) -> tuple[bytes, bool]:
    """Return (key, was_wrapped). Raises MasterKeyUnavailable on an unreadable blob."""
    raw = key_file.read_bytes().strip()
    if not raw.startswith(_DPAPI_PREFIX):
        return raw, False
    if not dpapi_available():
        raise MasterKeyUnavailable(
            f"{key_file} is DPAPI-protected and can only be read on the Windows "
            "account that created it"
        )
    try:
        blob = base64.b64decode(raw[len(_DPAPI_PREFIX):])
        return _dpapi_unprotect(blob), True
    except MasterKeyUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 - any failure here means the same thing
        raise MasterKeyUnavailable(f"{key_file} could not be unwrapped: {exc}") from exc


def _atomic_write(key_file: Path, payload: bytes) -> None:
    """Write via a sibling temp file and rename, so a crash mid-write can never
    leave a truncated master.key behind for the next start to read."""
    key_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = key_file.with_name(key_file.name + ".tmp")
    tmp.write_bytes(payload)
    tmp.chmod(0o600)
    os.replace(tmp, key_file)


def _write_master_key_file(key_file: Path, key: bytes) -> None:
    payload = key
    if protection_mode() == DPAPI_MODE and dpapi_available():
        try:
            payload = _wrap_master_key(key)
        except Exception:  # noqa: BLE001
            logger.warning(
                "Could not DPAPI-wrap the master key; storing it unwrapped at %s", key_file
            )
            payload = key
    _atomic_write(key_file, payload)


def _upgrade_plaintext_file(key_file: Path, key: bytes) -> None:
    """Wrap a plaintext file from an earlier version, in place.

    The round trip is verified before the file is replaced so a DPAPI problem
    can never orphan the stored credentials.
    """
    try:
        wrapped_payload = _wrap_master_key(key)
        if _dpapi_unprotect(base64.b64decode(wrapped_payload[len(_DPAPI_PREFIX):])) == key:
            _atomic_write(key_file, wrapped_payload)
            logger.info("Wrapped the credentials master key with DPAPI")
    except Exception:  # noqa: BLE001
        logger.warning("Could not DPAPI-wrap the master key; leaving the file as is")


def _master_key() -> bytes:
    env_key = os.environ.get("CREDENTIALS_MASTER_KEY")
    if env_key:
        register_secret(env_key)
        return env_key.encode()
    key_file = master_key_path()
    if key_file.exists():
        key, wrapped = _read_master_key_file(key_file)
        if not key:
            raise MasterKeyUnavailable(f"{key_file} is empty")
        if not wrapped and protection_mode() == DPAPI_MODE and dpapi_available():
            _upgrade_plaintext_file(key_file, key)
        register_secret(key)
        return key
    key = Fernet.generate_key()
    _write_master_key_file(key_file, key)
    register_secret(key)
    logger.info(f"Generated new credentials master key at {key_file}")
    return key


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        key = _master_key()
        try:
            _fernet = Fernet(key)
        except (ValueError, TypeError) as exc:
            # An empty or corrupt file, or a mangled CREDENTIALS_MASTER_KEY.
            raise MasterKeyUnavailable(
                f"{master_key_path()} does not hold a valid Fernet key ({exc})"
            ) from exc
    return _fernet


def encrypt_value(value: str) -> str:
    """Fernet token for a secret, or "" for an empty value.

    Used directly by callers that store their own ciphertext column (custom
    endpoint keys) rather than an app_settings row. Raises MasterKeyUnavailable
    when there is no usable master key; callers that answer HTTP turn that into
    a 503 with master_key_recovery_message().
    """
    if not value:
        return ""
    register_secret(value)
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt_value(token: str, label: str = "value") -> str:
    if not token:
        return ""
    try:
        value = _get_fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        logger.warning(
            f"Could not decrypt {label}; master key changed? "
            f"(env CREDENTIALS_MASTER_KEY or {master_key_path()})"
        )
        return ""
    except MasterKeyUnavailable as exc:
        # Worded so the label never sits directly before a colon: the log
        # scrubber treats "api_key: <text>" as a credential and would eat the
        # file path this message exists to report.
        logger.warning(
            f"Stored {label} credential is unreadable because the master key "
            f"cannot be used - {exc}"
        )
        return ""
    register_secret(value)
    return value


async def get_secret(db, key: str) -> str:
    return decrypt_value(await get_app_setting(db, key), key)


async def set_secret(db, key: str, value: str) -> None:
    await set_app_setting(db, key, encrypt_value(value))


def env_provider_key(provider: str) -> str:
    if provider == "google":
        value = settings.GEMINI_API_KEY
    elif provider == "openai":
        value = settings.OPENAI_API_KEY
    elif provider == "openai-compatible":
        value = settings.OPENAI_COMPATIBLE_API_KEY
    else:
        value = ""
    if value:
        register_secret(value)
    return value


async def get_provider_key(db, provider: str) -> str:
    stored = await get_secret(db, f"credentials.{provider}.api_key")
    if stored:
        return stored
    return env_provider_key(provider)


async def resolve_provider_key(provider: str) -> str:
    """get_provider_key with its own short-lived DB session."""
    from app.database import async_session

    async with async_session() as db:
        return await get_provider_key(db, provider)


def mask_key(value: str) -> str:
    """Display form of a stored key: the last four characters only.

    The leading characters of a provider key are a fixed prefix ("AIza",
    "sk-proj-") that identifies nothing, and every character shown is one an
    attacker no longer has to guess, so the mask stops at the trailing four
    that let a user tell two keys apart.
    """
    if len(value) < 12:
        return ""
    return f"...{value[-4:]}"


def key_fingerprint(value: str) -> str:
    """Non-reversible identity for a key, used to tie a passed connection
    test to the exact key that passed it."""
    if not value:
        return ""
    return hashlib.sha256(value.encode()).hexdigest()
