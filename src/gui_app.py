"""
Main entry point for GUI interface
"""
import sys

from PySide6.QtWidgets import QApplication

from src.gui.playlist_gui import SpotifyPlaylistGUI


def main():
    """GUI entry point for Spotify Playlist Updater"""
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = SpotifyPlaylistGUI()
    window.show()
    app.aboutToQuit.connect(window.cleanup_resources)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
