from datetime import timedelta
import concurrent.futures
from math import ceil
import spotipy
from config import (
    print_if_not_quiet,
    cache,
    args,
    logger,
    playlist_lock,
    track_retrieval_lock,
    artist_retrieval_lock,
    processed_track_sets,
)
from utils import process_track
from auth import get_spotify_client

sp = get_spotify_client()
user = sp.current_user()


def getuserplaylists(refresh=False):
    """
    Get all playlists for the current user with caching support.

    Args:
        refresh: Whether to force a refresh (overrides use_cache)

    Returns:
        List of playlist dictionaries or None if there was an error
    """
    cache_key = "user_playlists"
    cached_data = cache.get(cache_key)

    if not user:
        logger.error("No authenticated user found. Please authenticate first.")
        return None

    # If refresh is requested, we'll bypass the cache
    if cached_data and not refresh:
        logger.debug("Using cached playlists data")
        return cached_data

    # Use a lock to prevent multiple simultaneous fetches in non-interactive mode
    with playlist_lock:
        # Check cache again after acquiring the lock (another thread might have updated it)
        cached_data = cache.get(cache_key)
        if cached_data and not refresh:
            logger.debug("Using cached playlists data (after lock)")
            return cached_data

        try:
            logger.info("Fetching user playlists from Spotify API")
            playlistlist = []

            # Get the first page of playlists
            playlists = sp.current_user_playlists(
                limit=50
            )  # Maximum allowed by Spotify API
            if not playlists or "items" not in playlists:
                logger.warning("No playlists found for the user")
                return []
            total = playlists["total"]

            # Process the first batch
            for playlist in playlists["items"]:
                if playlist["owner"]["id"] == user["id"]:
                    playlistlist.append(playlist)
                    # Also cache individual playlists
                    cache_key_playlist = f"user_playlist_{playlist['name'].lower()}"
                    cache.set(
                        cache_key_playlist,
                        playlist,
                        expire=timedelta(days=1).total_seconds(),
                    )

            # Print status for the first batch
            if not args.non_interactive:
                print_if_not_quiet(
                    f"Loaded {len(playlistlist)} playlists out of {total} playlists"
                )
            else:
                logger.info(
                    f"Loaded {len(playlistlist)} playlists out of {total} playlists"
                )

            # Continue fetching until there are no more playlists
            offset = 50  # Start from the next batch

            while offset < total:
                next_playlists = sp.current_user_playlists(limit=50, offset=offset)
                if not next_playlists or "items" not in next_playlists:
                    logger.info("No more playlists found")
                    break
                for playlist in next_playlists["items"]:
                    if playlist["owner"]["id"] == user["id"]:
                        playlistlist.append(playlist)
                        # Also cache individual playlists
                        cache_key_playlist = f"user_playlist_{playlist['name'].lower()}"
                        cache.set(
                            cache_key_playlist,
                            playlist,
                            expire=timedelta(days=1).total_seconds(),
                        )

                # Print status after each batch
                if not args.non_interactive:
                    print_if_not_quiet(
                        f"Loaded {len(playlistlist)} playlists out of {total} playlists"
                    )
                else:
                    logger.info(
                        f"Loaded {len(playlistlist)} playlists out of {total} playlists"
                    )

                # Move to the next batch
                offset += 50

            # Set a longer cache expiry for non-interactive mode to reduce API calls
            expire_time = timedelta(days=1).total_seconds()
            cache.set(cache_key, playlistlist, expire=expire_time)

            logger.info(f"Successfully loaded all {len(playlistlist)} playlists")
            return playlistlist

        except spotipy.SpotifyException as e:
            logger.error(f"Error getting playlists: {e}")
            return None


def getuserplaylist(playlist_name):
    """
    Get a user's playlist by name with proper caching.

    Args:
        playlist_name: Name of the playlist to find

    Returns:
        The playlist dictionary or None if not found
    """
    # First, try the individual playlist cache
    try:
        cache_key = f"user_playlist_{playlist_name.lower()}"
        cached_data = cache.get(cache_key)
        if not cached_data:
            logger.debug(
                f"No cached data for playlist {playlist_name}, fetching from API"
            )
            # If not found in cache, fetch all playlists and search
            all_playlists = getuserplaylists(refresh=False)
            if not all_playlists:
                logger.warning("No playlists found in Spotify API")
                return None

            # Search for the playlist by name
            for playlist in all_playlists:
                if (
                    isinstance(playlist, dict)
                    and playlist["name"].lower() == playlist_name.lower()
                ):
                    # Cache this specific playlist
                    cache.set(
                        cache_key,
                        playlist,
                        expire=timedelta(days=1).total_seconds(),
                    )
                    return playlist

            logger.warning(f"Playlist {playlist_name} not found")
            return None
        return cached_data
    except Exception as e:
        logger.error(f"Error accessing cache for playlist {playlist_name}: {e}")
        return None


def gettracks(playlist_id=None, refresh=False):
    """
    Get tracks, either from a specific playlist or the user's saved tracks.
    Supports caching and parallel fetching for better performance.

    Args:
        playlist_id: Optional playlist ID. If None, will fetch user's saved tracks
        refresh: Whether to force a refresh and bypass cache

    Returns:
        List of normalized track objects
    """
    cache_key = f"tracks_{playlist_id}" if playlist_id else "saved_tracks"
    cached_data = cache.get(cache_key)

    # Check if we should use cache or refresh
    if cached_data and not refresh:
        logger.debug(
            f"Using cached tracks for {'saved tracks' if not playlist_id else playlist_id}"
        )
        return cached_data

    # In non-interactive mode, make sure we only fetch a playlist's tracks once per run
    if args.non_interactive and playlist_id and not refresh:
        with track_retrieval_lock:
            if playlist_id in processed_track_sets:
                logger.debug(
                    f"Using already fetched tracks for {playlist_id} from this session"
                )
                return processed_track_sets[playlist_id]

    # Use a lock to prevent multiple simultaneous fetches
    with track_retrieval_lock:
        # Check cache again after acquiring lock (only if not forcing refresh)
        if not refresh:
            cached_data = cache.get(cache_key)
            if cached_data:
                return cached_data

            # For non-interactive mode, check again if another thread fetched these tracks
            if (
                args.non_interactive
                and playlist_id
                and playlist_id in processed_track_sets
            ):
                return processed_track_sets[playlist_id]

        try:
            logger.info(
                f"Fetching tracks for {'saved tracks' if not playlist_id else playlist_id}"
            )
            tracklist = []

            # Determine which API method to use
            if playlist_id:
                result = sp.playlist_items(playlist_id=playlist_id, limit=100)
            else:
                result = sp.current_user_saved_tracks(limit=50)

            if not result or "items" not in result:
                logger.warning(
                    f"No tracks found for {'saved tracks' if not playlist_id else playlist_id}"
                )
                return []
            total = result["total"]
            if total == 0:
                logger.warning(
                    f"No tracks found for {'saved tracks' if not playlist_id else playlist_id}"
                )
                return []

            # Progress tracking variables
            chunk_size = (
                50 if not playlist_id else 100
            )  # Different limits for different APIs
            num_chunks = ceil(total / chunk_size)

            # Log progress
            if not args.non_interactive and total > chunk_size:
                print_if_not_quiet(f"Fetching {total} tracks in {num_chunks} chunks")
            else:
                logger.info(f"Fetching {total} tracks in {num_chunks} chunks")

            # Function to process a single track
            def process_tracks_chunk(offset):
                try:
                    # Get the chunk of tracks
                    chunk_number = (offset // chunk_size) + 1
                    logger.info(
                        f"Starting chunk {chunk_number} of {num_chunks} (offset {offset})"
                    )

                    if playlist_id:
                        chunk = sp.playlist_items(
                            playlist_id=playlist_id, limit=chunk_size, offset=offset
                        )
                    else:
                        chunk = sp.current_user_saved_tracks(
                            limit=chunk_size, offset=offset
                        )

                    # Process each track in the chunk
                    chunk_tracks = []

                    if not chunk or "items" not in chunk:
                        logger.warning(
                            f"No items found in chunk {chunk_number} at offset {offset}"
                        )
                        return chunk_tracks
                    for i, item in enumerate(chunk["items"]):
                        track = item["track"]
                        if track and track["id"]:  # Skip local files and None tracks
                            # Handle saved tracks vs playlist tracks differently
                            position = offset + i if playlist_id else None
                            track_obj = process_track(track, position)
                            if track_obj:
                                chunk_tracks.append(track_obj)
                    logger.info(
                        f"Completed chunk {chunk_number} of {num_chunks} (offset {offset}): processed {len(chunk_tracks)} tracks"
                    )
                    return chunk_tracks
                except Exception as e:
                    logger.error(f"Error fetching chunk at offset {offset}: {e}")
                    raise e

            # Process first chunk (we already fetched it)
            logger.info(f"Processing first chunk (0 to {chunk_size - 1})")
            for i, item in enumerate(result["items"]):
                track = item["track"]
                if track and track["id"]:  # Skip local files and None tracks
                    position = i if playlist_id else None
                    track_obj = process_track(track, position)
                    if track_obj:
                        tracklist.append(track_obj)
            logger.info(
                f"Completed first chunk (0 to {chunk_size - 1}): processed {len(tracklist)} tracks"
            )

            # If there are more chunks to fetch, process them in parallel
            if total > chunk_size:
                offsets = range(chunk_size, total, chunk_size)

                # Use thread pool for parallel fetching (but limit concurrency to avoid rate limits)
                with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                    futures = [
                        executor.submit(process_tracks_chunk, offset)
                        for offset in offsets
                    ]

                    # Process results as they complete
                    for i, future in enumerate(
                        concurrent.futures.as_completed(futures)
                    ):
                        try:
                            chunk_tracks = future.result()
                            current_count = len(tracklist)
                            tracklist.extend(chunk_tracks)
                            new_count = len(tracklist)

                            logger.info(
                                f"Added chunk result: {new_count - current_count} tracks (total now: {new_count}/{total})"
                            )

                            # Update progress for user
                            if not args.non_interactive:
                                print_if_not_quiet(
                                    f"Fetched {len(tracklist)} of {total} tracks"
                                )
                            else:
                                logger.debug(
                                    f"Fetched {len(tracklist)} of {total} tracks"
                                )

                        except Exception as e:
                            logger.error(f"Error processing chunk {i + 1}: {e}")
                            raise e

            # Sort tracks by position if playlist
            if playlist_id:
                tracklist.sort(key=lambda x: x["position"])

            # After fetching is complete, add to processed_track_sets if non-interactive
            if args.non_interactive and playlist_id:
                processed_track_sets[playlist_id] = tracklist

            # Set longer cache expiry for non-interactive mode
            expire_time = timedelta(days=1).total_seconds()
            cache.set(cache_key, tracklist, expire=expire_time)

            logger.info(
                f"Successfully fetched {len(tracklist)} tracks for {'saved tracks' if not playlist_id else playlist_id}"
            )
            return tracklist

        except spotipy.SpotifyException as e:
            logger.error(f"Error getting tracks: {e}")
            raise e
        except Exception as e:
            logger.error(f"Error in worker thread: {e}")
            raise e


def getuserfollowedartists(refresh: bool = False):
    """
    Get all followed artists for the current user with caching support.
    Args:
        refresh: Whether to force a refresh (overrides use_cache)
    Returns:
        List of artist dictionaries or None if there was an error
    """

    cache_key = "followed_artists"
    cached_data = cache.get(cache_key)
    if cached_data and not refresh:
        logger.debug("Using cached followed artists data")
        return cached_data
    with artist_retrieval_lock:
        cached_data = cache.get(cache_key)
        if cached_data and not refresh:
            logger.debug("Using cached followed artists data (after lock)")
            return cached_data

        try:
            logger.info("Fetching followed artists from Spotify API")
            artistlist = []

            # Get the first page of followed artists
            artists = sp.current_user_followed_artists(limit=50)
            if not artists or "artists" not in artists:
                logger.warning("No followed artists found for the user")
                return []
            total = artists["artists"]["total"]

            # Process the first batch
            for artist in artists["artists"]["items"]:
                artistlist.append(artist)

            # Print status for the first batch
            if not args.non_interactive:
                print_if_not_quiet(
                    f"Loaded {len(artistlist)} followed artists out of {total} artists"
                )
            else:
                logger.info(
                    f"Loaded {len(artistlist)} followed artists out of {total} artists"
                )

            # Continue fetching until there are no more artists
            offset = 50  # Start from the next batch

            while offset < total:
                next_artists = sp.current_user_followed_artists(limit=50, after=offset)
                if not next_artists or "artists" not in next_artists:
                    logger.info("No more followed artists found")
                    break
                for artist in next_artists["artists"]["items"]:
                    artistlist.append(artist)

                # Print status after each batch
                if not args.non_interactive:
                    print_if_not_quiet(
                        f"Loaded {len(artistlist)} followed artists out of {total} artists"
                    )
                else:
                    logger.info(
                        f"Loaded {len(artistlist)} followed artists out of {total} artists"
                    )

                # Move to the next batch
                offset += 50

            # Set a longer cache expiry for non-interactive mode to reduce API calls
            expire_time = timedelta(days=1).total_seconds()
            cache.set(cache_key, artistlist, expire=expire_time)

            logger.info(f"Successfully loaded all {len(artistlist)} followed artists")
            return artistlist

        except spotipy.SpotifyException as e:
            logger.error(f"Error getting followed artists: {e}")
            return None

def getuserfollowedartists_playlists(refresh: bool = False):
    """
    Get all followed artists and their playlists for the current user with caching support.
    Args:
        refresh: Whether to force a refresh (overrides use_cache)
    Returns:
        List of artist dictionaries with their playlists or None if there was an error
    """
    artists = getuserfollowedartists(refresh=refresh)
    if not artists:
        return []

    artist_playlists = {}
    for artist in artists:
        try:
            if not artist or not isinstance(artist, dict) or "name" not in artist or "uri" not in artist:
                logger.warning("Invalid artist data, skipping")
                continue
            playlists = getuserplaylist(artist["name"])
            if playlists:
                artist_playlists[artist["name"]] = playlists
            else:
                logger.warning(f"No playlists found for artist {artist['name']}")
        except Exception as e:
            artist_name = artist.get('name', 'Unknown') if artist and isinstance(artist, dict) else 'Unknown'
            logger.error(f"Error fetching playlists for artist {artist_name}: {e}")
            continue
