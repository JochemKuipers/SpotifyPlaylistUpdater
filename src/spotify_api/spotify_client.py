"""
Core Spotify API functionality for the Spotify Playlist Updater.
"""
import atexit
import concurrent.futures
import logging
from math import ceil
from typing import List, Dict

import spotipy
from spotipy.oauth2 import SpotifyOAuth

from src.utils.track_utils import (
    clean_name,
    format_duration,
    is_track_match,
)

# Set up logging
logger = logging.getLogger(__name__)


class SpotifyPlaylistUpdater:
    def __init__(self, client_id: str, client_secret: str, redirect_uri: str):
        """Initialize Spotify client with OAuth"""
        scope = "playlist-read-private playlist-read-collaborative playlist-modify-private playlist-modify-public user-read-private user-read-email"

        self.sp = spotipy.Spotify(
            auth_manager=SpotifyOAuth(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
                scope=scope,
            )
        )

        # Get current user information for market specification
        try:
            self.user = self.sp.current_user()
            self.market = self.user.get("country", "US")
            print(
                f"Logged in as: {self.user.get('display_name', 'Unknown')} ({self.market})"
            )
        except Exception as e:
            print(f"Warning: Could not get user info: {e}")
            self.user = None
            self.market = "US"

        # Initialize caches
        self._playlists_cache = None
        self._playlist_tracks_cache = {}

        # Register cleanup function
        atexit.register(self._cleanup)

    def _cleanup(self):
        """Clean up Spotify client to avoid deletion errors"""
        try:
            if hasattr(self, "sp") and self.sp:
                self.sp = None
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

    def get_user_playlists(self, force_refresh=False) -> List[Dict]:
        """Get all user playlists with details using caching"""
        # Return cached playlists if available and not forcing refresh
        if self._playlists_cache is not None and not force_refresh:
            logger.info(
                f"Using cached playlists ({len(self._playlists_cache)} playlists)"
            )
            return self._playlists_cache

        try:
            logger.info("Fetching user playlists")
            playlists = []

            # Get first batch
            result = self.sp.current_user_playlists(limit=50)
            total = result["total"]

            if total == 0:
                logger.warning("No playlists found")
                self._playlists_cache = []
                return []

            # Process first batch
            for item in result["items"]:
                playlists.append(
                    {
                        "name": item["name"],
                        "id": item["id"],
                        "uri": item["uri"],
                        "owner": item["owner"]["display_name"],
                    }
                )

            # If there are more playlists, fetch them in parallel
            if total > 50:
                chunk_size = 50
                num_chunks = ceil(total / chunk_size)
                print(f"Fetching {total} playlists in {num_chunks} chunks")

                def process_playlist_chunk(offset):
                    try:
                        chunk_number = (offset // chunk_size) + 1
                        logger.info(
                            f"Processing playlist chunk {chunk_number} (offset {offset})"
                        )

                        chunk = self.sp.current_user_playlists(
                            limit=chunk_size, offset=offset
                        )
                        chunk_playlists = []

                        for item in chunk["items"]:
                            chunk_playlists.append(
                                {
                                    "name": item["name"],
                                    "id": item["id"],
                                    "uri": item["uri"],
                                    "owner": item["owner"]["display_name"],
                                }
                            )

                        logger.info(
                            f"Completed playlist chunk {chunk_number}: {len(chunk_playlists)} playlists"
                        )
                        return chunk_playlists
                    except Exception as e:
                        logger.error(
                            f"Error fetching playlist chunk at offset {offset}: {e}"
                        )
                        raise e

                # Process remaining chunks in parallel
                offsets = range(50, total, chunk_size)
                with concurrent.futures.ThreadPoolExecutor(
                        max_workers=3
                ) as executor:  # Reduced workers
                    futures = [
                        executor.submit(process_playlist_chunk, offset)
                        for offset in offsets
                    ]

                    for future in concurrent.futures.as_completed(futures):
                        try:
                            chunk_playlists = future.result()
                            playlists.extend(chunk_playlists)
                            print(f"Fetched {len(playlists)} of {total} playlists")
                        except Exception as e:
                            logger.error(f"Error processing playlist chunk: {e}")
                            raise e

            # Cache the results
            self._playlists_cache = playlists
            logger.info(f"Successfully fetched and cached {len(playlists)} playlists")
            return playlists

        except Exception as e:
            logger.error(f"Error getting playlists: {e}")
            raise e

    def find_playlist_by_name(self, playlist_name: str) -> Dict:
        """Find a playlist by name using cached playlists"""
        playlists = self.get_user_playlists()  # This will use cache if available

        print(f"Searching for playlist '{playlist_name}' in cached playlists...")
        playlist_matches = []

        for playlist in playlists:
            # Exact match (case insensitive)
            if playlist["name"].lower() == playlist_name.lower():
                playlist_matches.append(("exact", playlist))
            # Partial match (contains)
            elif playlist_name.lower() in playlist["name"].lower():
                playlist_matches.append(("partial", playlist))
            # Reverse partial match (playlist name contains search term)
            elif playlist["name"].lower() in playlist_name.lower():
                playlist_matches.append(("reverse", playlist))

        # Use best match
        if playlist_matches:
            # Sort by match quality: exact > partial > reverse
            match_priority = {"exact": 0, "partial": 1, "reverse": 2}
            playlist_matches.sort(key=lambda x: match_priority[x[0]])

            best_match = playlist_matches[0]
            matched_playlist = best_match[1]

            if best_match[0] == "exact":
                print(f"✓ Found exact match: '{matched_playlist['name']}'")
            else:
                print(
                    f"✓ Found {best_match[0]} match: '{matched_playlist['name']}' (searched for '{playlist_name}')"
                )

                # Show other possible matches if available
                if len(playlist_matches) > 1:
                    print("Other possible matches:")
                    for i, (match_type, pl) in enumerate(playlist_matches[1:], 1):
                        print(f"  {i}. '{pl['name']}' ({match_type} match)")

            return matched_playlist
        else:
            print(f"❌ No playlist matching '{playlist_name}' found!")
            print("\nDid you mean one of these playlists?")
            # Show playlists that might be similar
            for playlist in playlists[:10]:  # Show first 10 as suggestions
                print(f"  - '{playlist['name']}'")
            return {}

    def get_playlist_tracks(self, playlist_name: str) -> List[Dict]:
        """Get all track details from a playlist by name using caching"""
        # Check cache first
        if playlist_name in self._playlist_tracks_cache:
            logger.info(f"Using cached tracks for playlist '{playlist_name}'")
            return self._playlist_tracks_cache[playlist_name]

        try:
            # Find the playlist using cached playlists
            playlist = self.find_playlist_by_name(playlist_name)
            if not playlist:
                return []

            playlist_id = playlist["id"]
            matched_name = playlist["name"]
            print(f"✓ Using playlist '{matched_name}'")

            # Get initial batch to determine total count
            result = self.sp.playlist_items(playlist_id, limit=100, market=self.market)
            total = result["total"]

            if total == 0:
                print("Playlist is empty")
                tracklist = []
                self._playlist_tracks_cache[playlist_name] = tracklist
                return tracklist

            logger.info(f"Fetching {total} tracks from playlist")
            tracklist = []

            # Process first chunk
            for item in result["items"]:
                if item["track"]:
                    track = item["track"]
                    tracklist.append(
                        {
                            "name": clean_name(track["name"]),
                            "duration": format_duration(track["duration_ms"]),
                            "artists": [artist["name"] for artist in track["artists"]],
                            "uri": track["uri"],
                        }
                    )

            # If there are more tracks, fetch them in parallel
            if total > 100:
                chunk_size = 100
                num_chunks = ceil(total / chunk_size)
                print(f"Fetching {total} tracks in {num_chunks} chunks")

                def process_track_chunk(offset):
                    try:
                        chunk_number = (offset // chunk_size) + 1
                        logger.info(
                            f"Processing track chunk {chunk_number} (offset {offset})"
                        )

                        chunk = self.sp.playlist_items(
                            playlist_id,
                            limit=chunk_size,
                            offset=offset,
                            market=self.market,
                        )
                        chunk_tracks = []

                        for item in chunk["items"]:
                            if item["track"]:
                                track = item["track"]
                                chunk_tracks.append(
                                    {
                                        "name": clean_name(track["name"]),
                                        "duration": format_duration(
                                            track["duration_ms"]
                                        ),
                                        "artists": [
                                            artist["name"]
                                            for artist in track["artists"]
                                        ],
                                        "uri": track["uri"],
                                    }
                                )

                        logger.info(
                            f"Completed track chunk {chunk_number}: {len(chunk_tracks)} tracks"
                        )
                        return chunk_tracks
                    except Exception as e:
                        logger.error(
                            f"Error fetching track chunk at offset {offset}: {e}"
                        )
                        raise e

                # Process remaining chunks in parallel
                offsets = range(100, total, chunk_size)
                with concurrent.futures.ThreadPoolExecutor(
                        max_workers=3
                ) as executor:  # Reduced workers
                    futures = [
                        executor.submit(process_track_chunk, offset)
                        for offset in offsets
                    ]

                    for future in concurrent.futures.as_completed(futures):
                        try:
                            chunk_tracks = future.result()
                            tracklist.extend(chunk_tracks)
                            print(f"Fetched {len(tracklist)} of {total} tracks")
                        except Exception as e:
                            logger.error(f"Error processing track chunk: {e}")
                            raise e

            # Cache the results
            self._playlist_tracks_cache[playlist_name] = tracklist
            print(
                f"Found and cached {len(tracklist)} tracks in playlist '{matched_name}' (market: {self.market})"
            )
            return tracklist

        except Exception as e:
            logger.error(f"Error getting playlist tracks: {e}")
            raise e

    def find_missing_tracks(self, artist_name: str, playlist_name: str) -> List[Dict]:
        """Compare artist discography with playlist and find missing tracks"""
        playlist_tracks = self.get_playlist_tracks(playlist_name)

        # Exit early if playlist not found
        if not playlist_tracks:
            print("Cannot compare - playlist not found or empty!")
            return []

        artist_tracks = self.get_artist_all_tracks(artist_name)

        if not artist_tracks:
            return []

        print(
            f"\nStarting comparison between {len(artist_tracks)} artist tracks and {len(playlist_tracks)} playlist tracks..."
        )

        # Find missing tracks using improved matching (ignore albums)
        missing_tracks = []

        for artist_track in artist_tracks:
            is_missing = True

            for playlist_track in playlist_tracks:
                if is_track_match(artist_track, playlist_track):
                    is_missing = False
                    break

            if is_missing:
                missing_tracks.append(artist_track)

        if not missing_tracks:
            print("No missing tracks! Playlist is complete.")
            return []

        # Remove duplicates from missing tracks (same name and similar duration, ignore album)
        unique_missing = []
        for track in missing_tracks:
            is_duplicate = False
            for existing in unique_missing:
                if is_track_match(track, existing):
                    is_duplicate = True
                    break
            if not is_duplicate:
                unique_missing.append(track)

        # Sort by release date for display purposes
        unique_missing.sort(key=lambda x: x["release_date"])

        print(f"\nFound {len(unique_missing)} unique missing tracks:")
        for track in unique_missing:
            print(
                f"- {track['name']} ({track['duration']}) (example from: {track['album']}, {track['release_date']})"
            )

        return unique_missing

    def find_non_artist_tracks(
            self, artist_name: str, playlist_name: str
    ) -> List[Dict]:
        """Find tracks in playlist that are NOT from the specified artist"""
        playlist_tracks = self.get_playlist_tracks(playlist_name)

        if not playlist_tracks:
            print("Cannot compare - playlist not found or empty!")
            return []

        # Get artist info for comparison (with market)
        results = self.sp.search(q=artist_name, type="artist", market=self.market)

        if not results["artists"]["items"]:
            print(f"Artist '{artist_name}' not found!")
            return []

        # Find the correct artist
        target_artist_id = None
        for artist in results["artists"]["items"]:
            if artist["name"].lower() == artist_name.lower():
                target_artist_id = artist["id"]
                break

        if not target_artist_id:
            print(f"Exact match for artist '{artist_name}' not found!")
            return []

        # Process tracks in parallel batches
        track_ids = [track["uri"].split(":")[-1] for track in playlist_tracks]
        batch_size = 50  # Spotify allows up to 50 tracks per request
        num_batches = ceil(len(track_ids) / batch_size)

        logger.info(f"Processing {len(track_ids)} tracks in {num_batches} batches")

        def process_track_batch(batch_info):
            batch_number, start_idx, batch_ids = batch_info
            try:
                logger.info(
                    f"Processing track batch {batch_number} ({len(batch_ids)} tracks)"
                )

                # Get multiple tracks at once
                tracks_details = self.sp.tracks(batch_ids, market=self.market)
                batch_non_artist_tracks = []

                for j, full_track in enumerate(tracks_details["tracks"]):
                    if not full_track:
                        continue

                    track_artist_ids = [
                        artist["id"] for artist in full_track["artists"]
                    ]

                    # If target artist is not in the track's artists, it's a non-artist track
                    if target_artist_id not in track_artist_ids:
                        original_track = playlist_tracks[start_idx + j]
                        batch_non_artist_tracks.append(
                            {
                                "name": original_track["name"],
                                "duration": original_track["duration"],
                                "artists": original_track["artists"],
                                "uri": original_track["uri"],
                                "main_artist": full_track["artists"][0]["name"],
                            }
                        )

                logger.info(
                    f"Track batch {batch_number} completed: {len(batch_non_artist_tracks)} non-artist tracks"
                )
                return batch_non_artist_tracks

            except Exception as e:
                logger.error(f"Error processing track batch {batch_number}: {e}")
                # Fallback: process tracks individually
                fallback_tracks = []
                for j, track_id in enumerate(batch_ids):
                    try:
                        full_track = self.sp.track(track_id, market=self.market)
                        track_artist_ids = [
                            artist["id"] for artist in full_track["artists"]
                        ]

                        if target_artist_id not in track_artist_ids:
                            original_track = playlist_tracks[start_idx + j]
                            fallback_tracks.append(
                                {
                                    "name": original_track["name"],
                                    "duration": original_track["duration"],
                                    "artists": original_track["artists"],
                                    "uri": original_track["uri"],
                                    "main_artist": full_track["artists"][0]["name"],
                                }
                            )
                    except Exception as track_error:
                        logger.error(
                            f"Error processing individual track {track_id}: {track_error}"
                        )
                        continue

                logger.info(
                    f"Track batch {batch_number} fallback completed: {len(fallback_tracks)} non-artist tracks"
                )
                return fallback_tracks

        # Create batches with batch numbers and start indices
        batches = []
        for i in range(0, len(track_ids), batch_size):
            batch_number = (i // batch_size) + 1
            batch_ids = track_ids[i: i + batch_size]
            batches.append((batch_number, i, batch_ids))

        # Process batches in parallel
        non_artist_tracks = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(process_track_batch, batch) for batch in batches]

            for future in concurrent.futures.as_completed(futures):
                try:
                    batch_tracks = future.result()
                    non_artist_tracks.extend(batch_tracks)
                    print(f"Total non-artist tracks found: {len(non_artist_tracks)}")
                except Exception as e:
                    logger.error(f"Error in track batch processing: {e}")

        return non_artist_tracks

    def find_non_artist_tracks_multiple(
            self, artist_names: List[str], playlist_name: str
    ) -> List[Dict]:
        """Find tracks in playlist that are NOT from any of the specified artists using optimized batching"""
        playlist_tracks = self.get_playlist_tracks(playlist_name)  # Uses cache

        if not playlist_tracks:
            print("Cannot compare - playlist not found or empty!")
            return []

        # Get artist IDs for all artists
        target_artist_ids = []

        for artist_name in artist_names:
            results = self.sp.search(
                q=artist_name.strip(), type="artist", market=self.market
            )

            if not results["artists"]["items"]:
                print(f"Artist '{artist_name}' not found!")
                continue

            # Find exact match
            for artist in results["artists"]["items"]:
                if artist["name"].lower() == artist_name.strip().lower():
                    target_artist_ids.append(artist["id"])
                    print(f"Found artist ID for: {artist['name']}")
                    break

        if not target_artist_ids:
            print("No valid artists found!")
            return []

        # Process tracks in parallel batches with optimized batching
        track_ids = [track["uri"].split(":")[-1] for track in playlist_tracks]
        batch_size = 50  # Spotify allows up to 50 tracks per request
        num_batches = ceil(len(track_ids) / batch_size)

        logger.info(f"Processing {len(track_ids)} tracks in {num_batches} batches")

        def process_track_batch(batch_info):
            batch_number, start_idx, batch_ids = batch_info
            try:
                # Add small delay between batches to avoid rate limiting
                import time

                time.sleep(0.1)

                logger.info(
                    f"Processing track batch {batch_number} ({len(batch_ids)} tracks)"
                )

                # Get multiple tracks at once
                tracks_details = self.sp.tracks(batch_ids, market=self.market)
                batch_non_artist_tracks = []

                for j, full_track in enumerate(tracks_details["tracks"]):
                    if not full_track:
                        continue

                    track_artist_ids = [
                        artist["id"] for artist in full_track["artists"]
                    ]

                    # If none of the target artists are in the track's artists, it's a non-artist track
                    is_by_target_artist = any(
                        artist_id in track_artist_ids for artist_id in target_artist_ids
                    )

                    if not is_by_target_artist:
                        original_track = playlist_tracks[start_idx + j]
                        batch_non_artist_tracks.append(
                            {
                                "name": original_track["name"],
                                "duration": original_track["duration"],
                                "artists": original_track["artists"],
                                "uri": original_track["uri"],
                                "main_artist": full_track["artists"][0]["name"],
                            }
                        )

                logger.info(
                    f"Track batch {batch_number} completed: {len(batch_non_artist_tracks)} non-artist tracks"
                )
                return batch_non_artist_tracks

            except Exception as e:
                logger.error(f"Error processing track batch {batch_number}: {e}")
                return []  # Return empty list instead of trying fallback to avoid more API calls

        # Create batches with batch numbers and start indices
        batches = []
        for i in range(0, len(track_ids), batch_size):
            batch_number = (i // batch_size) + 1
            batch_ids = track_ids[i: i + batch_size]
            batches.append((batch_number, i, batch_ids))

        # Process batches with reduced concurrency
        non_artist_tracks = []
        with concurrent.futures.ThreadPoolExecutor(
                max_workers=2
        ) as executor:  # Reduced to 2 workers
            futures = [executor.submit(process_track_batch, batch) for batch in batches]

            for future in concurrent.futures.as_completed(futures):
                try:
                    batch_tracks = future.result()
                    non_artist_tracks.extend(batch_tracks)
                    print(f"Total non-artist tracks found: {len(non_artist_tracks)}")
                except Exception as e:
                    logger.error(f"Error in track batch processing: {e}")

        return non_artist_tracks

    def get_artist_all_tracks(self, artist_name: str) -> List[Dict]:
        """Get all tracks from an artist's discography using parallel processing"""
        try:
            # Search for artist
            results = self.sp.search(q=artist_name, type="artist", market=self.market)

            if not results["artists"]["items"]:
                print(f"Artist '{artist_name}' not found!")
                return []

            artist_id = None
            artist_name_found = None

            # Find exact match
            for artist in results["artists"]["items"]:
                if artist["name"].lower() == artist_name.lower():
                    artist_id = artist["id"]
                    artist_name_found = artist["name"]
                    print(f"Found artist: {artist_name_found}")
                    break

            if not artist_id:
                print(f"Exact match for artist '{artist_name}' not found!")
                return []

            # Get all albums
            logger.info(f"Fetching albums for {artist_name_found}")
            all_album_ids = []

            albums = self.sp.artist_albums(
                artist_id,
                album_type="album,single,compilation",
                limit=50,
                country=self.market,
            )

            while albums:
                for album in albums["items"]:
                    all_album_ids.append(album["id"])

                if albums["next"]:
                    albums = self.sp.next(albums)
                else:
                    break

            print(f"Found {len(all_album_ids)} albums/singles for {artist_name_found}")

            if not all_album_ids:
                return []

            # Process albums in parallel batches with reduced concurrency
            all_tracks = []
            batch_size = 20  # Spotify allows up to 20 albums per request
            num_batches = ceil(len(all_album_ids) / batch_size)
            print(f"Processing {len(all_album_ids)} albums in {num_batches} batches")

            def process_album_batch(batch_info):
                batch_number, batch_ids = batch_info
                try:
                    # Add small delay between batches
                    import time

                    time.sleep(0.1)

                    logger.info(
                        f"Processing album batch {batch_number} ({len(batch_ids)} albums)"
                    )

                    # Get album details in batch
                    albums_details = self.sp.albums(batch_ids, market=self.market)
                    batch_tracks = []

                    for album_detail in albums_details["albums"]:
                        if not album_detail:
                            continue

                        for track in album_detail["tracks"]["items"]:
                            # Only include tracks where the artist is the main artist
                            if any(
                                    artist["id"] == artist_id for artist in track["artists"]
                            ):
                                batch_tracks.append(
                                    {
                                        "name": clean_name(track["name"]),
                                        "duration": format_duration(
                                            track["duration_ms"]
                                        ),
                                        "artists": [
                                            artist["name"]
                                            for artist in track["artists"]
                                        ],
                                        "album": album_detail["name"],
                                        "release_date": album_detail["release_date"],
                                        "uri": track["uri"],
                                    }
                                )

                    logger.info(
                        f"Completed album batch {batch_number}: {len(batch_tracks)} tracks"
                    )
                    return batch_tracks

                except Exception as e:
                    logger.error(f"Error processing album batch {batch_number}: {e}")
                    return []  # Return empty list to avoid more API calls

            # Create batches with batch numbers
            batches = []
            for i in range(0, len(all_album_ids), batch_size):
                batch_number = (i // batch_size) + 1
                batch_ids = all_album_ids[i: i + batch_size]
                batches.append((batch_number, batch_ids))

            # Process batches with reduced concurrency
            with concurrent.futures.ThreadPoolExecutor(
                    max_workers=3
            ) as executor:  # Reduced workers
                futures = [
                    executor.submit(process_album_batch, batch) for batch in batches
                ]

                for future in concurrent.futures.as_completed(futures):
                    try:
                        batch_tracks = future.result()
                        all_tracks.extend(batch_tracks)
                        print(f"Total tracks collected: {len(all_tracks)}")
                    except Exception as e:
                        logger.error(f"Error in album batch processing: {e}")

            print(f"Found {len(all_tracks)} total tracks by {artist_name_found}")
            return all_tracks

        except Exception as e:
            logger.error(f"Error getting artist tracks: {e}")
            raise e

    def get_artist_all_tracks_multiple(self, artist_names: List[str]) -> List[Dict]:
        """Get all tracks from multiple artists' discographies using parallel processing"""
        try:
            all_tracks = []

            print(f"Getting tracks for {len(artist_names)} artists...")

            for artist_name in artist_names:
                print(f"\nGetting tracks for artist: {artist_name}")
                artist_tracks = self.get_artist_all_tracks(artist_name)

                if artist_tracks:
                    all_tracks.extend(artist_tracks)
                    print(f"Added {len(artist_tracks)} tracks from {artist_name}")
                else:
                    print(f"No tracks found for {artist_name}")

            # Remove duplicates based on track name and duration
            print(f"\nRemoving duplicates from {len(all_tracks)} total tracks...")
            unique_tracks = []

            for track in all_tracks:
                is_duplicate = False
                for existing in unique_tracks:
                    if is_track_match(track, existing):
                        is_duplicate = True
                        break
                if not is_duplicate:
                    unique_tracks.append(track)

            print(f"Total unique tracks across all artists: {len(unique_tracks)}")
            return unique_tracks

        except Exception as e:
            logger.error(f"Error getting tracks for multiple artists: {e}")
            raise e

    def remove_track_from_playlist(self, playlist_name: str, track: Dict) -> bool:
        """Remove a single track from a playlist"""
        if not track:
            print("No track to remove!")
            return False

        # Get playlist ID
        playlists = self.get_user_playlists()
        playlist_id = None

        for playlist in playlists:
            if playlist["name"].lower() == playlist_name.lower():
                playlist_id = playlist["id"]
                break

        if not playlist_id:
            print(f"❌ Playlist '{playlist_name}' not found!")
            return False

        try:
            # Extract track URI
            track_uri = track["uri"]

            # Remove track from playlist
            self.sp.playlist_remove_all_occurrences_of_items(playlist_id, [track_uri])

            print(f"✅ Successfully removed '{track['name']}' from '{playlist_name}'!")

            # Update the cached playlist tracks if it exists
            if playlist_name in self._playlist_tracks_cache:
                # Remove all occurrences of this track from cache
                self._playlist_tracks_cache[playlist_name] = [
                    cached_track
                    for cached_track in self._playlist_tracks_cache[playlist_name]
                    if cached_track["uri"] != track_uri
                ]

            return True

        except Exception as e:
            print(f"❌ Error removing track from playlist: {e}")
            return False

    def remove_tracks_from_playlist(
            self, playlist_name: str, tracks: List[Dict]
    ) -> bool:
        """Remove multiple tracks from a playlist"""
        if not tracks:
            print("No tracks to remove!")
            return False

        # Get playlist ID
        playlists = self.get_user_playlists()
        playlist_id = None

        for playlist in playlists:
            if playlist["name"].lower() == playlist_name.lower():
                playlist_id = playlist["id"]
                break

        if not playlist_id:
            print(f"❌ Playlist '{playlist_name}' not found!")
            return False

        try:
            # Extract track URIs
            track_uris = [track["uri"] for track in tracks]

            # Remove tracks in batches of 100 (Spotify API limit)
            removed_count = 0
            for i in range(0, len(track_uris), 100):
                batch = track_uris[i: i + 100]
                self.sp.playlist_remove_all_occurrences_of_items(playlist_id, batch)
                removed_count += len(batch)
                print(
                    f"Removed {len(batch)} tracks from playlist (total: {removed_count}/{len(track_uris)})"
                )

            print(
                f"✅ Successfully removed {removed_count} tracks from '{playlist_name}'!"
            )

            # Update the cached playlist tracks if it exists
            if playlist_name in self._playlist_tracks_cache:
                removed_uris = set(track_uris)
                self._playlist_tracks_cache[playlist_name] = [
                    cached_track
                    for cached_track in self._playlist_tracks_cache[playlist_name]
                    if cached_track["uri"] not in removed_uris
                ]

            return True

        except Exception as e:
            print(f"❌ Error removing tracks from playlist: {e}")
            return False

    def find_missing_and_extra_tracks(
            self, artist_name: str, playlist_name: str
    ) -> Dict:
        """Compare artist discography with playlist and find both missing and extra tracks"""
        # Parse artist names (handle aliases separated by "/")
        artist_names = [name.strip() for name in artist_name.split("/")]

        if len(artist_names) > 1:
            print(f"Detected multiple artist aliases: {artist_names}")

        playlist_tracks = self.get_playlist_tracks(playlist_name)

        # Exit early if playlist not found
        if not playlist_tracks:
            print("Cannot compare - playlist not found or empty!")
            return {"missing": [], "extra": []}

        # Get tracks from all artists/aliases
        if len(artist_names) == 1:
            artist_tracks = self.get_artist_all_tracks(artist_names[0])
        else:
            artist_tracks = self.get_artist_all_tracks_multiple(artist_names)

        if not artist_tracks:
            return {"missing": [], "extra": []}

        print(
            f"\nStarting comparison between {len(artist_tracks)} artist tracks and {len(playlist_tracks)} playlist tracks..."
        )

        # Find missing tracks (artist tracks not in playlist)
        missing_tracks = []
        for artist_track in artist_tracks:
            is_missing = True
            for playlist_track in playlist_tracks:
                if is_track_match(artist_track, playlist_track):
                    is_missing = False
                    break
            if is_missing:
                missing_tracks.append(artist_track)

        # Remove duplicates from missing tracks
        unique_missing = []
        for track in missing_tracks:
            is_duplicate = False
            for existing in unique_missing:
                if is_track_match(track, existing):
                    is_duplicate = True
                    break
            if not is_duplicate:
                unique_missing.append(track)

        # Find extra tracks (playlist tracks not from the artist)
        if len(artist_names) == 1:
            extra_tracks = self.find_non_artist_tracks(artist_names[0], playlist_name)
        else:
            extra_tracks = self.find_non_artist_tracks_multiple(
                artist_names, playlist_name
            )

        # Sort results
        unique_missing.sort(key=lambda x: x["release_date"])
        extra_tracks.sort(key=lambda x: x["name"].lower())

        artist_display = " / ".join(artist_names)
        print(f"\nFound {len(unique_missing)} missing tracks from {artist_display}")
        if unique_missing:
            for track in unique_missing:
                print(
                    f"  - {track['name']} ({track['duration']}) from {track['album']}"
                )

        print(f"\nFound {len(extra_tracks)} tracks NOT by {artist_display}")
        if extra_tracks:
            for track in extra_tracks:
                print(
                    f"  - {track['name']} ({track['duration']}) by {track['main_artist']}"
                )

        return {"missing": unique_missing, "extra": extra_tracks}

    def add_tracks_to_playlist(self, playlist_name: str, tracks: List[Dict]) -> bool:
        """Add tracks to a playlist"""
        if not tracks:
            print("No tracks to add!")
            return False

        # Get playlist ID
        playlists = self.get_user_playlists()
        playlist_id = None

        for playlist in playlists:
            if playlist["name"].lower() == playlist_name.lower():
                playlist_id = playlist["id"]
                break

        if not playlist_id:
            print(f"❌ Playlist '{playlist_name}' not found!")
            return False

        try:
            # Extract track URIs
            track_uris = [track["uri"] for track in tracks]

            # Add tracks in batches of 100 (Spotify API limit)
            added_count = 0
            for i in range(0, len(track_uris), 100):
                batch = track_uris[i: i + 100]
                self.sp.playlist_add_items(playlist_id, batch)
                added_count += len(batch)
                print(
                    f"Added {len(batch)} tracks to playlist (total: {added_count}/{len(track_uris)})"
                )

            print(f"✅ Successfully added {added_count} tracks to '{playlist_name}'!")
            return True

        except Exception as e:
            print(f"❌ Error adding tracks to playlist: {e}")
            return False
