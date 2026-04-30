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


import sys
import json
import os
import subprocess
import tempfile
import shutil
from pathlib import Path
from PyQt6.QtCore import QThread, pyqtSignal
from lufus.writing.partition_scheme import PartitionScheme

class FlashWorker(QThread):
    # worker thread for usb flashing operation via pkexec helper
    progress = pyqtSignal(int)
    status = pyqtSignal(str)
    flash_done = pyqtSignal(bool)

    def __init__(self, options: dict, t: dict):
        super().__init__()
        self.options = options
        self._T = t
        self.process = None

    def run(self):
        # Create a temporary file for options
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(self.options, f)
            options_path = f.name

        try:
            # Find the flash_worker.py script
            import lufus.writing.flash_worker as fw
            worker_script = Path(fw.__file__).resolve()
            
            # Prepare the command
            if os.geteuid() == 0:
                cmd = [sys.executable, str(worker_script), options_path]
            else:
                pkexec_path = shutil.which("pkexec")
                if not pkexec_path:
                    self.status.emit("Error: pkexec not found. Cannot acquire root privileges.")
                    self.flash_done.emit(False)
                    return
                # Determine how to run the script (python vs executable)
                cmd = [pkexec_path, sys.executable, str(worker_script), options_path]
            
            # Start the process
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )

            success = False
            for line in self.process.stdout:
                line = line.strip()
                if line.startswith("PROGRESS:"):
                    try:
                        pct = int(line.split(":", 1)[1])
                        self.progress.emit(pct)
                    except ValueError:
                        pass
                elif line.startswith("STATUS:"):
                    msg = line.split(":", 1)[1]
                    self.status.emit(msg)
                elif "success=True" in line:
                    success = True
                elif "success=False" in line:
                    success = False

            self.process.wait()
            # If dd or other tools exited with success but we didn't catch the final log
            if self.process.returncode == 0:
                success = True
            
            self.flash_done.emit(success)

        except Exception as e:
            self.status.emit(f"Flash error: {str(e)}")
            self.flash_done.emit(False)
        finally:
            if os.path.exists(options_path):
                try:
                    os.unlink(options_path)
                except OSError:
                    pass

    def terminate(self):
        if self.process:
            try:
                # Try to kill the process group if we had one, 
                # but pkexec might make this tricky.
                self.process.terminate()
            except Exception:
                pass
        super().terminate()

