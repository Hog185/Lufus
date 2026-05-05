#!/bin/bash
set -e

echo "Building on Alpine (musl) using Docker..."

docker run --rm \
    -v "$(pwd):/build" \
    -w /build \
    alpine:latest \
    sh -c '
        apk add --no-cache python3 pyqt6 pyqt6-qt6 python3-pip gcc musl-dev linux-headers

        pip install --break-system-packages nuitka pyinstaller psutil pyudev packaging platformdirs

        pyinstaller --onefile \
            --collect-all PyQt6 \
            --add-binary "/usr/bin/dd:bin" \
            --add-binary "/usr/bin/pkexec:bin" \
            --add-binary "/usr/bin/sudo:bin" \
            --add-binary "/usr/bin/lsblk:bin" \
            --add-binary "/usr/bin/mount:bin" \
            --add-binary "/usr/bin/umount:bin" \
            --add-binary "/usr/sbin/blkid:bin" \
            --add-binary "/usr/sbin/badblocks:bin" \
            --add-binary "/usr/sbin/mkfs.ntfs:bin" \
            --add-binary "/usr/sbin/mkfs.vfat:bin" \
            --add-binary "/usr/sbin/mkfs.exfat:bin" \
            --add-binary "/usr/sbin/mkfs.ext4:bin" \
            --add-binary "/usr/sbin/mkfs.btrfs:bin" \
            --add-data "src/lufus/gui/languages:/lufus/gui/languages" \
            --add-data "src/lufus/gui/themes:/lufus/gui/themes" \
            --add-data "src/lufus/gui/assets:/lufus/gui/assets" \
            --add-data "src/lufus/writing/grub.cfg:/lufus/writing" \
            --add-data "src/lufus/writing/uefi-ntfs.img:/lufus/writing" \
            --name lufus src/lufus/__main__.py
    '

echo "Done! Output: dist/lufus (musl build)"
echo "Size: $(ls -lh dist/lufus | awk '{print $5}')"
