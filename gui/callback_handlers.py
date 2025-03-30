# gui/callback_handlers.py
"""
Module containing the slots that handle signals emitted by the worker threads
(GitHubWorker, LLMWorker, FileWorker). These update the MainWindow state
and UI based on the results of background operations.
"""

import logging
import os
from typing import Optional, Dict, List, Tuple, TYPE_CHECKING

from PySide6.QtWidgets import QListWidget, QListWidgetItem, QMessageBox
from PySide6.QtGui import QColor # Import QColor
from PySide6.QtCore import Qt # Import Qt for MatchFlag

# Import necessary modules
from core.exceptions import ConfigurationError, LLMError
from . import diff_view # To update diff view

# Constants
CORRECTION_RETRY_TEMPERATURE = 0.4 # Needs to be defined or imported

# Define colours for file list items
COLOR_PROPOSED = QColor("orange")  # Yellow/Orange for proposed changes
COLOR_SAVED = QColor("green")    # Green for saved changes
COLOR_DEFAULT = QColor("black")   # Default text colour (can adjust if theme changes)
COLOR_VALIDATION_ERROR = QColor("red") # Optional: Red for validation errors

# Type hint for MainWindow to avoid circular import if necessary
if TYPE_CHECKING:
	from .main_window import MainWindow

logger = logging.getLogger(__name__)


def _find_list_widget_item(list_widget: 'QListWidget', text: str) -> Optional[QListWidgetItem]:
	"""Helper function to find a QListWidgetItem by its text."""
	items = list_widget.findItems(text, Qt.MatchFlag.MatchExactly)
	return items[0] if items else None

# --- GitHub Worker Callbacks ---

def on_clone_load_finished(window: 'MainWindow', repoPath: str, fileList: list) -> None:
	"""
	Handles the completion of the repository clone/load operation.
	Loads repository information, populates the file list, applies ignore rules,
	and triggers a dirty status check. Resets file list colours.
	"""
	logger.info(f"Clone/Load finished successfully. Path: {repoPath}, Files: {len(fileList)}")
	window._isBusy = False # Mark cloning as done before starting next steps
	window._clonedRepoPath = repoPath

	# Reset state related to previous repo/LLM response
	window._parsedFileData = None
	window._validationErrors = None
	window._originalFileContents.clear()
	window._llmResponseArea.clear()
	window._originalCodeArea.clear()
	window._proposedCodeArea.clear()
	window._promptInput.clear() # Clear prompt too? Optional.

	# Save path to config
	window._saveLastRepoPath(repoPath)
	window._updateStatusBar(f"Repository loaded ({len(fileList)} files). Applying ignore rules...", 5000)

	# --- .codebaseignore Handling (Copied from original) ---
	codebase_ignore_filename: str = '.codebaseignore'
	codebase_ignore_path = os.path.join(repoPath, codebase_ignore_filename)
	matches = None # Function to check if a path matches ignore rules

	try:
		if os.path.exists(codebase_ignore_path) and os.path.isfile(codebase_ignore_path):
			parser_used = None
			try:
				import gitignore_parser
				logger.debug(f"Found 'gitignore_parser' module: {gitignore_parser}")
				if hasattr(gitignore_parser, 'parse') and callable(gitignore_parser.parse):
					with open(codebase_ignore_path, 'r', encoding='utf-8', errors='ignore') as f:
						matches = gitignore_parser.parse(f)
					if callable(matches):
						parser_used = "gitignore_parser.parse()"
						logger.info(f"Loaded rules from {codebase_ignore_filename} using gitignore_parser.parse()")
					else:
						logger.warning(f"gitignore_parser.parse() did not return a callable for {codebase_ignore_filename}.")
						matches = None
				else:
					logger.debug(f"'gitignore_parser' module lacks callable 'parse' attribute.")
					matches = None
			except ImportError:
				logger.debug("'gitignore-parser' (hyphen) library not found, trying 'gitignore_parser' (underscore).")
				matches = None
			except Exception as e_parse:
				logger.error(f"Error using 'gitignore_parser.parse()' for {codebase_ignore_filename}: {e_parse}", exc_info=True)
				matches = None

			if matches is None:
				try:
					# Attempt direct import of function if module structure allows
					from gitignore_parser import parse_gitignore
					logger.debug(f"Found 'parse_gitignore' function from gitignore_parser module.")
					matches = parse_gitignore(codebase_ignore_path)
					if callable(matches):
						parser_used = "parse_gitignore()"
						logger.info(f"Loaded rules from {codebase_ignore_filename} using parse_gitignore()")
					else:
						logger.warning(f"parse_gitignore() did not return a callable for {codebase_ignore_filename}.")
						matches = None
				except ImportError:
					logger.warning(f"Neither 'gitignore-parser' nor 'gitignore_parser' library seems to be installed correctly or function is not directly importable.")
					window._appendLogMessage(f"WARNING: No suitable gitignore parsing library found. Cannot apply {codebase_ignore_filename} rules.")
				except Exception as e_func:
					logger.error(f"Error using 'parse_gitignore()' function for {codebase_ignore_filename}: {e_func}", exc_info=True)
					window._appendLogMessage(f"ERROR: Failed parsing {codebase_ignore_filename} with parse_gitignore(): {e_func}")
					matches = None

			if not parser_used and matches is None:
				logger.error(f"Failed to load or parse {codebase_ignore_filename} using available methods.")
				window._appendLogMessage(f"ERROR: Could not parse {codebase_ignore_filename}. Check library installations and file content.")
		else:
			logger.info(f"'{codebase_ignore_filename}' not found in repository root. All files will be selected by default.")

	except Exception as e_top:
		logger.error(f"Unexpected error during {codebase_ignore_filename} handling: {e_top}", exc_info=True)
		window._appendLogMessage(f"ERROR: Unexpected error handling {codebase_ignore_filename}: {e_top}")
		matches = None
	# --- End .codebaseignore Handling ---

	# Populate the file list widget
	window._fileListWidget.clear()
	window._fileListWidget.addItems(sorted(fileList)) # Add all tracked files first

	# --- Set default selection based on .codebaseignore ---
	selected_files_init = []
	ignored_count = 0
	total_count = window._fileListWidget.count()

	window._fileListWidget.blockSignals(True) # Block signals during selection/colouring

	for i in range(total_count):
		item = window._fileListWidget.item(i)
		if not item: continue # Safety check
		file_path_relative = item.text()
		abs_repo_path = os.path.abspath(repoPath)
		# Use os.path.join for robust path construction
		file_path_absolute = os.path.join(abs_repo_path, file_path_relative)

		should_select = True # Select by default
		if matches and callable(matches):
			try:
				# Use absolute path for matching
				if matches(file_path_absolute):
					should_select = False
					ignored_count += 1
			except Exception as e_match:
				logger.warning(f"Error matching file '{file_path_relative}' against {codebase_ignore_filename} rules: {e_match}")

		item.setSelected(should_select)
		item.setForeground(COLOR_DEFAULT) # <<-- Reset colour on load
		if should_select:
			selected_files_init.append(file_path_relative)

	window._fileListWidget.blockSignals(False) # Re-enable signals
	# --- End default selection ---

	window._selectedFiles = sorted(selected_files_init) # Update internal state
	logger.info(f"Initial file selection complete. Ignored {ignored_count}/{total_count} files. Selected: {len(window._selectedFiles)} files.")
	window._updateStatusBar(f"Repository loaded. Initial selection set ({len(window._selectedFiles)}/{total_count} files). Checking status...", 5000)

	# Automatically check dirty status after successful load
	if not window._isBusy and window._clonedRepoPath:
		window._isBusy = True # Set busy for the dirty check
		window._updateWidgetStates()
		window._updateProgress(-1, "Checking repository status...")
		window._githubWorker.startIsDirty(window._clonedRepoPath)
	else:
		logger.warning("Cannot start dirty check after clone/load operation finished.")
		window._updateWidgetStates()


def on_is_dirty_finished(window: 'MainWindow', is_dirty: bool) -> None:
	"""Handles the completion of the repository dirty status check."""
	if not window._clonedRepoPath: return # Avoid updates if repo was unloaded

	logger.info(f"Repository dirty status check completed: {is_dirty}")
	window._repoIsDirty = is_dirty
	window._isBusy = False # Finished the dirty check task
	status_msg = "Repository status: Dirty (Uncommitted changes exist)" if is_dirty else "Repository status: Clean"
	window._updateStatusBar(status_msg, 5000)
	window._updateProgress(100, "Status check complete.") # Mark progress as complete
	window._updateWidgetStates() # Update button enable/disable states


def on_pull_finished(window: 'MainWindow', message: str, had_conflicts: bool) -> None:
	"""Handles the completion of a git pull operation."""
	if not window._clonedRepoPath: return

	logger.info(f"Pull finished: {message}, Conflicts: {had_conflicts}")
	window._isBusy = False # Task done
	window._updateStatusBar(f"Pull finished. {message}", 10000)
	window._updateProgress(100, "Pull complete.")

	if had_conflicts:
		window._showWarning("Pull Conflicts", f"Pull completed, but merge conflicts likely occurred.\nDetails: {message}\nPlease resolve conflicts manually using Git tools.")
		window._repoIsDirty = True # Conflicts make it dirty
		window._updateWidgetStates()
	else:
		window._showInfo("Pull Finished", message)
		# Re-check dirty status after a successful pull without known conflicts
		if window._clonedRepoPath and not window._isBusy:
			window._isBusy = True
			window._updateWidgetStates()
			window._updateStatusBar("Checking repository status after pull...", 5000)
			window._updateProgress(-1, "Checking status...")
			window._githubWorker.startIsDirty(window._clonedRepoPath)
		elif window._clonedRepoPath:
			logger.warning("Could not automatically re-check dirty status after pull.")
			window._repoIsDirty = False # Assume clean if we can't check
			window._updateWidgetStates()

def on_commit_push_finished(window: 'MainWindow', message: str) -> None:
	"""Handles the completion of a commit and push operation."""
	if not window._clonedRepoPath: return

	logger.info(f"Commit/Push finished: {message}")
	window._isBusy = False # Task done
	window._updateStatusBar("Commit and push successful.", 5000)
	window._updateProgress(100, "Commit/Push complete.")
	window._showInfo("Commit/Push Successful", message)
	window._repoIsDirty = False # Assume clean after successful push

	# Clear state related to the previous change set
	window._parsedFileData = None
	window._validationErrors = None
	window._llmResponseArea.clear()
	window._promptInput.clear()
	# Reset file list colors to default
	for i in range(window._fileListWidget.count()):
		item = window._fileListWidget.item(i)
		if item:
			item.setForeground(COLOR_DEFAULT)

	# Update diff view to reflect clean state
	diff_view.display_selected_file_diff(window, window._fileListWidget.currentItem())
	window._updateWidgetStates() # Update buttons (commit should be disabled)


def on_list_files_finished(window: 'MainWindow', fileList: list) -> None:
	"""Placeholder: Handles the completion of listing files (if needed)."""
	# This might be used if listing files becomes a separate async action
	logger.debug(f"List files finished callback triggered with {len(fileList)} files.")
	# Potentially update UI or state if listFiles is called independently
	window._resetTaskState() # Example: Reset state if this was a distinct task

def on_read_file_finished(window: 'MainWindow', content: str) -> None:
	"""Placeholder: Handles the completion of reading a single file (if needed)."""
	# This might be used if reading a file becomes a separate async action
	logger.debug(f"Read file finished callback triggered. Content length: {len(content)}")
	# Potentially update UI (e.g., display content) or state
	window._resetTaskState() # Example: Reset state if this was a distinct task

# --- LLM Worker Callbacks ---

def on_llm_finished(window: 'MainWindow', response: str) -> None:
	"""Handles the successful response from the LLM query, including correction attempts."""
	logger.info(f"LLM query finished. Response length: {len(response)}")

	# Ensure necessary attributes exist
	if not all(hasattr(window, attr) for attr in ['_isBusy', '_updateProgress', '_llmResponseArea', '_bottomTabWidget', '_parsedFileData', '_validationErrors', '_correction_attempted', '_updateStatusBar', '_updateWidgetStates', '_fileListWidget']):
		logger.error("MainWindow object missing required attributes in on_llm_finished.")
		return

	window._isBusy = False
	window._updateProgress(100, "LLM query complete.")
	window._llmResponseArea.setPlainText(response) # Display the latest response

	# Switch to the LLM Response tab
	llm_tab_index = -1
	for i in range(window._bottomTabWidget.count()):
		if window._bottomTabWidget.tabText(i) == "LLM Response":
			llm_tab_index = i
			break
	if llm_tab_index != -1:
		window._bottomTabWidget.setCurrentIndex(llm_tab_index)
	else:
		logger.warning("Could not find 'LLM Response' tab to switch to automatically.")

	# Reset parsing/validation state as new response arrived
	window._parsedFileData = None
	window._validationErrors = None
	# Reset file list colors - will be updated by parse step
	for i in range(window._fileListWidget.count()):
		item = window._fileListWidget.item(i)
		if item:
			item.setForeground(COLOR_DEFAULT)

	# Refresh diff view (show original vs placeholder proposed)
	diff_view.display_selected_file_diff(window, window._fileListWidget.currentItem())

	if window._correction_attempted:
		# This was the response to a correction request
		window._updateStatusBar("LLM correction received. Parsing corrected response...", 10000)
		# Need to import event_handlers here or call MainWindow method if kept
		from . import event_handlers
		# Automatically trigger parsing again
		event_handlers.handle_parse_and_validate(window)
	else:
		# This was the response to the initial query
		window._updateStatusBar("LLM query successful. Click 'Parse & Validate' to process the response.", 5000)
		window._updateWidgetStates() # Update state now that response is available

# --- File Worker Callbacks ---

def on_file_contents_read(window: "MainWindow", fileContents: Dict[str, str], userInstruction: str) -> None:
	"""Handles completion of reading files before sending to LLM."""
	if not window._isBusy: return # Avoid processing if task was cancelled

	logger.info(f"File reading finished ({len(fileContents)} files). Querying LLM...")
	window._originalFileContents = fileContents # Store original contents

	# Update diff view for focused file now that original content is cached
	diff_view.display_selected_file_diff(window, window._fileListWidget.currentItem())

	# Get model name from config
	try:
		modelName = window._configManager.getConfigValue('General', 'DefaultLlmModel', fallback='gemini-1.5-flash-latest') or 'gemini-1.5-flash-latest'
	except ConfigurationError as e:
		window._showError("Config Error", f"Could not read LLM model from config: {e}")
		window._resetTaskState()
		return

	# Build the prompt
	try:
		# Use the LLM Interface instance from the window
		if hasattr(window, '_llmInterfaceInstance'):
			prompt = window._llmInterfaceInstance.buildPrompt(userInstruction, fileContents)
			logger.debug(f"Built prompt for LLM (length: {len(prompt)} chars).")
		else:
			raise AttributeError("LLM interface instance not found on main window.")
	except Exception as e:
		window._showError("Prompt Error", f"Failed to build prompt for LLM: {e}")
		window._resetTaskState()
		return

	# Send query to LLM worker
	window._updateStatusBar("Sending request to LLM...")
	window._updateProgress(-1, "Sending to LLM...")
	window._llmWorker.startQuery(modelName, prompt)


def on_parsing_finished(window: 'MainWindow', parsedData: Dict[str, str], validationResults: Dict[str, List[str]]) -> None:
	"""Handles the result of parsing and validation. Updates file list colours."""
	if not window._clonedRepoPath: return # Avoid updates if repo unloaded

	logger.info(f"Parsing finished. Parsed items: {len(parsedData)}. Validation Errors: {len(validationResults)}")
	window._isBusy = False # Parsing task is done
	window._parsedFileData = parsedData
	window._validationErrors = validationResults if validationResults else None # Store None if empty dict

	# Ensure original content is loaded for all parsed files (important for diff and color)
	if window._clonedRepoPath and window._parsedFileData:
		logger.debug("Ensuring original content is cached for parsed files before displaying diff...")
		# Use the diff_view module's constant
		from .diff_view import MAX_DIFF_FILE_SIZE
		for file_path in window._parsedFileData.keys():
			# Use sentinel to avoid re-checking files already known (None or content)
			if window._originalFileContents.get(file_path, "__NOT_CHECKED__") == "__NOT_CHECKED__":
				full_path = os.path.join(window._clonedRepoPath, file_path)
				if os.path.exists(full_path) and os.path.isfile(full_path):
					try:
						if os.path.getsize(full_path) > MAX_DIFF_FILE_SIZE:
							logger.warning(f"Original file {file_path} too large ({os.path.getsize(full_path)} bytes). Storing placeholder.")
							window._originalFileContents[file_path] = f"<File too large (>{MAX_DIFF_FILE_SIZE // 1024} KB)>"
						else:
							with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
								window._originalFileContents[file_path] = f.read()
							logger.debug(f"Loaded original content for {file_path} after parse.")
					except Exception as e:
						logger.error(f"Error reading original file {file_path} after parse: {e}", exc_info=True)
						window._originalFileContents[file_path] = f"<Error reading file: {e}>"
				else:
					window._originalFileContents[file_path] = None # Mark as non-existent
					logger.debug(f"Original file {file_path} not found locally after parse (likely new file).")

	# Log validation results and update status
	status_msg = ""
	if window._validationErrors:
		log_message = ["--- Validation Failed ---"]
		error_files = set()
		for file_path, errors in window._validationErrors.items():
			error_files.add(os.path.basename(file_path))
			log_message.append(f"  File: {file_path}")
			for error in errors:
				log_message.append(f"    * {error}")
		log_message.append("-------------------------")
		window._appendLogMessage("\n".join(log_message))
		error_summary = f"Validation failed for {len(window._validationErrors)} file(s).\nCheck Application Log tab.\n\nFiles:\n - " + "\n - ".join(sorted(list(error_files)))
		window._showWarning("Code Validation Failed", error_summary)
		status_msg = f"Response parsed. Validation FAILED ({len(window._validationErrors)} file(s))."
	else:
		file_count_msg = f"{len(parsedData)} file(s)" if parsedData else "No changes"
		status_msg = f"Response parsed: {file_count_msg} found. Validation OK."
		window._appendLogMessage("--- Validation OK ---")
		# Clear correction flag ONLY on successful validation
		window._correction_attempted = False

	window._updateStatusBar(status_msg, 10000)
	window._updateProgress(100, "Parse & Validate complete.")

	# Add any new files mentioned in the parsed data to the list widget
	current_files_in_widget = set(window._fileListWidget.item(i).text() for i in range(window._fileListWidget.count()))
	new_files_added_to_widget = False
	if window._parsedFileData:
		window._fileListWidget.blockSignals(True) # Block signals during add
		for filePath in sorted(window._parsedFileData.keys()):
			if filePath not in current_files_in_widget:
				newItem = QListWidgetItem(filePath)
				# Don't set color here yet, wait for loop below
				window._fileListWidget.addItem(newItem)
				new_files_added_to_widget = True
		if new_files_added_to_widget:
			window._fileListWidget.sortItems() # Keep list sorted
		window._fileListWidget.blockSignals(False) # Re-enable signals

	# --- Update file list colours based on parsed data ---
	window._fileListWidget.blockSignals(True)
	for i in range(window._fileListWidget.count()):
		item = window._fileListWidget.item(i)
		if not item: continue
		file_path = item.text()

		item_color = COLOR_DEFAULT # Start with default

		if window._parsedFileData and file_path in window._parsedFileData:
			# File has proposed changes
			original_content = window._originalFileContents.get(file_path)
			proposed_content = window._parsedFileData[file_path]

			# Check if it's a new file or content has changed
			# Handle case where original content was unreadable (treat as changed)
			is_new = original_content is None
			is_unreadable = isinstance(original_content, str) and original_content.startswith("<")
			is_different = original_content != proposed_content

			if is_new or is_unreadable or is_different:
				# Consider using red if validation failed for this file
				# if window._validationErrors and file_path in window._validationErrors:
				#    item_color = COLOR_VALIDATION_ERROR
				# else:
				item_color = COLOR_PROPOSED # Set to yellow if proposed changes exist

		item.setForeground(item_color)
	window._fileListWidget.blockSignals(False)
	# --- End colour update ---

	# Refresh the diff display for the currently focused item
	diff_view.display_selected_file_diff(window, window._fileListWidget.currentItem())
	window._updateWidgetStates() # Update button states based on outcome


def on_saving_finished(window: 'MainWindow', savedFiles: list) -> None:
	"""Handles the completion of saving files to disk. Updates file list colours."""
	if not window._clonedRepoPath: return

	logger.info(f"Saving finished successfully. Saved files: {len(savedFiles)}")
	window._isBusy = False # Saving task done
	window._updateStatusBar(f"Changes saved locally ({len(savedFiles)} files).", 5000)
	window._updateProgress(100, "Saving complete.")

	if savedFiles:
		window._showInfo("Save Successful", f"{len(savedFiles)} file(s) saved/updated in\n'{window._clonedRepoPath}'.")
		window._repoIsDirty = True # Saving makes the repo dirty

		# Update the original content cache with the newly saved content
		if window._parsedFileData:
			for saved_path in savedFiles:
				# Ensure the saved path uses consistent separators if needed
				# norm_saved_path = os.path.normpath(saved_path)
				if saved_path in window._parsedFileData:
					window._originalFileContents[saved_path] = window._parsedFileData[saved_path]

		# --- Update colours for saved files ---
		window._fileListWidget.blockSignals(True)
		for saved_path in savedFiles:
			# Find item corresponding to the saved path
			items = window._fileListWidget.findItems(saved_path, Qt.MatchFlag.MatchExactly)
			if items:
				item = items[0]
				item.setForeground(COLOR_SAVED) # Set to green
			else:
				logger.warning(f"Could not find list widget item for saved file: {saved_path}")
		window._fileListWidget.blockSignals(False)
		# --- End colour update ---

		# Clear parsed data/errors after successful save
		window._parsedFileData = None
		window._validationErrors = None
		# Refresh diff view to show saved state (original should now match proposed conceptually)
		diff_view.display_selected_file_diff(window, window._fileListWidget.currentItem())
	else:
		logger.info("Saving finished, but no files were listed as saved.")
		if window._parsedFileData is not None: # Check if there was data *to* save
			window._showInfo("Save Complete", "Processing complete, but no files reported as saved.")
			# Clear parsed data even if nothing was saved
			window._parsedFileData = None
			window._validationErrors = None
			# Reset potentially yellow items back to black if save happened but didn't include them
			# (e.g., user deselected files before saving, or save was partial - though save should be atomic)
			# This might be overly aggressive, let's leave non-saved items yellow if they were.
			diff_view.display_selected_file_diff(window, window._fileListWidget.currentItem())

	window._updateWidgetStates() # Update button states (commit should be enabled now)

# --- Error Handling Callbacks ---

def handle_worker_error(window: 'MainWindow', errorMessage: str, worker_name: str) -> None:
	"""Handles generic, unexpected errors from worker threads."""
	logger.critical(f"Unexpected error in {worker_name}: {errorMessage}", exc_info=True)
	window._resetTaskState()
	window._showError("Unexpected Background Task Error", f"A critical internal error occurred in {worker_name}:\n{errorMessage}")
	window._appendLogMessage(f"CRITICAL ERROR ({worker_name}): {errorMessage}")


def handle_github_error(window: 'MainWindow', errorMessage: str) -> None:
	"""Handles specific errors related to GitHub operations."""
	logger.error(f"GitHub operation failed: {errorMessage}")
	# Check if it was a clone/load related error
	is_load_error = any(s in errorMessage.lower() for s in ["clone", "load", "not found", "authentication failed", "valid git repo", "invalid repository", "not a git repo"])

	window._resetTaskState() # Reset busy state regardless
	window._showError("Git/GitHub Error", errorMessage)
	window._appendLogMessage(f"GIT ERROR: {errorMessage}")

	if is_load_error:
		# Reset repo-specific state fully if loading/cloning failed
		logger.info("Resetting repository state due to load/clone error.")
		window._clonedRepoPath = None
		window._fileListWidget.clear()
		window._repoIsDirty = False
		window._originalFileContents.clear()
		window._parsedFileData = None
		window._validationErrors = None
		window._originalCodeArea.clear()
		window._proposedCodeArea.clear()
		window._llmResponseArea.clear()
		window._promptInput.clear()
		window._selectedFiles = []
		window._updateWidgetStates() # Update UI to reflect no repo loaded


def handle_llm_error(window: 'MainWindow', errorMessage: str) -> None:
	"""Handles errors related to LLM configuration or API calls."""
	logger.error(f"LLM operation failed: {errorMessage}")
	window._resetTaskState()
	window._showError("LLM/Configuration Error", errorMessage)
	window._llmResponseArea.setPlainText(f"--- LLM Error ---\n{errorMessage}")
	window._appendLogMessage(f"LLM ERROR: {errorMessage}")


def handle_file_processing_error(window: 'MainWindow', errorMessage: str) -> None:
	"""Handles file processing errors, potentially triggering an LLM correction retry."""
	logger.error(f"File processing failed: {errorMessage}")
	# _isBusy should be False as worker emitted error signal

	is_parsing_error = "parsingerror:" in errorMessage.lower() # Make check case-insensitive
	can_retry = not window._correction_attempted and is_parsing_error

	if can_retry:
		logger.warning("Initial parsing failed. Attempting LLM self-correction.")
		window._correction_attempted = True # Mark that we are trying now
		window._updateStatusBar("Initial parsing failed. Requesting LLM correction...", 0)
		window._appendLogMessage(f"PARSE ERROR: {errorMessage}. Requesting LLM correction...")
		window._updateProgress(-1, "Requesting correction...")
		window._isBusy = True # Set busy again for the correction call
		window._updateWidgetStates()

		try:
			original_bad_response = window._llmResponseArea.toPlainText()
			original_instruction = window._promptInput.toPlainText()
			expected_format = window._configManager.getConfigValue('General', 'ExpectedOutputFormat', fallback='json') or 'json'
			model_name = window._configManager.getConfigValue('General', 'DefaultLlmModel', fallback='gemini-1.5-flash-latest') or 'gemini-1.5-flash-latest'

			if not original_bad_response: raise ValueError("Missing original LLM response for correction.")
			if not original_instruction: raise ValueError("Missing original user instruction for correction.")

			# Build the correction prompt using the LLM Interface instance
			if hasattr(window, '_llmInterfaceInstance'):
				correction_prompt = window._llmInterfaceInstance.build_correction_prompt(
					original_bad_output=original_bad_response,
					original_instruction=original_instruction,
					expected_format=expected_format
				)
				logger.debug(f"Built correction prompt (length: {len(correction_prompt)} chars).")
			else:
				raise AttributeError("LLM interface instance not found on main window.")


			# Trigger LLMWorker with correction task and lower temperature
			window._llmWorker.startCorrectionQuery(model_name, correction_prompt, CORRECTION_RETRY_TEMPERATURE)
			# Do not reset state here, wait for _onLlmFinished

		except (ConfigurationError, ValueError, LLMError, AttributeError, Exception) as e:
			logger.critical(f"Failed to initiate LLM correction query: {e}", exc_info=True)
			window._resetTaskState()
			window._showError("Correction Error", f"Could not initiate LLM correction attempt: {e}")
			window._appendLogMessage(f"CRITICAL: Failed to start correction query: {e}")
			window._correction_attempted = False # Allow trying again manually
	else:
		# Not a parsing error, or correction already attempted/failed
		error_title = "File Processing Error"
		error_message = errorMessage
		log_prefix = "FILE ERROR"
		if is_parsing_error:
			if window._correction_attempted:
				logger.error("LLM correction attempt also failed to produce parsable output.")
				log_prefix = "LLM CORRECTION FAILED"
				error_title = "LLM Correction Failed"
				error_message = f"The LLM failed to correct the output format.\nOriginal Parse Error:\n{errorMessage}"
			else:
				# Parsing error, but retry not possible (e.g., not configured, already tried)
				log_prefix = "PARSE ERROR (Final)"
				error_title = "Parsing Error"
				# error_message remains errorMessage

		window._appendLogMessage(f"{log_prefix}: {errorMessage}")
		window._resetTaskState() # Reset busy state
		window._showError(error_title, error_message)

		# Clear potentially invalid parsed data if error occurred during parsing phase
		if is_parsing_error:
			window._parsedFileData = None
			window._validationErrors = None
			# Refresh diff view
			diff_view.display_selected_file_diff(window, window._fileListWidget.currentItem())
			window._updateWidgetStates()