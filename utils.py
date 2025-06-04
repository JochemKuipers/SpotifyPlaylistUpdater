import re
from config import logger


def clean_name(song_name):
    try:
        if re.search(r"[\[(].*?(feat\.?|with\.?)", song_name, re.IGNORECASE):
            song_name = re.split(r"[\[(].*", song_name, maxsplit=1)[0].strip()
        else:
            song_name = re.sub(
                r"\s*(feat\.|with\.)\s.*$", "", song_name, flags=re.IGNORECASE
            ).strip()
    except Exception as e:
        logger.error(f"Error cleaning name: {e}")
        raise e
    return song_name


def format_duration(duration_ms):
    try:
        if type(duration_ms) is not int:
            return duration_ms
        duration = duration_ms / 1000
        minutes = int(duration / 60)
        seconds = int(duration % 60)
    except Exception as e:
        logger.error(f"Error formatting duration: {e}")
        raise e
    return f"{minutes}:{seconds:02d}"


def is_duration_within_range(duration1, duration2, range_seconds=5):
    def duration_to_seconds(duration):
        minutes, seconds = map(int, duration.split(":"))
        return minutes * 60 + seconds

    try:
        duration1_seconds = duration_to_seconds(duration1)
        duration2_seconds = duration_to_seconds(duration2)
        return abs(duration1_seconds - duration2_seconds) <= range_seconds
    except Exception as e:
        logger.error(f"Error comparing durations: {e}")
        return False


def split_artists(artists):
    if not artists:
        return None
    if len(artists) == 1:
        return tuple(artists[0].split(", "))
    return tuple(artists)


def process_track(track, postition=None):
    track_info = {
        "track": {
            "uri": track["uri"],
            "original_name": track["name"],
            "cleaned_name": clean_name(track["name"]),
            "artists": split_artists([artist["name"] for artist in track["artists"]]),
            "album": track["album"]["name"],
            "duration": format_duration(track["duration_ms"]),
            "position": postition,
            "is_local": track["is_local"],
            "explicit": track["explicit"],
        }
    }
    return track_info["track"]
