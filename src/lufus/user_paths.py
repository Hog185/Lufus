"""
Utility for detecting user's XDG_DOWNLOAD_DIR across root elevation
Falls back to ~/ if no XDG_DOWNLOAD_DIR is found
Made it so it runs as fast as possible before exiting to free like 2-3 KB RAM if you are using an OptiPlex GX270 or smth
"""

import os
from pathlib import Path
from platformdirs import user_downloads_dir, user_documents_dir
from lufus.lufus_logging import get_logger

log = get_logger(__name__)

# Environment variable used to tunnel the path through the root/pkexec barrier
ENV_DOWNLOAD_DIR = "LUFUS_DOWNLOAD_DIR"


def get_best_starting_dir() -> str:
    """
    Identify the best default dir for the file browser.

    This function works in two steps:
    1: Pre-elevation: Detects the real user's XDG_DOWNLOAD_DIR. If nothing is fonud, it falls back to ~/.
    2: Post-elevation: Gets the path from the tunneled environment variable.

    Returns:
        str: An absolute path to a valid directory.
    """
    # 1. High Priority: Check if we've already tunneled the path via environment
    tunneled = os.environ.get(ENV_DOWNLOAD_DIR)
    if tunneled:
        if os.path.isdir(tunneled):
            log.debug("Using tunneled user path: %s", tunneled)
            return tunneled
        log.warning("Tunneled path %s is no longer a valid directory.", tunneled)

    # 2. Medium Priority: Use platformdirs to find XDG standard paths
    # This works best when called before elevation (geteuid != 0)
    try:
        # Standard XDG Downloads
        dl_path = user_downloads_dir()
        if dl_path and os.path.isdir(dl_path):
            log.debug("Detected XDG Downloads directory: %s", dl_path)
            return str(dl_path)
    except Exception as e:
        log.error("Failed to resolve XDG Downloads directory: %s", e)

    # 3. Low Priority: Home directory fallback
    home = str(Path.home())
    log.debug("Falling back to home directory: %s", home)
    return home
