import argparse
import diskcache
import logging
import threading


# Setup command line arguments
parser = argparse.ArgumentParser(description="Spotify Playlist Creator")
parser.add_argument("--quiet", action="store_true", help="Suppress output")
parser.add_argument(
    "--non-interactive", action="store_true", help="Non-interactive mode"
)
parser.add_argument("--dry-run", action="store_true", help="Dry run")
parser.add_argument("--refresh", action="store_true", help="Refresh cache")

args = parser.parse_args()

# Setup cache
cache = diskcache.Cache("spotifyplaylistcreator_cache")

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s - %(filename)s:%(lineno)d",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler("spotifyplaylistcleaner.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

playlist_lock = threading.Lock()
track_retrieval_lock = threading.Lock()
artist_retrieval_lock = threading.Lock()

processed_playlists = set()
processed_track_sets = {}


def reset_processed_tracking():
    """Reset the tracking of processed playlists and tracks"""
    with playlist_lock:
        processed_playlists.clear()
        processed_track_sets.clear()


def print_if_not_quiet(message):
    if not args.quiet:
        print(message)


def invalidate_cache(cache_key):
    if cache_key in cache:
        del cache[cache_key]
