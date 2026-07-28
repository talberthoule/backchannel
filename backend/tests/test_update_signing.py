import base64
import copy
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.services.update_signing import (
    canonical_update_bytes,
    parse_release_signing_keys,
    public_update_descriptor,
    sign_platform_manifest,
    verify_update_descriptor,
)


PRIVATE = bytes(range(1, 33))
PUBLIC = Ed25519PrivateKey.from_private_bytes(PRIVATE).public_key().public_bytes(
    serialization.Encoding.Raw,
    serialization.PublicFormat.Raw,
)
MANIFEST = {
    "version": "v1.2.3",
    "commit": "b" * 40,
    "published_at": "2026-07-26T18:00:00Z",
    "release_notes": "Security and reliability fixes.",
    "asset": {
        "id": "windows-x64",
        "platform": "Windows x64",
        "filename": "Backchannel-windows-x64.zip",
        "key": "releases/v1.2.3/Backchannel-windows-x64.zip",
        "size": 7,
        "sha256": "a" * 64,
        "content_type": "application/zip",
    },
}
UNSIGNED_DESCRIPTOR = {
    "version": MANIFEST["version"],
    "commit": MANIFEST["commit"],
    "published_at": MANIFEST["published_at"],
    "release_notes": MANIFEST["release_notes"],
    "asset": {
        key: MANIFEST["asset"][key]
        for key in ("id", "platform", "filename", "size", "sha256")
    },
    "key_id": "test-key",
    "schema": 1,
}


class UpdateSigningTests(unittest.TestCase):
    def signed_descriptor(self):
        return public_update_descriptor(
            sign_platform_manifest(MANIFEST, "test-key", PRIVATE)
        )

    def verify(self, descriptor, current_version="1.2.2", keys=None):
        return verify_update_descriptor(
            descriptor,
            "windows-x64",
            current_version,
            {"test-key": PUBLIC} if keys is None else keys,
        )

    def test_canonical_bytes_are_exact(self):
        self.assertEqual(
            canonical_update_bytes(UNSIGNED_DESCRIPTOR),
            b'{"asset":{"filename":"Backchannel-windows-x64.zip",'
            b'"id":"windows-x64","platform":"Windows x64",'
            b'"sha256":"' + b"a" * 64 + b'","size":7},'
            b'"commit":"' + b"b" * 40 + b'","key_id":"test-key",'
            b'"published_at":"2026-07-26T18:00:00Z",'
            b'"release_notes":"Security and reliability fixes.",'
            b'"schema":1,"version":"v1.2.3"}',
        )

    def test_signs_public_fields_and_verifies_a_copy(self):
        signed_manifest = sign_platform_manifest(MANIFEST, "test-key", PRIVATE)
        self.assertEqual(set(signed_manifest["update"]), {"key_id", "schema", "signature"})
        descriptor = public_update_descriptor(signed_manifest)
        verified = self.verify(descriptor)
        self.assertEqual(verified, descriptor)
        self.assertIsNot(verified, descriptor)
        self.assertEqual(
            base64.urlsafe_b64decode(descriptor["signature"] + "=="),
            Ed25519PrivateKey.from_private_bytes(PRIVATE).sign(
                canonical_update_bytes(UNSIGNED_DESCRIPTOR)
            ),
        )

    def test_rejects_tampered_signed_fields(self):
        signed = self.signed_descriptor()
        mutations = {
            "schema": lambda value: value.__setitem__("schema", 2),
            "boolean schema": lambda value: value.__setitem__("schema", True),
            "timestamp": lambda value: value.__setitem__(
                "published_at", "2026-07-27T18:00:00Z"
            ),
            "notes": lambda value: value.__setitem__("release_notes", "Other"),
            "size": lambda value: value["asset"].__setitem__("size", 8),
            "hash": lambda value: value["asset"].__setitem__("sha256", "c" * 64),
            "version": lambda value: value.__setitem__("version", "v1.2.4"),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                changed = copy.deepcopy(signed)
                mutate(changed)
                with self.assertRaises(ValueError):
                    self.verify(changed)

    def test_rejects_unknown_or_wrong_key_and_unsigned_descriptor(self):
        signed = self.signed_descriptor()
        with self.assertRaisesRegex(ValueError, "key"):
            self.verify(signed, keys={})
        wrong = Ed25519PrivateKey.generate().public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        with self.assertRaisesRegex(ValueError, "signature"):
            self.verify(signed, keys={"test-key": wrong})
        signed.pop("signature")
        with self.assertRaises(ValueError):
            self.verify(signed)

    def test_rejects_wrong_platform_filename_and_noncanonical_version(self):
        signed = self.signed_descriptor()
        with self.assertRaisesRegex(ValueError, "platform"):
            verify_update_descriptor(
                signed, "linux-x64", "v1.2.2", {"test-key": PUBLIC}
            )
        changed = copy.deepcopy(signed)
        changed["asset"]["filename"] = "wrong.zip"
        with self.assertRaises(ValueError):
            self.verify(changed)
        changed = copy.deepcopy(signed)
        changed["version"] = "v01.2.3"
        with self.assertRaisesRegex(ValueError, "version"):
            self.verify(changed)

    def test_rejects_downgrades_extra_fields_and_oversized_notes(self):
        signed = self.signed_descriptor()
        with self.assertRaisesRegex(ValueError, "newer"):
            self.verify(signed, current_version="v1.2.3")
        changed = copy.deepcopy(signed)
        changed["extra"] = True
        with self.assertRaises(ValueError):
            self.verify(changed)
        manifest = copy.deepcopy(MANIFEST)
        manifest["release_notes"] = "x" * 8193
        with self.assertRaisesRegex(ValueError, "release notes"):
            sign_platform_manifest(manifest, "test-key", PRIVATE)

    def test_parses_only_exact_public_key_documents(self):
        encoded = base64.urlsafe_b64encode(PUBLIC).rstrip(b"=").decode()
        self.assertEqual(
            parse_release_signing_keys(
                {"active": "test-key", "keys": {"test-key": encoded}}
            ),
            ("test-key", {"test-key": PUBLIC}),
        )
        with self.assertRaises(ValueError):
            parse_release_signing_keys(
                {"active": "test-key", "keys": {"test-key": encoded}, "extra": True}
            )
        with self.assertRaisesRegex(ValueError, "active"):
            parse_release_signing_keys(
                {"active": "missing", "keys": {"test-key": encoded}}
            )


if __name__ == "__main__":
    unittest.main()
