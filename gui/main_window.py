# gui/main_window.py
"""
Main application window module for the GUI application.

This module defines the primary window class (`MainWindow`), manages application
state, initializes UI components by calling setup functions, connects signals,
sets up logging, and handles window-level events like closing.
It orchestrates interactions between the UI, worker threads, and core logic.
"""

# Standard library imports
import os
import logging
from typing import Optional, Dict, List, Tuple, Any

# Qt imports
from PySide6.QtWidgets import QMainWindow, QWidget, QMessageBox, QTextEdit, QListWidgetItem
from PySide6.QtCore import Slot, Signal
from PySide6.QtGui import QFont # Keep necessary Qt imports

# Local Core/Util imports
from core.config_manager import ConfigManager
from core.exceptions import ConfigurationError
from core.github_handler import GitHubHandler, GitProgressHandler
from core.llm_interface import LLMInterface
from utils.logger_setup import setupLogging # Import if GUI handler setup remains here
from gui.gui_utils import QtLogHandler      # Import if GUI handler setup remains here

# Local GUI module imports for setup and handling
from . import ui_setup
from . import signal_connections
from . import diff_view # Needed for closeEvent and potentially state resets

# Worker Threads
from .threads import GitHubWorker, LLMWorker, FileWorker

# Initialize logging for this module
logger: logging.Logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """
    Main application window class.

    Orchestrates the application's GUI, state management, and interaction
    with background worker threads for Git, LLM, and file operations.

    Attributes:
        _configManager (ConfigManager): Handles application configuration.
        _githubHandlerInstance (GitHubHandler): Handles Git operations.
        _llmInterfaceInstance (LLMInterface): Handles LLM interactions.
        _githubWorker (GitHubWorker): Worker thread for Git tasks.
        _llmWorker (LLMWorker): Worker thread for LLM tasks.
        _fileWorker (FileWorker): Worker thread for file processing tasks.
        _gitProgressHandler (GitProgressHandler): Handles Git progress updates for GUI.
        _clonedRepoPath (Optional[str]): Path to the currently loaded repository.
        _selectedFiles (List[str]): List of currently selected relative file paths.
        _originalFileContents (Dict[str, Optional[str]]): Cache of original file content.
        _parsedFileData (Optional[Dict[str, str]]): Parsed data from LLM response.
        _validationErrors (Optional[Dict[str, List[str]]]): Validation errors from parsing.
        _repoIsDirty (bool): Flag indicating uncommitted changes in the repo.
        _isBusy (bool): Flag indicating if a background task is running.
        _is_syncing_scroll (bool): Flag to prevent scrollbar sync recursion.
        _correction_attempted (bool): Flag if LLM correction has been tried.
        signalLogMessage (Signal): Signal to emit formatted log messages for the GUI log area.
        # UI Widgets (initialized in ui_setup) - examples:
        # _repoUrlInput, _fileListWidget, _promptInput, _llmResponseArea,
        # _originalCodeArea, _proposedCodeArea, _appLogArea, _progressBar, etc.
    """

    signalLogMessage = Signal(str)

    def __init__(self: 'MainWindow', configManager: ConfigManager, parent: Optional[QWidget] = None) -> None:
        """
        Initialize the main window.

        Args:
            configManager: Configuration manager instance.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        logger.info("Initializing MainWindow...")
        self._configManager = configManager

        # --- Initialize State Variables ---
        self._clonedRepoPath: Optional[str] = None
        self._selectedFiles: List[str] = []
        self._originalFileContents: Dict[str, Optional[str]] = {} # Allows caching None for non-existent files
        self._parsedFileData: Optional[Dict[str, str]] = None
        self._validationErrors: Optional[Dict[str, List[str]]] = None
        self._isBusy: bool = False
        self._repoIsDirty: bool = False
        self._is_syncing_scroll: bool = False
        self._correction_attempted: bool = False

        # --- Initialize Core Handlers ---
        # These can be used directly by handlers if needed, passed via `window` arg
        self._githubHandlerInstance = GitHubHandler()
        self._llmInterfaceInstance = LLMInterface(configManager=self._configManager)

        # --- Initialize UI ---
        # UI widgets (_repoUrlInput, _fileListWidget, etc.) are created here
        ui_setup.setup_ui(self)

        # --- Load Initial Settings ---
        self._loadInitialSettings()

        # --- Initialize Workers and Progress Handler ---
        self._gitProgressHandler = GitProgressHandler(parent_qobject=self) # Create handler instance
        self._githubWorker = GitHubWorker(parent=self)
        self._llmWorker = LLMWorker(parent=self, configManager=self._configManager)
        self._fileWorker = FileWorker(parent=self)
        # Connect progress handler signal (if it exists) directly to the worker's signal? No, worker uses it.
        # Worker's progress signal will be connected to MainWindow's _updateProgress slot below.

        # --- Connect Signals ---
        signal_connections.connect_signals(self)

        # --- Setup GUI Logging ---
        self._setupGuiLogging() # Keep this here as it adds a handler to the root logger

        # --- Final UI Updates ---
        self._updateWidgetStates() # Set initial enabled/disabled states
        logger.info("MainWindow initialized.")

    # --- Settings Load/Save ---
    def _loadInitialSettings(self: 'MainWindow') -> None:
        """Loads initial settings like the last repository path."""
        try:
            last_repo = self._configManager.getConfigValue('General', 'LastRepoPath', fallback='')
            if last_repo and isinstance(last_repo, str) and last_repo.strip():
                logger.info(f"Loaded last used repository path: {last_repo}")
                self._repoUrlInput.setText(last_repo)
            else:
                logger.debug("No last repository path found in config.")
        except ConfigurationError as e:
            logger.warning(f"Could not read LastRepoPath from config: {e}")
        except Exception as e:
            logger.error(f"Unexpected error loading initial settings: {e}", exc_info=True)

    def _saveLastRepoPath(self: 'MainWindow', repoPath: str) -> None:
        """Saves the last used repository path to the configuration file."""
        try:
            logger.debug(f"Attempting to save last repo path: {repoPath}")
            self._configManager.setConfigValue('General', 'LastRepoPath', repoPath)
            logger.info(f"Saved last repository path to config: {repoPath}")
        except ConfigurationError as e:
            logger.error(f"Failed to save LastRepoPath to config: {e}")
        except Exception as e:
            logger.error(f"Unexpected error saving last repo path: {e}", exc_info=True)

    # --- GUI Logging Setup ---
    def _setupGuiLogging(self: 'MainWindow') -> None:
        """Configures and adds the QtLogHandler to the root logger."""
        try:
            # Use the signal emitter directly from self.signalLogMessage
            guiHandler = QtLogHandler(signal_emitter=self.signalLogMessage.emit, parent=self)
            guiLogLevelName = self._configManager.getConfigValue('Logging', 'GuiLogLevel', fallback='DEBUG')
            guiLogLevel = getattr(logging, guiLogLevelName.upper(), logging.DEBUG)
            guiHandler.setLevel(guiLogLevel)
            logFormat = self._configManager.getConfigValue('Logging', 'GuiLogFormat', fallback='%(asctime)s - %(levelname)s - %(message)s')
            dateFormat = self._configManager.getConfigValue('Logging', 'GuiLogDateFormat', fallback='%H:%M:%S')
            formatter = logging.Formatter(logFormat, datefmt=dateFormat)
            guiHandler.setFormatter(formatter)
            logging.getLogger().addHandler(guiHandler)
            logger.info(f"GUI logging handler added with level {logging.getLevelName(guiLogLevel)}.")
        # Keep ImportError check if QtLogHandler is optional
        except ImportError:
            logger.error("QtLogHandler import failed or dependencies missing. GUI logging disabled.")
        except ConfigurationError as e:
            logger.error(f"Configuration error setting up GUI logging: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Failed to setup GUI logging handler: {e}", exc_info=True)

    # --- Core State and UI Update Methods (kept in MainWindow) ---

    def _updateWidgetStates(self: 'MainWindow') -> None:
        """
        Enables/disables widgets based on the current application state.
        Needs access to state variables (_isBusy, _clonedRepoPath, etc.) and widgets.
        """
        # Determine state flags
        repoLoaded = self._clonedRepoPath is not None and os.path.isdir(self._clonedRepoPath)
        responseAvailable = bool(self._llmResponseArea.toPlainText().strip()) if hasattr(self, '_llmResponseArea') else False
        parsedDataAvailable = self._parsedFileData is not None
        # Check if parsed data dict actually has items
        parsedDataHasContent = parsedDataAvailable and bool(self._parsedFileData)
        # Validation passed if parsed data exists AND there are no validation errors
        validationPassed = parsedDataAvailable and self._validationErrors is None
        repoIsActuallyDirty = repoLoaded and self._repoIsDirty
        enabledIfNotBusy = not self._isBusy

        # Update widget enabled state - uses widget names set in ui_setup
        # Wrap in hasattr checks for robustness during initialization phases
        if hasattr(self, '_repoUrlInput'): self._repoUrlInput.setEnabled(enabledIfNotBusy)
        if hasattr(self, '_browseButton'): self._browseButton.setEnabled(enabledIfNotBusy)
        if hasattr(self, '_cloneButton'): self._cloneButton.setEnabled(enabledIfNotBusy)

        if hasattr(self, '_fileListWidget'): self._fileListWidget.setEnabled(enabledIfNotBusy and repoLoaded)
        if hasattr(self, '_promptInput'): self._promptInput.setEnabled(enabledIfNotBusy and repoLoaded)
        if hasattr(self, '_sendToLlmButton'): self._sendToLlmButton.setEnabled(enabledIfNotBusy and repoLoaded)
        if hasattr(self, '_pasteResponseButton'): self._pasteResponseButton.setEnabled(enabledIfNotBusy) # Allow pasting anytime not busy

        if hasattr(self, '_parseButton'): self._parseButton.setEnabled(enabledIfNotBusy and responseAvailable)
        if hasattr(self, '_saveFilesButton'): self._saveFilesButton.setEnabled(enabledIfNotBusy and parsedDataHasContent and repoLoaded and validationPassed)
        if hasattr(self, '_commitPushButton'): self._commitPushButton.setEnabled(enabledIfNotBusy and repoLoaded and repoIsActuallyDirty)

        # Make response area read-only while busy
        if hasattr(self, '_llmResponseArea'): self._llmResponseArea.setReadOnly(self._isBusy)


    def _resetTaskState(self: 'MainWindow') -> None:
        """Resets the busy flag and updates UI elements after a task."""
        logger.debug("Resetting task state (busy=False).")
        self._isBusy = False
        self._correction_attempted = False # Reset correction flag too
        self._updateWidgetStates()
        self._updateProgress(101, "") # Value > 100 hides the progress bar
        self._updateStatusBar("Idle.")


    # Slot directly connected from worker signals
    @Slot(int, str)
    def _updateProgress(self: 'MainWindow', value: int, message: str) -> None:
        """Updates the progress bar visibility, value, and format."""
        if not hasattr(self, '_progressBar'): return # Check if progress bar exists

        if not self._isBusy and value <= 100: # Don't show progress if not busy, unless hiding it (value > 100)
            self._progressBar.setVisible(False)
            return

        if value == -1: # Indeterminate
            self._progressBar.setVisible(True)
            self._progressBar.setRange(0, 0)
            self._progressBar.setFormat(message or "Working...")
        elif 0 <= value <= 100: # Determinate
            self._progressBar.setVisible(True)
            self._progressBar.setRange(0, 100)
            self._progressBar.setValue(value)
            format_str = f"{message} (%p%)" if message else "%p%"
            self._progressBar.setFormat(format_str)
        else: # Hide progress bar (value > 100 or invalid)
            self._progressBar.setVisible(False)
            self._progressBar.setRange(0, 100) # Reset range
            self._progressBar.setValue(0)      # Reset value
            self._progressBar.setFormat("%p%")  # Reset format


    # Slot directly connected from worker signals
    @Slot(str, int) # Allow specifying timeout
    def _updateStatusBar(self: 'MainWindow', message: str, timeout: int = 0) -> None:
        """Updates the status bar message."""
        if hasattr(self, '_statusBar') and self._statusBar:
            self._statusBar.showMessage(message, timeout)
        # else:
            # logger.warning(f"Status bar not initialized when trying to show: {message}")


    # --- GUI Log Appender ---
    @Slot(str)
    def _appendLogMessage(self: 'MainWindow', message: str) -> None:
        """Appends a formatted log message to the GUI log area."""
        if hasattr(self, '_appLogArea') and self._appLogArea:
            # Append plain text; assumes logger already formatted it
            self._appLogArea.appendPlainText(message)
            # Auto-scroll to bottom
            sb = self._appLogArea.verticalScrollBar()
            if sb:
                sb.setValue(sb.maximum())
        # Do not log here, as this is called *by* the logger


    # --- Message Box Helpers (Convenience) ---
    def _showError(self: 'MainWindow', title: str, message: str) -> None:
        """Displays a critical error message box."""
        logger.error(f"Showing Error Dialog - {title}: {message}")
        QMessageBox.critical(self, title, str(message))

    def _showWarning(self: 'MainWindow', title: str, message: str) -> None:
        """Displays a warning message box."""
        logger.warning(f"Showing Warning Dialog - {title}: {message}")
        QMessageBox.warning(self, title, str(message))

    def _showInfo(self: 'MainWindow', title: str, message: str) -> None:
        """Displays an informational message box."""
        logger.info(f"Showing Info Dialog - {title}: {message}")
        QMessageBox.information(self, title, str(message))


    # --- Window Close Event ---
    def closeEvent(self: 'MainWindow', event) -> None:
        """Handles the window close event, ensuring background tasks are stopped."""
        can_close = True
        if self._isBusy:
            reply = QMessageBox.question(self, 'Confirm Exit',
                                    "A background task is currently running.\nAre you sure you want to exit?",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                    QMessageBox.StandardButton.Cancel)
            if reply == QMessageBox.StandardButton.Cancel:
                event.ignore()
                can_close = False

        if can_close:
            logger.info("Attempting graceful shutdown of worker threads...")
            # Use helper function to stop workers
            self._stop_worker_threads()
            logger.info("Shutdown sequence complete. Closing application window.")
            super().closeEvent(event) # Accept the close event


    def _stop_worker_threads(self: 'MainWindow') -> None:
        """Attempts to gracefully stop all running worker threads."""
        workers_to_stop: List[Any] = []
        if hasattr(self, '_githubWorker') and self._githubWorker: workers_to_stop.append(self._githubWorker)
        if hasattr(self, '_llmWorker') and self._llmWorker: workers_to_stop.append(self._llmWorker)
        if hasattr(self, '_fileWorker') and self._fileWorker: workers_to_stop.append(self._fileWorker)

        for worker in workers_to_stop:
            if hasattr(worker, 'isRunning') and worker.isRunning():
                worker_name = worker.__class__.__name__
                logger.debug(f"Requesting quit for {worker_name}...")
                try:
                    # Prefer requestInterruption for cleaner shutdown if implemented in BaseWorker
                    if hasattr(worker, 'requestInterruption'):
                        worker.requestInterruption()
                        if not worker.wait(2000): # Wait up to 2 seconds
                            logger.warning(f"{worker_name} did not finish after interruption request and wait. Termination may not be clean.")
                            # worker.terminate() # Avoid terminate if possible
                    else:
                        # Fallback if requestInterruption is not available
                        worker.quit()
                        if not worker.wait(1000): # Shorter wait for quit
                            logger.warning(f"{worker_name} did not finish after quit() and wait. Termination may not be clean.")
                            # worker.terminate()
                except Exception as e:
                    logger.error(f"Error stopping worker {worker_name}: {e}", exc_info=True)