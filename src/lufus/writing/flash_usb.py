import os
import re
import shlex
import subprocess
from lufus.utils import strip_partition_suffix
from lufus.writing.check_file_sig import check_iso_signature
from lufus.writing.windows.detect import is_windows_iso
from lufus.writing.windows.flash import flash_windows
from lufus.lufus_logging import get_logger
from lufus.writing.partition_scheme import PartitionScheme

log = get_logger(__name__)


# TODO: Decide if these are needed — currently never called in this module
# def pkexec_not_found():
#     log.error("The command pkexec or labeling software was not found on your system.")
#
# def format_fail():
#     log.error("Formatting failed. Was the password correct? Is the drive unmounted?")
#
# def log_unexpected_error():
#     log.error("An unexpected error occurred")


def flash_usb(
    device: str, iso_path: str, scheme: PartitionScheme = PartitionScheme.SIMPLE_FAT32, progress_cb=None, status_cb=None
) -> bool:
    def _status(msg: str) -> None:
        log.info(msg)
        if status_cb:
            status_cb(msg)

    _status(f"flash_usb called: iso={iso_path}, device={device}")

    original_device = device
    device = strip_partition_suffix(device)
    if device != original_device:
        _status(f"Stripped partition suffix: {original_device} -> {device}")

    try:
        iso_size = os.path.getsize(iso_path)
        _status(f"File size: {iso_size:,} bytes ({iso_size / (1024**3):.2f} GiB)")

        if iso_path.lower().endswith(".iso"):
            _status(f"Validating ISO9660 signature for: {iso_path}")
            if not check_iso_signature(iso_path):
                log.error("ISO signature check FAILED for %s, aborting flash", iso_path)
                _status(f"ISO signature check FAILED for {iso_path}, aborting flash")
                return False
            _status("ISO signature check passed")
        else:
            _status(f"Not an ISO file ({os.path.basename(iso_path)}), skipping ISO signature check")

        _status("Checking if image contains installation markers...")
        if is_windows_iso(iso_path):
            _status("OS Installation media detected, routing to flash_windows (ISO mode)")
            return flash_windows(
                device,
                iso_path,
                scheme,
                progress_cb=progress_cb,
                status_cb=status_cb,
            )
        else:
            _status("Not a Windows ISO, will use dd for flashing")

        dd_args = [
            "dd",
            f"if={shlex.quote(iso_path)}",
            f"of={shlex.quote(device)}",
            "bs=4M",
            "status=progress",
            "conv=fsync",
            "oflag=direct",
        ]

        _status(f"Spawning dd: {' '.join(dd_args)}")
        _status(f"Writing {iso_size:,} bytes to {device}, this may take several minutes...")

        try:
            process = subprocess.Popen(dd_args, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL)
        except FileNotFoundError:
            log.error("Flash failed: 'dd' utility not found. Install coreutils.")
            _status("Flash failed: 'dd' utility not found. Install coreutils.")
            return False

        _status(f"dd process started with PID {process.pid}")

        buf = b""
        last_pct = -1
        while True:
            chunk = process.stderr.readline()
            if not chunk:
                break
            buf += chunk
            parts = re.split(rb"[\r\n]", buf)
            buf = parts[-1]
            for line in parts[:-1]:
                line = line.strip()
                if not line:
                    continue
                m = re.match(rb"^(\d+)\s+bytes", line)
                if m and iso_size > 0:
                    bytes_done = int(m.group(1))
                    pct = min(int(bytes_done * 100 / iso_size), 99)
                    if pct != last_pct:
                        _status(f"dd progress: {bytes_done:,} / {iso_size:,} bytes ({pct}%)")
                        last_pct = pct
                    if progress_cb:
                        progress_cb(pct)
                else:
                    log.warning("dd stderr: %s", line.decode("utf-8", errors="replace"))

        process.wait()
        _status(f"dd process exited with return code {process.returncode}")

        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, dd_args)

        _status(f"dd completed successfully: {iso_path} -> {device}")
        return True

    except OSError as e:
        log.error("Flash failed with OSError: %s", e)
        _status(f"Flash failed with OSError: {e}")
        return False
    except subprocess.CalledProcessError as e:
        log.error(
            "Flash failed with CalledProcessError: returncode=%d, cmd=%s",
            e.returncode,
            e.cmd,
        )
        _status(f"Flash failed with CalledProcessError: returncode={e.returncode}, cmd={e.cmd}")
        return False
