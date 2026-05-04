import sys
from pathlib import Path
from PyQt6.QtCore import QThread, pyqtSignal
from lufus.writing.partition_scheme import PartitionScheme


class VerifyWorker(QThread):
    # worker thread for sha256 verification >:D
    progress = pyqtSignal(str)
    int_progress = pyqtSignal(int)
    flash_done = pyqtSignal(bool)

    def __init__(self, iso_path: str, expected_hash: str):
        super().__init__()
        # store paths for verification
        self.iso_path = iso_path
        self.expected_hash = expected_hash

    def run(self):
        # run verification in background thread :3
        try:
            import hashlib

            p = Path(self.iso_path)
            if not p.is_file():
                self.progress.emit(f"Verification error: file not found: {self.iso_path}")
                self.flash_done.emit(False)
                return
            file_size = p.stat().st_size
            self.progress.emit(f"Verifying SHA256 checksum for {self.iso_path}...")
            normalized = self.expected_hash.strip().lower()
            sha256 = hashlib.sha256()
            bytes_read = 0
            with p.open("rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    sha256.update(chunk)
                    bytes_read += len(chunk)
                    pct = min(int(bytes_read * 100 / file_size), 99) if file_size > 0 else 0
                    self.int_progress.emit(pct)
            calculated = sha256.hexdigest()
            if calculated != normalized:
                self.progress.emit(f"SHA256 mismatch: expected {normalized}, got {calculated}")
            self.flash_done.emit(calculated == normalized)
        except Exception as e:
            self.progress.emit(f"Verification error: {str(e)}")
            self.flash_done.emit(False)


class FlashWorker(QThread):
    # worker thread for usb flashing operation meow
    progress = pyqtSignal(int)
    status = pyqtSignal(str)
    flash_done = pyqtSignal(bool)
    request_tweaks = pyqtSignal()

    def __init__(self, options: dict, t: dict):
        super().__init__()
        # store options for flashing
        self.options = options
        self._T = t

    def run(self):
        # run flash operation in background thread
        _saved_stdout = sys.stdout
        sys.stdout = sys.__stdout__
        try:
            from lufus import state as states
            from lufus.drives import formatting as fo
            from lufus.writing.flash_usb import flash_usb
            import glob

            options = self.options
            # apply options to states :3
            for key, value in options.items():
                setattr(states, key, value)

            device_node = options["device"]
            states.device_node = device_node
            iso_path = options.get("iso_path", "")
            flash_mode = options["currentflash"]
            image_option = options["image_option"]

            # unmount all partitions before flashing :D
            self.status.emit(
                self._T.get("status_unmounting_all", "Unmounting all partitions on {device}...").format(
                    device=device_node
                )
            )
            partitions = glob.glob(f"{device_node}*")
            unmounted_parts = []
            for part in partitions:
                if part != device_node:  # don't unmount the device itself
                    self.status.emit(self._T.get("status_unmounting", "Unmounting {part}...").format(part=part))
                    fo.unmount(part)
                    unmounted_parts.append(part)

            # perform operation based on image option
            if image_option == 3:  # Format Only
                self.status.emit(self._T.get("status_format_starting", "Starting format operation..."))
                self.progress.emit(10)
                self.status.emit(self._T.get("status_format_in_progress", "Formatting drive..."))
                self.progress.emit(50)
                success = fo.disk_format(status_cb=self.status.emit)
                if success:
                    self.progress.emit(80)
                    for part in unmounted_parts:
                        self.status.emit(self._T.get("status_remounting", "Remounting {part}...").format(part=part))
                        fo.remount(part)
                    self.progress.emit(100)
                    self.status.emit(self._T.get("status_format_complete", "Format complete!"))
                else:
                    self.status.emit(
                        self._T.get("status_format_failed", "Format FAILED. Check the log above for the exact error.")
                    )

            elif image_option == 0:  # Windows
                # ISO mode (flash_mode 0) uses the specialised flash_windows path.
                # Any other mode (e.g. DD) uses the generic flash_usb path.
                scheme = PartitionScheme.SIMPLE_FAT32
                success = flash_usb(
                    device_node, iso_path, scheme, progress_cb=self.progress.emit, status_cb=self.status.emit
                )
            else:
                # Other flash modes (Linux, Other)
                fs_text = options.get("fs_text", "ext4")
                scheme_map = {
                    "ext4": PartitionScheme.LINUX,
                    "FAT32": PartitionScheme.SIMPLE_FAT32,
                    "exFAT": PartitionScheme.WINDOWS_EXFAT,
                    "UDF": PartitionScheme.LINUX,  # Generic catch-all for now
                }
                scheme = scheme_map.get(fs_text, PartitionScheme.LINUX)

                success = flash_usb(
                    device_node,
                    iso_path,
                    scheme,
                    progress_cb=self.progress.emit,
                    status_cb=self.status.emit,
                )

            self.flash_done.emit(bool(success))
        except Exception as e:
            self.status.emit(self._T.get("status_flash_error", "Flash error: {error}").format(error=e))
            self.flash_done.emit(False)
        finally:
            # restore stdout :D
            sys.stdout = _saved_stdout
