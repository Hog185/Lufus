import psutil
import hashlib
from pathlib import Path
import os
from lufus.lufus_logging import get_logger

log = get_logger(__name__)


def _is_valid_sha256_hex(hash_value: str) -> bool:
    normalized = hash_value.strip().lower()
    if len(normalized) != 64:
        return False
    return all(char in "0123456789abcdef" for char in normalized)


def check_iso_signature(file_path: str) -> bool:
    """
    Validate ISO9660 Primary Volume Descriptor at sector 16.
    Offsets:
      32768: volume descriptor type (0x01 for PVD)
      32769-32773: standard identifier 'CD001'
      32774: version (0x01)
    """
    p = Path(file_path)
    if not p.is_file():
        log.error("ISO signature check: %s is not a valid file", file_path)
        return False

    file_size = p.stat().st_size
    log.info("ISO signature check: opening %s (%d bytes)", file_path, file_size)

    try:
        with p.open("rb") as f:
            f.seek(32768)
            data = f.read(7)
            if len(data) < 7:
                log.error(
                    "ISO signature check: file too small to contain a PVD (read %d bytes at offset 32768, need 7)",
                    len(data),
                )
                return False

            vd_type, ident, version = data[0], data[1:6], data[6]
            log.info(
                "ISO signature check: PVD bytes -> type=0x%02X, ident=%s, version=0x%02X",
                vd_type,
                ident,
                version,
            )

            if vd_type == 0x01 and ident == b"CD001" and version == 0x01:
                log.info("ISO signature check: PASSED for %s", file_path)
                return True
            else:
                log.error(
                    "ISO signature check: FAILED - expected type=0x01/ident=CD001/version=0x01, "
                    "got type=0x%02X/ident=%s/version=0x%02X",
                    vd_type,
                    ident,
                    version,
                )
                return False
    except OSError as err:
        log.error("ISO signature check: OSError reading %s: %s", file_path, err)

    return False


def _parent_block_device(device_node: str) -> str | None:
    dev_name = os.path.basename(device_node)
    sys_class = Path("/sys/class/block") / dev_name

    try:
        parent_name = sys_class.resolve().parent.name
        if parent_name == dev_name:
            return device_node
        return f"/dev/{parent_name}"
    except OSError:
        return None


def _resolve_device_node(usb_mount_path: str) -> str | None:
    """Resolve a mount path to its underlying device node for dd."""
    normalized = os.path.normpath(usb_mount_path)
    log.info("Resolving device node for mount path: %s", normalized)
    for part in psutil.disk_partitions(all=True):
        if os.path.normpath(part.mountpoint) == normalized:
            result = _parent_block_device(part.device) or part.device
            log.info(
                "Resolved %s -> device=%s, raw block device=%s",
                normalized,
                part.device,
                result,
            )
            return result
    log.warning("Could not resolve device node for: %s", normalized)
    return None


def check_sha256(file_path: str, expected_hash: str) -> bool:
    """Check the SHA256 hash of a file against an expected value."""
    p = Path(file_path)
    if not p.is_file():
        log.error("SHA256 check: %s is not a valid file", file_path)
        return False

    file_size = p.stat().st_size
    log.info("SHA256 check: starting hash of %s (%d bytes)", file_path, file_size)

    normalized_expected_hash = expected_hash.strip().lower()
    if not _is_valid_sha256_hex(normalized_expected_hash):
        log.error("SHA256 check: provided expected hash is not valid 64-char hex")
        return False

    sha256 = hashlib.sha256()
    bytes_read = 0
    try:
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):  # 1MB chunks
                sha256.update(chunk)
                bytes_read += len(chunk)
        calculated_hash = sha256.hexdigest()
        log.info("SHA256 check: hashed %d bytes", bytes_read)
        log.info("SHA256 check: expected   %s", normalized_expected_hash)
        log.info("SHA256 check: calculated %s", calculated_hash)
        if calculated_hash == normalized_expected_hash:
            log.info("SHA256 check: MATCH for %s", file_path)
            return True
        else:
            log.error(
                "SHA256 check: MISMATCH for %s - file may be corrupted or tampered with",
                file_path,
            )
            return False
    except OSError as err:
        log.error("SHA256 check: OSError reading %s: %s", file_path, err)

    return False


# to the person that reads this: may you have a good day <3
# love, koyo
