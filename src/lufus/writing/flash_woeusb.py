import re
import shutil
import subprocess



def flash_woeusb(device: str, iso_path: str, progress_cb=None, status_cb=None) -> bool:
    def _emit(pct: int):
        if progress_cb:
            progress_cb(pct)

    def _status(msg: str):
        print(msg)
        if status_cb:
            status_cb(msg)

    woeusb_args = [
        "sudo",
        "woeusb",
        "--device",     
        iso_path,
        device,
    ]

    _status(f"Flashing with woeusb: {' '.join(woeusb_args)}")

    try:
        process = subprocess.Popen(
            woeusb_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  
        )

        buf = b""
        while True:
            chunk = process.stdout.read(256)
            if not chunk:
                break

            buf += chunk

            # Split on both \r and \n so in-place updates (\r) are handled
            parts = re.split(rb"[\r\n]", buf)
            buf = parts[-1] 

            for line in parts[:-1]:
                line = line.strip()
                if not line:
                    continue

                decoded = line.decode(errors="replace")

                m = re.match(r"^\s*(\d{1,3})\s*%", decoded)
                if m and progress_cb:
                    pct = min(int(m.group(1)), 99)
                    _emit(pct)
                    continue
                _status(decoded)

        process.wait()

        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, woeusb_args)

        _emit(100)
        _status(f"Successfully flashed {iso_path} to {device} via woeusb")
        return True

    except subprocess.CalledProcessError as e:
        _status(f"woeusb flash failed (exit {e.returncode}): {e}")
        return False
    except Exception as e:
        _status(f"Unexpected error during woeusb flash: {e}")
        return False
