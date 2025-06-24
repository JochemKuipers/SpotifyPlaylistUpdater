"""
Utility functions for Spotify Playlist Updater.
"""

import logging
import re
from typing import Dict

# Set up logging
logger = logging.getLogger(__name__)


def clean_name(song_name):
    """
    Clean track names by removing featuring artists, parentheses, etc.
    """
    try:
        # Remove featuring artists in parentheses or brackets that contain feat/with
        # This regex looks for parentheses/brackets that specifically contain feat/with
        song_name = re.sub(
            r"[\[(]\s*(feat\.?|with\.?)[^])}]*[])}]",
            "",
            song_name,
            flags=re.IGNORECASE,
        ).strip()

        # Remove featuring artists after "feat." or "with." (anywhere in the string)
        song_name = re.sub(
            r"\s*(feat\.|with\.)\s.*$", "", song_name, flags=re.IGNORECASE
        ).strip()

        # Remove featuring artists after " - " followed by "with" or "feat"
        song_name = re.sub(
            r"\s*-\s*(with\s|feat\.?\s).*$", "", song_name, flags=re.IGNORECASE
        ).strip()

        # Remove standalone " - " at the end (like "$$$ - ")
        song_name = re.sub(r"\s*-\s*$", "", song_name).strip()

        # Remove trailing dashes, hyphens, and extra whitespace
        song_name = re.sub(r"[\s\-–—]+$", "", song_name).strip()

        # Also remove leading dashes that might be left
        song_name = re.sub(r"^[\s\-–—]+", "", song_name).strip()

    except Exception as e:
        logger.error("Error cleaning name: %s", e)
        raise e
    return song_name


def format_duration(duration_ms):
    """
    Format track duration from milliseconds to MM:SS format.
    """
    try:
        if isinstance(duration_ms, str):
            return duration_ms
        duration = duration_ms / 1000
        minutes = int(duration / 60)
        seconds = int(duration % 60)
    except Exception as e:
        logger.error("Error formatting duration: %s", e)
        raise e
    return f"{minutes}:{seconds:02d}"


def is_duration_within_range(duration1, duration2, range_seconds=5):
    """
    Check if two track durations are within a specified range (default 5 seconds).
    """

    def duration_to_seconds(duration):
        minutes, seconds = map(int, duration.split(":"))
        return minutes * 60 + seconds

    try:
        duration1_seconds = duration_to_seconds(duration1)
        duration2_seconds = duration_to_seconds(duration2)
        return abs(duration1_seconds - duration2_seconds) <= range_seconds
    except Exception as e:
        logger.error("Error comparing durations: %s", e)
        return False


def is_track_match(track1: Dict, track2: Dict) -> bool:
    """
    Check if two tracks are the same based on name and duration tolerance only.
    """
    # Compare cleaned names (case insensitive)
    name_match = track1["name"].lower() == track2["name"].lower()

    # Compare durations with 5-second tolerance
    duration_match = is_duration_within_range(track1["duration"], track2["duration"], 5)

    return name_match and duration_match
