import os
import re
import subprocess
from lufus.writing.check_file_sig import _resolve_device_node
from lufus.writing.check_file_sig import check_iso_signature
from lufus.drives import find_usb as fu
from lufus.drives import states
from lufus.writing.detect_windows import is_windows_iso
from lufus.writing.flash_windows import flash_windows


def pkexecNotFound():
    print(
        "Error: The command pkexec or labeling software was not found on your system."
    )


def FormatFail():
    print("Error: Formatting failed. Was the password correct? Is the drive unmounted?")


def unexpected():
    print("An unexpected error occurred")


def _strip_partition_suffix(device: str) -> str:  # [ANNOTATION] Extract helper so NVMe/MMC/SCSI stripping is testable in isolation.
    """Strip a partition number suffix to get the raw block device.

    Handles NVMe (/dev/nvme0n1p1 -> /dev/nvme0n1), MMC
    (/dev/mmcblk0p1 -> /dev/mmcblk0), and standard SCSI/SATA/USB
    (/dev/sdb1 -> /dev/sdb). Returns the input unchanged if no
    partition suffix is found.
    """
    # NVMe: /dev/nvmeXnYpZ -> /dev/nvmeXnY
    m = re.match(r"^(/dev/nvme\d+n\d+)p\d+$", device)  # [ANNOTATION] Dedicated NVMe pattern prevents stripping 'n1' number from device name.
    if m:
        return m.group(1)
    # MMC/eMMC: /dev/mmcblkXpY -> /dev/mmcblkX
    m = re.match(r"^(/dev/mmcblk\d+)p\d+$", device)  # [ANNOTATION] Dedicated MMC pattern handles 'p' separator correctly.
    if m:
        return m.group(1)
    # Standard SCSI/SATA/USB: /dev/sdXN -> /dev/sdX
    m = re.match(r"^(/dev/[a-z]+)\d+$", device)  # [ANNOTATION] Restrict to letter-only base name so numeric device names aren't mangled.
    if m:
        return m.group(1)
    return device


def FlashUSB(iso_path: str, raw_device: str, progress_cb=None, status_cb=None) -> bool:  # [ANNOTATION] Add type hints to public function signature for clarity.
    def _status(msg: str) -> None:
        print(msg)
        if status_cb:
            status_cb(msg)

    _status(f"FlashUSB called: iso={iso_path}, device={raw_device}")

    original_device = raw_device
    raw_device = _strip_partition_suffix(raw_device)  # [ANNOTATION] Use dedicated helper instead of bare re.sub which broke NVMe device names.
    if raw_device != original_device:
        _status(f"Stripped partition suffix: {original_device} -> {raw_device}")

    try:
        iso_size = os.path.getsize(iso_path)
        _status(f"File size: {iso_size:,} bytes ({iso_size / (1024**3):.2f} GiB)")

        if iso_path.lower().endswith(".iso"):
            _status(f"Validating ISO9660 signature for: {iso_path}")
            if not check_iso_signature(iso_path):
                _status(f"ISO signature check FAILED for {iso_path}, aborting flash")
                return False
            _status("ISO signature check passed")
        else:
            _status(f"Not an ISO file ({os.path.basename(iso_path)}), skipping ISO signature check")

        _status("Checking if image contains installation markers...")
        if is_windows_iso(iso_path):
            _status("OS Installation media detected, routing to flash_windows (ISO mode)")
            return flash_windows(
                raw_device,
                iso_path,
                progress_cb=progress_cb,
                status_cb=status_cb,
            )
        else:
            _status("Not a Windows ISO, will use dd for flashing")

        dd_args = [
            "dd",
            f"if={iso_path}",
            f"of={raw_device}",
            "bs=4M",
            "status=progress",
            "conv=fsync",
            "oflag=direct",
        ]

        _status(f"Spawning dd: {' '.join(dd_args)}")
        _status(
            f"Writing {iso_size:,} bytes to {raw_device}, this may take several minutes..."
        )

        try:  # [ANNOTATION] Wrap Popen in inner try so FileNotFoundError returns False instead of propagating.
            process = subprocess.Popen(
                dd_args, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL
            )
        except FileNotFoundError:  # [ANNOTATION] Catch missing 'dd' binary explicitly and return False gracefully.
            _status("Flash failed: 'dd' utility not found. Install coreutils.")
            return False

        _status(f"dd process started with PID {process.pid}")

        buf = b""
        last_pct = -1
        while True:
            chunk = process.stderr.readline()  # [ANNOTATION] Use readline() instead of read(256) to avoid partial-line parsing and potential blocking on exit.
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
                        _status(
                            f"dd progress: {bytes_done:,} / {iso_size:,} bytes ({pct}%)"
                        )
                        last_pct = pct
                    if progress_cb:
                        progress_cb(pct)

        process.wait()
        _status(f"dd process exited with return code {process.returncode}")

        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, dd_args)

        _status(f"dd completed successfully: {iso_path} -> {raw_device}")
        return True

    except OSError as e:  # [ANNOTATION] Catch OSError from os.path.getsize (missing file) so callers always get False not an exception.
        _status(f"Flash failed with OSError: {e}")
        return False
    except subprocess.CalledProcessError as e:
        _status(
            f"Flash failed with CalledProcessError: returncode={e.returncode}, cmd={e.cmd}"
        )
        return False
