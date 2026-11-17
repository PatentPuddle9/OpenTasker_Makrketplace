#!/usr/bin/env python3
"""Focused security regression tests for Marketplace image uploads."""

from __future__ import annotations

import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from validate_marketplace import validate_png


def png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def sample_png(extra_chunks: tuple[tuple[bytes, bytes], ...] = (), width: int = 1, height: int = 1) -> bytes:
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    pixels = b"\x00" + bytes([255, 0, 0, 255]) * width
    compressed = zlib.compress(pixels * height)
    chunks = [png_chunk(b"IHDR", ihdr)]
    chunks.extend(png_chunk(kind, data) for kind, data in extra_chunks)
    chunks.extend([png_chunk(b"IDAT", compressed), png_chunk(b"IEND", b"")])
    return b"\x89PNG\r\n\x1a\n" + b"".join(chunks)


class MarketplacePngSecurityTests(unittest.TestCase):
    def validate(self, payload: bytes, max_bytes: int = 2 * 1024 * 1024) -> list[str]:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "image.png"
            path.write_bytes(payload)
            return validate_png(path, max_bytes, "test.png")

    def test_accepts_plain_png(self):
        self.assertEqual(self.validate(sample_png()), [])

    def test_rejects_exif_and_text_metadata(self):
        for kind, payload in (
            (b"eXIf", b"private metadata"),
            (b"tEXt", b"Comment\x00private text"),
            (b"zTXt", b"Comment\x00\x00compressed"),
            (b"iTXt", b"Comment\x00\x00\x00\x00\x00private text"),
            (b"tIME", b"\x07\xea\x0b\x11\x0c\x00\x00"),
            (b"iCCP", b"profile\x00\x00profile-data"),
        ):
            with self.subTest(chunk=kind):
                errors = self.validate(sample_png(((kind, payload),)))
                self.assertTrue(errors)
                self.assertIn("metadata-bearing", errors[0])

    def test_rejects_invalid_chunk_checksum(self):
        payload = bytearray(sample_png())
        payload[29] ^= 0x01
        errors = self.validate(bytes(payload))
        self.assertTrue(errors)
        self.assertIn("checksum", errors[0])

    def test_rejects_oversized_dimensions(self):
        errors = self.validate(sample_png(width=2049, height=1))
        self.assertTrue(errors)
        self.assertIn("dimensions", errors[0])

    def test_rejects_trailing_bytes(self):
        errors = self.validate(sample_png() + b"extra")
        self.assertTrue(errors)
        self.assertIn("trailing data", errors[0])

    def test_rejects_files_over_limit(self):
        errors = self.validate(sample_png(), max_bytes=32)
        self.assertTrue(errors)
        self.assertIn("between 45 bytes", errors[0])


if __name__ == "__main__":
    unittest.main()
