"""
Main entry point for CLI interface
"""
import argparse
import sys

from src.spotify_api.spotify_client import SpotifyPlaylistUpdater


def main():
    """CLI entry point for Spotify Playlist Updater"""
    parser = argparse.ArgumentParser(
        description="Compare artist discography with playlist"
    )
    parser.add_argument(
        "playlist_name", help="Name of the playlist (also used as artist name)"
    )
    parser.add_argument("--client-id", required=True, help="Spotify Client ID")
    parser.add_argument("--client-secret", required=True, help="Spotify Client Secret")
    parser.add_argument(
        "--redirect-uri",
        default="http://127.0.0.1:3000/callback",
        help="Redirect URI (default: http://127.0.0.1:3000/callback)",
    )
    parser.add_argument(
        "--list-playlists", action="store_true", help="Just list all playlists and exit"
    )

    args = parser.parse_args()
    updater = None

    try:
        updater = SpotifyPlaylistUpdater(
            client_id=args.client_id,
            client_secret=args.client_secret,
            redirect_uri=args.redirect_uri,
        )

        # If just listing playlists, do that and exit
        if args.list_playlists:
            playlists = updater.get_user_playlists()
            print(f"\nYour {len(playlists)} playlists:")
            for i, playlist in enumerate(playlists, 1):
                print(f"{i:3d}. '{playlist['name']}' (by {playlist['owner']})")
            return

        # Use playlist name as artist name
        artist_name = args.playlist_name
        playlist_name = args.playlist_name

        print(
            f"Comparing '{artist_name}' discography with playlist '{playlist_name}'..."
        )

        # Use the comprehensive method that finds both missing and extra tracks
        result = updater.find_missing_and_extra_tracks(artist_name, playlist_name)
        missing_tracks = result["missing"]
        extra_tracks = result["extra"]

        if missing_tracks:
            print(
                f"\nSummary: {len(missing_tracks)} tracks are missing from the playlist"
            )
        else:
            print("\n✅ All artist tracks are in the playlist!")

        if extra_tracks:
            print(f"Note: {len(extra_tracks)} tracks in playlist are by other artists")

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
    finally:
        # Clean up to prevent deletion errors
        if updater:
            updater._cleanup()


if __name__ == "__main__":
    main()
