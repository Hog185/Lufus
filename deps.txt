# Lufus External Dependencies (Non-Python)

## System Privileges
- pkexec (polkit)
- sudo
- runuser (util-linux)

## Flashing & Imaging
- dd (coreutils)
- sync (coreutils)
- cp (coreutils)
- rm (coreutils)
- mkdir (coreutils)

## Partitioning & Disk Info
- lsblk (util-linux)
- parted
- sfdisk (util-linux)
- partprobe (parted)
- udevadm (systemd/udev)
- wipefs (util-linux)
- blockdev (util-linux)
- badblocks (e2fsprogs)

## Filesystem Tools
- mkfs.vfat, fatlabel (dosfstools)
- mkfs.exfat (exfatprogs or exfat-utils)
- mkfs.ntfs / mkntfs, ntfslabel (ntfs-3g)
- mkfs.ext4, e2label (e2fsprogs)
- mkudffs, udflabel (udftools)

## Mounting & ISO Handling
- mount (util-linux)
- umount (util-linux)
- 7z (p7zip-full) - Used for Windows ISO detection
- isoinfo (genisoimage) - Fallback for Windows ISO detection

## Process & System Management
- lsof
- fuser (psmisc)
- pgrep (procps)
- which (debianutils or similar)
- stty (coreutils)
- xdg-user-dir (xdg-user-dirs)
- xdg-open (xdg-utils)

## Windows Image Operations (WIM)
- wimlib-imagex (wimlib / wimtools)
- wimmountrw (wimlib)
- wimunmount (wimlib)

## Bootloader Installation
- grub-install (grub2 / grub-common)

## GUI & System Libraries (PyQt6 Requirements)
- libgl1
- libx11-6
- libxcb1
- libxrender1
- fontconfig
- libfreetype6
- libxext6
- libxrandr2
- libxcursor1
- libxi6
- libxfixes3
- libxcomposite1
- libxdamage1

## Package Managers (Used for auto-installing missing tools)
- apt-get (Debian/Ubuntu)
- dnf (Fedora/RHEL)
- pacman (Arch)
- zypper (openSUSE)

## Python Environment
- python3
- python3-pip
- python3-venv

## Other (from requirements-system.txt)
- wget
- file
