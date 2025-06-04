import spotipy
from spotipy.oauth2 import SpotifyOAuth
import dotenv
import os

dotenv.load_dotenv()

client_id = os.getenv("SPOTIPY_CLIENT_ID")
client_secret = os.getenv("SPOTIPY_CLIENT_SECRET")
redirect_uri = os.getenv("SPOTIPY_REDIRECT_URI")

scopes = "user-library-read user-read-playback-state user-follow-read user-modify-playback-state playlist-read-private playlist-modify-public playlist-modify-private"


def get_spotify_client():
    """
    Authenticate with Spotify and return a Spotipy client.
    """
    sp = spotipy.Spotify(
        auth_manager=SpotifyOAuth(
            scope=scopes,
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
        )
    )

    if not sp.current_user():
        raise Exception("Authentication failed. Please check your credentials.")

    return sp


def get_spotify_user():
    """
    Get the current authenticated Spotify user.

    Returns:
        dict: User profile information.
    """
    sp = get_spotify_client()
    user = sp.current_user()

    if not user:
        raise Exception("Failed to retrieve user information.")

    return user
