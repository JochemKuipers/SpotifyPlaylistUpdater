# Spotify Playlist Updater

A Python application that helps you manage your Spotify playlists by comparing an artist's complete discography with your playlist to find missing tracks and identify non-artist tracks. Available as both a command-line tool and a modern GUI application.

## Features

- **Missing Track Detection**: Find tracks from an artist's discography that are missing from your playlist
- **Non-Artist Track Identification**: Identify tracks in your playlist that are not by the specified artist(s)
- **Multiple Artist Support**: Handle artist aliases (e.g., "Artist Name / Alias Name")
- **Batch Operations**: Add/remove multiple tracks at once
- **Smart Matching**: Uses track name and duration matching with tolerance for slight differences
- **Caching**: Intelligent caching system for playlists and tracks to improve performance
- **GUI Interface**: User-friendly PyQt6-based graphical interface
- **Command Line Interface**: Simple CLI for automation and scripting

## Screenshots

### GUI Application
- **Three-panel layout**: Missing tracks, non-artist tracks, and detailed track information
- **Playlist autocomplete**: Loads your playlists for easy selection
- **Individual/bulk operations**: Add or remove tracks individually or in bulk
- **Real-time progress**: Progress indicators for all operations

## Installation

### Prerequisites
- Python 3.7 or higher
- Spotify Developer Account (for API credentials)

### Install Dependencies

```bash
pip install spotipy PyQt6
```

### Spotify API Setup

1. Go to [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. Create a new application
3. Note your **Client ID** and **Client Secret**
4. Add `http://127.0.0.1:3000/callback` as a redirect URI in your app settings

## Usage

### GUI Application (Recommended)

```bash
python gui.py
```

1. **Enter Credentials**: Input your Spotify Client ID and Client Secret
2. **Save Credentials**: Click "Save Credentials" to store them locally
3. **Select Playlist**: Use the autocomplete field to select a playlist (it will load your playlists automatically)
4. **Analyze**: Click "Analyze Playlist" to compare the artist's discography with your playlist
5. **Review Results**: 
   - Left panel shows missing tracks from the artist
   - Right panel shows non-artist tracks in your playlist
   - Bottom panel shows detailed information about selected tracks
6. **Take Action**: Add missing tracks or remove non-artist tracks as needed

### Command Line Interface

```bash
python main.py "Artist/Playlist Name" --client-id YOUR_CLIENT_ID --client-secret YOUR_CLIENT_SECRET
```

#### Options

- `--client-id`: Your Spotify Client ID (required)
- `--client-secret`: Your Spotify Client Secret (required)
- `--redirect-uri`: Redirect URI (default: `http://127.0.0.1:3000/callback`)
- `--list-playlists`: List all your playlists and exit

#### Examples

```bash
# Analyze a playlist
python main.py "Taylor Swift" --client-id abc123 --client-secret def456

# Handle artist aliases
python main.py "Kanye West / Ye" --client-id abc123 --client-secret def456

# List all playlists
python main.py "dummy" --client-id abc123 --client-secret def456 --list-playlists
```

## How It Works

### Track Matching Algorithm
The application uses intelligent track matching based on:
- **Track name comparison** (case-insensitive, with featured artist removal)
- **Duration matching** (5-second tolerance for slight differences)

### Artist Name Cleaning
Automatically removes featuring artists and collaborations:
- `"Song (feat. Artist)"` → `"Song"`
- `"Song - with Artist"` → `"Song"`
- `"Song feat. Artist"` → `"Song"`

### Multiple Artist Support
Use `/` to separate artist names for aliases:
- `"Kanye West / Ye"` will find tracks under both names
- Automatically deduplicates tracks found under multiple aliases

## File Structure

```
SpotifyPlaylistUpdater/
├── main.py              # Core logic and CLI interface
├── gui.py               # PyQt6 GUI application
├── README.md            # This file
├── .gitignore          # Git ignore rules
└── credentials.json     # Saved API credentials (created after first save)
```

## Configuration

### Credentials Storage
The GUI automatically saves your credentials to `credentials.json` for convenience. This file contains:

```json
{
    "client_id": "your_client_id",
    "client_secret": "your_client_secret", 
    "redirect_uri": "http://127.0.0.1:3000/callback"
}
```

### Cache Behavior
- **Playlist cache**: Stores your playlist list to avoid repeated API calls
- **Track cache**: Caches playlist tracks for faster re-analysis
- **Auto-refresh**: Caches refresh when credentials change

## API Rate Limiting

The application includes built-in rate limiting and optimization:
- **Parallel processing**: Uses ThreadPoolExecutor for faster data fetching
- **Batch requests**: Groups API calls to minimize requests
- **Smart delays**: Automatic delays between batches to avoid rate limits
- **Reduced concurrency**: Configurable worker limits to stay within API limits

## Troubleshooting

### Common Issues

1. **"Artist not found"**
   - Ensure the artist name is spelled correctly
   - Try using the exact name as it appears on Spotify
   - For artists with aliases, use the format: `"Main Name / Alias"`

2. **"Playlist not found"**
   - Make sure you have access to the playlist
   - Check that the playlist name matches exactly (case-insensitive matching is supported)

3. **Authentication Issues**
   - Verify your Client ID and Client Secret
   - Ensure `http://127.0.0.1:3000/callback` is added to your Spotify app settings
   - Try clearing the `.cache` file in your directory

4. **Rate Limiting**
   - If you encounter rate limiting, the app will automatically retry
   - For large playlists, the process may take several minutes

### Debug Mode
Set logging level for more detailed output:

```python
import logging
logging.basicConfig(level=logging.INFO)
```

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is for educational and personal use. Please respect Spotify's Terms of Service and API rate limits.

## Acknowledgments

- **Spotipy**: Python library for Spotify Web API
- **PyQt6**: Cross-platform GUI toolkit
- **Spotify Web API**: For providing access to music data

---

**Note**: This application requires a Spotify account and valid API credentials. It does not store or transmit your music data beyond what's necessary for playlist comparison.