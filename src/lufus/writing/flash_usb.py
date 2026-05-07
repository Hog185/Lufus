import os
import re
import shlex
import subprocess
from lufus.utils import strip_partition_suffix
from lufus.writing.check_file_sig import check_iso_signature
from lufus.writing.windows.detect import detect_iso_type, IsoType, is_windows_iso
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

    # Strip any partition suffix first (e.g. /dev/nvme0n1p1 -> /dev/nvme0n1,
    # /dev/sdb1 -> /dev/sdb) so that validation operates on the whole-disk path.
    original_device = device
    device = strip_partition_suffix(device)
    if device != original_device:
        _status(f"Stripped partition suffix: {original_device} -> {device}")

    # Validate the (already-stripped) device path before any operation —
    # prevents accidental writes to system disks if a bad options file or
    # UI bug passes a wrong path.
    if not re.match(r"^/dev/(sd[a-z]+|nvme[0-9]+n[0-9]+|mmcblk[0-9]+)$", device):
        log.error("flash_usb: invalid device path %r — aborting", device)
        _status(f"Flash aborted: invalid device path {device!r}")
        return False

    try:
        iso_size = os.path.getsize(iso_path)
        _status(f"File size: {iso_size:,} bytes ({iso_size / (1024**3):.2f} GiB)")
        if progress_cb:
            progress_cb(2)

        if iso_path.lower().endswith(".iso"):
            _status(f"Validating ISO9660 signature for: {iso_path}")
            if not check_iso_signature(iso_path):
                log.error("ISO signature check FAILED for %s, aborting flash", iso_path)
                _status(f"ISO signature check FAILED for {iso_path}, aborting flash")
                return False
            _status("ISO signature check passed")
        else:
            _status(f"Not an ISO file ({os.path.basename(iso_path)}), skipping ISO signature check")

        if progress_cb:
            progress_cb(5)

        _status("Checking if image contains installation markers...")
        iso_type = detect_iso_type(iso_path)
        if progress_cb:
            progress_cb(8)

        if iso_type == IsoType.WINDOWS:
            _status("Windows Installation media detected, routing to flash_windows (ISO mode)")
            return flash_windows(
                device,
                iso_path,
                scheme,
                progress_cb=progress_cb,
                status_cb=status_cb,
            )

        if iso_type == IsoType.LINUX:
            _status("Linux Installation media detected, will use dd for flashing")
        else:
            _status("Generic or unknown image, will use dd for flashing")

        if progress_cb:
            progress_cb(10)

        dd_args = [
            "dd",
            f"if={iso_path}",
            f"of={device}",
            "bs=4M",
            "status=progress",
            "conv=fsync",
            "oflag=direct",
        ]

        _status(f"Spawning dd: {' '.join(dd_args)}")
        _status(f"Writing {iso_size:,} bytes to {shlex.quote(device)}, this may take several minutes...")

        try:
            # Use LC_ALL=C to ensure "bytes" is the keyword for progress parsing
            # and set a consistent output format across different locales.
            env = os.environ.copy()
            env["LC_ALL"] = "C"
            process = subprocess.Popen(dd_args, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, env=env)
        except FileNotFoundError:
            log.error("Flash failed: 'dd' utility not found. Install coreutils.")
            _status("Flash failed: 'dd' utility not found. Install coreutils.")
            return False

        _status(f"dd process started with PID {process.pid}")

        buf = b""
        last_pct = -1
        while True:
            # Read in small chunks to handle \r progress updates from dd without blocking
            # until a newline (\n) is received. status=progress usually emits \r.
            try:
                chunk = process.stderr.read(128)
            except Exception as e:
                log.warning("Error reading dd stderr: %s", e)
                break

            if not chunk:
                break
            buf += chunk
            # Split by \r or \n to catch all progress updates
            parts = re.split(rb"[\r\n]", buf)
            # The last part might be incomplete, keep it in the buffer
            buf = parts[-1]

            for line in parts[:-1]:
                line = line.strip()
                if not line:
                    continue
                m = re.match(rb"^(\d+)\s+bytes", line)
                if m and iso_size > 0:
                    bytes_done = int(m.group(1))
                    # Scale progress to 10-95% range to leave room for early steps and final sync
                    pct_raw = min(int(bytes_done * 100 / iso_size), 100)
                    pct = 10 + int(pct_raw * 0.85)

                    if pct != last_pct:
                        _status(f"dd progress: {bytes_done:,} / {iso_size:,} bytes ({pct_raw}%)")
                        last_pct = pct
                    if progress_cb:
                        progress_cb(pct)
                else:
                    # Filter out common dd output lines to avoid logging noise
                    line_str = line.decode("utf-8", errors="replace")
                    if not any(x in line_str for x in ["records in", "records out", "copied"]):
                        log.warning("dd stderr: %s", line_str)

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
