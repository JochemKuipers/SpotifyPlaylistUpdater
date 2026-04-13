"""
Main entry point for GUI interface
"""

import logging
import sys

from PySide6.QtWidgets import QApplication

from src.gui.playlist_gui import SpotifyPlaylistGUI


def main():
    """GUI entry point for Spotify Playlist Updater"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = SpotifyPlaylistGUI()
    window.show()
    app.aboutToQuit.connect(window.cleanup_resources)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
