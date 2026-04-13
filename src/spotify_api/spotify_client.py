"""
Core Spotify API functionality for the Spotify Playlist Updater.
"""

from __future__ import annotations

import concurrent.futures
import logging
import threading
import time
from math import ceil
from typing import Any, Callable, Dict, Iterable, List, Mapping, Sequence, cast

import spotipy
from spotipy.oauth2 import SpotifyOAuth
from spotipy.exceptions import SpotifyException

from src.utils.track_utils import (
    clean_name,
    format_duration,
    is_track_match,
)
from src.utils.app_paths import get_cache_dir

logger = logging.getLogger(__name__)


class SpotifyPlaylistUpdater:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        *,
        enable_concurrency: bool = True,
        max_workers: int = 3,
    ):
        """Initialize Spotify client with OAuth"""
        scope = "playlist-read-private playlist-read-collaborative playlist-modify-private playlist-modify-public user-read-private user-read-email"

        # Set up cache file path in app data directory
        cache_dir = get_cache_dir()
        cache_path = cache_dir / ".spotify_cache"

        self.sp = spotipy.Spotify(
            auth_manager=SpotifyOAuth(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
                scope=scope,
                cache_path=str(cache_path),
            )
        )

        # Concurrency settings. We avoid sharing a single Spotipy client across threads:
        # each worker creates its own `spotipy.Spotify` instance using the same auth manager.
        self._enable_concurrency = enable_concurrency
        self._max_workers = max(1, int(max_workers))
        self._auth_lock = threading.Lock()

        # Cache current user once (used for filtering owned playlists).
        self.user: Dict[str, Any] = cast(
            Dict[str, Any], self._call_spotify(self.sp.current_user) or {}
        )

    def close(self) -> None:
        """Release the underlying Spotipy client (best-effort)."""
        self._cleanup()

    def _cleanup(self) -> None:
        """
        Backwards-compatible cleanup hook.

        Older parts of the app call `_cleanup()` explicitly. Spotipy doesn't require
        explicit closing, but we null out references to help GC and avoid shutdown
        edge-cases.
        """
        try:
            if hasattr(self, "sp"):
                del self.sp
        except Exception:
            logger.exception("Error cleaning up Spotify client")

    def _call_spotify(
        self,
        fn: Callable[..., Any],
        *args: Any,
        _max_retries: int = 6,
        **kwargs: Any,
    ) -> Any:
        """
        Call Spotify API with basic retry/backoff.

        Handles Spotify rate limits (429) and transient 5xx responses.
        """
        attempt = 0
        while True:
            try:
                return fn(*args, **kwargs)
            except SpotifyException as e:
                status = getattr(e, "http_status", None)
                headers = getattr(e, "headers", None) or {}

                # Rate limited
                if status == 429 and attempt < _max_retries:
                    retry_after = headers.get("Retry-After")
                    try:
                        wait_s = int(retry_after) if retry_after is not None else 1
                    except (TypeError, ValueError):
                        wait_s = 1
                    wait_s = max(1, min(wait_s, 60))
                    logger.warning("Spotify rate limit hit; sleeping %ss", wait_s)
                    time.sleep(wait_s)
                    attempt += 1
                    continue

                # Transient server errors
                if status in {500, 502, 503, 504} and attempt < _max_retries:
                    wait_s = min(2**attempt, 30)
                    logger.warning("Spotify server error %s; retrying in %ss", status, wait_s)
                    time.sleep(wait_s)
                    attempt += 1
                    continue

                raise

    def _make_worker_client(self) -> spotipy.Spotify:
        """
        Create a Spotipy client suitable for use in a worker thread.

        Sharing a single Spotipy client instance across threads is risky; Spotipy uses a
        shared requests session and may refresh tokens, touching the cache file.
        We re-create the client per worker and serialize token refresh/cache access.
        """
        auth_manager = self.sp.auth_manager
        return spotipy.Spotify(auth_manager=auth_manager)

    def _map_batches_concurrently(
        self,
        batches: Sequence[Sequence[str]],
        fetch_fn: Callable[[spotipy.Spotify, Sequence[str]], Any],
    ) -> List[Any]:
        """Fetch many independent batches concurrently (bounded, best-effort)."""
        if not batches:
            return []
        if not self._enable_concurrency or self._max_workers <= 1 or len(batches) == 1:
            client = self.sp
            return [fetch_fn(client, batch) for batch in batches]

        results: List[Any] = [None] * len(batches)
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(self._max_workers, len(batches))
        ) as executor:
            future_map: Dict[concurrent.futures.Future[Any], int] = {}
            for idx, batch in enumerate(batches):
                future = executor.submit(
                    lambda i=idx, b=batch: fetch_fn(self._make_worker_client(), b)
                )
                future_map[future] = idx

            for future in concurrent.futures.as_completed(future_map):
                idx = future_map[future]
                results[idx] = future.result()

        return results

    def _get_playlist_tracks_by_id(
        self,
        playlist_id: str,
        *,
        client: spotipy.Spotify | None = None,
        log_skips: bool = False,
    ) -> List[Dict[str, Any]]:
        """Fetch all usable track entries for a playlist ID."""
        sp = client or self.sp
        result = self._call_spotify(sp.playlist_items, playlist_id, limit=100)
        total = int(result.get("total") or 0)
        if total == 0:
            return []

        tracklist: List[Dict[str, Any]] = []
        skipped_missing_track = 0
        skipped_unusable_id = 0
        skipped_unplayable = 0
        skipped_local = 0

        for item in self._iter_paged(result):
            track = (item or {}).get("track")
            if not isinstance(track, dict) or not track:
                skipped_missing_track += 1
                continue

            is_local = bool((item or {}).get("is_local")) or bool(track.get("is_local"))
            if is_local:
                skipped_local += 1
                continue

            if track.get("is_playable") is False:
                skipped_unplayable += 1
                continue

            uri = track.get("uri")
            track_id = track.get("id")
            if not uri or not track_id:
                skipped_unusable_id += 1
                continue

            tracklist.append(
                {
                    "name": clean_name(track.get("name") or ""),
                    "duration": format_duration(int(track.get("duration_ms") or 0)),
                    "artists": list(track.get("artists") or []),
                    "uri": uri,
                }
            )

        if log_skips and (
            skipped_missing_track or skipped_unusable_id or skipped_unplayable or skipped_local
        ):
            logger.info(
                "Skipped playlist items (missing=%s, unusable_id=%s, unplayable=%s, local=%s)",
                skipped_missing_track,
                skipped_unusable_id,
                skipped_unplayable,
                skipped_local,
            )

        return tracklist

    @staticmethod
    def _duration_to_seconds(duration: str) -> int:
        minutes, seconds = duration.split(":")
        return int(minutes) * 60 + int(seconds)

    def _missing_tracks_fast(
        self,
        *,
        artist_tracks: List[Dict[str, Any]],
        playlist_tracks: List[Dict[str, Any]],
        tolerance_seconds: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Find missing tracks using the same rule as `is_track_match`, but indexed.
        """
        index: Dict[str, List[int]] = {}
        for t in playlist_tracks:
            name = str(t.get("name") or "").lower()
            dur = t.get("duration")
            if not name or not isinstance(dur, str) or ":" not in dur:
                continue
            index.setdefault(name, []).append(self._duration_to_seconds(dur))

        for durs in index.values():
            durs.sort()

        missing: List[Dict[str, Any]] = []
        for at in artist_tracks:
            name = str(at.get("name") or "").lower()
            dur = at.get("duration")
            if not name or not isinstance(dur, str) or ":" not in dur:
                missing.append(at)
                continue
            target = self._duration_to_seconds(dur)
            durs = index.get(name)
            if not durs:
                missing.append(at)
                continue

            lo, hi = 0, len(durs)
            while lo < hi:
                mid = (lo + hi) // 2
                if durs[mid] < target:
                    lo = mid + 1
                else:
                    hi = mid

            found = False
            for k in (lo - 1, lo, lo + 1):
                if 0 <= k < len(durs) and abs(durs[k] - target) <= tolerance_seconds:
                    found = True
                    break
            if not found:
                missing.append(at)

        unique: List[Dict[str, Any]] = []
        seen: Dict[str, List[int]] = {}
        for t in missing:
            name = str(t.get("name") or "").lower()
            dur = t.get("duration")
            if not name or not isinstance(dur, str) or ":" not in dur:
                unique.append(t)
                continue
            target = self._duration_to_seconds(dur)
            existing = seen.setdefault(name, [])
            if any(abs(x - target) <= tolerance_seconds for x in existing):
                continue
            existing.append(target)
            unique.append(t)

        return unique

    def _extra_tracks_fast(
        self,
        *,
        artist_name: str,
        playlist_tracks: List[Dict[str, Any]],
        client: spotipy.Spotify | None = None,
    ) -> List[Dict[str, Any]]:
        """Find non-artist tracks using playlist embedded artist IDs/names."""
        sp = client or self.sp
        results = self._call_spotify(sp.search, q=artist_name, type="artist")
        items = ((results or {}).get("artists") or {}).get("items") or []
        target_artist_id = None
        for artist in items:
            if (artist.get("name") or "").lower() == artist_name.lower():
                target_artist_id = artist.get("id")
                break
        if not target_artist_id:
            return []

        extra: List[Dict[str, Any]] = []
        for t in playlist_tracks:
            artists = t.get("artists") or []
            artist_ids = {
                a.get("id")
                for a in artists
                if isinstance(a, dict) and a.get("id")
            }
            if target_artist_id in artist_ids:
                continue
            main_artist = None
            if artists and isinstance(artists[0], dict):
                main_artist = artists[0].get("name")
            extra.append(
                {
                    "name": t.get("name"),
                    "duration": t.get("duration"),
                    "artists": artists,
                    "uri": t.get("uri"),
                    "main_artist": main_artist or "Unknown",
                }
            )
        return extra

    def _extra_tracks_fast_multiple(
        self,
        *,
        artist_names: List[str],
        playlist_tracks: List[Dict[str, Any]],
        client: spotipy.Spotify | None = None,
    ) -> List[Dict[str, Any]]:
        """Like `_extra_tracks_fast`, but accepts multiple artist aliases."""
        sp = client or self.sp
        normalized_names = {n.strip().lower() for n in artist_names if n and n.strip()}
        if not normalized_names:
            return []

        target_artist_ids: set[str] = set()
        for name in sorted(normalized_names):
            results = self._call_spotify(sp.search, q=name, type="artist")
            items = ((results or {}).get("artists") or {}).get("items") or []
            for artist in items:
                if (artist.get("name") or "").strip().lower() == name:
                    artist_id = artist.get("id")
                    if artist_id:
                        target_artist_ids.add(str(artist_id))
                    break

        if not target_artist_ids and not normalized_names:
            return []

        extra: List[Dict[str, Any]] = []
        for t in playlist_tracks:
            artists = t.get("artists") or []
            artist_ids = {
                str(a.get("id"))
                for a in artists
                if isinstance(a, dict) and a.get("id")
            }
            artist_display_names = {
                (a.get("name") or "").strip().lower()
                for a in artists
                if isinstance(a, dict) and a.get("name")
            }

            if artist_ids.intersection(target_artist_ids) or artist_display_names.intersection(
                normalized_names
            ):
                continue

            main_artist = None
            if artists and isinstance(artists[0], dict):
                main_artist = artists[0].get("name")
            extra.append(
                {
                    "name": t.get("name"),
                    "duration": t.get("duration"),
                    "artists": artists,
                    "uri": t.get("uri"),
                    "main_artist": main_artist or "Unknown",
                }
            )

        return extra

    def _iter_paged(
        self,
        first_page: Mapping[str, Any],
    ) -> Iterable[Dict[str, Any]]:
        """Yield items from a Spotipy paging object sequentially."""
        page: Mapping[str, Any] = first_page
        while True:
            for item in (page.get("items") or []):
                if isinstance(item, dict):
                    yield item
            if page.get("next"):
                page = cast(Mapping[str, Any], self._call_spotify(self.sp.next, page) or {})
            else:
                break

    def get_user_playlists(self) -> List[Dict]:
        """Get all user playlists with details"""
        try:
            logger.info("Fetching user playlists")
            result = self._call_spotify(self.sp.current_user_playlists, limit=50)
            total = int(result.get("total") or 0)

            if total == 0:
                logger.warning("No playlists found")
                return []

            playlists: List[Dict[str, Any]] = []
            user_id = (self.user or {}).get("id")

            for item in self._iter_paged(result):
                owner_id = ((item or {}).get("owner") or {}).get("id")
                # Only include playlists owned by the current user (same behavior as before).
                if user_id and owner_id != user_id:
                    continue
                owner_display = ((item or {}).get("owner") or {}).get("display_name")
                playlists.append(
                    {
                        "name": item.get("name"),
                        "id": item.get("id"),
                        "uri": item.get("uri"),
                        "owner": owner_display,
                    }
                )

            logger.info("Successfully fetched %s playlists", len(playlists))
            return playlists

        except Exception:
            logger.exception("Error getting playlists")
            raise

    def find_playlist_by_name(self, playlist_name: str) -> Dict:
        """Find a playlist by name using cached playlists"""
        playlists = self.get_user_playlists()  # This will use cache if available

        logger.info("Searching for playlist '%s' in user playlists", playlist_name)
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
                logger.info("Found exact playlist match: '%s'", matched_playlist["name"])
            else:
                logger.info(
                    "Found %s playlist match: '%s' (searched '%s')",
                    best_match[0],
                    matched_playlist["name"],
                    playlist_name,
                )

                if len(playlist_matches) > 1:
                    logger.info("Other possible playlist matches: %s", len(playlist_matches) - 1)

            return matched_playlist
        else:
            logger.warning("No playlist matching '%s' found", playlist_name)
            return {}

    def get_playlist_tracks(self, playlist_name: str) -> List[Dict]:
        """Get all track details from a playlist by name"""
        try:
            # Find the playlist using cached playlists
            playlist = self.find_playlist_by_name(playlist_name)
            if not playlist:
                return []

            playlist_id = playlist["id"]
            matched_name = playlist["name"]
            logger.info("Using playlist '%s'", matched_name)
            tracklist = self._get_playlist_tracks_by_id(str(playlist_id), log_skips=True)
            logger.info("Found %s tracks in playlist '%s'", len(tracklist), matched_name)
            return tracklist

        except Exception:
            logger.exception("Error getting playlist tracks")
            raise

    def find_missing_tracks(self, artist_name: str, playlist_name: str) -> List[Dict]:
        """Compare artist discography with playlist and find missing tracks"""
        playlist_tracks = self.get_playlist_tracks(playlist_name)

        # Exit early if playlist not found
        if not playlist_tracks:
            logger.warning("Cannot compare - playlist not found or empty")
            return []

        artist_tracks = self.get_artist_all_tracks(artist_name)

        if not artist_tracks:
            return []

        logger.info(
            "Starting comparison between %s artist tracks and %s playlist tracks",
            len(artist_tracks),
            len(playlist_tracks),
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
            logger.info("No missing tracks - playlist is complete")
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

        logger.info("Found %s unique missing tracks", len(unique_missing))

        return unique_missing

    def find_non_artist_tracks(
        self, artist_name: str, playlist_name: str
    ) -> List[Dict]:
        """Find tracks in playlist that are NOT from the specified artist"""
        playlist_tracks = self.get_playlist_tracks(playlist_name)

        if not playlist_tracks:
            logger.warning("Cannot compare - playlist not found or empty")
            return []

        # Get artist info for comparison
        results = self._call_spotify(self.sp.search, q=artist_name, type="artist")

        if not results["artists"]["items"]:
            logger.warning("Artist '%s' not found", artist_name)
            return []

        # Find the correct artist
        target_artist_id = None
        for artist in results["artists"]["items"]:
            if artist["name"].lower() == artist_name.lower():
                target_artist_id = artist["id"]
                break

        if not target_artist_id:
            logger.warning("Exact match for artist '%s' not found", artist_name)
            return []

        # Process tracks in parallel batches
        track_ids = [
            t["uri"].split(":")[-1]
            for t in playlist_tracks
            if isinstance(t, dict) and t.get("uri") and str(t["uri"]).startswith("spotify:track:")
        ]
        batch_size = 50  # Spotify allows up to 50 tracks per request
        num_batches = ceil(len(track_ids) / batch_size)

        logger.info("Processing %s tracks in %s batches", len(track_ids), num_batches)

        non_artist_tracks: List[Dict[str, Any]] = []
        batches = [track_ids[i : i + batch_size] for i in range(0, len(track_ids), batch_size)]

        def fetch_tracks(client: spotipy.Spotify, ids: Sequence[str]) -> Any:
            return self._call_spotify(client.tracks, ids)

        batch_results = self._map_batches_concurrently(batches, fetch_tracks)

        for batch_idx, tracks_details in enumerate(batch_results):
            start = batch_idx * batch_size
            for j, full_track in enumerate((tracks_details.get("tracks") or [])):
                if not full_track:
                    continue
                track_artist_ids = [a.get("id") for a in (full_track.get("artists") or [])]
                if target_artist_id in track_artist_ids:
                    continue
                original_track = playlist_tracks[start + j]
                main_artist = None
                if full_track.get("artists"):
                    main_artist = full_track["artists"][0].get("name")
                non_artist_tracks.append(
                    {
                        "name": original_track["name"],
                        "duration": original_track["duration"],
                        "artists": original_track["artists"],
                        "uri": original_track["uri"],
                        "main_artist": main_artist or "Unknown",
                    }
                )

        return non_artist_tracks

    def find_non_artist_tracks_multiple(
        self, artist_names: List[str], playlist_name: str
    ) -> List[Dict]:
        """Find tracks in playlist that are NOT from any of the specified artists using optimized batching"""
        playlist_tracks = self.get_playlist_tracks(playlist_name)

        if not playlist_tracks:
            logger.warning("Cannot compare - playlist not found or empty")
            return []

        # Get artist IDs for all artists
        target_artist_ids = []

        for artist_name in artist_names:
            results = self._call_spotify(self.sp.search, q=artist_name.strip(), type="artist")

            if not results["artists"]["items"]:
                logger.warning("Artist '%s' not found", artist_name)
                continue

            # Find exact match
            for artist in results["artists"]["items"]:
                if artist["name"].lower() == artist_name.strip().lower():
                    target_artist_ids.append(artist["id"])
                    logger.info("Found artist ID for: %s", artist["name"])
                    break

        if not target_artist_ids:
            logger.warning("No valid artists found")
            return []

        # Process tracks in parallel batches with optimized batching
        track_ids = [
            t["uri"].split(":")[-1]
            for t in playlist_tracks
            if isinstance(t, dict) and t.get("uri") and str(t["uri"]).startswith("spotify:track:")
        ]
        batch_size = 50  # Spotify allows up to 50 tracks per request
        num_batches = ceil(len(track_ids) / batch_size)

        logger.info("Processing %s tracks in %s batches", len(track_ids), num_batches)

        non_artist_tracks: List[Dict[str, Any]] = []
        normalized_names = {n.strip().lower() for n in artist_names}
        batches = [track_ids[i : i + batch_size] for i in range(0, len(track_ids), batch_size)]

        def fetch_tracks(client: spotipy.Spotify, ids: Sequence[str]) -> Any:
            return self._call_spotify(client.tracks, ids)

        batch_results = self._map_batches_concurrently(batches, fetch_tracks)

        for batch_idx, tracks_details in enumerate(batch_results):
            start = batch_idx * batch_size
            for j, full_track in enumerate((tracks_details.get("tracks") or [])):
                if not full_track:
                    continue

                original_track = playlist_tracks[start + j]
                original_artist_names = {
                    (a.get("name") or "").strip().lower()
                    for a in (original_track.get("artists") or [])
                }
                original_artist_ids = {
                    a.get("id")
                    for a in (original_track.get("artists") or [])
                    if a.get("id")
                }

                is_allowed = bool(original_artist_ids.intersection(target_artist_ids)) or bool(
                    original_artist_names.intersection(normalized_names)
                )
                if is_allowed:
                    continue

                main_artist = None
                if full_track.get("artists"):
                    main_artist = full_track["artists"][0].get("name")
                non_artist_tracks.append(
                    {
                        "name": original_track["name"],
                        "duration": original_track["duration"],
                        "artists": original_track["artists"],
                        "uri": original_track["uri"],
                        "main_artist": main_artist or "Unknown",
                    }
                )

        return non_artist_tracks

    def get_artist_all_tracks(self, artist_name: str) -> List[Dict]:
        """Get all tracks from an artist's discography"""
        try:
            # Search for artist
            results = self._call_spotify(self.sp.search, q=artist_name, type="artist")

            if not results["artists"]["items"]:
                logger.warning("Artist '%s' not found", artist_name)
                return []

            artist_id = None
            artist_name_found = None

            # Find exact match
            for artist in results["artists"]["items"]:
                if artist["name"].lower() == artist_name.lower():
                    artist_id = artist["id"]
                    artist_name_found = artist["name"]
                    logger.info("Found artist: %s", artist_name_found)
                    break

            if not artist_id:
                logger.warning("Exact match for artist '%s' not found", artist_name)
                return []

            # Get all albums
            logger.info(f"Fetching albums for {artist_name_found}")
            all_album_ids = []

            albums = self._call_spotify(
                self.sp.artist_albums,
                artist_id,
                album_type="album,single,compilation",
                limit=50,
            )

            while albums:
                for album in albums["items"]:
                    all_album_ids.append(album["id"])

                if albums["next"]:
                    albums = self._call_spotify(self.sp.next, albums)
                else:
                    break

            logger.info("Found %s albums/singles for %s", len(all_album_ids), artist_name_found)

            if not all_album_ids:
                return []

            all_tracks = []
            batch_size = 20  # Spotify allows up to 20 albums per request
            num_batches = ceil(len(all_album_ids) / batch_size)
            logger.info("Processing %s albums in %s batches", len(all_album_ids), num_batches)

            album_batches = [
                all_album_ids[i : i + batch_size]
                for i in range(0, len(all_album_ids), batch_size)
            ]

            def fetch_albums(client: spotipy.Spotify, ids: Sequence[str]) -> Any:
                return self._call_spotify(client.albums, ids)

            batch_results = self._map_batches_concurrently(album_batches, fetch_albums)

            for albums_details in batch_results:
                for album_detail in (albums_details.get("albums") or []):
                    if not album_detail:
                        continue
                    album_name = album_detail.get("name")
                    release_date = album_detail.get("release_date")
                    for track in ((album_detail.get("tracks") or {}).get("items") or []):
                        track_artists = track.get("artists") or []
                        if not (
                            any(a.get("id") == artist_id for a in track_artists)
                            or any(
                                (a.get("name") or "") == artist_name_found
                                for a in track_artists
                            )
                        ):
                            continue
                        all_tracks.append(
                            {
                                "name": clean_name(track.get("name") or ""),
                                "duration": format_duration(
                                    int(track.get("duration_ms") or 0)
                                ),
                                "artists": track_artists,
                                "album": album_name,
                                "release_date": release_date,
                                "uri": track.get("uri"),
                            }
                        )

            logger.info("Found %s total tracks by %s", len(all_tracks), artist_name_found)
            return all_tracks

        except Exception:
            logger.exception("Error getting artist tracks")
            raise

    def get_artist_all_tracks_multiple(self, artist_names: List[str]) -> List[Dict]:
        """Get all tracks from multiple artists' discographies"""
        try:
            all_tracks = []

            logger.info("Getting tracks for %s artists...", len(artist_names))

            for artist_name in artist_names:
                logger.info("Getting tracks for artist: %s", artist_name)
                artist_tracks = self.get_artist_all_tracks(artist_name)

                if artist_tracks:
                    all_tracks.extend(artist_tracks)
                    logger.info("Added %s tracks from %s", len(artist_tracks), artist_name)
                else:
                    logger.info("No tracks found for %s", artist_name)

            # Remove duplicates based on track name and duration
            logger.info("Removing duplicates from %s total tracks...", len(all_tracks))
            unique_tracks = []

            for track in all_tracks:
                is_duplicate = False
                for existing in unique_tracks:
                    if is_track_match(track, existing):
                        is_duplicate = True
                        break
                if not is_duplicate:
                    unique_tracks.append(track)

            logger.info("Total unique tracks across all artists: %s", len(unique_tracks))
            return unique_tracks

        except Exception:
            logger.exception("Error getting tracks for multiple artists")
            raise

    def remove_track_from_playlist(self, playlist_name: str, track: Dict) -> bool:
        """Remove a single track from a playlist"""
        if not track:
            logger.warning("No track to remove")
            return False

        # Get playlist ID
        playlists = self.get_user_playlists()
        playlist_id = None

        for playlist in playlists:
            if playlist["name"].lower() == playlist_name.lower():
                playlist_id = playlist["id"]
                break

        if not playlist_id:
            logger.warning("Playlist '%s' not found", playlist_name)
            return False

        try:
            # Extract track URI
            track_uri = track["uri"]

            # Remove track from playlist
            self._call_spotify(
                self.sp.playlist_remove_all_occurrences_of_items,
                playlist_id,
                [track_uri],
            )

            logger.info("Removed '%s' from '%s'", track.get("name"), playlist_name)
            return True

        except Exception:
            logger.exception("Error removing track from playlist")
            return False

    def remove_tracks_from_playlist(
        self, playlist_name: str, tracks: List[Dict]
    ) -> bool:
        """Remove multiple tracks from a playlist"""
        if not tracks:
            logger.warning("No tracks to remove")
            return False

        # Get playlist ID
        playlists = self.get_user_playlists()
        playlist_id = None

        for playlist in playlists:
            if playlist["name"].lower() == playlist_name.lower():
                playlist_id = playlist["id"]
                break

        if not playlist_id:
            logger.warning("Playlist '%s' not found", playlist_name)
            return False

        try:
            # Extract track URIs
            track_uris = [track["uri"] for track in tracks]

            # Remove tracks in batches of 100 (Spotify API limit)
            removed_count = 0
            for i in range(0, len(track_uris), 100):
                batch = track_uris[i : i + 100]
                self._call_spotify(
                    self.sp.playlist_remove_all_occurrences_of_items,
                    playlist_id,
                    batch,
                )
                removed_count += len(batch)
                logger.info(
                    "Removed %s tracks (total %s/%s)",
                    len(batch),
                    removed_count,
                    len(track_uris),
                )

            logger.info(
                "Successfully removed %s tracks from '%s'",
                removed_count,
                playlist_name,
            )
            return True

        except Exception:
            logger.exception("Error removing tracks from playlist")
            return False

    def remove_tracks_from_playlist_id(
        self, playlist_id: str, tracks: List[Dict]
    ) -> bool:
        """Remove multiple tracks from a playlist by playlist ID."""
        if not tracks:
            logger.warning("No tracks to remove")
            return False

        try:
            track_uris = [track["uri"] for track in tracks if track and track.get("uri")]
            removed_count = 0
            for i in range(0, len(track_uris), 100):
                batch = track_uris[i : i + 100]
                self._call_spotify(
                    self.sp.playlist_remove_all_occurrences_of_items,
                    playlist_id,
                    batch,
                )
                removed_count += len(batch)
                logger.info(
                    "Removed %s tracks (total %s/%s)",
                    len(batch),
                    removed_count,
                    len(track_uris),
                )

            logger.info(
                "Successfully removed %s tracks from playlist_id=%s",
                removed_count,
                playlist_id,
            )
            return True
        except Exception:
            logger.exception("Error removing tracks from playlist_id=%s", playlist_id)
            return False

    def find_missing_and_extra_tracks(
        self, artist_name: str, playlist_name: str
    ) -> Dict:
        """Compare artist discography with playlist and find both missing and extra tracks"""
        # Parse artist names (handle aliases separated by "/")
        artist_names = [name.strip() for name in artist_name.split("/")]

        if len(artist_names) > 1:
            logger.info("Detected multiple artist aliases: %s", artist_names)

        playlist_tracks = self.get_playlist_tracks(playlist_name)

        # Exit early if playlist not found
        if not playlist_tracks:
            logger.warning("Cannot compare - playlist not found or empty")
            return {"missing": [], "extra": []}

        # Get tracks from all artists/aliases
        if len(artist_names) == 1:
            artist_tracks = self.get_artist_all_tracks(artist_names[0])
        else:
            artist_tracks = self.get_artist_all_tracks_multiple(artist_names)

        if not artist_tracks:
            return {"missing": [], "extra": []}

        logger.info(
            "Starting comparison between %s artist tracks and %s playlist tracks",
            len(artist_tracks),
            len(playlist_tracks),
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
        logger.info("Found %s missing tracks from %s", len(unique_missing), artist_display)
        logger.info("Found %s tracks NOT by %s", len(extra_tracks), artist_display)

        return {"missing": unique_missing, "extra": extra_tracks}

    def add_tracks_to_playlist(self, playlist_name: str, tracks: List[Dict]) -> bool:
        """Add tracks to a playlist"""
        if not tracks:
            logger.warning("No tracks to add")
            return False

        # Get playlist ID
        playlists = self.get_user_playlists()
        playlist_id = None

        for playlist in playlists:
            if playlist["name"].lower() == playlist_name.lower():
                playlist_id = playlist["id"]
                break

        if not playlist_id:
            logger.warning("Playlist '%s' not found", playlist_name)
            return False

        try:
            # Extract track URIs
            track_uris = [track["uri"] for track in tracks]

            # Add tracks in batches of 100 (Spotify API limit)
            added_count = 0
            for i in range(0, len(track_uris), 100):
                batch = track_uris[i : i + 100]
                self._call_spotify(self.sp.playlist_add_items, playlist_id, batch)
                added_count += len(batch)
                logger.info(
                    "Added %s tracks (total %s/%s)",
                    len(batch),
                    added_count,
                    len(track_uris),
                )

            logger.info("Successfully added %s tracks to '%s'", added_count, playlist_name)
            return True

        except Exception:
            logger.exception("Error adding tracks to playlist")
            return False

    def add_tracks_to_playlist_id(self, playlist_id: str, tracks: List[Dict]) -> bool:
        """Add tracks to a playlist by playlist ID."""
        if not tracks:
            logger.warning("No tracks to add")
            return False
        try:
            track_uris = [track["uri"] for track in tracks if track and track.get("uri")]
            added_count = 0
            for i in range(0, len(track_uris), 100):
                batch = track_uris[i : i + 100]
                self._call_spotify(self.sp.playlist_add_items, playlist_id, batch)
                added_count += len(batch)
                logger.info(
                    "Added %s tracks (total %s/%s)",
                    len(batch),
                    added_count,
                    len(track_uris),
                )
            logger.info(
                "Successfully added %s tracks to playlist_id=%s",
                added_count,
                playlist_id,
            )
            return True
        except Exception:
            logger.exception("Error adding tracks to playlist_id=%s", playlist_id)
            return False

    def add_tracks_to_saved_tracks(self, tracks: List[Dict]) -> bool:
        """Add the given tracks to the user's Saved Tracks library."""
        if not tracks:
            logger.warning("No tracks to save")
            return False

        track_ids: List[str] = []
        for t in tracks:
            if not t or not t.get("uri"):
                continue
            uri = str(t["uri"])
            if uri.startswith("spotify:track:"):
                track_ids.append(uri.split(":")[-1])

        if not track_ids:
            logger.warning("No valid Spotify track IDs to save")
            return False

        try:
            saved = 0
            for i in range(0, len(track_ids), 50):
                batch = track_ids[i : i + 50]
                self._call_spotify(self.sp.current_user_saved_tracks_add, batch)
                saved += len(batch)
            logger.info("Saved %s tracks to user's library", saved)
            return True
        except Exception:
            logger.exception("Error saving tracks to user's library")
            return False

    def analyze_all_playlists(self) -> Dict:
        """Analyze all user playlists by extracting artist names from playlist names"""
        try:
            logger.info("Starting analysis of all playlists...")
            
            # Get all user playlists
            playlists = self.get_user_playlists()
            if not playlists:
                logger.info("No playlists found to analyze")
                return {}
            
            logger.info("Found %s playlists to analyze", len(playlists))
            
            results: Dict[str, Any] = {}

            def analyze_one(pl: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
                playlist_name = str(pl.get("name") or "")
                playlist_id = pl.get("id")
                artist_name = playlist_name.strip()
                artist_names = [n.strip() for n in artist_name.split("/") if n.strip()]

                if not artist_name or not playlist_id:
                    return playlist_name, {"missing": [], "extra": [], "total_tracks": 0}

                sp = self._make_worker_client()

                if len(artist_names) > 1:
                    artist_tracks = self.get_artist_all_tracks_multiple(artist_names)
                else:
                    artist_tracks = self.get_artist_all_tracks(artist_name)
                if not artist_tracks:
                    return playlist_name, {
                        "missing": [],
                        "extra": [],
                        "total_tracks": 0,
                        "error": f"No tracks found for artist: {artist_name}",
                    }

                playlist_tracks = self._get_playlist_tracks_by_id(
                    str(playlist_id), client=sp, log_skips=False
                )
                if not playlist_tracks:
                    return playlist_name, {"missing": [], "extra": [], "total_tracks": 0}

                unique_missing = self._missing_tracks_fast(
                    artist_tracks=artist_tracks,
                    playlist_tracks=playlist_tracks,
                    tolerance_seconds=5,
                )
                if len(artist_names) > 1:
                    extra_tracks = self._extra_tracks_fast_multiple(
                        artist_names=artist_names, playlist_tracks=playlist_tracks, client=sp
                    )
                else:
                    extra_tracks = self._extra_tracks_fast(
                        artist_name=artist_name, playlist_tracks=playlist_tracks, client=sp
                    )

                unique_missing.sort(key=lambda x: x.get("release_date") or "")
                extra_tracks.sort(key=lambda x: str(x.get("name") or "").lower())

                return playlist_name, {
                    "artist_name": artist_name,
                    "missing": unique_missing,
                    "extra": extra_tracks,
                    "total_tracks": len(playlist_tracks),
                    "artist_tracks_count": len(artist_tracks),
                }

            max_workers = min(self._max_workers, max(1, len(playlists)))
            if self._enable_concurrency and max_workers > 1:
                with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = [executor.submit(analyze_one, pl) for pl in playlists]
                    for future in concurrent.futures.as_completed(futures):
                        name, data = future.result()
                        results[name] = data
            else:
                for pl in playlists:
                    name, data = analyze_one(pl)
                    results[name] = data
            
            logger.info("Analysis complete! Analyzed %s playlists", len(results))
            return results
            
        except Exception:
            logger.exception("Error analyzing all playlists")
            raise
