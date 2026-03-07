import os
import re
import subprocess
from lufus.writing.check_file_sig import _resolve_device_node
from lufus.writing.check_file_sig import check_iso_signature
from lufus.drives import find_usb as fu
from lufus.drives import states
from lufus.writing.detect_windows import is_windows_iso
from lufus.writing.flash_windows import flash_windows
from lufus.writing.flash_woeusb import flash_woeusb


def pkexecNotFound():
    print("Error: The command pkexec or labeling software was not found on your system.")

def FormatFail():
    print("Error: Formatting failed. Was the password correct? Is the drive unmounted?")

def unexpected():
    print("An unexpected error occurred")


def FlashUSB(iso_path, raw_device, progress_cb=None, status_cb=None) -> bool:
    print(raw_device)
    raw_device = re.sub(r"[0-9]+$", "", raw_device)
    print(raw_device)

    try:
        if not check_iso_signature(iso_path):
            print("INVALID ISO")
            return False

        if is_windows_iso(iso_path):
            print("Windows ISO detected")

            if states.currentflash == 0:
                print("ISO mode selected - using flash_windows")
                return flash_windows(
                    raw_device, iso_path,
                    progress_cb=progress_cb,
                    status_cb=status_cb,
                )
            elif states.currentflash == 1:
                print("Woe USB mode selected - using woeusb")
                return flash_woeusb(
                    raw_device, iso_path,
                    progress_cb=progress_cb,
                    status_cb=status_cb,
                )

        dd_args = [
            "dd",
            f"if={iso_path}",
            f"of={raw_device}",
            "bs=4M",
            "status=progress",
            "conv=fdatasync",
        ]

        print(f"Flashing with dd: {' '.join(dd_args)}")

        iso_size = os.path.getsize(iso_path)
        process = subprocess.Popen(dd_args, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL)

        buf = b""
        while True:
            chunk = process.stderr.read(256)
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
                if m and progress_cb and iso_size > 0:
                    bytes_done = int(m.group(1))
                    pct = min(int(bytes_done * 100 / iso_size), 99)
                    progress_cb(pct)

        process.wait()
        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, dd_args)

        print(f"Successfully flashed {iso_path} to {raw_device}")
        return True

    except subprocess.CalledProcessError as e:
        print(f"Flash failed: {e}")
        return False