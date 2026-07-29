"""Strict Ed25519 signing contract for desktop update descriptors."""

import base64
import copy
import json
import re
from datetime import datetime

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


TRUSTED_ASSETS = {
    "windows-x64": (
        "Windows x64",
        "Backchannel-windows-x64.zip",
        "application/zip",
    ),
    "macos-arm64": (
        "macOS arm64",
        "Backchannel-macos-arm64.zip",
        "application/zip",
    ),
    "linux-x64": (
        "Linux x64",
        "Backchannel-linux-x64.tar.gz",
        "application/gzip",
    ),
}
VERSION_RE = re.compile(
    r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"
)
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
KEY_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
SIGNATURE_RE = re.compile(r"^[A-Za-z0-9_-]{86}$")
RAW_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
PUBLIC_FIELDS = {
    "version",
    "commit",
    "published_at",
    "release_notes",
    "asset",
    "key_id",
    "schema",
}


def _exact_dict(value: object, keys: set[str], label: str) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"invalid {label}")
    return value


def _version_parts(value: object, *, installed: bool = False) -> tuple[int, int, int]:
    if installed and isinstance(value, str) and not value.startswith("v"):
        value = f"v{value}"
    match = VERSION_RE.fullmatch(value) if isinstance(value, str) else None
    if not match:
        raise ValueError("invalid version")
    return tuple(map(int, match.groups()))


def _validate_timestamp(value: object) -> str:
    if not isinstance(value, str) or not TIMESTAMP_RE.fullmatch(value):
        raise ValueError("invalid published timestamp")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise ValueError("invalid published timestamp") from error
    return value


def _validate_notes(value: object) -> str:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 8192:
        raise ValueError("invalid release notes")
    return value


def _validate_asset(value: object, version: str, *, private: bool) -> dict:
    public_keys = {"id", "platform", "filename", "size", "sha256"}
    keys = public_keys | ({"key", "content_type"} if private else set())
    asset = _exact_dict(value, keys, "asset")
    trusted = TRUSTED_ASSETS.get(asset["id"])
    if (
        trusted is None
        or asset["platform"] != trusted[0]
        or asset["filename"] != trusted[1]
        or type(asset["size"]) is not int
        or asset["size"] <= 0
        or not isinstance(asset["sha256"], str)
        or not HASH_RE.fullmatch(asset["sha256"])
    ):
        raise ValueError("invalid trusted asset")
    if private and (
        asset["key"] != f"releases/{version}/{trusted[1]}"
        or asset["content_type"] != trusted[2]
    ):
        raise ValueError("invalid private asset metadata")
    return asset


def _validate_unsigned_descriptor(value: object) -> dict:
    descriptor = _exact_dict(value, PUBLIC_FIELDS, "update descriptor")
    _version_parts(descriptor["version"])
    if not isinstance(descriptor["commit"], str) or not COMMIT_RE.fullmatch(
        descriptor["commit"]
    ):
        raise ValueError("invalid commit")
    _validate_timestamp(descriptor["published_at"])
    _validate_notes(descriptor["release_notes"])
    _validate_asset(descriptor["asset"], descriptor["version"], private=False)
    if (
        not isinstance(descriptor["key_id"], str)
        or not KEY_ID_RE.fullmatch(descriptor["key_id"])
    ):
        raise ValueError("invalid key id")
    if type(descriptor["schema"]) is not int or descriptor["schema"] != 1:
        raise ValueError("invalid schema")
    return descriptor


def canonical_update_bytes(descriptor: dict) -> bytes:
    """Return the only byte representation accepted for update signatures."""
    _validate_unsigned_descriptor(descriptor)
    return json.dumps(
        descriptor, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _encode_signature(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode_signature(value: object) -> bytes:
    if not isinstance(value, str) or not SIGNATURE_RE.fullmatch(value):
        raise ValueError("invalid signature")
    try:
        decoded = base64.b64decode(value + "==", altchars=b"-_", validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError("invalid signature") from error
    if len(decoded) != 64:
        raise ValueError("invalid signature")
    return decoded


def _decode_raw_key(value: object) -> bytes:
    if not isinstance(value, str) or not RAW_KEY_RE.fullmatch(value):
        raise ValueError("invalid public key")
    try:
        decoded = base64.b64decode(value + "=", altchars=b"-_", validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError("invalid public key") from error
    if len(decoded) != 32:
        raise ValueError("invalid public key")
    return decoded


def parse_release_signing_keys(value: object) -> tuple[str, dict[str, bytes]]:
    """Parse the exact checked-in public-key document."""
    document = _exact_dict(value, {"active", "keys"}, "signing key document")
    if not isinstance(document["active"], str):
        raise ValueError("invalid active key")
    raw_keys = document["keys"]
    if not isinstance(raw_keys, dict) or not raw_keys:
        raise ValueError("invalid signing keys")
    keys = {}
    for key_id, encoded in raw_keys.items():
        if not isinstance(key_id, str) or not KEY_ID_RE.fullmatch(key_id):
            raise ValueError("invalid key id")
        keys[key_id] = _decode_raw_key(encoded)
    if document["active"] not in keys:
        raise ValueError("active key is not present")
    return document["active"], keys


def _public_from_manifest(manifest: dict, *, include_signature: bool) -> dict:
    asset = manifest["asset"]
    descriptor = {
        "version": manifest["version"],
        "commit": manifest["commit"],
        "published_at": manifest["published_at"],
        "release_notes": manifest["release_notes"],
        "asset": {
            key: asset[key]
            for key in ("id", "platform", "filename", "size", "sha256")
        },
        "key_id": manifest["update"]["key_id"],
        "schema": manifest["update"]["schema"],
    }
    if include_signature:
        descriptor["signature"] = manifest["update"]["signature"]
    return descriptor


def _validated_platform_manifest(manifest: dict) -> dict:
    source = _exact_dict(
        manifest,
        {"version", "commit", "published_at", "release_notes", "asset"},
        "platform manifest",
    )
    _version_parts(source["version"])
    if not isinstance(source["commit"], str) or not COMMIT_RE.fullmatch(
        source["commit"]
    ):
        raise ValueError("invalid commit")
    _validate_timestamp(source["published_at"])
    _validate_notes(source["release_notes"])
    _validate_asset(source["asset"], source["version"], private=True)
    return source


def platform_signing_request(manifest: dict, key_id: str) -> tuple[dict, bytes]:
    """Build the public descriptor and bytes for detached signing."""
    unsigned = _validated_platform_manifest(manifest)
    if not isinstance(key_id, str) or not KEY_ID_RE.fullmatch(key_id):
        raise ValueError("invalid key id")

    signed = copy.deepcopy(unsigned)
    signed["update"] = {"key_id": key_id, "schema": 1}
    descriptor = _public_from_manifest(signed, include_signature=False)
    return descriptor, canonical_update_bytes(descriptor)


def attach_platform_signature(
    manifest: dict, key_id: str, signature: str, public_key: bytes
) -> dict:
    """Validate and attach a detached Ed25519 signature."""
    _, request = platform_signing_request(manifest, key_id)
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(
            _decode_signature(signature), request
        )
    except InvalidSignature as error:
        raise ValueError("invalid update signature") from error

    signed = copy.deepcopy(manifest)
    signed["update"] = {"key_id": key_id, "schema": 1, "signature": signature}
    return signed


def sign_platform_manifest(manifest: dict, key_id: str, private_key: bytes) -> dict:
    """Validate and sign one immutable progressive platform manifest."""
    if not isinstance(private_key, bytes) or len(private_key) != 32:
        raise ValueError("invalid private key")

    _, request = platform_signing_request(manifest, key_id)
    signed = copy.deepcopy(manifest)
    signed["update"] = {"key_id": key_id, "schema": 1}
    signed["update"]["signature"] = _encode_signature(
        Ed25519PrivateKey.from_private_bytes(private_key).sign(request)
    )
    return signed


def public_update_descriptor(manifest: dict) -> dict:
    """Remove private object metadata from a signed platform manifest."""
    signed = _exact_dict(
        manifest,
        {
            "version",
            "commit",
            "published_at",
            "release_notes",
            "asset",
            "update",
        },
        "signed platform manifest",
    )
    _validate_asset(signed["asset"], signed["version"], private=True)
    update = _exact_dict(
        signed["update"], {"key_id", "schema", "signature"}, "update signature"
    )
    descriptor = _public_from_manifest(signed, include_signature=True)
    _validate_unsigned_descriptor(
        {key: value for key, value in descriptor.items() if key != "signature"}
    )
    _decode_signature(update["signature"])
    return descriptor


def verify_update_descriptor(
    descriptor: object,
    platform_id: str,
    current_version: str,
    public_keys: dict[str, bytes],
) -> dict:
    """Verify a newer descriptor for the exact expected desktop platform."""
    value = _exact_dict(
        descriptor, PUBLIC_FIELDS | {"signature"}, "signed update descriptor"
    )
    unsigned = {key: value[key] for key in PUBLIC_FIELDS}
    _validate_unsigned_descriptor(unsigned)
    if platform_id not in TRUSTED_ASSETS or value["asset"]["id"] != platform_id:
        raise ValueError("update platform does not match")
    if _version_parts(value["version"]) <= _version_parts(
        current_version, installed=True
    ):
        raise ValueError("update must be newer than installed version")
    if not isinstance(public_keys, dict) or value["key_id"] not in public_keys:
        raise ValueError("unknown update key")
    public_key = public_keys[value["key_id"]]
    if not isinstance(public_key, bytes) or len(public_key) != 32:
        raise ValueError("invalid public key")
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(
            _decode_signature(value["signature"]),
            canonical_update_bytes(unsigned),
        )
    except InvalidSignature as error:
        raise ValueError("invalid update signature") from error
    return copy.deepcopy(value)
