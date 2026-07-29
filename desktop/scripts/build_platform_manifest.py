"""Build deterministic identity and one immutable platform manifest."""

import argparse
import base64
import hmac
import json
import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.update_signing import (  # noqa: E402
    attach_platform_signature,
    parse_release_signing_keys,
    platform_signing_request,
    sign_platform_manifest,
)
from build_release_manifest import (
    _json_bytes,
    build_platform_manifest,
    build_release_identity,
)


def _private_key_from_environment() -> bytes:
    encoded = os.environ.get("BACKCHANNEL_RELEASE_SIGNING_PRIVATE_KEY", "")
    if not encoded:
        raise ValueError(
            "BACKCHANNEL_RELEASE_SIGNING_PRIVATE_KEY is required"
        )
    try:
        value = base64.b64decode(encoded + "=", altchars=b"-_", validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError("release signing private key is invalid") from error
    if len(value) != 32:
        raise ValueError("release signing private key is invalid")
    return value


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read signing keys: {path}") from error


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset", type=Path, required=True)
    parser.add_argument("--platform-id", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--published-at", required=True)
    parser.add_argument("--keys-file", type=Path)
    parser.add_argument("--release-notes-file", type=Path)
    parser.add_argument("--release-out", type=Path)
    parser.add_argument("--platform-out", type=Path)
    parser.add_argument("--signing-request-out", type=Path)
    parser.add_argument("--detached-key-id")
    parser.add_argument("--detached-signature")
    arguments = parser.parse_args()
    try:
        request_mode = arguments.signing_request_out is not None
        detached_mode = (
            arguments.detached_key_id is not None
            or arguments.detached_signature is not None
        )
        if request_mode and (
            detached_mode
            or arguments.release_out is not None
            or arguments.platform_out is not None
        ):
            raise ValueError("signing request mode writes only --signing-request-out")
        if request_mode is False and (
            arguments.release_out is None or arguments.platform_out is None
        ):
            raise ValueError("--release-out and --platform-out are required")
        if detached_mode and (
            arguments.detached_key_id is None
            or arguments.detached_signature is None
        ):
            raise ValueError("detached signing requires key id and signature")
        release = build_release_identity(
            arguments.tag, arguments.commit, arguments.published_at
        )
        keys_file = arguments.keys_file or ROOT / "desktop" / "release_signing_keys.json"
        notes_file = (
            arguments.release_notes_file
            or ROOT / ".github" / "release-notes" / f"{arguments.tag}.md"
        )
        key_id, public_keys = parse_release_signing_keys(_read_json(keys_file))
        try:
            release_notes = notes_file.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise ValueError(f"cannot read release notes: {notes_file}") from error
        unsigned_platform = build_platform_manifest(
            arguments.asset, arguments.tag, arguments.commit, arguments.platform_id
        )
        manifest = {
            **unsigned_platform,
            "published_at": release["published_at"],
            "release_notes": release_notes,
        }
        if request_mode:
            _, request = platform_signing_request(manifest, key_id)
        elif detached_mode:
            if arguments.detached_key_id != key_id:
                raise ValueError("detached key id is not the active key")
            platform = attach_platform_signature(
                manifest, key_id, arguments.detached_signature, public_keys[key_id]
            )
        else:
            private_key = _private_key_from_environment()
            derived_public = (
                Ed25519PrivateKey.from_private_bytes(private_key)
                .public_key()
                .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
            )
            if not hmac.compare_digest(derived_public, public_keys[key_id]):
                raise ValueError("release signing private key does not match active key")
            platform = sign_platform_manifest(manifest, key_id, private_key)
    except ValueError as error:
        parser.error(str(error))
    if request_mode:
        arguments.signing_request_out.parent.mkdir(parents=True, exist_ok=True)
        arguments.signing_request_out.write_bytes(request)
        return
    arguments.release_out.parent.mkdir(parents=True, exist_ok=True)
    arguments.platform_out.parent.mkdir(parents=True, exist_ok=True)
    arguments.release_out.write_bytes(_json_bytes(release))
    arguments.platform_out.write_bytes(_json_bytes(platform))


if __name__ == "__main__":
    main()
