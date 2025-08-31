"""
GUI module for Spotify Playlist Updater.
"""

import json
import os

from PySide6.QtCore import QThread, Signal, Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QProgressBar,
    QGroupBox,
    QFormLayout,
    QMessageBox,
    QSplitter,
    QCompleter,
    QTreeWidget,
    QTreeWidgetItem,
)

from src.spotify_api.spotify_client import SpotifyPlaylistUpdater
from src.utils.app_paths import get_credentials_path


class SpotifyManager:
    """Singleton manager for Spotify client to prevent multiple instances"""

    _instance = None
    _client = None
    _credentials = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def get_client(self, client_id, client_secret, redirect_uri):
        """Get or create Spotify client with given credentials"""
        current_creds = (client_id, client_secret, redirect_uri)

        # Only create new client if credentials changed or no client exists
        if self._credentials != current_creds or self._client is None:
            if self._client:
                # Clean up old client
                try:
                    self._client._cleanup()
                except Exception as e:
                    print(f"Error cleaning up old client: {e}")

            self._client = SpotifyPlaylistUpdater(
                client_id, client_secret, redirect_uri
            )
            self._credentials = current_creds

        return self._client

    def cleanup(self):
        """Clean up the client"""
        if self._client:
            try:
                self._client._cleanup()
            except Exception as e:
                print(f"Error cleaning up old client: {e}")
            self._client = None
            self._credentials = None


class PlaylistFetcher(QThread):
    """Worker thread to fetch playlists on startup"""

    playlists_fetched: Signal = Signal(list)
    error: Signal = Signal(str)

    def __init__(self, client_id, client_secret, redirect_uri):
        super().__init__()
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

    def run(self):
        try:
            # Only fetch if we have credentials
            if not all([self.client_id, self.client_secret]):
                return

            # Use singleton manager
            manager = SpotifyManager()
            updater = manager.get_client(
                self.client_id, self.client_secret, self.redirect_uri
            )

            playlists = updater.get_user_playlists()
            playlist_names = [playlist["name"] for playlist in playlists]
            self.playlists_fetched.emit(playlist_names)

        except Exception as e:
            self.error.emit(f"Failed to fetch playlists: {str(e)}")


class SpotifyWorker(QThread):
    """Worker thread for Spotify operations to prevent GUI freezing"""

    progress_update = Signal(str)
    finished = Signal(dict)
    error = Signal(str)
    tracks_added = Signal(bool, str)
    tracks_removed = Signal(bool, str)

    def __init__(
        self,
        client_id,
        client_secret,
        redirect_uri,
        artist_name,
        playlist_name,
        operation="analyze",
        tracks_to_add=None,
        tracks_to_remove=None,
    ):
        super().__init__()
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.artist_name = artist_name
        self.playlist_name = playlist_name
        self.operation = operation
        self.tracks_to_add = tracks_to_add or []
        self.tracks_to_remove = tracks_to_remove or []

    def run(self):
        try:
            self.progress_update.emit("Connecting to Spotify...")

            # Use singleton manager to prevent multiple clients
            manager = SpotifyManager()
            updater = manager.get_client(
                self.client_id, self.client_secret, self.redirect_uri
            )

            if self.operation == "analyze":
                self._analyze_playlist(updater)
            elif self.operation == "add_tracks":
                self._add_tracks(updater)
            elif self.operation == "remove_tracks":
                self._remove_tracks(updater)

        except Exception as e:
            self.error.emit(f"Error: {str(e)}")

    def _analyze_playlist(self, updater):
        """Analyze playlist for missing and extra tracks"""
        self.progress_update.emit(f"Searching for playlist '{self.playlist_name}'...")

        # Parse artist names to show what we're analyzing
        artist_names = [name.strip() for name in self.artist_name.split("/")]
        if len(artist_names) > 1:
            artist_display = " / ".join(artist_names)
            self.progress_update.emit(f"Analyzing multiple artists: {artist_display}")
        else:
            self.progress_update.emit(f"Analyzing artist: {artist_names[0]}")

        self.progress_update.emit("Analyzing playlist vs artist discography...")
        result = updater.find_missing_and_extra_tracks(
            self.artist_name, self.playlist_name
        )

        self.progress_update.emit("Analysis complete!")
        self.finished.emit(result)

    def _add_tracks(self, updater):
        """Add tracks to playlist"""
        self.progress_update.emit(
            f"Adding {len(self.tracks_to_add)} tracks to playlist..."
        )

        success = updater.add_tracks_to_playlist(self.playlist_name, self.tracks_to_add)

        if success:
            self.tracks_added.emit(
                True, f"Successfully added {len(self.tracks_to_add)} tracks!"
            )
        else:
            self.tracks_added.emit(False, "Failed to add tracks to playlist.")

    def _remove_tracks(self, updater):
        """Remove tracks from playlist"""
        self.progress_update.emit(
            f"Removing {len(self.tracks_to_remove)} tracks from playlist..."
        )

        success = updater.remove_tracks_from_playlist(
            self.playlist_name, self.tracks_to_remove
        )

        if success:
            self.tracks_removed.emit(
                True,
                f"Successfully removed {len(self.tracks_to_remove)} non-artist tracks!",
            )
        else:
            self.tracks_removed.emit(False, "Failed to remove tracks from playlist.")


class AllPlaylistsWorker(QThread):
    """Worker thread for analyzing all playlists at once"""

    progress_update = Signal(str)
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, client_id, client_secret, redirect_uri):
        super().__init__()
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

    def run(self):
        try:
            self.progress_update.emit("Connecting to Spotify...")

            # Use singleton manager to prevent multiple clients
            manager = SpotifyManager()
            updater = manager.get_client(
                self.client_id, self.client_secret, self.redirect_uri
            )

            self.progress_update.emit("Analyzing all playlists...")
            result = updater.analyze_all_playlists()

            self.progress_update.emit("Analysis complete!")
            self.finished.emit(result)

        except Exception as e:
            self.error.emit(f"Error: {str(e)}")


class SpotifyPlaylistGUI(QMainWindow):
    """Main GUI class for Spotify Playlist Updater"""

    def __init__(self):
        super().__init__()
        self.individual_action_button = None
        self.remove_tracks_button = None
        self.extra_list = None
        self.add_tracks_button = None
        self.status_label = None
        self.missing_list = None
        self.progress_bar = None
        self.analyze_button = None
        self.save_creds_button = None
        self.refresh_playlists_button = None
        self.playlist_name_edit = None
        self.redirect_uri_edit = None
        self.client_secret_edit = None
        self.client_id_edit = None
        self.details_text = None
        self._creds_timer = None
        self.selected_track_indices = None
        self.current_selection = None
        self.worker = None
        self.playlist_fetcher = None
        self.missing_tracks_data = []
        self.extra_tracks_data = []
        self.playlist_completer = None
        self.spotify_manager = SpotifyManager()
        self.all_playlists_worker = None # Initialize the new worker
        self.init_ui()
        self.load_credentials()
        self.fetch_playlists()

    def __del__(self):
        """Cleanup when GUI is destroyed"""
        self.cleanup_resources()

    def cleanup_resources(self):
        """Clean up all resources"""
        try:
            # Stop any running workers
            if self.worker and self.worker.isRunning():
                self.worker.requestInterruption()
                if not self.worker.wait(1000):
                    self.worker.terminate()

            if self.playlist_fetcher and self.playlist_fetcher.isRunning():
                self.playlist_fetcher.requestInterruption()
                if not self.playlist_fetcher.wait(1000):
                    self.playlist_fetcher.terminate()

            if self.all_playlists_worker and self.all_playlists_worker.isRunning():
                self.all_playlists_worker.requestInterruption()
                if not self.all_playlists_worker.wait(1000):
                    self.all_playlists_worker.terminate()

            # Clean up Spotify manager
            self.spotify_manager.cleanup()
        except Exception as e:
            print(f"Error during cleanup: {e}")

    def closeEvent(self, event):
        """Handle window close event"""
        self.cleanup_resources()
        event.accept()

    def init_ui(self):
        """Initialize the GUI layout and components"""
        self.setWindowTitle("Spotify Playlist Updater")
        self.setGeometry(100, 100, 1200, 800)

        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Main layout
        main_layout = QVBoxLayout(central_widget)

        # Title
        title = QLabel("Spotify Playlist Updater")
        title.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #1DB954;")
        title.setMaximumHeight(40)  # Limit height of title
        main_layout.addWidget(title)

        # Credentials group
        creds_group = QGroupBox("Spotify API Credentials")
        creds_layout = QFormLayout()

        self.client_id_edit = QLineEdit()
        self.client_id_edit.setPlaceholderText("Your Spotify Client ID")
        # Connect to refresh playlists when credentials change
        self.client_id_edit.textChanged.connect(self.on_credentials_changed)
        creds_layout.addRow("Client ID:", self.client_id_edit)

        self.client_secret_edit = QLineEdit()
        self.client_secret_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.client_secret_edit.setPlaceholderText("Your Spotify Client Secret")
        # Connect to refresh playlists when credentials change
        self.client_secret_edit.textChanged.connect(self.on_credentials_changed)
        creds_layout.addRow("Client Secret:", self.client_secret_edit)

        self.redirect_uri_edit = QLineEdit()
        self.redirect_uri_edit.setText("http://127.0.0.1:3000/callback")
        creds_layout.addRow("Redirect URI:", self.redirect_uri_edit)

        creds_group.setLayout(creds_layout)
        creds_group.setMaximumHeight(120)  # Limit the height of the group box
        main_layout.addWidget(creds_group)

        # Search group
        search_group = QGroupBox("Artist/Playlist Search")
        search_layout = QFormLayout()

        self.playlist_name_edit = QLineEdit()
        self.playlist_name_edit.setPlaceholderText(
            "Enter playlist name (loading suggestions...)"
        )

        # Add refresh button for playlists
        refresh_layout = QHBoxLayout()
        refresh_layout.addWidget(self.playlist_name_edit)

        self.refresh_playlists_button = QPushButton("🔄")
        self.refresh_playlists_button.setMaximumWidth(30)
        self.refresh_playlists_button.setToolTip("Refresh playlist suggestions")
        self.refresh_playlists_button.clicked.connect(self.fetch_playlists)
        refresh_layout.addWidget(self.refresh_playlists_button)

        search_layout.addRow("Playlist/Artist Name:", refresh_layout)

        search_group.setLayout(search_layout)
        search_group.setMaximumHeight(65)  # Limit the height of the group box
        main_layout.addWidget(search_group)

        # Buttons
        button_layout = QHBoxLayout()

        self.save_creds_button = QPushButton("Save Credentials")
        self.save_creds_button.clicked.connect(self.save_credentials)
        button_layout.addWidget(self.save_creds_button)

        self.analyze_button = QPushButton("Analyze Playlist")
        self.analyze_button.clicked.connect(self.analyze_playlist)
        button_layout.addWidget(self.analyze_button)

        self.analyze_all_button = QPushButton("Analyze All Playlists")
        self.analyze_all_button.clicked.connect(self.analyze_all_playlists)
        self.analyze_all_button.setStyleSheet(
            "QPushButton { background-color: #9b59b6; color: white; font-weight: bold; padding: 8px; }"
        )
        button_layout.addWidget(self.analyze_all_button)

        main_layout.addLayout(button_layout)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        main_layout.addWidget(self.progress_bar)

        # Status label
        self.status_label = QLabel("Ready - Loading playlists...")
        self.status_label.setStyleSheet("color: #666; font-style: italic;")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setMaximumHeight(30)  # Limit height
        main_layout.addWidget(self.status_label)

        # Updated splitter for three panels
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)

        # Missing tracks panel
        missing_group = QGroupBox("Missing Tracks (Not in Playlist)")
        missing_layout = QVBoxLayout()
        self.missing_tree = QTreeWidget()
        self.missing_tree.setHeaderLabel("Missing Tracks")
        self.missing_tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        missing_layout.addWidget(self.missing_tree)

        # Add tracks button under missing tracks list
        self.add_tracks_button = QPushButton("Add All Missing Tracks")
        self.add_tracks_button.clicked.connect(self.add_missing_tracks)
        self.add_tracks_button.setEnabled(False)
        self.add_tracks_button.setStyleSheet(
            "QPushButton { "
            "background-color: #1DB954; "
            "color: white; "
            "font-weight: bold; "
            "padding: 8px; "
            "}"
        )
        missing_layout.addWidget(self.add_tracks_button)

        missing_group.setLayout(missing_layout)
        splitter.addWidget(missing_group)

        # Extra tracks panel
        extra_group = QGroupBox("Non-Artist Tracks (In Playlist)")
        extra_layout = QVBoxLayout()
        self.extra_tree = QTreeWidget()
        self.extra_tree.setHeaderLabel("Non-Artist Tracks")
        self.extra_tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        extra_layout.addWidget(self.extra_tree)

        # Add remove tracks button under extra tracks list
        self.remove_tracks_button = QPushButton("Remove All Non-Artist Tracks")
        self.remove_tracks_button.clicked.connect(self.remove_non_artist_tracks)
        self.remove_tracks_button.setEnabled(False)
        self.remove_tracks_button.setStyleSheet(
            "QPushButton { background-color: #e74c3c; color: white; font-weight: bold; padding: 8px; }"
        )
        extra_layout.addWidget(self.remove_tracks_button)

        extra_group.setLayout(extra_layout)
        splitter.addWidget(extra_group)

        # Details panel
        details_group = QGroupBox("Track Details")
        details_layout = QVBoxLayout()
        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)
        details_layout.addWidget(self.details_text)

        # Add individual track action button
        self.individual_action_button = QPushButton("Select tracks to see actions")
        self.individual_action_button.setEnabled(False)
        self.individual_action_button.clicked.connect(self.perform_individual_action)
        self.individual_action_button.setStyleSheet(
            "QPushButton { background-color: #3498db; color: white; font-weight: bold; padding: 8px; }"
        )
        details_layout.addWidget(self.individual_action_button)

        details_group.setLayout(details_layout)
        splitter.addWidget(details_group)

        # Connect list selection changes to details (use selectionChanged instead of itemClicked)
        self.missing_tree.itemSelectionChanged.connect(self.update_selection_details)
        self.extra_tree.itemSelectionChanged.connect(self.update_selection_details)

        # Track which list is currently selected
        self.current_selection = None  # Will be 'missing' or 'extra'
        self.selected_track_indices = []

        # Set initial splitter sizes
        splitter.setSizes([300, 300, 400])

    def load_credentials(self):
        """Load saved credentials if they exist"""
        try:
            credentials_path = get_credentials_path()
            if os.path.exists(credentials_path):
                with open(credentials_path) as f:
                    creds = json.load(f)
                    self.client_id_edit.setText(creds.get("client_id", ""))
                    self.client_secret_edit.setText(creds.get("client_secret", ""))
                    self.redirect_uri_edit.setText(
                        creds.get("redirect_uri", "http://127.0.0.1:3000/callback")
                    )
        except Exception as e:
            print(f"Error loading credentials: {e}")

    def save_credentials(self):
        """Save credentials to file"""
        try:
            creds = {
                "client_id": self.client_id_edit.text(),
                "client_secret": self.client_secret_edit.text(),
                "redirect_uri": self.redirect_uri_edit.text(),
            }
            credentials_path = get_credentials_path()
            # Open the file in write mode
            with open(credentials_path, "w") as f:
                json.dump(creds, f)

            QMessageBox.information(self, "Success", "Credentials saved successfully!")
            self.fetch_playlists()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save credentials: {e}")

    def on_credentials_changed(self):
        """Called when credentials are changed to refresh playlists"""
        # Cancel any pending timer
        if hasattr(self, "_creds_timer") and self._creds_timer is not None:
            self._creds_timer.stop()

        # Stop any running playlist fetcher
        if self.playlist_fetcher and self.playlist_fetcher.isRunning():
            self.playlist_fetcher.terminate()
            self.playlist_fetcher.wait(1000)

        self._creds_timer = QTimer()
        self._creds_timer.setSingleShot(True)
        self._creds_timer.timeout.connect(self.fetch_playlists)
        self._creds_timer.start(2000)

    def fetch_playlists(self):
        """Fetch playlists asynchronously for autocomplete"""
        if not all([self.client_id_edit.text(), self.client_secret_edit.text()]):
            self.status_label.setText("Ready - Enter credentials to load playlists")
            return

        # Stop any currently running fetcher
        if self.playlist_fetcher and self.playlist_fetcher.isRunning():
            return

        self.status_label.setText("Loading playlists...")
        self.refresh_playlists_button.setEnabled(False)

        self.playlist_fetcher = PlaylistFetcher(
            self.client_id_edit.text(),
            self.client_secret_edit.text(),
            self.redirect_uri_edit.text(),
        )

        self.playlist_fetcher.playlists_fetched.connect(
            self.setup_playlist_autocomplete
        )
        self.playlist_fetcher.error.connect(self.playlist_fetch_error)
        # Remove the problematic connection and let Qt handle object lifecycle
        self.playlist_fetcher.start()

    def setup_playlist_autocomplete(self, playlist_names):
        """Setup autocomplete for playlist names"""
        try:
            self.playlist_completer = QCompleter(playlist_names)
            self.playlist_completer.setCaseSensitivity(
                Qt.CaseSensitivity.CaseInsensitive
            )
            self.playlist_completer.setFilterMode(Qt.MatchFlag.MatchContains)

            self.playlist_name_edit.setCompleter(self.playlist_completer)

            self.playlist_name_edit.setPlaceholderText(
                f"Enter playlist name ({len(playlist_names)} playlists loaded)"
            )

            self.status_label.setText(f"Ready - {len(playlist_names)} playlists loaded")
            self.refresh_playlists_button.setEnabled(True)

        except Exception as e:
            self.playlist_fetch_error(f"Error setting up autocomplete: {e}")

    def playlist_fetch_error(self, error_message):
        """Handle playlist fetch error"""
        self.status_label.setText("Ready - Failed to load playlists")
        self.refresh_playlists_button.setEnabled(True)
        self.playlist_name_edit.setPlaceholderText(
            "Enter playlist name (failed to load suggestions)"
        )
        print(f"Playlist fetch error: {error_message}")

    def analyze_playlist(self):
        """Start the playlist analysis"""
        if not all(
            [
                self.client_id_edit.text(),
                self.client_secret_edit.text(),
                self.playlist_name_edit.text(),
            ]
        ):
            QMessageBox.warning(self, "Warning", "Please fill in all required fields!")
            return

        # Stop any running worker
        if self.worker and self.worker.isRunning():
            self.worker.terminate()
            self.worker.wait(3000)

        # Clear previous results and disable buttons
        self.analyze_button.setEnabled(False)
        self.add_tracks_button.setEnabled(False)
        self.remove_tracks_button.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.missing_tree.clear() # Clear the tree widget
        self.extra_tree.clear() # Clear the tree widget
        self.details_text.clear()

        # Start worker thread
        self.worker = SpotifyWorker(
            self.client_id_edit.text(),
            self.client_secret_edit.text(),
            self.redirect_uri_edit.text(),
            self.playlist_name_edit.text(),
            self.playlist_name_edit.text(),
            operation="analyze",
        )

        self.worker.progress_update.connect(self.update_status)
        self.worker.finished.connect(self.analysis_finished)
        self.worker.error.connect(self.analysis_error)
        self.worker.finished.connect(
            lambda: setattr(self.worker, "deleteLater", lambda: None)
        )
        self.worker.start()

    def analyze_all_playlists(self):
        """Start the analysis of all playlists"""
        if not all(
            [
                self.client_id_edit.text(),
                self.client_secret_edit.text(),
            ]
        ):
            QMessageBox.warning(self, "Warning", "Please fill in all required fields!")
            return

        # Stop any running worker
        if hasattr(self, 'all_playlists_worker') and self.all_playlists_worker and self.all_playlists_worker.isRunning():
            self.all_playlists_worker.terminate()
            self.all_playlists_worker.wait(3000)

        # Clear previous results and disable buttons
        self.analyze_all_button.setEnabled(False)
        self.analyze_button.setEnabled(False)
        self.add_tracks_button.setEnabled(False)
        self.remove_tracks_button.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        
        # Clear existing lists
        self.missing_tree.clear() # Clear the tree widget
        self.extra_tree.clear() # Clear the tree widget
        self.details_text.clear()

        # Start worker thread
        self.all_playlists_worker = AllPlaylistsWorker(
            self.client_id_edit.text(),
            self.client_secret_edit.text(),
            self.redirect_uri_edit.text(),
        )

        self.all_playlists_worker.progress_update.connect(self.update_status)
        self.all_playlists_worker.finished.connect(self.all_playlists_analysis_finished)
        self.all_playlists_worker.error.connect(self.all_playlists_analysis_error)
        self.all_playlists_worker.start()

    def display_all_playlists_results(self, results):
        """Display results for all playlists in collapsible tree structures"""
        if not results:
            self.status_label.setText("No playlists found or no results available")
            return
        
        # Store the all playlists results for later use
        self.all_playlists_results = results
        
        # Display results grouped by playlist in collapsible trees
        self.missing_tree.clear()
        self.extra_tree.clear()
        
        total_missing = 0
        total_extra = 0
        
        for playlist_name, playlist_data in results.items():
            if "error" in playlist_data:
                # Add error as a special item in missing tree
                error_item = QTreeWidgetItem([f"❌ {playlist_name}: {playlist_data['error']}"])
                self.missing_tree.addTopLevelItem(error_item)
                continue
            
            missing_tracks = playlist_data.get("missing", [])
            extra_tracks = playlist_data.get("extra", [])
            artist_name = playlist_data.get("artist_name", "Unknown")
            
            # Create missing tracks playlist group
            if missing_tracks:
                playlist_header = QTreeWidgetItem([f"📁 {playlist_name} ({artist_name}) - {len(missing_tracks)} missing tracks"])
                playlist_header.setExpanded(False)  # Start collapsed
                self.missing_tree.addTopLevelItem(playlist_header)
                
                # Add missing tracks as children
                for track in missing_tracks:
                    track_item = QTreeWidgetItem([f"• {track['name']} ({track['duration']}) - {track.get('album', 'Unknown Album')}"])
                    track_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "track", "track_data": track, "playlist": playlist_name})
                    playlist_header.addChild(track_item)
                
                total_missing += len(missing_tracks)
            
            # Create extra tracks playlist group
            if extra_tracks:
                playlist_header = QTreeWidgetItem([f"📁 {playlist_name} ({artist_name}) - {len(extra_tracks)} extra tracks"])
                playlist_header.setExpanded(False)  # Start collapsed
                self.extra_tree.addTopLevelItem(playlist_header)
                
                # Add extra tracks as children
                for track in extra_tracks:
                    track_item = QTreeWidgetItem([f"• {track['name']} by {track.get('main_artist', 'Unknown')} ({track['duration']})"])
                    track_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "track", "track_data": track, "playlist": playlist_name})
                    playlist_header.addChild(track_item)
                
                total_extra += len(extra_tracks)
        
        # Update button states
        if total_missing > 0:
            self.add_tracks_button.setEnabled(True)
            self.add_tracks_button.setText(f"Add All Missing Tracks ({total_missing})")
        else:
            self.add_tracks_button.setEnabled(False)
            self.add_tracks_button.setText("Add All Missing Tracks")
        
        if total_extra > 0:
            self.remove_tracks_button.setEnabled(True)
            self.remove_tracks_button.setText(f"Remove All Non-Artist Tracks ({total_extra})")
        else:
            self.remove_tracks_button.setEnabled(False)
            self.remove_tracks_button.setText("Remove All Non-Artist Tracks")
        
        # Update status
        total_playlists = len(results)
        self.status_label.setText(f"Analysis Complete: {total_playlists} playlists analyzed - {total_missing} missing, {total_extra} extra tracks")

    def all_playlists_analysis_finished(self, results):
        """Handle completion of all playlists analysis"""
        self.progress_bar.setVisible(False)
        self.analyze_all_button.setEnabled(True)
        self.analyze_button.setEnabled(True)
        
        self.display_all_playlists_results(results)
        
        # Show success message
        total_playlists = len(results)
        QMessageBox.information(
            self,
            "Analysis Complete",
            f"Successfully analyzed {total_playlists} playlists! Results are displayed in the lists above."
        )

    def all_playlists_analysis_error(self, error_message):
        """Handle error in all playlists analysis"""
        self.progress_bar.setVisible(False)
        self.analyze_all_button.setEnabled(True)
        self.analyze_button.setEnabled(True)
        
        self.status_label.setText("❌ All playlists analysis failed")
        QMessageBox.critical(self, "Error", error_message)

    def update_selection_details(self):
        """Update details panel based on current selection in either tree"""
        missing_selected = self.missing_tree.selectedItems()
        extra_selected = self.extra_tree.selectedItems()

        # Clear other tree's selection when selecting from one tree
        if missing_selected and extra_selected:
            sender = self.sender()
            if sender == self.missing_tree:
                self.extra_tree.clearSelection()
                extra_selected = []
            else:
                self.missing_tree.clearSelection()
                missing_selected = []

        if missing_selected:
            self.current_selection = "missing"
            # Filter out playlist headers and get only track items
            track_items = [item for item in missing_selected if item.parent() is not None]
            if track_items:
                self.selected_track_indices = []
                self.selected_tracks_data = []
                for item in track_items:
                    track_data = item.data(0, Qt.ItemDataRole.UserRole)
                    if track_data and track_data.get("type") == "track":
                        self.selected_tracks_data.append(track_data["track_data"])
                self.show_selected_tracks_details("missing")
            else:
                # Only headers selected, clear details
                self.current_selection = None
                self.selected_track_indices = []
                self.selected_tracks_data = []
                self.details_text.clear()
                self.individual_action_button.setText("Select tracks to see actions")
                self.individual_action_button.setEnabled(False)
        elif extra_selected:
            self.current_selection = "extra"
            # Filter out playlist headers and get only track items
            track_items = [item for item in extra_selected if item.parent() is not None]
            if track_items:
                self.selected_track_indices = []
                self.selected_tracks_data = []
                for item in track_items:
                    track_data = item.data(0, Qt.ItemDataRole.UserRole)
                    if track_data and track_data.get("type") == "track":
                        self.selected_tracks_data.append(track_data["track_data"])
                self.show_selected_tracks_details("extra")
            else:
                # Only headers selected, clear details
                self.current_selection = None
                self.selected_track_indices = []
                self.selected_tracks_data = []
                self.details_text.clear()
                self.individual_action_button.setText("Select tracks to see actions")
                self.individual_action_button.setEnabled(False)
        else:
            # No selection
            self.current_selection = None
            self.selected_track_indices = []
            self.selected_tracks_data = []
            self.details_text.clear()
            self.individual_action_button.setText("Select tracks to see actions")
            self.individual_action_button.setEnabled(False)
            self.individual_action_button.setStyleSheet(
                "QPushButton { background-color: #3498db; color: white; font-weight: bold; padding: 8px; }"
            )

    def show_selected_tracks_details(self, selection_type):
        """Show details for selected tracks"""
        if not hasattr(self, 'selected_tracks_data') or not self.selected_tracks_data:
            return

        tracks = self.selected_tracks_data

        if selection_type == "missing":
            action_text = f"Add {len(tracks)} Selected Track{'s' if len(tracks) != 1 else ''} to Playlist"
            button_color = "#1DB954"  # Green
        else:
            action_text = f"Remove {len(tracks)} Selected Track{'s' if len(tracks) != 1 else ''} from Playlist"
            button_color = "#e74c3c"  # Red

        # Update button
        self.individual_action_button.setText(action_text)
        self.individual_action_button.setEnabled(True)
        self.individual_action_button.setStyleSheet(
            f"QPushButton {{ background-color: {button_color}; color: white; font-weight: bold; padding: 8px; }}"
        )

        # Show details
        if len(tracks) == 1:
            # Single track - show full details
            track = tracks[0]
            artists_data = track.get("artists")
            if isinstance(artists_data, list) and artists_data:
                artist_names = [a.get("name", "Unknown Artist") for a in artists_data]
            else:
                artist_names = ["Unknown Artist"]
            if selection_type == "missing":
                details = f"""
MISSING TRACK DETAILS:

Track Name: {track.get("name", "Unknown Track")}
Duration: {track.get("duration", "Unknown Duration")}
Artists: {", ".join(artist_names)}
Album: {track.get("album", "Unknown Album")}
Release Date: {track.get("release_date", "Unknown Release Date")}
Spotify URI: {track.get("uri", "Unknown URI")}

Click the button below to add this track to your playlist.
                """.strip()
            else:
                details = f"""
NON-ARTIST TRACK DETAILS:

Track Name: {track.get("name", "Unknown Track")}
Duration: {track.get("duration", "Unknown Duration")}
Main Artist: {track.get("main_artist", "Unknown Artist")}
All Artists: {", ".join(artist_names)}
Spotify URI: {track.get("uri", "Unknown URI")}

This track is in your playlist but is not by the target artist.
Click the button below to remove this track from your playlist.
                """.strip()
        else:
            # Multiple tracks - show summary
            if selection_type == "missing":
                details = f"""
SELECTED MISSING TRACKS ({len(tracks)} tracks):

"""
                for i, track in enumerate(tracks, 1):
                    details += f"{i}. {track.get('name', 'Unknown Track')} ({track.get('duration', 'Unknown Duration')}) - {track.get('album', 'Unknown Album')}\n"

                details += f"\nClick the button below to add all {len(tracks)} tracks to your playlist."
            else:
                details = f"""
SELECTED NON-ARTIST TRACKS ({len(tracks)} tracks):

"""
                for i, track in enumerate(tracks, 1):
                    details += f"{i}. {track.get('name', 'Unknown Track')} ({track.get('duration', 'Unknown Duration')}) by {track.get('main_artist', 'Unknown Artist')}\n"

                details += f"\nClick the button below to remove all {len(tracks)} tracks from your playlist."

        self.details_text.setPlainText(details)

    def perform_individual_action(self):
        """Perform the individual action for the selected tracks"""
        if not self.selected_track_indices:
            return

        if self.current_selection == "missing":
            self.add_selected_tracks()
        elif self.current_selection == "extra":
            self.remove_selected_tracks()

    def add_selected_tracks(self):
        """Add selected missing tracks to the playlist"""
        if not self.selected_track_indices:
            return

        selected_tracks = [
            self.missing_tracks_data[i]
            for i in self.selected_track_indices
            if 0 <= i < len(self.missing_tracks_data)
        ]

        if not selected_tracks:
            return

        # Confirm with user
        track_names = [track.get("name", "Unknown Track") for track in selected_tracks]
        if len(selected_tracks) == 1:
            message = f"Are you sure you want to add '{track_names[0]}' to the playlist '{self.playlist_name_edit.text()}'?"
        else:
            message = f"Are you sure you want to add {len(selected_tracks)} selected tracks to the playlist '{self.playlist_name_edit.text()}'?\n\nTracks: {', '.join(track_names[:3])}"
            if len(track_names) > 3:
                message += f" and {len(track_names) - 3} more..."

        reply = QMessageBox.question(
            self,
            "Confirm Addition",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Disable buttons and show progress
        self.analyze_button.setEnabled(False)
        self.add_tracks_button.setEnabled(False)
        self.individual_action_button.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)

        # Start worker thread for adding selected tracks
        self.worker = SpotifyWorker(
            self.client_id_edit.text(),
            self.client_secret_edit.text(),
            self.redirect_uri_edit.text(),
            self.playlist_name_edit.text(),
            self.playlist_name_edit.text(),
            operation="add_tracks",
            tracks_to_add=selected_tracks,
        )

        self.worker.progress_update.connect(self.update_status)
        self.worker.tracks_added.connect(self.selected_tracks_added)
        self.worker.error.connect(self.analysis_error)
        self.worker.start()

    def remove_selected_tracks(self):
        """Remove selected non-artist tracks from the playlist"""
        if not self.selected_track_indices:
            return

        selected_tracks = [
            self.extra_tracks_data[i]
            for i in self.selected_track_indices
            if 0 <= i < len(self.extra_tracks_data)
        ]

        if not selected_tracks:
            return

        # Confirm with user
        track_names = [
            f"{track.get('name', 'Unknown Track')} by {track.get('main_artist', 'Unknown Artist')}"
            for track in selected_tracks
        ]
        if len(selected_tracks) == 1:
            message = f"Are you sure you want to remove '{track_names[0]}' from the playlist '{self.playlist_name_edit.text()}'?\n\nThis action cannot be undone."
        else:
            message = f"Are you sure you want to remove {len(selected_tracks)} selected tracks from the playlist '{self.playlist_name_edit.text()}'?\n\nTracks: {', '.join(track_names[:2])}"
            if len(track_names) > 2:
                message += f" and {len(track_names) - 2} more..."
            message += "\n\nThis action cannot be undone."

        reply = QMessageBox.question(
            self,
            "Confirm Removal",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Disable buttons and show progress
        self.analyze_button.setEnabled(False)
        self.remove_tracks_button.setEnabled(False)
        self.individual_action_button.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)

        # Start worker thread for removing selected tracks
        self.worker = SpotifyWorker(
            self.client_id_edit.text(),
            self.client_secret_edit.text(),
            self.redirect_uri_edit.text(),
            self.playlist_name_edit.text(),
            self.playlist_name_edit.text(),
            operation="remove_tracks",
            tracks_to_remove=selected_tracks,
        )

        self.worker.progress_update.connect(self.update_status)
        self.worker.tracks_removed.connect(self.selected_tracks_removed)
        self.worker.error.connect(self.analysis_error)
        self.worker.start()

    def add_missing_tracks(self):
        """Add all missing tracks to the playlist"""
        if not self.missing_tracks_data:
            QMessageBox.warning(self, "Warning", "No missing tracks to add!")
            return

        # Confirm with user
        reply = QMessageBox.question(
            self,
            "Confirm Addition",
            f"Are you sure you want to add {len(self.missing_tracks_data)} missing tracks to the playlist '{self.playlist_name_edit.text()}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Disable buttons and show progress
        self.analyze_button.setEnabled(False)
        self.add_tracks_button.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)

        # Start worker thread for adding tracks
        self.worker = SpotifyWorker(
            self.client_id_edit.text(),
            self.client_secret_edit.text(),
            self.redirect_uri_edit.text(),
            self.playlist_name_edit.text(),
            self.playlist_name_edit.text(),
            operation="add_tracks",
            tracks_to_add=self.missing_tracks_data,
        )

        self.worker.progress_update.connect(self.update_status)
        self.worker.tracks_added.connect(self.tracks_added_finished)
        self.worker.error.connect(self.analysis_error)
        self.worker.start()

    def remove_non_artist_tracks(self):
        """Remove all non-artist tracks from the playlist"""
        if not self.extra_tracks_data:
            QMessageBox.warning(self, "Warning", "No non-artist tracks to remove!")
            return

        # Confirm with user
        reply = QMessageBox.question(
            self,
            "Confirm Removal",
            f"Are you sure you want to remove {len(self.extra_tracks_data)} non-artist tracks from the playlist '{self.playlist_name_edit.text()}'?\n\nThis action cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Disable buttons and show progress
        self.analyze_button.setEnabled(False)
        self.add_tracks_button.setEnabled(False)
        self.remove_tracks_button.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)

        # Start worker thread for removing tracks
        self.worker = SpotifyWorker(
            self.client_id_edit.text(),
            self.client_secret_edit.text(),
            self.redirect_uri_edit.text(),
            self.playlist_name_edit.text(),
            self.playlist_name_edit.text(),
            operation="remove_tracks",
            tracks_to_remove=self.extra_tracks_data,
        )

        self.worker.progress_update.connect(self.update_status)
        self.worker.tracks_removed.connect(self.tracks_removed_finished)
        self.worker.error.connect(self.analysis_error)
        self.worker.start()

    def update_status(self, message):
        """Update status label"""
        self.status_label.setText(message)

    def analysis_finished(self, result):
        """Handle analysis completion"""
        self.progress_bar.setVisible(False)
        self.analyze_button.setEnabled(True)

        missing_tracks = result.get("missing", [])
        extra_tracks = result.get("extra", [])

        # Parse artist names for display
        artist_names = [
            name.strip() for name in self.playlist_name_edit.text().split("/")
        ]
        artist_display = (
            " / ".join(artist_names) if len(artist_names) > 1 else artist_names[0]
        )

        # Update missing tracks list
        if not missing_tracks:
            self.status_label.setText(
                f"✅ No missing tracks! All {artist_display} tracks are in playlist."
            )
            self.add_tracks_button.setEnabled(False)
        else:
            self.status_label.setText(
                f"Found {len(missing_tracks)} missing tracks from {artist_display}"
            )
            self.add_tracks_button.setEnabled(True)

            # Create playlist header
            playlist_header = QTreeWidgetItem([f"📁 {self.playlist_name_edit.text()} ({artist_display}) - {len(missing_tracks)} missing tracks"])
            self.missing_tree.addTopLevelItem(playlist_header)
            
            # Add missing tracks as children
            for track in missing_tracks:
                track_item = QTreeWidgetItem([f"• {track['name']} ({track['duration']}) - {track.get('album', 'Unknown Album')}"])
                track_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "track", "track_data": track, "playlist": self.playlist_name_edit.text()})
                playlist_header.addChild(track_item)

        # Update extra tracks list
        if not extra_tracks:
            self.remove_tracks_button.setEnabled(False)
        else:
            self.remove_tracks_button.setEnabled(True)

        # Create playlist header for extra tracks
        if extra_tracks:
            playlist_header = QTreeWidgetItem([f"📁 {self.playlist_name_edit.text()} ({artist_display}) - {len(extra_tracks)} extra tracks"])
            self.extra_tree.addTopLevelItem(playlist_header)
            
            # Add extra tracks as children
            for track in extra_tracks:
                track_item = QTreeWidgetItem([f"• {track['name']} by {track.get('main_artist', 'Unknown')} ({track['duration']})"])
                track_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "track", "track_data": track, "playlist": self.playlist_name_edit.text()})
                playlist_header.addChild(track_item)

        # Expand all items in both trees for single playlist analysis
        self.missing_tree.expandAll()
        self.extra_tree.expandAll()

        # Store data
        self.missing_tracks_data = missing_tracks
        self.extra_tracks_data = extra_tracks

        # Reset individual action button
        self.individual_action_button.setText("Select tracks to see actions")
        self.individual_action_button.setEnabled(False)
        self.current_selection = None
        self.selected_track_indices = []

        # Show summary with artist info
        if not missing_tracks and not extra_tracks:
            QMessageBox.information(
                self,
                "Analysis Complete",
                f"Perfect playlist! No missing tracks and all tracks are by {artist_display}.",
            )
        elif not missing_tracks:
            QMessageBox.information(
                self,
                "Analysis Complete",
                f"All {artist_display} tracks are in playlist, but found {len(extra_tracks)} tracks by other artists.",
            )
        elif not extra_tracks:
            QMessageBox.information(
                self,
                "Analysis Complete",
                f"All playlist tracks are by {artist_display}, but {len(missing_tracks)} tracks are missing.",
            )
        else:
            QMessageBox.information(
                self,
                "Analysis Complete",
                f"Found {len(missing_tracks)} missing tracks from {artist_display} and {len(extra_tracks)} tracks by other artists.",
            )

    def selected_tracks_added(self, success, message):
        """Handle selected tracks addition completion"""
        self.progress_bar.setVisible(False)
        self.analyze_button.setEnabled(True)

        if success:
            # Remove the selected tracks from our data and list (in reverse order to maintain indices)
            for index in sorted(self.selected_track_indices, reverse=True):
                if 0 <= index < len(self.missing_tracks_data):
                    self.missing_tracks_data.pop(index)
                    # Find the item in the tree widget and remove it
                    for i in range(self.missing_tree.topLevelItemCount()): # Changed to missing_tree
                        item = self.missing_tree.topLevelItem(i)
                        if item.text(0).startswith(f"📁 {self.playlist_name_edit.text()} ({self.playlist_name_edit.text().split('/')[-1]}) -"):
                            for j in range(item.childCount()):
                                if item.child(j).text(0).startswith(f"  • {self.missing_tracks_data[index]['name']} ({self.missing_tracks_data[index]['duration']}) - {self.missing_tracks_data[index]['album']}"): # Changed to missing_tree
                                    self.missing_tree.takeTopLevelItem(i).takeChild(j) # Changed to missing_tree
                                    break
                            break

            # Clear details and disable button
            self.details_text.clear()
            self.individual_action_button.setText("Select tracks to see actions")
            self.individual_action_button.setEnabled(False)
            self.current_selection = None
            self.selected_track_indices = []

            # Update add all button state
            if not self.missing_tracks_data:
                self.add_tracks_button.setEnabled(False)
            else:
                self.add_tracks_button.setEnabled(True)

            self.status_label.setText("✅ Selected tracks added successfully!")
            QMessageBox.information(self, "Success", message)
        else:
            self.individual_action_button.setEnabled(True)
            self.status_label.setText("❌ Failed to add selected tracks")
            QMessageBox.critical(self, "Error", message)

        # Re-enable other buttons appropriately
        if self.missing_tracks_data:
            self.add_tracks_button.setEnabled(True)
        if self.extra_tracks_data:
            self.remove_tracks_button.setEnabled(True)

    def selected_tracks_removed(self, success, message):
        """Handle selected tracks removal completion"""
        self.progress_bar.setVisible(False)
        self.analyze_button.setEnabled(True)

        if success:
            # Remove the selected tracks from our data and list (in reverse order to maintain indices)
            for index in sorted(self.selected_track_indices, reverse=True):
                if 0 <= index < len(self.extra_tracks_data):
                    self.extra_tracks_data.pop(index)
                    # Find the item in the tree widget and remove it
                    for i in range(self.extra_tree.topLevelItemCount()):
                        item = self.extra_tree.topLevelItem(i)
                        if item.text(0).startswith(f"📁 {self.playlist_name_edit.text()} ({self.playlist_name_edit.text().split('/')[-1]}) -"):
                            for j in range(item.childCount()):
                                if item.child(j).text(0).startswith(f"  • {self.extra_tracks_data[index]['name']} by {self.extra_tracks_data[index]['main_artist']} ({self.extra_tracks_data[index]['duration']})"):
                                    self.extra_tree.takeTopLevelItem(i).takeChild(j)
                                    break
                            break

            # Clear details and disable button
            self.details_text.clear()
            self.individual_action_button.setText("Select tracks to see actions")
            self.individual_action_button.setEnabled(False)
            self.current_selection = None
            self.selected_track_indices = []

            # Update remove all button state
            if not self.extra_tracks_data:
                self.remove_tracks_button.setEnabled(False)
            else:
                self.remove_tracks_button.setEnabled(True)

            self.status_label.setText("✅ Selected tracks removed successfully!")
            QMessageBox.information(self, "Success", message)
        else:
            self.individual_action_button.setEnabled(True)
            self.status_label.setText("❌ Failed to remove selected tracks")
            QMessageBox.critical(self, "Error", message)

        # Re-enable other buttons appropriately
        if self.missing_tracks_data:
            self.add_tracks_button.setEnabled(True)
        if self.extra_tracks_data:
            self.remove_tracks_button.setEnabled(True)

    def tracks_removed_finished(self, success, message):
        """Handle track removal completion"""
        self.progress_bar.setVisible(False)
        self.analyze_button.setEnabled(True)

        if success:
            self.remove_tracks_button.setEnabled(False)
            self.status_label.setText("✅ Non-artist tracks removed successfully!")
            # Clear the extra tracks list since they've been removed
            self.extra_tree.clear()
            self.details_text.clear()
            self.extra_tracks_data = []
            QMessageBox.information(self, "Success", message)
        else:
            self.remove_tracks_button.setEnabled(True)
            self.status_label.setText("❌ Failed to remove tracks")
            QMessageBox.critical(self, "Error", message)

        # Re-enable add button if there are missing tracks
        if self.missing_tracks_data:
            self.add_tracks_button.setEnabled(True)

    def tracks_added_finished(self, success, message):
        """Handle track addition completion"""
        self.progress_bar.setVisible(False)
        self.analyze_button.setEnabled(True)

        if success:
            self.add_tracks_button.setEnabled(False)
            self.status_label.setText("✅ Tracks added successfully!")
            # Clear the missing tracks list since they've been added
            self.missing_tree.clear() # Changed to missing_tree
            self.details_text.clear()
            self.missing_tracks_data = []
            QMessageBox.information(self, "Success", message)
        else:
            self.add_tracks_button.setEnabled(True)
            self.status_label.setText("❌ Failed to add tracks")
            QMessageBox.critical(self, "Error", message)

        # Re-enable remove button if there are extra tracks
        if self.extra_tracks_data:
            self.remove_tracks_button.setEnabled(True)

    def analysis_error(self, error_message):
        """Handle analysis error"""
        self.progress_bar.setVisible(False)
        self.analyze_button.setEnabled(True)
        self.add_tracks_button.setEnabled(False)
        self.remove_tracks_button.setEnabled(False)
        self.individual_action_button.setEnabled(False)
        self.status_label.setText("❌ Operation failed")
        QMessageBox.critical(self, "Error", error_message)
