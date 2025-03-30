# Updated Codebase/gui/event_handlers.py
# --- START: gui/event_handlers.py ---
# gui/event_handlers.py
"""
Module containing the primary event handling slots for user interactions
in the MainWindow (e.g., button clicks, selection changes).
These functions are typically connected to widget signals (like `clicked`).
"""

import logging
import os
from typing import Optional, Dict, List, TYPE_CHECKING

# Qt Imports
from PySide6.QtWidgets import QFileDialog, QMessageBox, QInputDialog, QLineEdit, QListWidgetItem

# Local Imports
from core.exceptions import ConfigurationError # Custom exception class
from . import diff_view # For refreshing diff view if needed (e.g., after paste)

# Type hint for MainWindow to avoid circular import issues at runtime
if TYPE_CHECKING:
	from .main_window import MainWindow # Import only for type hinting

# Logger for this module
logger: logging.Logger = logging.getLogger(__name__)

# Constant for LLM correction retry temperature (consider moving to config or main_window)
CORRECTION_RETRY_TEMPERATURE: float = 0.4


# --- Repository Handlers ---

def handle_browse_repo(window: 'MainWindow') -> None:
	"""
	Handles the 'Browse...' button click. Opens a directory selection dialog
	for the user to choose a local repository folder. Updates the repository
	path input field if a directory is selected.

	Args:
		window (MainWindow): The main application window instance.
	"""
	# Suggest starting directory based on current input or user's home directory
	startDir: str = window._repoUrlInput.text() or os.path.expanduser("~")

	# Open the standard Qt directory selection dialog
	directory: str = QFileDialog.getExistingDirectory(
		window, # Parent widget
		"Select Local Repository Folder", # Dialog title
		startDir # Starting directory
	)

	# If the user selected a directory (didn't cancel), update the input field
	if directory:
		window._repoUrlInput.setText(directory)


def handle_clone_load_repo(window: 'MainWindow') -> None:
	"""
	Handles the 'Clone / Load Repo' button click.
	Determines the target path, clears relevant state, and starts the
	GitHubWorker thread to perform the clone or load operation asynchronously.

	Args:
		window (MainWindow): The main application window instance.
	"""
	# Prevent action if another background task is already running
	if window._isBusy:
		window._showWarning("Busy", "Another task is currently running. Please wait.")
		return

	# Get repository URL or path from input field, removing leading/trailing whitespace
	repoUrlOrPath: str = window._repoUrlInput.text().strip()
	if not repoUrlOrPath:
		# Show error if input is empty
		window._showError("Repository Missing", "Please enter a repository URL or select a local path.")
		return

	# --- Determine Clone Target Path ---
	# This logic decides the final local path based on whether the input
	# is already a local directory or a URL needing cloning.
	cloneTargetFullPath: str = ""
	try:
		if os.path.isdir(repoUrlOrPath):
			# If the input path is an existing directory, use its absolute path
			cloneTargetFullPath = os.path.abspath(repoUrlOrPath)
			logger.info(f"Input is a directory, attempting to load: {cloneTargetFullPath}")
		else:
			# If input is likely a URL, determine a suitable local directory to clone into
			logger.info(f"Input is not a directory, assuming URL for cloning: {repoUrlOrPath}")
			# Get the default base directory for clones from configuration
			defaultCloneDir: str = window._configManager.getConfigValue('General', 'DefaultCloneDir', fallback='./cloned_repos')
			cloneBaseDir: str = os.path.abspath(defaultCloneDir)
			# Ensure the base cloning directory exists
			os.makedirs(cloneBaseDir, exist_ok=True)

			# Extract a repository name from the URL to use for the subdirectory
			repoName: str = os.path.basename(repoUrlOrPath.rstrip('/')) # Get last part of path
			repoName = repoName[:-4] if repoName.endswith('.git') else repoName # Remove trailing '.git' if present

			# Sanitize the repository name to create a safe directory name
			# Keep alphanumeric, hyphen, underscore; replace others or use default
			safeRepoName: str = "".join(c for c in repoName if c.isalnum() or c in ('-', '_')).strip() or "repository"

			# Construct the full path where the repo will be cloned
			cloneTargetFullPath = os.path.join(cloneBaseDir, safeRepoName)
			logger.info(f"Determined clone target directory: {cloneTargetFullPath}")

	except ConfigurationError as e:
		# Handle errors reading configuration
		window._showError("Configuration Error", f"Could not determine clone directory from config: {e}")
		return
	except OSError as e:
		# Handle errors creating directories
		window._showError("Directory Creation Error", f"Could not create base clone directory '{cloneBaseDir}': {e}")
		return
	except Exception as e:
		# Catch any other unexpected errors during path determination
		window._showError("Path Determination Error", f"Could not determine target path for cloning/loading: {e}")
		return
	# --- End Clone Target Path ---

	# --- Start Clone/Load Operation ---
	logger.info(f"Initiating clone/load for input '{repoUrlOrPath}' into target '{cloneTargetFullPath}'")
	window._isBusy = True # Set application to busy state
	window._updateWidgetStates() # Update UI (disable buttons etc.)
	window._updateStatusBar("Loading/Cloning repository...")
	window._updateProgress(-1, "Starting clone/load...") # Show indeterminate progress

	# Clear previous application state before loading new repo
	window._clonedRepoPath = None
	window._fileListWidget.clear()
	window._selectedFiles = []
	window._originalFileContents.clear()
	window._parsedFileData = None
	window._validationErrors = None
	window._acceptedChangesState.clear() # Reset acceptance state
	window._current_chunk_id_list = [] # Reset chunk metadata
	window._current_chunk_start_block_map = {}
	window._last_clicked_chunk_id = None
	window._originalCodeArea.clear() # Clear diff views
	window._proposedCodeArea.clear()
	window._llmResponseArea.clear() # Clear previous LLM response text
	window._promptInput.clear() # Optionally clear prompt input area

	# Start the background worker thread for the clone/load operation
	# Note: Authentication tokens are generally handled by Git credential managers (configured externally)
	# and not passed directly in modern workflows for security reasons. authToken is None here.
	window._githubWorker.startClone(repoUrlOrPath, cloneTargetFullPath, authToken=None)


# --- File List Handlers ---

def handle_file_selection_change(window: 'MainWindow') -> None:
	"""
	Updates the internal list `_selectedFiles` when the user changes the selection
	in the `_fileListWidget`.

	Args:
		window (MainWindow): The main application window instance.
	"""
	# Get all currently selected QListWidgetItem objects
	selectedItems: List[QListWidgetItem] = window._fileListWidget.selectedItems()
	# Extract the text (relative file path) from each item and store sorted list
	window._selectedFiles = sorted([item.text() for item in selectedItems])
	logger.debug(f"File selection changed. Currently selected: {len(window._selectedFiles)} files.")
	# The diff view updates automatically via the currentItemChanged signal connection


# --- LLM Interaction Handlers ---

def handle_send_to_llm(window: 'MainWindow') -> None:
	"""
	Handles the 'Send to LLM' button click.
	Reads the content of selected files and starts the process to send the
	user's instruction and file context to the LLM via background workers.

	Args:
		window (MainWindow): The main application window instance.
	"""
	if window._isBusy:
		window._showWarning("Busy", "Another task is currently running. Please wait.")
		return

	# Get user instruction text and perform checks
	userInstruction: str = window._promptInput.toPlainText().strip()
	if not userInstruction:
		window._showError("LLM Instruction Missing", "Please enter instructions for the LLM.")
		return
	if not window._clonedRepoPath:
		# Ensure a repository is loaded before proceeding
		window._showError("Repository Not Loaded", "Please load a repository before sending instructions to the LLM.")
		return

	# Check file selection and confirm with user if none are selected
	file_context_msg: str = ""
	file_count: int = len(window._selectedFiles) # Uses the list updated by handle_file_selection_change

	if file_count == 0:
		# Ask for confirmation if proceeding without file context
		reply: QMessageBox.StandardButton = QMessageBox.question(
			window,
			"No Files Selected for Context",
			"No files are currently selected in the list.\n"
			"The LLM will receive only your instruction without any file content.\n\n"
			"Proceed without file context?",
			QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
			QMessageBox.StandardButton.Cancel # Default button is Cancel
		)
		if reply == QMessageBox.StandardButton.Cancel:
			# User chose not to proceed
			logger.debug("Send to LLM cancelled by user due to no file selection.")
			return
		file_context_msg = "without file context"
	else:
		# Prepare informational message about the context being sent
		plural: str = 's' if file_count > 1 else ''
		file_context_msg = f"with context from {file_count} file{plural}"

	logger.info(f"Preparing to send instructions to LLM {file_context_msg}.")

	# --- Reset State Before Starting LLM Cycle ---
	window._correction_attempted = False # Reset correction attempt flag
	window._isBusy = True
	window._updateWidgetStates() # Update UI immediately
	window._originalFileContents.clear() # Clear old file cache before reading new selection
	window._parsedFileData = None # Clear previous LLM results
	window._validationErrors = None
	window._acceptedChangesState.clear() # Reset acceptance decisions
	window._current_chunk_id_list = [] # Reset chunk metadata
	window._current_chunk_start_block_map = {}
	window._last_clicked_chunk_id = None
	window._originalCodeArea.clear() # Clear diff view
	window._proposedCodeArea.clear()
	window._llmResponseArea.clear() # Clear previous LLM response display
	window._updateStatusBar(f"Reading {file_count} file{plural} for LLM context...")
	window._updateProgress(-1, f"Reading {file_count} file{plural}...")
	# --- End State Reset ---

	# Start the file worker to read the content of selected files asynchronously
	# The result will be handled by the on_file_contents_read callback
	window._fileWorker.startReadFileContents(window._clonedRepoPath, window._selectedFiles, userInstruction)


def handle_paste_response(window: 'MainWindow') -> None:
	"""
	Handles the 'Paste LLM Response' button click.
	Clears relevant state and prepares the UI for the user to paste a response
	manually into the LLM Response text area.

	Args:
		window (MainWindow): The main application window instance.
	"""
	if window._isBusy:
		window._showWarning("Busy", "Another operation is in progress. Cannot paste response now.")
		return

	logger.info("Paste LLM Response button clicked. Clearing state and focusing response area.")

	# Clear state related to previous LLM response and its processing
	window._llmResponseArea.clear()
	window._parsedFileData = None
	window._validationErrors = None
	window._acceptedChangesState.clear()
	window._current_chunk_id_list = []
	window._current_chunk_start_block_map = {}
	window._last_clicked_chunk_id = None
	window._proposedCodeArea.clear() # Clear proposed diff view as well

	# Automatically switch to the 'LLM Response' tab
	llm_tab_index: int = -1
	for i in range(window._bottomTabWidget.count()):
		if window._bottomTabWidget.tabText(i) == "LLM Response":
			llm_tab_index = i
			break
	if llm_tab_index != -1:
		window._bottomTabWidget.setCurrentIndex(llm_tab_index)
	else:
		# Log if the tab wasn't found, but continue
		logger.warning("Could not find 'LLM Response' tab to switch to automatically.")

	# Set focus to the response area and provide user instructions via status bar
	window._llmResponseArea.setFocus()
	window._correction_attempted = False # Reset correction flag for manual paste workflow
	window._updateStatusBar("Paste LLM response into the 'LLM Response' tab, then click 'Parse & Validate'.", 5000)

	# Refresh the diff view (will show original vs. placeholder as no proposed data exists)
	diff_view.display_selected_file_diff(window, window._fileListWidget.currentItem())
	window._updateWidgetStates() # Ensure Parse button state is updated etc.


# --- Processing and Action Handlers ---

def handle_parse_and_validate(window: 'MainWindow') -> None:
	"""
	Handles the 'Parse & Validate' button click.
	Retrieves the text from the LLM Response area and starts the FileWorker
	to parse and validate it asynchronously.

	Args:
		window (MainWindow): The main application window instance.
	"""
	if window._isBusy:
		window._showWarning("Busy", "Another task is currently running. Please wait.")
		return

	# Get the raw text content from the LLM response widget
	llmResponse: str = window._llmResponseArea.toPlainText().strip()
	if not llmResponse:
		# Show error if there's nothing to parse
		window._showError("Empty Response", "The LLM Response area is empty. Cannot parse.")
		return

	# Determine the expected output format (e.g., 'json', 'yaml') from configuration
	try:
		expectedFormat: str = window._configManager.getConfigValue('General', 'ExpectedOutputFormat', fallback='json') or 'json'
	except ConfigurationError as e:
		window._showError("Configuration Error", f"Could not read expected output format from configuration: {e}")
		return

	logger.info(f"Requesting parse & validate of LLM response (expecting format: {expectedFormat})...")
	window._isBusy = True # Set busy state
	window._updateWidgetStates() # Update UI
	window._updateStatusBar(f"Parsing response ({expectedFormat})...")
	window._updateProgress(-1, f"Parsing {expectedFormat}...") # Indeterminate progress

	# Reset state related to parsing, validation, and acceptance before starting
	window._parsedFileData = None
	window._validationErrors = None
	window._acceptedChangesState.clear()
	window._current_chunk_id_list = []
	window._current_chunk_start_block_map = {}
	window._last_clicked_chunk_id = None
	window._proposedCodeArea.clear() # Clear previous proposed diff

	# Start the file worker's parsing task
	window._fileWorker.startParsing(llmResponse, expectedFormat)


def handle_save_changes(window: 'MainWindow') -> None:
	"""
	Handles the 'Save All Changes' button click.
	Saves ALL files present in the parsed data (`_parsedFileData`) to disk,
	after confirming with the user and warning if any validation errors exist.

	Args:
		window (MainWindow): The main application window instance.
	"""
	if window._isBusy:
		window._showWarning("Busy", "Another task is currently running. Please wait.")
		return
	# Check if there is parsed data available to save
	if window._parsedFileData is None:
		window._showError("No Parsed Data", "No parsed data available. Please parse a valid LLM response first.")
		return
	# Check if repository path is valid
	if not window._clonedRepoPath or not os.path.isdir(window._clonedRepoPath):
		window._showError("Invalid Repository Path", "The loaded repository path is invalid or inaccessible.")
		return

	fileCount: int = len(window._parsedFileData)
	if fileCount == 0:
		# Inform user if the parsed data resulted in no files to change
		window._showInfo("No Changes to Save", "The parsed LLM response indicated no files needed modification.")
		return

	# --- Prepare Confirmation Dialog ---
	confirm_msg: str = (f"This will overwrite {fileCount} file(s) in the local repository:\n"
						 f"'{window._clonedRepoPath}'\n\n")

	# Check for validation errors and add a clear warning if found
	if window._validationErrors:
		error_count: int = len(window._validationErrors)
		# List the files with errors in the warning message
		error_files_summary: str = "\n - ".join(sorted(list(window._validationErrors.keys())))
		confirm_msg += (f"*** WARNING: Validation failed for {error_count} file(s): ***\n"
						 f"- {error_files_summary}\n\n"
						 f"Saving these files may introduce errors or prevent code execution.\n\n")

	confirm_msg += "Proceed with saving ALL listed files?"

	# Show confirmation dialog to the user
	reply: QMessageBox.StandardButton = QMessageBox.question(
		window,
		'Confirm Save All Changes', # Dialog Title
		confirm_msg, # Dialog Message (includes warning if applicable)
		QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
		QMessageBox.StandardButton.Cancel # Default button
	)
	# --- End Confirmation Dialog ---

	# Proceed only if user confirms
	if reply == QMessageBox.StandardButton.Cancel:
		logger.info("Save all changes cancelled by user.")
		return

	# Start the save operation via the FileWorker
	# Note: Validation status was only used for the warning; the save proceeds regardless now.
	logger.info(f"Requesting save of {fileCount} parsed files (validation status ignored for save action)...")
	window._isBusy = True
	window._updateWidgetStates() # Update UI
	window._updateStatusBar("Saving all parsed files locally...")
	window._updateProgress(-1, f"Saving {fileCount} files...")
	# Pass the entire parsed data dictionary to the worker
	window._fileWorker.startSaving(window._clonedRepoPath, window._parsedFileData)


def handle_commit_push(window: 'MainWindow') -> None:
	"""
	Handles the 'Commit & Push' button click.
	Checks repository status, prompts for commit message, confirms with user,
	and then starts the GitHubWorker to commit staged changes and push.

	Args:
		window (MainWindow): The main application window instance.
	"""
	if window._isBusy:
		window._showWarning("Busy", "Another task is currently running. Please wait.")
		return
	if not window._clonedRepoPath or not os.path.isdir(window._clonedRepoPath):
		window._showError("Invalid Repository Path", "The loaded repository path is invalid or inaccessible.")
		return

	# --- Check Repository Status ---
	# Perform an immediate check for uncommitted changes before proceeding
	try:
		# Use the handler instance directly for this synchronous check
		is_currently_dirty: bool = window._githubHandlerInstance.isDirty(window._clonedRepoPath)
		window._repoIsDirty = is_currently_dirty # Update internal state for UI consistency
	except Exception as e:
		# Handle errors during the status check itself
		window._showError("Git Status Error", f"Could not check repository status before commit: {e}")
		return

	# If repository is clean, inform user and stop
	if not window._repoIsDirty:
		window._showInfo("No Changes to Commit",
						 "The repository working directory is clean according to Git status.\n"
						 "Please stage changes using Git before using 'Commit & Push'.")
		window._updateWidgetStates() # Ensure button state reflects clean status
		return
	# --- End Status Check ---

	# --- Get Commit Message ---
	try:
		# Retrieve default message from config, provide fallback
		defaultMsg: str = window._configManager.getConfigValue('GitHub', 'DefaultCommitMessage', fallback="LLM Update via ColonelCode") or "LLM Update via ColonelCode"
	except ConfigurationError as e:
		# Log warning but use fallback if config read fails
		logger.warning(f"Could not read default commit message from configuration: {e}")
		defaultMsg = "LLM Update via ColonelCode"

	# Use QInputDialog to get commit message from the user
	commitMessage, ok = QInputDialog.getText(
		window, # Parent
		"Commit Message", # Dialog Title
		"Enter commit message for staged changes:", # Label text
		QLineEdit.EchoMode.Normal, # Input mode
		defaultMsg # Pre-filled text
	)

	# Proceed only if user entered text and clicked OK
	if not ok or not commitMessage.strip():
		window._showWarning("Commit Cancelled", "Commit message was empty or the dialog was cancelled.")
		return
	commitMessage = commitMessage.strip() # Use the stripped message
	# --- End Get Commit Message ---

	# --- Get Remote/Branch Details ---
	try:
		# Retrieve default remote and branch names from config, provide fallbacks
		remote: str = window._configManager.getConfigValue('GitHub', 'DefaultRemoteName', fallback='origin') or 'origin'
		branch: str = window._configManager.getConfigValue('GitHub', 'DefaultBranchName', fallback='main') or 'main'
	except ConfigurationError as e:
		window._showError("Configuration Error", f"Could not read Git remote/branch settings from configuration: {e}")
		return
	# --- End Get Remote/Branch ---

	# --- Confirmation Dialog ---
	reply: QMessageBox.StandardButton = QMessageBox.question(
		window,
		'Confirm Commit & Push',
		f"This will commit currently STAGED changes and attempt to push to remote '{remote}/{branch}'.\n"
		f"(Ensure desired changes are staged first using standard Git commands)\n\n"
		f"Commit Message:\n'{commitMessage}'\n\n"
		f"Proceed?",
		QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
		QMessageBox.StandardButton.Cancel # Default button
	)
	if reply == QMessageBox.StandardButton.Cancel:
		logger.info("Commit & Push cancelled by user.")
		return
	# --- End Confirmation Dialog ---

	# --- Start Commit & Push Worker ---
	logger.info(f"Requesting commit and push of staged changes to {remote}/{branch}...")
	window._isBusy = True
	window._updateWidgetStates() # Update UI
	window._updateStatusBar("Committing staged changes and pushing...")
	window._updateProgress(-1, "Commit/Push...") # Indeterminate progress
	# Call the GitHub worker thread to perform the operation asynchronously
	window._githubWorker.startCommitPush(window._clonedRepoPath, commitMessage, remote, branch)

# --- END: gui/event_handlers.py ---