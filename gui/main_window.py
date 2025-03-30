# Updated Codebase/gui/main_window.py
# --- START: gui/main_window.py ---
# gui/main_window.py
"""
Main application window module for the GUI application.

Handles GUI setup, state management, signal connections, logging,
and orchestrates interactions between UI, workers, and core logic.
Includes state and handling for line-by-line change acceptance,
focus highlighting, and keyboard navigation/acceptance using an event filter
and cursor positioning. Allows saving accepted changes even if validation failed.
"""

# Standard library imports
import os
import logging
import pprint # Used for debugging state dictionaries if needed
from typing import Optional, Dict, List, Tuple, Any, Set

# Qt imports
from PySide6.QtWidgets import QMainWindow, QWidget, QMessageBox, QTextEdit, QListWidgetItem
from PySide6.QtCore import Slot, Signal, QUrl, Qt, QTimer, QObject, QEvent
from PySide6.QtGui import QFont, QDesktopServices, QKeyEvent, QTextCursor # Import QTextCursor

# Local Core/Util imports
from core.config_manager import ConfigManager
from core.exceptions import ConfigurationError, ParsingError, FileProcessingError
from core.github_handler import GitHubHandler, GitProgressHandler
from core.llm_interface import LLMInterface
from utils.logger_setup import setupLogging
from gui.gui_utils import QtLogHandler

# Local GUI module imports
from . import ui_setup
from . import signal_connections
from . import diff_view # Requires functions/constants from diff_view
from .diff_view import ACCEPTANCE_PENDING, ACCEPTANCE_ACCEPTED, ACCEPTANCE_REJECTED # Import states
from .threads import GitHubWorker, LLMWorker, FileWorker # Worker threads

# Initialise logging for this module
logger: logging.Logger = logging.getLogger(__name__)

class MainWindow(QMainWindow):
	"""
	Main application window class.

	Orchestrates the application's GUI, state management, and interaction
	with background worker threads for Git, LLM, and file operations.
	Implements an event filter on the proposed code view to handle
	custom keyboard navigation and acceptance actions for diff chunks.
	"""

	# Signal emitted to send log messages to the GUI's log area
	signalLogMessage: Signal = Signal(str)

	def __init__(self: 'MainWindow', configManager: ConfigManager, parent: Optional[QWidget] = None) -> None:
		"""
		Initialise the main window.

		Args:
			configManager (ConfigManager): Instance for managing application configuration.
			parent (Optional[QWidget]): Optional parent widget. Defaults to None.
		"""
		super().__init__(parent)
		logger.info("Initialising MainWindow...")
		self._configManager: ConfigManager = configManager

		# --- State Variables ---
		# Repository and File Management
		self._clonedRepoPath: Optional[str] = None # Absolute path to the loaded/cloned repo
		self._selectedFiles: List[str] = [] # List of relative file paths selected in the UI list
		self._originalFileContents: Dict[str, Optional[str]] = {} # Cache for original file content (or load errors)

		# LLM Interaction and Parsing State
		self._parsedFileData: Optional[Dict[str, str]] = None # Data parsed from last valid LLM response {filepath: content}
		self._validationErrors: Optional[Dict[str, List[str]]] = None # Validation errors from last parse {filepath: [errors]}

		# Application Status Flags
		self._isBusy: bool = False # True if a background worker task is active
		self._repoIsDirty: bool = False # True if git status indicates uncommitted changes
		self._is_syncing_scroll: bool = False # Flag to prevent scrollbar signal loops
		self._correction_attempted: bool = False # True if an LLM self-correction has been tried for the current response

		# Diff Acceptance State
		self._acceptedChangesState: Dict[str, Dict[str, int]] = {} # {filepath: {chunk_id: ACCEPTANCE_STATE}}
		self._last_clicked_chunk_id: Optional[str] = None # Tracks the chunk last clicked/navigated to
		self._current_chunk_id_list: List[str] = [] # Ordered list of chunk IDs in the current diff view
		self._current_chunk_start_block_map: Dict[str, int] = {} # Map chunk ID to its starting text block index

		# --- Core Logic Handlers ---
		# Instances used for direct operations or passed to workers
		self._githubHandlerInstance: GitHubHandler = GitHubHandler()
		self._llmInterfaceInstance: LLMInterface = LLMInterface(configManager=self._configManager)

		# --- Initialise UI Elements ---
		# This function creates and lays out all widgets (defined in ui_setup.py)
		ui_setup.setup_ui(self)

		# --- Install Event Filter ---
		# Intercept events (specifically key presses) on the proposed code area
		if hasattr(self, '_proposedCodeArea'):
			self._proposedCodeArea.installEventFilter(self)
			logger.debug("Installed event filter on _proposedCodeArea.")
		else:
			# This should not happen if ui_setup is correct
			logger.error("Could not install event filter: _proposedCodeArea widget not found after UI setup.")

		# --- Load Initial Settings ---
		# E.g., Restore last used repository path
		self._loadInitialSettings()

		# --- Initialise Background Workers ---
		self._gitProgressHandler: GitProgressHandler = GitProgressHandler(parent_qobject=self) # For git clone/pull progress
		self._githubWorker: GitHubWorker = GitHubWorker(parent=self) # Thread for Git operations
		self._llmWorker: LLMWorker = LLMWorker(parent=self, configManager=self._configManager) # Thread for LLM API calls
		self._fileWorker: FileWorker = FileWorker(parent=self) # Thread for file parsing/saving

		# --- Connect Signals and Slots ---
		# Links UI actions and worker results to appropriate handler methods
		signal_connections.connect_signals(self)

		# --- Setup GUI Logging Handler ---
		# Directs application logs to the text area in the UI
		self._setupGuiLogging()

		# --- Final UI State Update ---
		# Set initial enabled/disabled states for buttons etc.
		self._updateWidgetStates()
		logger.info("MainWindow initialisation complete.")

	# --- Settings Load/Save ---
	def _loadInitialSettings(self: 'MainWindow') -> None:
		""" Loads initial settings like the last repository path from the config file. """
		try:
			# Attempt to retrieve the last used repository path
			last_repo: Optional[str] = self._configManager.getConfigValue('General', 'LastRepoPath', fallback=None)
			if last_repo and isinstance(last_repo, str) and last_repo.strip():
				# Set the input field if a valid path was found
				self._repoUrlInput.setText(last_repo)
				logger.info(f"Loaded last used repository path: {last_repo}")
			else:
				logger.debug("No last repository path found in configuration.")
		except ConfigurationError as e:
			# Log warning if config key is missing or invalid, but don't crash
			logger.warning(f"Could not read 'LastRepoPath' from configuration: {e}")
		except Exception as e:
			# Log unexpected errors during setting load
			logger.error(f"Unexpected error occurred loading initial settings: {e}", exc_info=True)

	def _saveLastRepoPath(self: 'MainWindow', repoPath: str) -> None:
		""" Saves the provided repository path to the configuration file. """
		try:
			# Update the value in the 'General' section, key 'LastRepoPath'
			self._configManager.setConfigValue('General', 'LastRepoPath', repoPath)
			logger.info(f"Saved last repository path to configuration: {repoPath}")
		except ConfigurationError as e:
			# Log errors specifically related to config saving
			logger.error(f"Failed to save 'LastRepoPath' to configuration: {e}")
		except Exception as e:
			# Log any other unexpected errors during saving
			logger.error(f"Unexpected error occurred saving last repository path: {e}", exc_info=True)

	# --- GUI Logging Setup ---
	def _setupGuiLogging(self: 'MainWindow') -> None:
		""" Configures and adds the custom QtLogHandler to the root logger. """
		try:
			# Create the handler, passing the emit method of the MainWindow's signal
			guiHandler: QtLogHandler = QtLogHandler(signal_emitter=self.signalLogMessage.emit, parent=self)

			# Get desired log level and format from configuration
			guiLogLevelName: str = self._configManager.getConfigValue('Logging', 'GuiLogLevel', fallback='DEBUG')
			guiLogLevel: int = getattr(logging, guiLogLevelName.upper(), logging.DEBUG) # Default to DEBUG if invalid
			logFormat: str = self._configManager.getConfigValue('Logging', 'GuiLogFormat', fallback='%(asctime)s - %(levelname)s - %(message)s')
			dateFormat: str = self._configManager.getConfigValue('Logging', 'GuiLogDateFormat', fallback='%H:%M:%S')

			# Set handler level and formatter
			guiHandler.setLevel(guiLogLevel)
			formatter: logging.Formatter = logging.Formatter(logFormat, datefmt=dateFormat)
			guiHandler.setFormatter(formatter)

			# Add the handler to the root logger
			logging.getLogger().addHandler(guiHandler)
			logger.info(f"GUI logging handler added with level {logging.getLevelName(guiLogLevel)}.")
		except ImportError:
			# Handle case where QtLogHandler might have dependencies missing (less likely now)
			logger.error("QtLogHandler import failed or dependencies missing. GUI logging disabled.")
		except ConfigurationError as e:
			# Log configuration errors during setup
			logger.error(f"Configuration error setting up GUI logging: {e}", exc_info=True)
		except Exception as e:
			# Log any other unexpected errors
			logger.error(f"Failed to setup GUI logging handler: {e}", exc_info=True)

	# --- Core State and UI Update Methods ---

	def _updateWidgetStates(self: 'MainWindow') -> None:
		"""
		Enables or disables UI widgets based on the current application state.
		Allows 'Save Accepted' button even if validation failed for the current file.
		Includes detailed logging of the conditions checked.
		"""
		# --- Determine State Flags ---
		repoLoaded: bool = bool(self._clonedRepoPath and os.path.isdir(self._clonedRepoPath))
		responseAvailable: bool = bool(hasattr(self, '_llmResponseArea') and self._llmResponseArea.toPlainText().strip())
		parsedDataAvailable: bool = self._parsedFileData is not None
		parsedDataHasContent: bool = parsedDataAvailable and bool(self._parsedFileData) # Check if dict is not empty
		currentFileName: Optional[str] = self._fileListWidget.currentItem().text() if self._fileListWidget.currentItem() else None

		# Check if *any* changes have been accepted for the current file
		hasAcceptedChangesForCurrentFile: bool = False
		if currentFileName and currentFileName in self._acceptedChangesState:
			# Check if any value in the file's chunk state dict is ACCEPTANCE_ACCEPTED
			hasAcceptedChangesForCurrentFile = any(
				state == ACCEPTANCE_ACCEPTED
				for state in self._acceptedChangesState[currentFileName].values()
			)

		# --- Button Enable Conditions ---
		# "Save All Validated Changes": Requires repo, parsed data with content, and *no overall validation errors*
		canSaveAll: bool = repoLoaded and parsedDataHasContent and (self._validationErrors is None)

		# "Save Accepted (Current File)": Requires repo loaded and accepted changes for the current file.
		# *** Validation status for the current file is intentionally ignored here. ***
		canSaveAccepted: bool = repoLoaded and hasAcceptedChangesForCurrentFile

		# Other state flags
		repoIsActuallyDirty: bool = repoLoaded and self._repoIsDirty # Based on git status check
		enabledIfNotBusy: bool = not self._isBusy # General flag for enabling UI during operations

		# --- Logging For Debugging Button States ---
		logger.debug("--- _updateWidgetStates ---")
		logger.debug(f"  repoLoaded: {repoLoaded}")
		logger.debug(f"  currentFileName: {currentFileName}")
		logger.debug(f"  parsedDataAvailable: {parsedDataAvailable}")
		logger.debug(f"  parsedDataHasContent: {parsedDataHasContent}")
		# Log validation status for information, even though not used for canSaveAccepted
		currentFileHadValidationError: bool = bool(self._validationErrors and currentFileName and currentFileName in self._validationErrors)
		logger.debug(f"  currentFileHadValidationError: {currentFileHadValidationError}")
		logger.debug(f"  hasAcceptedChangesForCurrentFile: {hasAcceptedChangesForCurrentFile}")
		logger.debug(f"  --> canSaveAccepted (Button Enable): {canSaveAccepted} (Requires: repoLoaded AND hasAcceptedChangesForCurrentFile)")
		logger.debug(f"  --> canSaveAll (Button Enable): {canSaveAll} (Requires: repoLoaded AND parsedDataHasContent AND NO overall validation errors)")
		logger.debug(f"  enabledIfNotBusy: {enabledIfNotBusy}")
		logger.debug("--------------------------")

		# --- Update Widget Enabled States ---
		# Use hasattr for safety during initialisation phases
		if hasattr(self, '_repoUrlInput'): self._repoUrlInput.setEnabled(enabledIfNotBusy)
		if hasattr(self, '_browseButton'): self._browseButton.setEnabled(enabledIfNotBusy)
		if hasattr(self, '_cloneButton'): self._cloneButton.setEnabled(enabledIfNotBusy)
		if hasattr(self, '_fileListWidget'): self._fileListWidget.setEnabled(enabledIfNotBusy and repoLoaded)
		if hasattr(self, '_promptInput'): self._promptInput.setEnabled(enabledIfNotBusy and repoLoaded)
		if hasattr(self, '_sendToLlmButton'): self._sendToLlmButton.setEnabled(enabledIfNotBusy and repoLoaded)
		if hasattr(self, '_pasteResponseButton'): self._pasteResponseButton.setEnabled(enabledIfNotBusy) # Allow pasting anytime not busy
		if hasattr(self, '_parseButton'): self._parseButton.setEnabled(enabledIfNotBusy and responseAvailable)
		# Apply the calculated conditions to the save buttons
		if hasattr(self, '_saveAcceptedButton'): self._saveAcceptedButton.setEnabled(enabledIfNotBusy and canSaveAccepted)
		if hasattr(self, '_saveFilesButton'): self._saveFilesButton.setEnabled(enabledIfNotBusy and canSaveAll)
		# Commit button requires repo loaded and actual uncommitted changes
		if hasattr(self, '_commitPushButton'): self._commitPushButton.setEnabled(enabledIfNotBusy and repoLoaded and repoIsActuallyDirty)
		# Make LLM response area read-only while busy to prevent edits
		if hasattr(self, '_llmResponseArea'): self._llmResponseArea.setReadOnly(self._isBusy)

	def _resetTaskState(self: 'MainWindow') -> None:
		""" Resets the busy flag, updates UI elements, and resets progress/status after a task. """
		logger.debug("Resetting application task state (busy=False).")
		self._isBusy = False
		self._correction_attempted = False # Reset correction flag too
		self._updateWidgetStates() # Re-enable/disable widgets based on new state
		self._updateProgress(101, "") # Value > 100 hides the progress bar
		self._updateStatusBar("Idle.") # Set status bar to idle message

	@Slot(int, str)
	def _updateProgress(self: 'MainWindow', value: int, message: str) -> None:
		"""
		Updates the progress bar visibility, value, and displayed message.

		Args:
			value (int): Progress percentage (0-100), -1 for indeterminate, >100 to hide.
			message (str): Text message to display alongside progress.
		"""
		if not hasattr(self, '_progressBar'): return # Safety check

		# Hide progress if not busy, unless explicitly hiding via value > 100
		if not self._isBusy and value <= 100:
			self._progressBar.setVisible(False)
			return

		if value == -1: # Indeterminate progress
			self._progressBar.setVisible(True)
			self._progressBar.setRange(0, 0) # Set range 0,0 for indeterminate animation
			self._progressBar.setFormat(message or "Working...") # Show message or default
		elif 0 <= value <= 100: # Determinate progress
			self._progressBar.setVisible(True)
			self._progressBar.setRange(0, 100)
			self._progressBar.setValue(value)
			format_str: str = f"{message} (%p%)" if message else "%p%" # Include message if provided
			self._progressBar.setFormat(format_str)
		else: # Hide progress bar (value > 100 or other invalid)
			self._progressBar.setVisible(False)
			# Reset state for next time
			self._progressBar.setRange(0, 100)
			self._progressBar.setValue(0)
			self._progressBar.setFormat("%p%")

	@Slot(str, int)
	def _updateStatusBar(self: 'MainWindow', message: str, timeout: int = 0) -> None:
		"""
		Updates the message displayed in the status bar.

		Args:
			message (str): The message to display.
			timeout (int): Duration in milliseconds to show the message (0 = permanent). Defaults to 0.
		"""
		if hasattr(self, '_statusBar') and self._statusBar:
			self._statusBar.showMessage(message, timeout)

	@Slot(str)
	def _appendLogMessage(self: 'MainWindow', message: str) -> None:
		""" Appends a formatted log message to the GUI's log text area. """
		# Check if the log area widget exists
		if hasattr(self, '_appLogArea') and self._appLogArea:
			# Append the message (Qt handles newlines automatically)
			self._appLogArea.append(message)
			# Note: QTextEdit.append() automatically scrolls to the bottom.

	# --- Message Box Convenience Methods ---
	def _showError(self: 'MainWindow', title: str, message: str) -> None:
		""" Displays a critical error message box. """
		logger.error(f"Displaying Error Dialog - Title: '{title}', Message: '{message}'")
		QMessageBox.critical(self, title, str(message))

	def _showWarning(self: 'MainWindow', title: str, message: str) -> None:
		""" Displays a warning message box. """
		logger.warning(f"Displaying Warning Dialog - Title: '{title}', Message: '{message}'")
		QMessageBox.warning(self, title, str(message))

	def _showInfo(self: 'MainWindow', title: str, message: str) -> None:
		""" Displays an informational message box. """
		logger.info(f"Displaying Info Dialog - Title: '{title}', Message: '{message}'")
		QMessageBox.information(self, title, str(message))

	# --- Diff View Interaction Handlers ---

	@Slot(QUrl)
	def _handle_diff_anchor_click(self: 'MainWindow', url: QUrl) -> None:
		"""
		Handles clicks on action links (accept ✓, reject ✘, undo ↩︎) within the diff view.
		Updates the internal acceptance state for the clicked chunk, updates the
		last focused chunk ID, and triggers a refresh of the diff display (preserving scroll).
		"""
		scheme: str = url.scheme() # Action type: 'accept', 'reject', 'undo'
		chunk_id: str = url.path() # Unique ID of the diff chunk

		# Validate input
		if not chunk_id:
			logger.warning(f"Diff action anchor clicked with no chunk_id: {url.toString()}")
			return
		current_item: Optional[QListWidgetItem] = self._fileListWidget.currentItem()
		if not current_item:
			logger.warning("Diff action anchor clicked but no file is currently focused.")
			return

		current_file_path: str = current_item.text()
		logger.debug(f"Diff Action Received: Scheme='{scheme}', ChunkID='{chunk_id}', File='{current_file_path}'")

		# Ensure the state dictionary exists for this file
		if current_file_path not in self._acceptedChangesState:
			self._acceptedChangesState[current_file_path] = {}

		# Store the ID of the chunk that was just interacted with (for focus and 'a' key)
		self._last_clicked_chunk_id = chunk_id
		logger.debug(f"Stored last focused chunk ID: {chunk_id}")

		# Determine the new acceptance state based on the action
		current_state: int = self._acceptedChangesState[current_file_path].get(chunk_id, ACCEPTANCE_PENDING)
		new_state: int = current_state # Default to no change
		state_changed: bool = False

		if scheme == "accept":
			if current_state != ACCEPTANCE_ACCEPTED:
				new_state = ACCEPTANCE_ACCEPTED
				state_changed = True
		elif scheme == "reject":
			if current_state != ACCEPTANCE_REJECTED:
				new_state = ACCEPTANCE_REJECTED
				state_changed = True
		elif scheme == "undo":
			if current_state != ACCEPTANCE_PENDING:
				new_state = ACCEPTANCE_PENDING
				state_changed = True
		elif scheme in ["http", "https"]:
			# Handle standard web links if they somehow appear
			logger.info(f"Opening external link: {url.toString()}")
			QDesktopServices.openUrl(url)
			return # Don't refresh UI for external links
		else:
			# Log unknown actions but don't crash
			logger.warning(f"Unknown diff action scheme received: '{scheme}'")
			return

		# If the state was changed, update the dictionary
		if state_changed:
			self._acceptedChangesState[current_file_path][chunk_id] = new_state
			logger.info(f"Chunk '{chunk_id}' state set to {new_state} for '{current_file_path}'. Acceptance State: {self._acceptedChangesState[current_file_path].get(chunk_id)}")
			# Refresh the diff view to show updated styles (accepted color) and focus highlight.
			# Crucially, preserve scroll position after a click action.
			logger.debug("Refreshing diff view (preserving scroll position).")
			diff_view.display_selected_file_diff(self, current_item, preserve_scroll=True)
		else:
			# Even if state didn't change (e.g., clicking accept on already accepted chunk),
			# still refresh to ensure the focus highlight is applied correctly.
			logger.debug("Acceptance state unchanged, refreshing view to apply focus highlight (preserving scroll).")
			diff_view.display_selected_file_diff(self, current_item, preserve_scroll=True)

		# Note: _updateWidgetStates() is called indirectly via display_selected_file_diff

	# --- Save Accepted Changes Handler ---
	@Slot()
	def _handle_save_accepted(self: 'MainWindow') -> None:
		"""
		Handles the 'Save Accepted (Current File)' button click.
		Generates content based ONLY on accepted changes for the focused file and saves it.
		"""
		if self._isBusy:
			self._showWarning("Busy", "Another task is currently running. Please wait.")
			return

		currentItem: Optional[QListWidgetItem] = self._fileListWidget.currentItem()
		if not currentItem:
			self._showError("No File Selected", "Please select a file in the list to save accepted changes.")
			return

		filePath: str = currentItem.text()
		logger.info(f"Attempting to save accepted changes for file: {filePath}")

		# --- Pre-save Checks ---
		if not self._clonedRepoPath or not os.path.isdir(self._clonedRepoPath):
			self._showError("Invalid Repository Path", "The loaded repository path is invalid or inaccessible.")
			return
		if filePath not in self._originalFileContents:
			# Original content is needed to reconstruct the file from accepted changes
			self._showError("Missing Original Content", f"Original content for '{filePath}' is not loaded. Cannot generate accepted version.")
			return
		# Check if there are actually any accepted changes for this file
		if filePath not in self._acceptedChangesState or not any(s == ACCEPTANCE_ACCEPTED for s in self._acceptedChangesState[filePath].values()):
			self._showInfo("No Accepted Changes", f"No changes have been explicitly accepted for '{filePath}'. Nothing to save.")
			return
		# Note: Validation check is deliberately omitted here based on user request.

		# Get original content (could be None if new file, handled by generate_accepted_content)
		original_content: Optional[str] = self._originalFileContents.get(filePath)
		# Get proposed content if available (needed by diff generator)
		proposed_content: Optional[str] = self._parsedFileData.get(filePath) if self._parsedFileData else None

		# Check if we have enough info to generate diff (at least original or proposed should exist)
		if original_content is None and proposed_content is None:
			# This case shouldn't happen if parsedData existed, but check defensively
			self._showError("Content Error", f"Neither original nor proposed content seems available for '{filePath}'. Cannot reconstruct.")
			return

		# Prepare data for generating the final content
		original_lines: List[str] = (original_content or "").splitlines() # Use empty list if None
		proposed_lines: List[str] = (proposed_content or "").splitlines() # Use empty list if None
		acceptance_state: Dict[str, int] = self._acceptedChangesState.get(filePath, {}) # Get specific state

		# --- Generate the Final Content ---
		try:
			# Use the helper function from the diff_view module
			final_content: Optional[str] = diff_view.generate_accepted_content(
				original_lines,
				proposed_lines,
				acceptance_state
			)
			# Check if generation failed (returned None)
			if final_content is None:
				self._showError("Content Generation Error", f"Failed to reconstruct the accepted content for '{filePath}'. Check logs for details.")
				return
		except Exception as e:
			logger.error(f"Error during generation of accepted content for '{filePath}': {e}", exc_info=True)
			self._showError("Content Generation Error", f"An unexpected error occurred while generating the accepted content for '{filePath}': {e}")
			return

		# --- Confirmation Dialog ---
		# Inform the user that validation status is ignored for this action
		confirm_msg: str = (f"This will overwrite the local file:\n"
							 f"'{os.path.join(self._clonedRepoPath, filePath)}'\n"
							 f"with ONLY the changes you have explicitly accepted.\n\n"
							 f"Note: Validation status for this file is ignored for this action.\n\n"
							 f"Proceed?")
		reply: QMessageBox.StandardButton = QMessageBox.question(
			self,
			'Confirm Save Accepted Changes',
			confirm_msg,
			QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
			QMessageBox.StandardButton.Cancel
		)
		if reply == QMessageBox.StandardButton.Cancel:
			logger.info("Save accepted changes cancelled by user.")
			return

		# --- Trigger Save Operation ---
		logger.info(f"Requesting save of accepted changes for file '{filePath}'...")
		self._isBusy = True
		self._updateWidgetStates() # Disable UI
		self._updateStatusBar(f"Saving accepted changes for {filePath}...")
		self._updateProgress(-1, "Saving file...")

		# Prepare data for the worker (dictionary containing only the current file)
		save_data: Dict[str, str] = {filePath: final_content}
		# Use the existing FileWorker's save task
		self._fileWorker.startSaving(self._clonedRepoPath, save_data)


	# --- Event Filter for Keyboard Navigation/Acceptance ---
	def eventFilter(self, watched: QObject, event: QEvent) -> bool:
		"""
		Filters key press events on the `_proposedCodeArea` text edit.
		Handles 'A' for accepting the focused chunk and Up/Down arrows
		for navigating between change chunks.

		Args:
			watched (QObject): The object that emitted the event.
			event (QEvent): The event object.

		Returns:
			bool: True if the event was handled here (and should be stopped),
				  False otherwise (allowing default processing).
		"""
		# Check if the event is a KeyPress on the target widget (_proposedCodeArea)
		if watched is self._proposedCodeArea and event.type() == QEvent.Type.KeyPress:
			# Cast the generic QEvent to QKeyEvent to access key details
			keyEvent: QKeyEvent = QKeyEvent(event)
			key: int = keyEvent.key()
			modifiers: Qt.KeyboardModifier = keyEvent.modifiers()

			# Process only if no keyboard modifiers (Shift, Ctrl, Alt, Meta) are pressed
			if not modifiers:
				# Check if a file is currently selected in the list widget
				current_item: Optional[QListWidgetItem] = self._fileListWidget.currentItem()
				if not current_item:
					# If no file is selected, don't handle the key press here
					return super().eventFilter(watched, event)

				# --- 'A' Key: Accept Focused Chunk ---
				if key == Qt.Key.Key_A:
					logger.debug("[EventFilter] 'A' key pressed in proposed diff area.")
					# Check if a chunk was previously clicked/navigated to
					if self._last_clicked_chunk_id:
						logger.info(f"[EventFilter] Triggering ACCEPT action via keyboard event filter for chunk: {self._last_clicked_chunk_id}")
						# Construct the URL as if the 'accept' link was clicked
						accept_url: QUrl = QUrl(f"accept:{self._last_clicked_chunk_id}")
						# Use QTimer.singleShot to call the handler slightly later,
						# avoiding potential issues calling it directly from the event filter.
						# The handler will update state and refresh the view (preserving scroll).
						QTimer.singleShot(0, lambda: (
							logger.debug("[EventFilter->Lambda] Calling _handle_diff_anchor_click for accept."),
							self._handle_diff_anchor_click(accept_url)
						))
						# Consume the event: Return True to prevent typing 'a' or default actions
						return True
					else:
						# No chunk is currently focused/selected via click or navigation
						logger.debug("[EventFilter] 'A' key ignored, no chunk currently focused ('_last_clicked_chunk_id' is None).")
						self._updateStatusBar("Click on a change chunk first to enable keyboard accept ('A').", 2000)
						# Consume the event to prevent typing 'a'
						return True

				# --- Up/Down Arrow Keys: Navigate Chunks ---
				elif key in [Qt.Key.Key_Down, Qt.Key.Key_Up]:
					key_name: str = "Down" if key == Qt.Key.Key_Down else "Up"
					logger.debug(f"[EventFilter] {key_name} arrow key pressed for chunk navigation.")

					# Check if the list of chunk IDs for the current diff is available
					if not self._current_chunk_id_list:
						logger.debug("[EventFilter] No change chunks found in the current view. Allowing default arrow key behavior.")
						# Allow default QTextEdit scrolling if there are no chunks to navigate
						return False # Do not handle event, let QTextEdit process it

					# Find the index of the currently focused chunk in the ordered list
					current_index: int = -1
					if self._last_clicked_chunk_id in self._current_chunk_id_list:
						try:
							current_index = self._current_chunk_id_list.index(self._last_clicked_chunk_id)
						except ValueError:
							logger.warning(f"Chunk ID '{self._last_clicked_chunk_id}' was in state but not found in list?")
							current_index = -1 # Treat as if nothing is selected

					# Calculate the index of the next/previous chunk
					num_chunks: int = len(self._current_chunk_id_list)
					next_index: int = -1
					if key == Qt.Key.Key_Down:
						# If nothing selected (-1), start from the first chunk (index 0)
						# Otherwise, move to the next, wrapping around to 0 if at the end
						next_index = 0 if current_index == -1 else (current_index + 1) % num_chunks
					elif key == Qt.Key.Key_Up:
						# If nothing selected (-1), start from the last chunk
						# Otherwise, move to the previous, wrapping around to end if at the beginning
						next_index = num_chunks - 1 if current_index == -1 else (current_index - 1 + num_chunks) % num_chunks

					# If a valid next chunk was found
					if 0 <= next_index < num_chunks:
						new_chunk_id: str = self._current_chunk_id_list[next_index]
						# Check if the focused chunk actually changed
						if new_chunk_id != self._last_clicked_chunk_id:
							# Update the state variable tracking the focused chunk
							self._last_clicked_chunk_id = new_chunk_id
							logger.info(f"[EventFilter] Navigating via keyboard to chunk: {new_chunk_id} (Index: {next_index})")

							# --- Trigger UI Update and Scroll ---
							# 1. Refresh the diff view to apply the focus highlight.
							#    Do NOT preserve scroll position - we want to scroll to the new chunk.
							#    Use QTimer to decouple from the event filter.
							QTimer.singleShot(0, lambda: (
								logger.debug(f"[EventFilter->Lambda] Calling display_selected_file_diff for navigation to '{new_chunk_id}'"),
								diff_view.display_selected_file_diff(self, current_item, preserve_scroll=False)
							))

							# 2. After the refresh (with a delay), move the cursor and ensure visibility.
							def scroll_to_new_chunk() -> None:
								""" Moves cursor to the start block of the new chunk and makes it visible. """
								# Check if widget still exists (window might close quickly)
								if not hasattr(self, '_proposedCodeArea'):
									logger.warning("[ScrollLambda] _proposedCodeArea no longer exists.")
									return

								# Find the target block number from the map
								target_block_num: int = self._current_chunk_start_block_map.get(new_chunk_id, -1)
								logger.debug(f"[ScrollLambda] Attempting to scroll to chunk '{new_chunk_id}', target block approx: {target_block_num}")

								if target_block_num >= 0:
									# Get the document and find the block by its number
									doc: Any = self._proposedCodeArea.document() # Use Any to satisfy type checker temporarily
									if doc is None: # Add check if document is None
										logger.warning("[ScrollLambda] Document not available.")
										return

									target_block: Any = doc.findBlockByNumber(target_block_num) # Use Any to satisfy type checker temporarily

									if target_block.isValid():
										# Create a cursor at the beginning of the target block
										cursor: QTextCursor = QTextCursor(target_block)
										# Set the text edit's cursor to this position
										self._proposedCodeArea.setTextCursor(cursor)
										# Scroll the viewport to make the cursor visible
										self._proposedCodeArea.ensureCursorVisible()
										logger.debug(f"[ScrollLambda] Moved cursor to block {target_block_num} and ensured visibility for chunk '{new_chunk_id}'.")
									else:
										logger.warning(f"[ScrollLambda] Could not find a valid QTextBlock for block number {target_block_num}")
								else:
									logger.warning(f"[ScrollLambda] Could not find start block number for chunk ID '{new_chunk_id}' in map.")

							# Schedule the scroll action with a slight delay (e.g., 100ms)
							# This gives Qt time to process the setHtml from the diff refresh.
							QTimer.singleShot(100, scroll_to_new_chunk)
							# --- End Scroll ---
						else:
							# Focused chunk didn't change (e.g., only one chunk in the list)
							logger.debug("[EventFilter] Navigation resulted in the same chunk being focused.")
					else:
						# Should not happen with modulo logic, but log if it does
						logger.warning("[EventFilter] Could not calculate a valid next chunk index.")

					# Consume the arrow key event: Return True to prevent default scrolling
					return True

		# If the event was not handled here (e.g., different widget, different key, modifiers pressed),
		# pass it to the base class's event filter implementation.
		return super().eventFilter(watched, event)
	# --- END eventFilter Method ---


	# --- Window Close Event ---
	def closeEvent(self: 'MainWindow', event: QEvent) -> None:
		""" Handles the window close event, ensuring graceful shutdown. """
		can_close: bool = True
		if self._isBusy:
			# Ask user for confirmation if a task is running
			reply: QMessageBox.StandardButton = QMessageBox.question(
				self, 'Confirm Exit',
				"A background task is currently running.\nAre you sure you want to exit?",
				QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
				QMessageBox.StandardButton.Cancel
			)
			if reply == QMessageBox.StandardButton.Cancel:
				event.ignore() # Prevent closing
				can_close = False

		if can_close:
			# Attempt to stop worker threads before closing
			logger.info("Attempting graceful shutdown of worker threads...")
			self._stop_worker_threads()
			logger.info("Shutdown sequence complete. Closing application window.")
			super().closeEvent(event) # Proceed with closing

	def _stop_worker_threads(self: 'MainWindow') -> None:
		""" Attempts to gracefully stop all running worker threads. """
		# List of worker attributes to check
		worker_attrs: List[str] = ['_githubWorker', '_llmWorker', '_fileWorker']
		workers_to_stop: List[Any] = [
			worker for attr in worker_attrs
			if hasattr(self, attr) and (worker := getattr(self, attr)) is not None
		]

		for worker in workers_to_stop:
			# Check if the worker object has an isRunning method/attribute and is running
			if hasattr(worker, 'isRunning') and worker.isRunning():
				worker_name: str = worker.__class__.__name__
				logger.debug(f"Requesting stop for {worker_name}...")
				try:
					# Prefer requestInterruption for QThreads if available
					if hasattr(worker, 'requestInterruption'):
						worker.requestInterruption()
						# Wait briefly for thread to finish
						if not worker.wait(1000): # Wait 1 second
							logger.warning(f"{worker_name} did not finish after interruption request and wait.")
							# Avoid terminate() if possible, as it can be unsafe
					else:
						# Fallback for other thread types or if interruption not implemented
						if hasattr(worker, 'quit'):
							worker.quit()
							if not worker.wait(500): # Shorter wait for quit
								logger.warning(f"{worker_name} did not finish after quit() and wait.")
						else:
							logger.warning(f"Cannot determine how to stop worker: {worker_name}")
				except Exception as e:
					# Log errors encountered during thread stopping
					logger.error(f"Error occurred while trying to stop worker {worker_name}: {e}", exc_info=True)

# --- END: gui/main_window.py ---