#!/usr/bin/env python3
import sys
import json
import os
import signal
import glob
from lufus.lufus_logging import get_logger, setup_logging
from lufus import state
from lufus.drives import formatting as fo
from lufus.writing.flash_usb import flash_usb
from lufus.writing.partition_scheme import PartitionScheme

setup_logging()
log = get_logger(__name__)

# Start a new process group so all children can be killed together
os.setpgrp()
pid_file = "/tmp/lufus_helper.pid"

# Write our PID so the GUI can find us
with open(pid_file, "w") as f:
    f.write(str(os.getpid()))

_ipc_msg = f"Helper started with PID={os.getpid()}, PGID={os.getpgrp()}"
print(f"STATUS:{_ipc_msg}")
sys.stdout.flush()
log.info(_ipc_msg)


def progress_cb(pct):
    print(f"PROGRESS:{pct}")
    sys.stdout.flush()
    log.debug("Progress: %s%%", pct)


def status_cb(msg):
    print(f"STATUS:{msg}")
    sys.stdout.flush()
    log.info("Status IPC: %s", msg)


def main():
    try:
        if len(sys.argv) != 2:
            _err = "Missing arguments"
            print(f"STATUS:{_err}")
            sys.stdout.flush()
            log.error(_err)
            sys.exit(1)

        options_file = sys.argv[1]
        try:
            with open(options_file, "r") as f:
                options = json.load(f)
        except Exception as e:
            _err = f"Failed to read options file: {e}"
            print(f"STATUS:{_err}")
            sys.stdout.flush()
            log.error(_err)
            sys.exit(1)

        # Clean up the temp file
        try:
            os.unlink(options_file)
        except Exception:
            pass

        # Set all states
        for key, value in options.items():
            if hasattr(state, key):
                setattr(state, key, value)

        device_node = options["device"]
        iso_path = options.get("iso_path", "")
        image_option = options["image_option"]

        # Unmount all partitions
        _msg = f"Unmounting all partitions on {device_node}..."
        print(f"STATUS:{_msg}")
        sys.stdout.flush()
        log.info(_msg)

        partitions = glob.glob(f"{device_node}*")
        for part in partitions:
            _pmsg = f"Unmounting {part}..."
            print(f"STATUS:{_pmsg}")
            sys.stdout.flush()
            log.info(_pmsg)
            fo.unmount(part)

        success = False
        if image_option == 4:  # Ventoy
            from lufus.writing.install_ventoy import install_grub

            status_cb("Installing Ventoy bootloader...")
            progress_cb(10)
            success = install_grub(device_node)
            if success:
                progress_cb(100)
                status_cb("Ventoy installation complete")
            else:
                status_cb("Ventoy installation failed")
                log.error("Ventoy installation failed for device %s", device_node)
        elif image_option == 3:  # Format Only
            status_cb("Starting format operation...")
            progress_cb(10)
            success = fo.disk_format(status_cb=status_cb)
            if success:
                progress_cb(100)
                status_cb("Format complete")
            else:
                status_cb("Format failed")
        else:  # Windows / Linux / Other
            fs_name = options.get("filesystem_name", state.filesystem_name)
            scheme_map = {
                "NTFS": PartitionScheme.WINDOWS_NTFS,
                "FAT32": PartitionScheme.SIMPLE_FAT32,
                "exFAT": PartitionScheme.WINDOWS_EXFAT,
            }
            success = flash_usb(
                device_node,
                iso_path,
                scheme_map.get(fs_name, PartitionScheme.SIMPLE_FAT32),
                progress_cb=progress_cb,
                status_cb=status_cb,
                image_option=image_option,
            )

        log.info("flash_worker exiting, success=%s", success)
        print(f"STATUS:success={success}")
        sys.stdout.flush()
        sys.exit(0 if success else 1)
    finally:
        # Remove the PID file when done
        try:
            os.unlink(pid_file)
        except Exception:
            pass


if __name__ == "__main__":
    main()
