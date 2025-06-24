# Spotify Playlist Updater

A Python application that helps you manage your Spotify playlists by comparing an artist's complete discography with your playlist to find missing tracks and identify non-artist tracks. Available as both a command-line tool and a modern GUI application.

## Features

- **Missing Track Detection**: Find tracks from an artist's discography that are missing from your playlist
- **Non-Artist Track Identification**: Identify tracks in your playlist that are not by the specified artist(s)
- **Multiple Artist Support**: Handle artist aliases (e.g., "Artist Name / Alias Name")
- **Batch Operations**: Add/remove multiple tracks at once
- **Smart Matching**: Uses track name and duration matching with tolerance for slight differences
- **Caching**: Intelligent caching system for playlists and tracks to improve performance
- **GUI Interface**: User-friendly PySide6-based graphical interface
- **Command Line Interface**: Simple CLI for automation and scripting
- **Standalone Executable**: Can be packaged as a standalone application using PyInstaller

## Screenshots

### GUI Application
- **Three-panel layout**: Missing tracks, non-artist tracks, and detailed track information
- **Playlist autocomplete**: Loads your playlists for easy selection
- **Individual/bulk operations**: Add or remove tracks individually or in bulk
- **Real-time progress**: Progress indicators for all operations

## Installation

### Prerequisites

- Python 3.12 or higher
- Spotify Developer Account (for API credentials)

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Spotify API Credentials

1. Go to [Spotify Developer Dashboard](https://developer.spotify.com/dashboard/)
2. Create a new application
3. Set the Redirect URI to `http://127.0.0.1:3000/callback`
4. Note your Client ID and Client Secret for use in the application

## Usage

### GUI Application

Run the GUI application:

```bash
python main_app.py
```

1. Enter your Spotify API credentials
2. Save your credentials for future use
3. Enter the playlist name (which is also used as the artist name)
4. Click "Analyze Playlist" to compare the playlist with the artist's discography
5. Add missing tracks or remove non-artist tracks as needed

### Command Line Interface

For command-line usage:

```bash
python -m src.cli "Playlist Name" --client-id YOUR_CLIENT_ID --client-secret YOUR_CLIENT_SECRET
```

To list all your playlists:

```bash
python -m src.cli "dummy" --client-id YOUR_CLIENT_ID --client-secret YOUR_CLIENT_SECRET --list-playlists
```

## Building a Standalone Executable

You can create a standalone executable using PyInstaller:

```bash
pip install pyinstaller
pyinstaller spotifyplaylistupdater.spec
```

The executable will be created in the `dist` folder.

## Project Structure

The project follows a modular architecture:

```
SpotifyPlaylistUpdater/
├── src/                      # Main package directory
│   ├── spotify_api/          # Core Spotify API functionality
│   ├── utils/                # Utility functions
│   ├── gui/                  # GUI implementation
│   ├── cli.py                # Command-line interface
│   └── gui_app.py            # GUI application entry point
├── main_app.py               # Main entry point
├── requirements.txt          # Dependencies
└── spotifyplaylistupdater.spec # PyInstaller specification
```

## License

This project is open source and available under the MIT License.

## Acknowledgments

- [Spotipy](https://spotipy.readthedocs.io/) - Lightweight Python library for the Spotify Web API
- [PySide6](https://doc.qt.io/qtforpython/index.html) - Python bindings for Qt GUI framework
