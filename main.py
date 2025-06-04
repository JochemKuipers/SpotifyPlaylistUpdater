from auth import get_spotify_client

def main():
    """
    Main function to run the Spotify client.
    """
    try:
        sp = get_spotify_client()
        print("Successfully authenticated with Spotify.")

        # Example usage: Get current user's profile
        user_profile = sp.current_user()
        print(f"User Profile: {user_profile['display_name']} ({user_profile['id']})")

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    main()