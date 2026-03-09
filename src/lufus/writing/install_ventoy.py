import subprocess
import sys
import os 
import shutil
import time

def install_ventoy(target_device):
    if "nvme" in target_device or "sda" in target_device:
        print(f"Caution: {target_device} might be a system drive.")
        confirm = input("Are you sure you want to wipe it? (type 'YES'): ")
        if confirm != "YES":
            sys.exit(1)

    sfdisk_input = f"""
label: gpt
device: {target_device}
unit: sectors

{target_device}1 : start=2048, size=2048, type=21686148-6449-6E6F-7444-6961676F6E61
{target_device}2 : start=4096, size=204800, type=C12A7328-F81F-11D2-BA4B-00A0C93EC93B
{target_device}3 : start=208896, type=EBD0A0A2-B9E5-4433-87C0-68B6B72699C7
    """

    try:
        print(f"--- Partitioning {target_device} ---")
        subprocess.run(['sfdisk', target_device], input=sfdisk_input.encode(), check=True)
        
        subprocess.run(["partprobe", target_device], check=False)
        subprocess.run(["udevadm", "settle", ], check=False)
        subprocess.run(['sync'], check=True)
        time.sleep(2)
        
        sep = 'p' if target_device[-1].isdigit() else ''
        efi_part = f"{target_device}{sep}2"
        data_part = f"{target_device}{sep}3"

        print(f"--- Formatting {efi_part} and {data_part} ---")
        subprocess.run(['mkfs.vfat', '-F', '32', '-n', 'EFI', efi_part], check=True)
        subprocess.run(['mkfs.exfat', '-L', 'OS_PART', data_part], check=True)

        efi_mount = "/tmp/efi_prepare"
        os.makedirs(efi_mount, exist_ok=True)
        subprocess.run(['mount', efi_part, efi_mount], check=True)
        
        print("--- Installing GRUB (Legacy + UEFI) ---")
        subprocess.run(['grub-install', '--target=i386-pc', f'--boot-directory={efi_mount}/boot', target_device], check=True)
        subprocess.run(['grub-install', '--target=x86_64-efi', f'--efi-directory={efi_mount}', f'--boot-directory={efi_mount}/boot', '--removable'], check=True)

        config_content = """
insmod part_gpt
insmod exfat
insmod loopback
insmod iso9660
insmod search_label
insmod regexp

set timeout=15
set default=0

search --no-floppy --label OS_PART --set=root

menuentry "--- AUTO-DETECTED ISO LIST ---" { true }

for isofile in /*.iso; do
    if [ -f "$isofile" ]; then
        menuentry "Boot: $isofile" "$isofile" {
            set iso_path="$2"
            loopback loop ($root)$iso_path
            
            if [ -f (loop)/casper/vmlinuz ]; then
                set p="/casper/" ; set k="vmlinuz" ; set i="initrd"
            elif [ -f (loop)/live/vmlinuz ]; then
                set p="/live/" ; set k="vmlinuz" ; set i="initrd.img"
            elif [ -f (loop)/arch/boot/x86_64/vmlinuz-linux ]; then
                set p="/arch/boot/x86_64/" ; set k="vmlinuz-linux" ; set i="initramfs-linux.img"
            else
                set p="/" ; set k="vmlinuz" ; set i="initrd.img"
            fi
            
            linux (loop)$p$k boot=live iso-scan/filename=$iso_path findiso=$iso_path root=live:LABEL=OS_PART rd.live.image quiet splash
            initrd (loop)$p$i
        }
    fi
done

menuentry "Reboot" { reboot }
menuentry "Power Off" { halt }
"""
        with open(f"{efi_mount}/boot/grub/grub.cfg", "w") as cfg:
            cfg.write(config_content)
        
        subprocess.run(['umount', efi_mount], check=True)
        print("\nSUCCESS: USB is prepared.")   
        
    except subprocess.CalledProcessError as e:
        print(f"Command failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: sudo python3 script.py /dev/sdX")
    else:
        install_ventoy(sys.argv[1])
