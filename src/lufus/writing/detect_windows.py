import subprocess
import re


def _read_iso_label(iso_path: str) -> str:
    try:
        with open(iso_path, "rb") as f:
            f.seek(32808)
            return f.read(32).decode("ascii", errors="replace").strip()
    except Exception:
        return ""


def _label_is_windows(label: str) -> bool:
    label = label.upper()
    if label.startswith("WIN") or label.startswith("WINDOWS"):
        return True
    if label == "ESD-ISO":
        return True
    if re.search(r"CC[A-Z]+_[A-Z0-9]+FRE_", label):
        return True
    return False


def is_windows_iso(iso_path: str) -> bool:
    print(f"Windows detection: checking {iso_path}")

    label = _read_iso_label(iso_path)
    print(f"Windows detection: ISO volume label={label!r}")
    if label and _label_is_windows(label):
        print("Windows detection: Windows label match -> Windows ISO confirmed via ISO header")
        return True

    try:
        print("Windows detection: running 7z to list ISO contents...")
        result = subprocess.run(
            ["7z", "l", iso_path], capture_output=True, text=True, timeout=30
        )
        print(f"Windows detection: 7z exited with code {result.returncode}")
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
                    print(
                        f"Windows detection: found marker '{marker}' in 7z listing -> Windows ISO confirmed"
                    )
                    return True
            print("Windows detection: none of the Windows markers found in 7z listing")
        else:
            print(f"Windows detection: 7z stderr: {result.stderr.strip()[:200]}")
    except FileNotFoundError:
        print(
            "Windows detection: 7z not found - install p7zip-full: sudo apt install p7zip-full"
        )
    except subprocess.TimeoutExpired:
        print("Windows detection: 7z timed out listing ISO after 30s")
    except Exception as e:
        print(f"Windows detection: 7z unexpected error: {type(e).__name__}: {e}")

    print("Windows detection: falling back to blkid volume label check...")
    try:
        result = subprocess.run(
            ["sudo", "blkid", "-o", "value", "-s", "LABEL", iso_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        blkid_label = result.stdout.strip()
        print(
            f"Windows detection: blkid returned label={blkid_label!r} (exit code {result.returncode})"
        )
        if _label_is_windows(blkid_label):
            print(
                f"Windows detection: Windows label match -> Windows ISO confirmed via blkid"
            )
            return True
        print("Windows detection: label does not match Windows patterns")
    except Exception as e:
        print(f"Windows detection: blkid error: {type(e).__name__}: {e}")

    print("Windows detection: result -> NOT a Windows ISO")
    return False
