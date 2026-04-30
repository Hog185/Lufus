import subprocess
import re
from lufus.lufus_logging import get_logger

log = get_logger(__name__)


def _read_iso_label(iso_path: str) -> str:
    try:
        with open(iso_path, "rb") as f:
            f.seek(32808)
            return f.read(32).decode("ascii", errors="replace").strip()
    except OSError:
        return ""


def _label_is_windows(label: str) -> bool:
    label = label.upper()
    if label.startswith("WIN"):
        return True
    if label == "ESD-ISO":
        return True
    if re.search(r"CC[A-Z]+_[A-Z0-9]+FRE_", label):
        return True
    return False


def is_windows_iso(iso_path: str) -> bool:
    log.info("Windows detection: checking %s", iso_path)

    label = _read_iso_label(iso_path)
    log.info("Windows detection: ISO volume label=%r", label)
    if label and _label_is_windows(label):
        log.info("Windows detection: Windows label match -> Windows ISO confirmed via ISO header")
        return True

    try:
        log.info("Windows detection: running 7z to list ISO contents...")
        result = subprocess.run(["7z", "l", iso_path], capture_output=True, text=True, timeout=30)
        log.info("Windows detection: 7z exited with code %d", result.returncode)
        if result.returncode == 0:
            files = result.stdout.lower()
            markers = [
                "sources/install.wim",
                "sources/install.esd",
                "sources/install.swm",
                "sources/boot.wim",
                "sources\\install.wim",
                "sources\\install.esd",
                "sources\\install.swm",
                "sources\\boot.wim",
            ]
            for marker in markers:
                if marker in files:
                    log.info(
                        "Windows detection: found marker %r in 7z listing -> Windows ISO confirmed",
                        marker,
                    )
                    return True
            log.info("Windows detection: none of the Windows markers found in 7z listing")
        else:
            log.warning("Windows detection: 7z stderr: %s", result.stderr.strip()[:200])
    except FileNotFoundError:
        log.warning("Windows detection: 7z not found - install p7zip-full: sudo apt install p7zip-full")
    except subprocess.TimeoutExpired:
        log.warning("Windows detection: 7z timed out listing ISO after 30s")
    except Exception as e:
        log.error("Windows detection: 7z unexpected error: %s: %s", type(e).__name__, e)

    log.info("Windows detection: falling back to blkid volume label check...")
    try:
        result = subprocess.run(
            ["sudo", "blkid", "-o", "value", "-s", "LABEL", iso_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        blkid_label = result.stdout.strip()
        log.info(
            "Windows detection: blkid returned label=%r (exit code %d)",
            blkid_label,
            result.returncode,
        )
        if _label_is_windows(blkid_label):
            log.info("Windows detection: Windows label match -> Windows ISO confirmed via blkid")
            return True
        log.info("Windows detection: label does not match Windows patterns")
    except Exception as e:
        log.error("Windows detection: blkid error: %s: %s", type(e).__name__, e)

    log.info("Windows detection: result -> NOT a Windows ISO")
    return False
