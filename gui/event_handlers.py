# gui/event_handlers.py
"""
Module containing the primary event handling slots for user interactions
in the MainWindow (e.g., button clicks, selection changes).
"""

import logging
import os
from typing import Optional, Dict, List, TYPE_CHECKING

from PySide6.QtWidgets import QFileDialog, QMessageBox, QInputDialog, QLineEdit, QListWidgetItem

from core.exceptions import ConfigurationError

# Type hint for MainWindow to avoid circular import if necessary
# if TYPE_CHECKING:
#    from .main_window import MainWindow

# Import other necessary modules or constants
from . import diff_view # For refreshing diff view
# Define CORRECTION_RETRY_TEMPERATURE if needed here or import from main_window/config
CORRECTION_RETRY_TEMPERATURE = 0.4

logger = logging.getLogger(__name__)


# --- Repository Handlers ---

def handle_browse_repo(window: 'MainWindow') -> None:
	"""Handles the 'Browse...' button click to select a local repository."""
	startDir = window._repoUrlInput.text() or os.path.expanduser("~")
	directory = QFileDialog.getExistingDirectory(window, "Select Local Repository Folder", startDir)
	if directory:
		window._repoUrlInput.setText(directory)

def handle_clone_load_repo(window: 'MainWindow') -> None:
	"""Handles the 'Clone / Load Repo' button click."""
	if window._isBusy:
		window._showWarning("Busy", "Another task is currently running. Please wait.")
		return

	repoUrlOrPath = window._repoUrlInput.text().strip()
	if not repoUrlOrPath:
		window._showError("Repository Missing", "Please enter a repository URL or select a local path.")
		return

	# Determine clone target path (copied logic from original MainWindow)
	try:
		if os.path.isdir(repoUrlOrPath):
			cloneTargetFullPath = os.path.abspath(repoUrlOrPath)
		else:
			defaultCloneDir = window._configManager.getConfigValue('General', 'DefaultCloneDir', fallback='./cloned_repos')
			cloneBaseDir = os.path.abspath(defaultCloneDir)
			os.makedirs(cloneBaseDir, exist_ok=True)
			repoName = os.path.basename(repoUrlOrPath.rstrip('/'))
			repoName = repoName[:-4] if repoName.endswith('.git') else repoName
			safeRepoName = "".join(c for c in repoName if c.isalnum() or c in ('-', '_')).strip() or "repository"
			cloneTargetFullPath = os.path.join(cloneBaseDir, safeRepoName)
	except ConfigurationError as e:
		window._showError("Configuration Error", f"Could not determine clone directory from config: {e}")
		return
	except OSError as e:
		window._showError("Path Error", f"Could not create clone directory '{cloneBaseDir}': {e}")
		return
	except Exception as e:
		window._showError("Path Error", f"Could not determine target path for cloning: {e}")
		return

	# --- Start clone operation ---
	window._isBusy = True
	window._updateWidgetStates()
	window._updateStatusBar("Loading/Cloning repository...")
	window._updateProgress(-1, "Starting clone/load...")

	# Clear previous state (important!)
	window._clonedRepoPath = None
	window._fileListWidget.clear()
	window._selectedFiles = []
	window._originalFileContents.clear()
	window._parsedFileData = None
	window._validationErrors = None
	window._originalCodeArea.clear()
	window._proposedCodeArea.clear()
	window._llmResponseArea.clear()
	window._promptInput.clear()

	# Start clone worker
	# Pass the progress handler instance from the window
	window._githubWorker.startClone(repoUrlOrPath, cloneTargetFullPath, None, window._gitProgressHandler)


# --- File List Handlers ---

def handle_file_selection_change(window: 'MainWindow') -> None:
	"""Updates the internal list of selected files when selection changes."""
	selectedItems = window._fileListWidget.selectedItems()
	window._selectedFiles = sorted([item.text() for item in selectedItems])
	logger.debug(f"Selection changed. Currently selected: {len(window._selectedFiles)} files.")
	# Note: Diff view update is handled by currentItemChanged signal connecting to diff_view module

# --- LLM Interaction Handlers ---

def handle_send_to_llm(window: 'MainWindow') -> None:
	"""Handles the 'Send to LLM' button click."""
	if window._isBusy:
		window._showWarning("Busy", "Another task is currently running. Please wait.")
		return

	userInstruction: str = window._promptInput.toPlainText().strip()
	if not userInstruction:
		window._showError("LLM Instruction Missing", "Please enter instructions for the LLM.")
		return
	if not window._clonedRepoPath:
		window._showError("Repository Not Loaded", "Please load a repository before sending to the LLM.")
		return

	# Check file selection (_selectedFiles is updated by handle_file_selection_change)
	if not window._selectedFiles:
		reply = QMessageBox.question(window, "No Files Selected",
								   "No files are selected to provide context to the LLM. Proceed without file context?",
								  QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
								  QMessageBox.StandardButton.Cancel)
		if reply == QMessageBox.StandardButton.Cancel:
			return
		file_context_msg = "without file context"
		file_count = 0
	else:
		file_count = len(window._selectedFiles)
		plural = 's' if file_count > 1 else ''
		file_context_msg = f"with context from {file_count} file{plural}"

	logger.info(f"Preparing to send instructions to LLM {file_context_msg}.")

	# Reset state before starting LLM interaction
	window._correction_attempted = False
	window._isBusy = True
	window._updateWidgetStates()
	window._originalFileContents.clear() # Clear old cache before reading new selection
	window._parsedFileData = None
	window._validationErrors = None
	window._originalCodeArea.clear() # Clear diff view
	window._proposedCodeArea.clear()
	window._llmResponseArea.clear()
	window._updateStatusBar(f"Reading {file_count} file{'s' if file_count!=1 else ''} for LLM context...")
	window._updateProgress(-1, f"Reading {file_count} file{'s' if file_count!=1 else ''}...")

	# Start worker to read file contents first
	window._fileWorker.startReadFileContents(window._clonedRepoPath, window._selectedFiles, userInstruction)


def handle_paste_response(window: 'MainWindow') -> None:
	"""Handles the 'Paste LLM Response' button click."""
	if window._isBusy:
		window._showWarning("Busy", "Another operation is in progress.")
		return

	# Clear state related to previous LLM response/parsing
	window._llmResponseArea.clear()
	window._parsedFileData = None
	window._validationErrors = None
	window._proposedCodeArea.clear() # Clear proposed diff view

	# Switch to the LLM Response tab
	llm_tab_index = -1
	for i in range(window._bottomTabWidget.count()):
		if window._bottomTabWidget.tabText(i) == "LLM Response":
			llm_tab_index = i
			break
	if llm_tab_index != -1:
		window._bottomTabWidget.setCurrentIndex(llm_tab_index)
	else:
		logger.warning("Could not find 'LLM Response' tab to switch to.")

	window._llmResponseArea.setFocus()
	# Reset correction flag
	window._correction_attempted = False
	window._updateStatusBar("Paste LLM response into the 'LLM Response' tab, then click 'Parse & Validate'.", 5000)

	# Refresh diff view (show original vs placeholder)
	diff_view.display_selected_file_diff(window, window._fileListWidget.currentItem())
	window._updateWidgetStates()


# --- Processing and Action Handlers ---

def handle_parse_and_validate(window: 'MainWindow') -> None:
	"""Handles the 'Parse & Validate' button click."""
	if window._isBusy:
		window._showWarning("Busy", "Another task is currently running. Please wait.")
		return

	llmResponse: str = window._llmResponseArea.toPlainText().strip()
	if not llmResponse:
		window._showError("Empty Response", "The LLM Response area is empty. Cannot parse.")
		return

	try:
		expectedFormat = window._configManager.getConfigValue('General', 'ExpectedOutputFormat', fallback='json') or 'json'
	except ConfigurationError as e:
		window._showError("Config Error", f"Could not read expected output format from config: {e}")
		return

	logger.info(f"Requesting parse & validate (format: {expectedFormat})...")
	window._isBusy = True
	window._updateWidgetStates()
	window._updateStatusBar(f"Parsing response ({expectedFormat})...")
	window._updateProgress(-1, f"Parsing {expectedFormat}...")

	# Reset parse/validation state before starting worker
	window._parsedFileData = None
	window._validationErrors = None
	window._proposedCodeArea.clear() # Clear proposed diff view

	window._fileWorker.startParsing(llmResponse, expectedFormat)


def handle_save_changes(window: 'MainWindow') -> None:
	"""Handles the 'Save Changes Locally' button click."""
	if window._isBusy:
		window._showWarning("Busy", "Another task is currently running. Please wait.")
		return
	if window._parsedFileData is None:
		window._showError("No Data", "No parsed data available. Please parse a valid LLM response first.")
		return
	if window._validationErrors:
		error_files = "\n - ".join(sorted(list(window._validationErrors.keys())))
		window._showError("Validation Errors", f"Cannot save changes when validation errors exist.\nFiles with errors:\n - {error_files}\nCheck logs and potentially ask LLM to correct.")
		return
	if not window._clonedRepoPath or not os.path.isdir(window._clonedRepoPath):
		window._showError("Invalid Repository Path", "The loaded repository path is invalid or inaccessible.")
		return

	fileCount = len(window._parsedFileData)
	if fileCount == 0:
		window._showInfo("No Changes to Save", "The parsed LLM response indicated no files needed modification.")
		return

	# Confirmation dialog
	reply = QMessageBox.question(window, 'Confirm Save',
							   f"This will overwrite {fileCount} file(s) in the local repository:\n'{window._clonedRepoPath}'\n\nProceed with saving?",
							   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
							   QMessageBox.StandardButton.Cancel)
	if reply == QMessageBox.StandardButton.Cancel:
		return

	logger.info(f"Requesting save of {fileCount} files...")
	window._isBusy = True
	window._updateWidgetStates()
	window._updateStatusBar("Saving files locally...")
	window._updateProgress(-1, "Saving files...")
	window._fileWorker.startSaving(window._clonedRepoPath, window._parsedFileData)


def handle_commit_push(window: 'MainWindow') -> None:
	"""Handles the 'Commit & Push' button click."""
	if window._isBusy:
		window._showWarning("Busy", "Another task is currently running. Please wait.")
		return
	if not window._clonedRepoPath or not os.path.isdir(window._clonedRepoPath):
		window._showError("Invalid Repository Path", "The loaded repository path is invalid or inaccessible.")
		return

	# Check dirty status immediately before commit attempt
	try:
		# Use the handler instance directly for immediate check
		is_currently_dirty = window._githubHandlerInstance.isDirty(window._clonedRepoPath)
		window._repoIsDirty = is_currently_dirty # Update internal state
	except Exception as e:
		window._showError("Git Status Error", f"Could not check repository status before commit: {e}")
		return

	if not window._repoIsDirty:
		window._showInfo("No Changes to Commit", "The repository is clean. There are no changes to commit and push.")
		window._updateWidgetStates() # Ensure button state is correct
		return

	# Get commit message
	try:
		defaultMsg = window._configManager.getConfigValue('GitHub', 'DefaultCommitMessage', fallback="LLM Update via ColonelCode")
	except ConfigurationError as e:
		logger.warning(f"Could not read default commit message from config: {e}")
		defaultMsg = "LLM Update via ColonelCode"

	commitMessage, ok = QInputDialog.getText(window, "Commit Message", "Enter commit message:", QLineEdit.EchoMode.Normal, defaultMsg)
	if not ok or not commitMessage.strip():
		window._showWarning("Commit Cancelled", "Commit message was empty or the dialog was cancelled.")
		return
	commitMessage = commitMessage.strip()

	# Get remote/branch details
	try:
		remote = window._configManager.getConfigValue('GitHub', 'DefaultRemoteName', fallback='origin') or 'origin'
		branch = window._configManager.getConfigValue('GitHub', 'DefaultBranchName', fallback='main') or 'main'
	except ConfigurationError as e:
		window._showError("Config Error", f"Could not read Git remote/branch settings from config: {e}")
		return

	# Confirmation dialog
	reply = QMessageBox.question(window, 'Confirm Commit & Push',
							   f"Commit changes and push to remote '{remote}/{branch}'?\n\nCommit Message:\n'{commitMessage}'",
							   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
							   QMessageBox.StandardButton.Cancel)
	if reply == QMessageBox.StandardButton.Cancel:
		return

	logger.info(f"Requesting commit and push to {remote}/{branch}...")
	window._isBusy = True
	window._updateWidgetStates()
	window._updateStatusBar("Committing and pushing changes...")
	window._updateProgress(-1, "Commit/Push...")
	# Pass the progress handler instance from the window
	window._githubWorker.startCommitPush(window._clonedRepoPath, commitMessage, remote, branch, window._gitProgressHandler)