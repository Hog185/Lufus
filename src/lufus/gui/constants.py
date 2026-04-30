from pathlib import Path

THEME_DIR = Path(__file__).parent / "themes"
ASSETS_DIR = Path(__file__).parent / "assets"

ICONS = {
    "about": ASSETS_DIR / "icons" / "about.svg",
    "settings": ASSETS_DIR / "icons" / "settings.svg",
    "website": ASSETS_DIR / "icons" / "website.svg",
    "refresh": ASSETS_DIR / "icons" / "refresh.svg",
    "log": ASSETS_DIR / "icons" / "log.svg",
}


def _find_resource_dir(name: str) -> Path | None:
    # look for resource directories like languages or themes
    candidate = Path(__file__).parent / name
    return candidate if candidate.is_dir() else None
