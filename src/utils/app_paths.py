"""
Utility functions for managing application data paths.
"""

import os
import platform
from pathlib import Path

APP_NAME = "SpotifyPlaylistUpdater"


def get_app_data_dir() -> Path:
    """
    Returns the appropriate application data directory based on the operating system.

    Returns:
        Path: Path to the application data directory
    """
    # Windows: %APPDATA%\SpotifyPlaylistUpdater
    if platform.system() == "Windows":
        app_data = os.path.join(os.environ.get("APPDATA", ""), APP_NAME)

    # macOS: ~/Library/Application Support/SpotifyPlaylistUpdater
    elif platform.system() == "Darwin":
        app_data = os.path.join(
            os.path.expanduser("~"), "Library", "Application Support", APP_NAME
        )

    # Linux/Other: ~/.local/share/SpotifyPlaylistUpdater
    else:
        app_data = os.path.join(os.path.expanduser("~"), ".local", "share", APP_NAME)

    # Create directory if it doesn't exist
    os.makedirs(app_data, exist_ok=True)

    return Path(app_data)


def get_credentials_path() -> Path:
    """
    Returns the path to the credentials file.

    Returns:
        Path: Path to the credentials file
    """
    return get_app_data_dir() / "credentials.json"


def get_cache_dir() -> Path:
    """
    Returns the path to the cache directory.

    Returns:
        Path: Path to the cache directory
    """
    cache_dir = get_app_data_dir() / "cache"
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir
