#!/bin/bash
set -euo pipefail

ls -la

if [[ -f "appimage-installer-config.sh" ]]; then
    echo "File is detected, we will proceed to install..."
    source appimage-installer-config.sh >> appimage-setup.log 
fi

if command -v python3 &>/dev/null; then
    PYTHON=python3
elif command -v python &>/dev/null; then
    PYTHON=python
else
    echo "FAILED to make PYTHON variable... both python3 and python don't exist here... :c"
    exit 1
fi

$PYTHON -m venv .venv-temp
source .venv-temp/bin/activate

# Install Python dependencies from file
$PYTHON -m pip install -r requirements-python.txt

# ----------------------------------------------------------------
# 4. Download and extract linuxdeploy (no Qt plugin needed)
# ----------------------------------------------------------------
rm -rf linuxdeploy-bin
wget -q https://github.com/linuxdeploy/linuxdeploy/releases/download/continuous/linuxdeploy-x86_64.AppImage
chmod +x linuxdeploy-x86_64.AppImage
./linuxdeploy-x86_64.AppImage --appimage-extract > /dev/null
mv squashfs-root linuxdeploy-bin
export PATH="$PWD/linuxdeploy-bin/usr/bin:$PATH"

# ----------------------------------------------------------------
# 5. Clean previous builds
# ----------------------------------------------------------------
rm -rf build dist AppDir

# ----------------------------------------------------------------
# 6. Run PyInstaller
# ----------------------------------------------------------------
$PYTHON -m PyInstaller src/lufus/__main__.py \
    --name lufus \
    --windowed \
    --paths src \
    --collect-all PyQt6 \
    --collect-all psutil \
    --hidden-import lufus.drives.autodetect_usb \
    --hidden-import lufus.drives.states \
    --add-data "src/lufus/gui:lufus/gui" \
    --noconfirm

# ----------------------------------------------------------------
# 7. Prepare AppDir structure
# ----------------------------------------------------------------
mkdir -p AppDir/usr/bin
cp -r dist/lufus/* AppDir/usr/bin/

# Create desktop file
cat > AppDir/lufus.desktop <<'DESKTOP'
[Desktop Entry]
Name=Lufus
Exec=lufus
Icon=lufus
Type=Application
Categories=Utility;
DESKTOP

# Create dummy icon (or copy your real one if present)
mkdir -p AppDir/usr/share/icons/hicolor/256x256/apps
if [ -f src/lufus/gui/assets/lufus.png ]; then
    cp src/lufus/gui/assets/lufus.png AppDir/usr/share/icons/hicolor/256x256/apps/lufus.png
else
    # Create a minimal PNG (1x1 transparent) using base64
    echo "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==" | base64 -d > AppDir/usr/share/icons/hicolor/256x256/apps/lufus.png
fi

# ----------------------------------------------------------------
# 8. Run linuxdeploy to bundle libraries and produce AppImage
# ----------------------------------------------------------------
linuxdeploy --appdir AppDir \
            --executable AppDir/usr/bin/lufus \
            --desktop-file AppDir/lufus.desktop \
            --output appimage

# ----------------------------------------------------------------
# 9. Rename the AppImage to a predictable name
# ----------------------------------------------------------------
# mv lufus-*.AppImage Lufus-x86_64.AppImage
rm linuxdeploy-x86_64.AppImage
rm linuxdeploy-x86_64.AppImage.*
rm -rf AppDir
rm -rf .venv-temp
rm -rf linuxdeploy-bin

echo "  Build finished inside container."
