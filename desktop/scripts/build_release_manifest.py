"""Build deterministic metadata for immutable desktop releases."""

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path


CHUNK_SIZE = 1024 * 1024
VERSION_RE = re.compile(
    r"^(?=.{2,32}$)v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"
)
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
UTC_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:Z|\+00:00)$")
ASSETS = (
    ("windows-x64", "Windows x64", "Backchannel-windows-x64.zip", "application/zip"),
    ("macos-arm64", "macOS arm64", "Backchannel-macos-arm64.zip", "application/zip"),
    ("linux-x64", "Linux x64", "Backchannel-linux-x64.tar.gz", "application/gzip"),
)
ASSETS_BY_ID = {asset[0]: asset for asset in ASSETS}


def _version(value: str, label: str = "tag") -> tuple[int, int, int]:
    match = VERSION_RE.fullmatch(value) if isinstance(value, str) else None
    if not match:
        raise ValueError(f"invalid canonical {label}: {value!r}")
    return tuple(map(int, match.groups()))


def _timestamp(value: str) -> str:
    if not isinstance(value, str) or not UTC_RE.fullmatch(value):
        raise ValueError("published timestamp must be strict UTC ISO-8601")
    canonical = value.removesuffix("+00:00") + ("Z" if value.endswith("+00:00") else "")
    try:
        datetime.strptime(canonical, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise ValueError(f"invalid published timestamp: {value!r}") from error
    return canonical


def _commit(value: str) -> str:
    if not isinstance(value, str) or not COMMIT_RE.fullmatch(value):
        raise ValueError("commit must be lowercase 40-hex")
    return value


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def build_release_identity(tag: str, commit: str, published_at: str) -> dict:
    _version(tag)
    return {
        "version": tag,
        "published_at": _timestamp(published_at),
        "commit": _commit(commit),
    }


def build_platform_manifest(
    asset_path: Path, tag: str, commit: str, platform_id: str
) -> dict:
    _version(tag)
    commit = _commit(commit)
    trusted = ASSETS_BY_ID.get(platform_id)
    if trusted is None:
        raise ValueError(f"invalid platform id: {platform_id!r}")
    asset_id, platform, filename, content_type = trusted
    path = Path(asset_path)
    if path.name != filename:
        raise ValueError(f"platform asset must use trusted filename: {filename}")
    if path.is_symlink():
        raise ValueError(f"release asset cannot be a symlink: {filename}")
    if not path.is_file():
        raise ValueError(f"release asset must be a regular file: {filename}")
    size = path.stat().st_size
    if size <= 0:
        raise ValueError(f"release asset cannot be empty: {filename}")
    return {
        "version": tag,
        "commit": commit,
        "asset": {
            "id": asset_id,
            "platform": platform,
            "filename": filename,
            "key": f"releases/{tag}/{filename}",
            "size": size,
            "sha256": _hash(path),
            "content_type": content_type,
        },
    }


def build_manifest(
    asset_dir: Path,
    tag: str,
    commit: str,
    published_at: str,
    allow_legacy_partial: bool = False,
) -> dict:
    """Validate release assets and return their trusted manifest."""
    _version(tag)
    _commit(commit)
    published_at = _timestamp(published_at)
    asset_dir = Path(asset_dir)
    if not asset_dir.is_dir():
        raise ValueError(f"asset directory does not exist: {asset_dir}")

    actual = {path.name for path in asset_dir.iterdir()}
    normal = {asset[2] for asset in ASSETS}
    legacy = {asset[2] for asset in ASSETS[:2]}
    expected = legacy if allow_legacy_partial else normal
    mode = "legacy Windows/macOS pair" if allow_legacy_partial else "exactly three release assets"
    if actual != expected:
        raise ValueError(f"asset directory must contain {mode}")

    assets = []
    for asset_id, platform, filename, content_type in ASSETS:
        if filename not in expected:
            continue
        path = asset_dir / filename
        if path.is_symlink():
            raise ValueError(f"release asset cannot be a symlink: {filename}")
        if not path.is_file():
            raise ValueError(f"release asset must be a regular file: {filename}")
        size = path.stat().st_size
        if size <= 0:
            raise ValueError(f"release asset cannot be empty: {filename}")
        assets.append(
            {
                "id": asset_id,
                "platform": platform,
                "filename": filename,
                "key": f"releases/{tag}/{filename}",
                "size": size,
                "sha256": _hash(path),
                "content_type": content_type,
            }
        )
    return {
        "version": tag,
        "published_at": published_at,
        "commit": commit,
        "assets": assets,
    }


def _validate_latest(path: Path, candidate: str) -> None:
    if not path.exists():
        return
    try:
        latest = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("current Latest is not valid JSON") from error
    if not isinstance(latest, dict) or set(latest) != {"version"}:
        raise ValueError("current Latest must be one-field JSON")
    current = _version(latest["version"], "Latest version")
    if _version(candidate) < current:
        raise ValueError(f"candidate {candidate} would regress Latest from {latest['version']}")


def _json_bytes(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"current Latest contains duplicate key: {key}")
        value[key] = item
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset-dir", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--published-at", required=True)
    parser.add_argument("--manifest-out", type=Path, required=True)
    parser.add_argument("--latest-out", type=Path, required=True)
    parser.add_argument("--current-latest", type=Path)
    parser.add_argument("--allow-legacy-partial", action="store_true")
    arguments = parser.parse_args()
    try:
        manifest = build_manifest(
            arguments.asset_dir,
            arguments.tag,
            arguments.commit,
            arguments.published_at,
            arguments.allow_legacy_partial,
        )
        if arguments.current_latest:
            _validate_latest(arguments.current_latest, arguments.tag)
    except ValueError as error:
        parser.error(str(error))

    arguments.manifest_out.parent.mkdir(parents=True, exist_ok=True)
    arguments.latest_out.parent.mkdir(parents=True, exist_ok=True)
    arguments.manifest_out.write_bytes(_json_bytes(manifest))
    arguments.latest_out.write_bytes(_json_bytes({"version": arguments.tag}))


if __name__ == "__main__":
    main()
