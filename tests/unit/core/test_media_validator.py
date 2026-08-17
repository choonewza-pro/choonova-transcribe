import struct
import unittest

from fastapi import HTTPException

from app.core.media_validator import (
    validate_extension,
    validate_magic_bytes,
    _is_isobmff_container,
)


def _ftyp_header(major_brand: bytes, compatible_brands: list = None) -> bytes:
    """Build a plausible ISO-BMFF `ftyp` header with the given major brand."""
    compatible_brands = compatible_brands or [b"M4A "]
    payload = major_brand + struct.pack(">I", 0) + b"".join(compatible_brands)
    box_size = 16 + 4 * len(compatible_brands)
    return struct.pack(">I", box_size) + b"ftyp" + payload


class TestValidateExtension(unittest.TestCase):
    def test_m4a_is_allowed(self):
        validate_extension("voice_note.m4a")

    def test_upper_case_extension_is_allowed(self):
        validate_extension("VOICE_NOTE.M4A")

    def test_unknown_extension_rejected(self):
        with self.assertRaises(HTTPException):
            validate_extension("evil.exe")

    def test_missing_filename_rejected(self):
        with self.assertRaises(HTTPException):
            validate_extension("")


class TestValidateMagicBytesM4a(unittest.TestCase):
    def test_standard_m4a_brand_accepted(self):
        mime = validate_magic_bytes(_ftyp_header(b"M4A "))
        self.assertTrue(mime.startswith("audio/") or mime.startswith("video/"))

    def test_isom_brand_accepted(self):
        mime = validate_magic_bytes(_ftyp_header(b"isom", [b"isom", b"mp42"]))
        self.assertTrue(mime.startswith("audio/") or mime.startswith("video/"))

    def test_mp42_brand_accepted(self):
        mime = validate_magic_bytes(_ftyp_header(b"mp42", [b"mp42", b"isom", b"M4A "]))
        self.assertTrue(mime.startswith("audio/") or mime.startswith("video/"))

    def test_m4b_brand_accepted_via_isobmff_fallback(self):
        mime = validate_magic_bytes(_ftyp_header(b"M4B "))
        self.assertEqual(mime, "audio/mp4")

    def test_m4v_brand_accepted_via_isobmff_fallback(self):
        mime = validate_magic_bytes(_ftyp_header(b"M4V "))
        self.assertEqual(mime, "audio/mp4")

    def test_3gp4_brand_accepted_via_isobmff_fallback(self):
        mime = validate_magic_bytes(_ftyp_header(b"3gp4"))
        self.assertEqual(mime, "audio/mp4")

    def test_leading_free_box_before_ftyp_accepted(self):
        header = struct.pack(">I", 16) + b"free" + bytes(8) + _ftyp_header(b"M4A ")
        self.assertTrue(_is_isobmff_container(header))
        mime = validate_magic_bytes(header)
        self.assertEqual(mime, "audio/mp4")

    def test_non_media_bytes_rejected(self):
        with self.assertRaises(HTTPException):
            validate_magic_bytes(b"this is definitely not a media file......" * 3)

    def test_short_empty_bytes_rejected(self):
        with self.assertRaises(HTTPException):
            validate_magic_bytes(b"")


class TestIsIsoBmffContainer(unittest.TestCase):
    def test_detects_ftyp_box(self):
        self.assertTrue(_is_isobmff_container(_ftyp_header(b"M4A ")))

    def test_no_ftyp_box(self):
        self.assertFalse(_is_isobmff_container(b"\x00" * 128))

    def test_empty_bytes(self):
        self.assertFalse(_is_isobmff_container(b""))


if __name__ == "__main__":
    unittest.main()