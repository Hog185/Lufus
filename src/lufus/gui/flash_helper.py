#!/usr/bin/env python3
import sys
import json
import os
import signal
import glob
from lufus.drives import states, formatting as fo
from lufus.writing.flash_usb import FlashUSB
from lufus.writing.flash_woeusb import flash_woeusb

# Start a new process group so all children can be killed together
os.setpgrp()
pid_file = "/tmp/lufus_helper.pid"

# Write our PID so the GUI can find us
with open(pid_file, "w") as f:
    f.write(str(os.getpid()))

print(f"STATUS:Helper started with PID={os.getpid()}, PGID={os.getpgrp()}")
sys.stdout.flush()

def progress_cb(pct):
    print(f"PROGRESS:{pct}")
    sys.stdout.flush()

def status_cb(msg):
    print(f"STATUS:{msg}")
    sys.stdout.flush()

def main():
    try:
        if len(sys.argv) != 2:
            print("STATUS:Missing arguments")
            sys.exit(1)

        options_file = sys.argv[1]
        try:
            with open(options_file, 'r') as f:
                options = json.load(f)
        except Exception as e:
            print(f"STATUS:Failed to read options file: {e}")
            sys.exit(1)

        # Clean up the temp file
        try:
            os.unlink(options_file)
        except Exception:
            pass

        # Set all states
        for key, value in options.items():
            setattr(states, key, value)

        device_node = options["device"]
        iso_path = options["iso_path"]
        flash_mode = options["currentflash"]
        image_option = options["image_option"]

        # Unmount all partitions
        print(f"STATUS:Unmounting all partitions on {device_node}...")
        partitions = glob.glob(f"{device_node}*")
        for part in partitions:
            print(f"STATUS:Unmounting {part}...")
            fo.unmount(part)

        # Decide which flashing function to call
        if image_option == 0:  # Windows
            if flash_mode == 0:
                success = FlashUSB(iso_path, device_node,
                                   progress_cb=progress_cb, status_cb=status_cb)
            elif flash_mode == 1:
                success = flash_woeusb(device_node, iso_path,
                                       progress_cb=progress_cb, status_cb=status_cb)
            else:
                success = False
        else:  # Linux / Any (including the old FlashWorker path)
            success = FlashUSB(iso_path, device_node,
                               progress_cb=progress_cb, status_cb=status_cb)

        sys.exit(0 if success else 1)
    finally:
        # Remove the PID file when done
        try:
            os.unlink(pid_file)
        except Exception:
            pass

if __name__ == "__main__":
    main()
