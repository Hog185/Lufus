# due to some issues it's only working with linux don't add without proper changing
import subprocess
import sys
import os
import shutil
import time
import urllib.request
import glob

# print("Python interpreter is interpreting comment. script will exit.")
# sys.exit(1)
# previous lines ensures python isn't broken.

"""
   This  script installs grub in a way that lets users to copy distro iso to the usb device and 
   boot of any copied iso's in the usb.
"""

WIMBOOT_URL = "https://github.com/ipxe/wimboot/releases/latest/download/wimboot"

def download_wimboot(dest_path)->bool:
    """
    Downloads wimboot, a bootloader necessary to boot into windows

    Args:
        dest_path (path): Download path

    Returns:
        true: download success
        false: download failed
    """
    print("--- Downloading wimboot ---")
    try:
        urllib.request.urlretrieve(WIMBOOT_URL, dest_path)
        print("wimboot downloaded successfully.")
        return True
    except Exception as e:
        print(f"WARNING: Could not download wimboot: {e}")
        print("Windows ISO booting will not work.")
        return False




def install_grub(target_device)->bool:
    """
    Prepares the USB drive with a hybrid GRUB bootloader for multi-ISO booting.
    
    This function performs partitioning via sfdisk, formats partitions to 
    FAT32 and exFAT, and installs GRUB to both the MBR and EFI partitions.
    
    Args:
        target_device: The system path to the disk (e.g., /dev/sdX).
        
    Returns:
        bool: True if the installation succeeded, False otherwise.
        
    Raises:
        subprocess.CalledProcessError: If a system command fails.
    """

    # Root and Safety Checks
    if os.geteuid() != 0:
        print("ERROR: This script must be run with sudo.")
        return False

    # Avoid nvme devices or soldered emmc(mmcblk)
    if "nvme" in target_device  or "mmcblk" in target_device:
        print(f"Aborting: {target_device} is likely to a system drive.")
        return False

    # Cleanup to avoid "Device Busy"
    print(f"--- Cleaning up {target_device} ---")
    for partition in glob.glob(f"{target_device}*"):
        subprocess.run(['umount', partition], check=False)
        
    # Partitioning Definition
    sfdisk_input = f"""
label: gpt
device: {target_device}
unit: sectors

{target_device}1 : start=2048, size=2048, type=21686148-6449-6E6F-7444-6961676F6E61
{target_device}2 : start=4096, size=204800, type=C12A7328-F81F-11D2-BA4B-00A0C93EC93B
{target_device}3 : start=208896, type=EBD0A0A2-B9E5-4433-87C0-68B6B72699C7
    """
    efi_mount = "/tmp/efi_prepare"
    data_mount = "/tmp/data_prepare"
    try:
        print(f"--- Partitioning {target_device} ---")
        subprocess.run(['sfdisk', target_device], input=sfdisk_input.encode(), check=True)
        
        # Determine partition names (handles /dev/sdaX vs /dev/nvme0n1pX)
        sep = 'p' if 'nvme' in target_device else ''
        efi_part = f"{target_device}{sep}2"
        data_part = f"{target_device}{sep}3"
        
        # Synchronization of kernel (Addressing the "No such file" error)
        print("Syncing with kernel...")
        subprocess.run(["partprobe", target_device], check=False)
        subprocess.run(["udevadm", "settle"], check=False)
        subprocess.run(["sync"], check=True)
        
        
        # Wait for device nodes to be created by udev
        for _ in range(10):
            if os.path.exists(data_part):
                break
            time.sleep(1)
        else:
            print(f"Error: {data_part} did not appear. Aborting.")
            return False
            
        # Formatting
        print(f"--- Formatting {efi_part} and {data_part} ---")
        subprocess.run(['mkfs.vfat', '-F', '32', '-n', 'EFI', efi_part], check=True)
        subprocess.run(['mkfs.exfat', '-L', 'OS_PART', data_part], check=True)

        #GRUB Installation
        os.makedirs(efi_mount, exist_ok=True)
        subprocess.run(['mount', efi_part, efi_mount], check=True)
        
        print("--- Installing GRUB (Legacy + UEFI) ---")
        subprocess.run(['grub-install', '--target=i386-pc', f'--boot-directory={efi_mount}/boot', target_device], check=True)
        subprocess.run(['grub-install', '--target=x86_64-efi', f'--efi-directory={efi_mount}', f'--boot-directory={efi_mount}/boot', '--removable'], check=True)
    
    
        # Copy grub.cfg
        script_dir = os.path.dirname(os.path.abspath(__file__))
        cfg_path = os.path.join(script_dir, "grub.cfg")
        if not os.path.exists(cfg_path):
            print("ERROR: grub.cfg not found next to the script.")
            return False
        shutil.copy(os.path.join(script_dir, "grub.cfg"), f"{efi_mount}/boot/grub/grub.cfg")

        # Download wimboot
        os.makedirs(data_mount, exist_ok=True)
        subprocess.run(['mount', data_part, data_mount], check=True)
        download_wimboot(f"{data_mount}/wimboot")
        subprocess.run(['umount', data_mount], check=True)  

        
        subprocess.run(['umount', efi_mount], check=True)
        print("\nSUCCESS: USB is ready. Copy .iso files to 'OS_PART'.")
        return True
        
        
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print(f"\nCommand failed: {e}")
            subprocess.run(['umount', efi_mount], check=False)  # cleanup on failure
            subprocess.run(['umount', data_mount], check=False)
            return False    
        



# this part is for testing the script
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: sudo python3 script.py /dev/sdX")
    else:
        if install_grub(sys.argv[1]):
            sys.exit(0)
        else:
            sys.exit(1)
