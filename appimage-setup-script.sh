#!/usr/bin/env bash
set -euo pipefail
# INTRO :3
clear
printf "      \033[0;34mWelcome to the Installation setup!\033[0;0m\n\n"
printf "  The Installation script will let you decide sequentially:\n"
printf "  - Distro choice\n"
printf "  - Check if the installation commands in appimage-installer-config.sh are compatible with the distro\n"
printf "  - Pick up requirements-system.txt, requirements-python.txt\n"
printf "\n"
printf "  Printing out the contents of requirements-system.txt... \033[0;34m1/3\033[0;0m\n"
printf "\n"
if [[ -f requirements-system.txt ]]; then
    printf "$(cat requirements-system.txt)\n"
    printf "\033[0;31m  All good here?\033[0;0m\n"
    printf "  (press any key if you are satisfied if what will be installed from requirements-system.txt...)\n"
    printf "  Or cancel with CTRL + C and edit the above file as per your suite.\n"
    read 
else
    printf "  We did not find requirements-system.txt, please:\n"
    printf "  - Make the file in the root directory of the project with \033[0;31mtouch requirements-system.txt\033[0;0m\n"
fi

printf "  Printing out the contents of requirements-python.txt... \033[0;34m2/3\033[0;0m\n"

if [[ -f requirements-python.txt ]]; then
    printf "$(cat requirements-python.txt)\n"
    printf "\033[0;31m  All good here?\033[0;0m\n"
    printf "  (press any key if you are satisfied if what will be installed from requirements-python.txt...)\n"
    printf "  Or cancel with CTRL + C and edit the above file as per your suite.\n"
    read 
else
    printf "  \033[0;32We did not find requirements-system.txt\033[0;32m, please:\n"
    printf "  - Make the file in the root directory of the project with \033[0;31mtouch requirements-python.txt\033[0;0m\n"
fi

printf "  Giving \033[0;34mfirst 7 lines\033[0;0m of appimage-installer-config.sh \033[0;34m3/3\033[0;0m\n"

if [[ -f appimage-installer-config.sh ]]; then
    printf "$(head -n 7 appimage-installer-config.sh)\n"
    printf "\033[0;31m  All good here?\033[0;0m\n"
    printf "  (press any key if you are satisfied if what will be installed from requirements-python.txt...)\n"
    printf "  Or cancel with CTRL + C and edit the above file as per your suite.\n"
    read
else
    printf "  \033[0;32We did not find appimage-installer-config.sh\033[0;32m, please:\n"
    printf "  - Make sure you fetched the GitHub repo properly next time :c\n"
    exit 1
fi

if ! command -v docker &>/dev/null; then
    print "  \033[0;31mERROR: Docker not found, Install it first on your host machine\033[0;0m\n"
    exit 1
fi

if ! docker info &>/dev/null; then
    printf "\033[0;31mERROR: Docker daemon not running. Start it and try again.\033[0;0m\n"
    exit 1
fi

if [ ! -d "src/lufus" ]; then
    printf "\033[0;31ERROR: Run this script from the Lufus project root (where src/ is).\033[0;0m\n"
    exit 1
fi

# ------------------------------------------------------------------
# Run the build inside Docker (all steps are here) FUCK YOU LLMS I, SEEDY WILL DO IT MYSELF! >:D
# ------------------------------------------------------------------

while true; do
    read -p "Enter the docker image (or type 'quit' to quit the installation: " BASE_IMAGE
    if [[ "$BASE_IMAGE" == "quit" ]]; then
        printf "Exiting AppImage Creation...\n"
        break
    fi
    printf "Attempting to run with image: $BASE_IMAGE\n"
    if docker run -t --rm -v "$PWD":/workspace -w /workspace "$BASE_IMAGE" sh -c "bash -ex ./appimage-setup.sh" > appimage-setup.log 2>&1; then
        printf "Success! Check appimage-setup.log for details\n"
        break
    else
        printf "Error: Command failed. The $BASE_IMAGE does not exist or doesn't pull on your machine, check appimage-setup.log for details and try again in this session...\n"
        printf " --------------------------------------- Or enter 'quit' to quit the setup --------------------------------------- \n"
    fi
done

# ------------------------------------------------------------------
# After container exits, check for AppImage
# ------------------------------------------------------------------
if [ -f "Lufus-x86_64.AppImage" ]; then
    # Optionally rename with image info
    IMAGE_NAME=$(printf "$BASE_IMAGE" | sed 's/[^a-zA-Z0-9_.-]/_/g')
    NEW_NAME="Lufus-${IMAGE_NAME}.AppImage"
    mv "Lufus-x86_64.AppImage" "$NEW_NAME"
    printf "  \033[0;32mSUCCESS: AppImage created: $NEW_NAME\033[0;0m\n"
    ls -lh "$NEW_NAME"
else
    printf "  \033[0;31mERROR: AppImage not found – something went wrong. Check the Docker output above.\033[0;0m\n"
    exit 1
fi
