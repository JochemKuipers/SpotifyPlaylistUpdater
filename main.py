from spotifyhelpers import getuserfollowedartists
import argparse


def parse_arguments():
    """
    Parse command line arguments.

    Returns:
        argparse.Namespace: Parsed arguments.
    """
    parser = argparse.ArgumentParser(
        description="Fetch all user playlists from Spotify."
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable caching of Spotify API responses.",
    )
    return parser.parse_args()


def main():
    """
    Main function to demonstrate fetching all user playlists concurrently.
    """
    try:
        artists = getuserfollowedartists(
            refresh=args.no_cache
        )  # Assuming this function is defined in spotifyhelpers.py
        if isinstance(artists, list) and artists:
            print(f"Fetched {len(artists)} followed artists.")
            for artist in artists:
                print(f"Artist: {artist['name']} - URI: {artist['uri']}")
        else:
            print("No followed artists found.")
    except Exception as e:
        print(f"An error occurred: {e}")


if __name__ == "__main__":
    args = parse_arguments()
    if args.no_cache:
        print("Caching is disabled. Fetching playlists without cache.")
    else:
        print("Using cache for fetching playlists.")
    main()
