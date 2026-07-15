"""Build deterministic identity and one immutable platform manifest."""

import argparse
from pathlib import Path

from build_release_manifest import (
    _json_bytes,
    build_platform_manifest,
    build_release_identity,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset", type=Path, required=True)
    parser.add_argument("--platform-id", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--published-at", required=True)
    parser.add_argument("--release-out", type=Path, required=True)
    parser.add_argument("--platform-out", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        release = build_release_identity(
            arguments.tag, arguments.commit, arguments.published_at
        )
        platform = build_platform_manifest(
            arguments.asset, arguments.tag, arguments.commit, arguments.platform_id
        )
    except ValueError as error:
        parser.error(str(error))
    arguments.release_out.parent.mkdir(parents=True, exist_ok=True)
    arguments.platform_out.parent.mkdir(parents=True, exist_ok=True)
    arguments.release_out.write_bytes(_json_bytes(release))
    arguments.platform_out.write_bytes(_json_bytes(platform))


if __name__ == "__main__":
    main()
