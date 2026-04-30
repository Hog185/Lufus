from __future__ import annotations
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lufus.writing.check_file_sig import check_iso_signature, check_sha256


def test_check_sha256_returns_false_when_file_does_not_exist(tmp_path: Path) -> None:
    missing_file = tmp_path / "missing.iso"
    assert check_sha256(str(missing_file), "abc") is False


def test_check_sha256_returns_true_for_matching_hash(tmp_path: Path) -> None:
    iso_file = tmp_path / "sample.iso"
    content = b"lufus test content"
    iso_file.write_bytes(content)

    expected_hash = hashlib.sha256(content).hexdigest()

    assert check_sha256(str(iso_file), expected_hash) is True


def test_check_sha256_accepts_case_insensitive_expected_hash(tmp_path: Path) -> None:
    iso_file = tmp_path / "sample.iso"
    content = b"lufus test content"
    iso_file.write_bytes(content)

    expected_hash_upper = hashlib.sha256(content).hexdigest().upper()

    assert check_sha256(str(iso_file), expected_hash_upper) is True


def test_check_sha256_accepts_expected_hash_with_whitespace(tmp_path: Path) -> None:
    iso_file = tmp_path / "sample.iso"
    content = b"lufus test content"
    iso_file.write_bytes(content)

    expected_hash_with_spaces = f"  {hashlib.sha256(content).hexdigest()}\n"

    assert check_sha256(str(iso_file), expected_hash_with_spaces) is True


def test_check_sha256_returns_false_for_mismatched_hash(tmp_path: Path) -> None:
    iso_file = tmp_path / "sample.iso"
    iso_file.write_bytes(b"lufus test content")

    wrong_hash = "0" * 64

    assert check_sha256(str(iso_file), wrong_hash) is False


def test_check_sha256_returns_false_for_invalid_hash_length(tmp_path: Path) -> None:
    iso_file = tmp_path / "sample.iso"
    iso_file.write_bytes(b"lufus test content")

    assert check_sha256(str(iso_file), "abc123") is False


def test_check_sha256_returns_false_for_non_hex_hash(tmp_path: Path) -> None:
    iso_file = tmp_path / "sample.iso"
    iso_file.write_bytes(b"lufus test content")

    assert check_sha256(str(iso_file), "g" * 64) is False


def test_check_iso_signature_returns_false_when_file_does_not_exist(tmp_path: Path) -> None:
    missing_file = tmp_path / "missing.iso"
    assert check_iso_signature(str(missing_file)) is False


def test_check_iso_signature_returns_false_when_file_too_small(tmp_path: Path) -> None:
    iso_file = tmp_path / "small.iso"
    iso_file.write_bytes(b"tiny")

    assert check_iso_signature(str(iso_file)) is False


def test_check_iso_signature_returns_true_for_valid_pvd(tmp_path: Path) -> None:
    iso_file = tmp_path / "valid.iso"
    payload = bytearray(32768 + 7)
    payload[32768] = 0x01
    payload[32769:32774] = b"CD001"
    payload[32774] = 0x01
    iso_file.write_bytes(bytes(payload))

    assert check_iso_signature(str(iso_file)) is True


def test_check_iso_signature_returns_false_for_invalid_pvd(tmp_path: Path) -> None:
    iso_file = tmp_path / "invalid.iso"
    payload = bytearray(32768 + 7)
    payload[32768] = 0x02
    payload[32769:32774] = b"CD001"
    payload[32774] = 0x01
    iso_file.write_bytes(bytes(payload))

    assert check_iso_signature(str(iso_file)) is False
