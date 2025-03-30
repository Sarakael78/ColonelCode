# Updated Codebase/gui/callback_handlers.py
# --- START: gui/callback_handlers.py ---
# gui/callback_handlers.py
"""
Module containing the slots that handle signals emitted by the worker threads
(GitHubWorker, LLMWorker, FileWorker). These update the MainWindow state
and UI based on the results of background operations.

Responsibilities include:
- Updating the file list and status after repository clone/load.
- Handling repository status checks (dirty/clean).
- Processing pull results, including conflict warnings.
- Managing commit/push completion status and state resets.
- Displaying LLM responses and triggering parsing.
- Processing file read results and initiating LLM queries.
- Handling parsing/validation outcomes, including path normalization and UI updates.
- Managing file saving completion and related state/UI updates.
- Displaying specific error messages from worker threads.
- Implementing LLM self-correction logic on parsing errors.
"""

import logging
import os
from typing import Optional, Dict, List, Tuple, TYPE_CHECKING, Set # Added Set

# Qt Imports
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QMessageBox
from PySide6.QtGui import QColor # Import QColor for styling list items
from PySide6.QtCore import Qt # Import Qt namespace for MatchFlag etc.

# Local Application Imports
from core.exceptions import ConfigurationError, LLMError # Custom exceptions
from . import diff_view # For triggering diff updates
from .diff_view import ACCEPTANCE_PENDING, ACCEPTANCE_ACCEPTED, ACCEPTANCE_REJECTED # Import state constants

# Type hint for MainWindow to avoid circular import issues at runtime
if TYPE_CHECKING:
	from .main_window import MainWindow # Import only for type hinting

# Logger for this module
logger: logging.Logger = logging.getLogger(__name__)

# --- Constants ---

# Temperature used when requesting LLM self-correction
CORRECTION_RETRY_TEMPERATURE: float = 0.4

# Colours used for styling items in the file list widget
COLOR_PROPOSED: QColor = QColor("#DAA520") # DarkGoldenrod (more visible yellow/orange)
COLOR_SAVED: QColor = QColor("green") # Green for successfully saved files
COLOR_DEFAULT: QColor = QListWidgetItem().foreground().color() # Use default theme text colour
COLOR_VALIDATION_ERROR: QColor = QColor("red") # Red for files with validation errors
COLOR_NEW_FILE: QColor = QColor("blue") # Blue for files identified as new by the LLM

# Prefix often spuriously added by LLM to file paths
KNOWN_SPURIOUS_PREFIX: str = "path/to/"


# --- Helper Functions ---

def _find_list_widget_item(list_widget: QListWidget, text: str) -> Optional[QListWidgetItem]:
	"""
	Searches a QListWidget for an item with the exact specified text.

	Args:
		list_widget (QListWidget): The list widget to search within.
		text (str): The exact text of the item to find.

	Returns:
		Optional[QListWidgetItem]: The found list item, or None if no item matches.
	"""
	# Use Qt.MatchFlag.MatchExactly for precise matching
	items: List[QListWidgetItem] = list_widget.findItems(text, Qt.MatchFlag.MatchExactly)
	# Return the first match if found, otherwise None
	return items[0] if items else None


# --- GitHub Worker Callback Handlers ---

def on_clone_load_finished(window: 'MainWindow', repoPath: str, fileList: List[str]) -> None:
	"""
	Handles the completion of the repository clone or load operation.

	- Updates the main window's repository path.
	- Resets relevant application state (parsed data, errors, acceptance state).
	- Saves the loaded path to configuration.
	- Parses the `.codebaseignore` file (if present) to determine default file selection.
	- Populates the file list widget, applying ignore rules and resetting item colours.
	- Triggers an asynchronous check for the repository's dirty status.

	Args:
		window (MainWindow): The main application window instance.
		repoPath (str): The absolute path to the successfully cloned or loaded repository.
		fileList (List[str]): A list of relative file paths tracked by Git in the repository.
	"""
	logger.info(f"Clone/Load finished successfully. Path: {repoPath}, Files Found: {len(fileList)}")
	window._isBusy = False # Mark the clone/load task as complete
	window._clonedRepoPath = repoPath # Store the path

	# Reset state related to previous repository, LLM interaction, and acceptance
	window._parsedFileData = None
	window._validationErrors = None
	window._originalFileContents.clear() # Clear cached original content
	window._llmResponseArea.clear()
	window._originalCodeArea.clear() # Clear diff views
	window._proposedCodeArea.clear()
	window._promptInput.clear() # Clear previous prompt
	window._acceptedChangesState.clear() # Reset acceptance decisions
	window._current_chunk_id_list = [] # Clear chunk metadata
	window._current_chunk_start_block_map = {}
	window._last_clicked_chunk_id = None

	# Save the loaded path for next session
	window._saveLastRepoPath(repoPath)
	window._updateStatusBar(f"Repository loaded ({len(fileList)} files). Applying ignore rules...", 5000)

	# --- .codebaseignore Handling ---
	# Attempts to load ignore rules using gitignore_parser library
	codebase_ignore_filename: str = '.codebaseignore'
	codebase_ignore_path: str = os.path.join(repoPath, codebase_ignore_filename)
	matches: Optional[callable] = None # Function returned by parser (or None)

	try:
		if os.path.exists(codebase_ignore_path) and os.path.isfile(codebase_ignore_path):
			parser_used: Optional[str] = None
			# Try using gitignore_parser module's parse function first
			try:
				import gitignore_parser
				if hasattr(gitignore_parser, 'parse') and callable(gitignore_parser.parse):
					with open(codebase_ignore_path, 'r', encoding='utf-8', errors='ignore') as f:
						matches = gitignore_parser.parse(f)
					if callable(matches): parser_used = "gitignore_parser.parse()"
					else: matches = None # Reset if parse didn't return callable
			except ImportError:
				logger.debug("'gitignore_parser' import failed, will try function import.")
				matches = None # Ensure matches is None if import fails
			except Exception as e_parse:
				logger.error(f"Error using 'gitignore_parser.parse()' for {codebase_ignore_filename}: {e_parse}", exc_info=True)
				matches = None

			# If module parse failed, try direct function import (alternative structure)
			if matches is None:
				try:
					# Attempt direct import of function if module structure allows
					from gitignore_parser import parse_gitignore
					matches = parse_gitignore(codebase_ignore_path)
					if callable(matches): parser_used = "parse_gitignore()"
					else: matches = None # Reset if function didn't return callable
				except ImportError:
					logger.warning(f"Could not find 'gitignore_parser' library or 'parse_gitignore' function.")
				except Exception as e_func:
					logger.error(f"Error using 'parse_gitignore()' function for {codebase_ignore_filename}: {e_func}", exc_info=True)
					matches = None

			# Log success or failure
			if parser_used:
				logger.info(f"Loaded ignore rules from {codebase_ignore_filename} using {parser_used}")
			elif matches is None and os.path.exists(codebase_ignore_path): # File exists but parsing failed
				logger.error(f"Failed to load or parse {codebase_ignore_filename} using available methods.")
				window._appendLogMessage(f"ERROR: Could not parse {codebase_ignore_filename}. Check library/file.")
		else:
			logger.info(f"'{codebase_ignore_filename}' not found in repository root. All files included by default.")
	except Exception as e_top:
		# Catch unexpected errors during ignore file handling
		logger.error(f"Unexpected error during {codebase_ignore_filename} handling: {e_top}", exc_info=True)
		window._appendLogMessage(f"ERROR: Unexpected error handling {codebase_ignore_filename}: {e_top}")
		matches = None # Ensure matches is None on error
	# --- End .codebaseignore Handling ---

	# --- Populate File List Widget ---
	# Clear existing items and add the new list, sorted alphabetically
	window._fileListWidget.clear()
	window._fileListWidget.addItems(sorted(fileList))

	# Apply ignore rules to set initial selection and reset item colours
	selected_files_init: List[str] = []
	ignored_count: int = 0
	total_count: int = window._fileListWidget.count()

	window._fileListWidget.blockSignals(True) # Prevent signals during batch update
	abs_repo_path: str = os.path.abspath(repoPath) # Get absolute path once for efficiency
	for i in range(total_count):
		item: Optional[QListWidgetItem] = window._fileListWidget.item(i)
		if not item: continue # Safety check

		file_path_relative: str = item.text()
		# Construct absolute path for matching against ignore rules
		file_path_absolute: str = os.path.join(abs_repo_path, file_path_relative)

		should_select: bool = True # Select by default
		# If ignore rules were loaded successfully, check if the file matches
		if matches and callable(matches):
			try:
				if matches(file_path_absolute):
					should_select = False # Don't select if ignored
					ignored_count += 1
			except Exception as e_match:
				# Log errors during matching but continue
				logger.warning(f"Error matching file '{file_path_relative}' against ignore rules: {e_match}")

		# Set the item's selected state and reset text colour
		item.setSelected(should_select)
		item.setForeground(COLOR_DEFAULT) # Reset colour to default on load
		if should_select:
			selected_files_init.append(file_path_relative) # Add to internal list if selected

	window._fileListWidget.blockSignals(False) # Re-enable signals
	# --- End File List Population ---

	# Update internal state and status bar
	window._selectedFiles = sorted(selected_files_init) # Store the initially selected files
	logger.info(f"Initial file selection complete. Ignored {ignored_count}/{total_count} files based on rules. Selected: {len(window._selectedFiles)} files.")
	window._updateStatusBar(f"Repository loaded. Initial selection: {len(window._selectedFiles)}/{total_count} files. Checking status...", 5000)

	# Automatically trigger a check for uncommitted changes after successful load
	if not window._isBusy and window._clonedRepoPath:
		logger.debug("Triggering repository status check after load.")
		window._isBusy = True # Set busy for the status check task
		window._updateWidgetStates() # Update UI to reflect busy state
		window._updateProgress(-1, "Checking repository status...") # Show indeterminate progress
		window._githubWorker.startIsDirty(window._clonedRepoPath) # Call worker
	else:
		# If busy or repo path invalid (shouldn't happen here), just update states
		logger.warning("Cannot start dirty check: Application busy or repository path invalid immediately after load.")
		window._updateWidgetStates() # Ensure UI reflects current state


def on_is_dirty_finished(window: 'MainWindow', is_dirty: bool) -> None:
	"""
	Handles the completion of the repository dirty status check.

	Args:
		window (MainWindow): The main application window instance.
		is_dirty (bool): True if uncommitted changes were detected, False otherwise.
	"""
	if not window._clonedRepoPath: return # Avoid updates if repo unloaded

	logger.info(f"Repository dirty status check completed: {'Dirty' if is_dirty else 'Clean'}")
	window._repoIsDirty = is_dirty # Update internal state flag
	window._isBusy = False # Finished the status check task
	status_msg: str = "Repository status: Dirty (Uncommitted changes exist)" if is_dirty else "Repository status: Clean"
	window._updateStatusBar(status_msg, 5000) # Show status briefly
	window._updateProgress(100, "Status check complete.") # Mark progress complete (hides bar)
	window._updateWidgetStates() # Update button enables based on new dirty state


def on_pull_finished(window: 'MainWindow', message: str, had_conflicts: bool) -> None:
	"""
	Handles the completion of a git pull operation.

	Args:
		window (MainWindow): The main application window instance.
		message (str): Status message from the Git pull operation.
		had_conflicts (bool): True if the handler detected likely merge conflicts post-pull.
	"""
	if not window._clonedRepoPath: return # Ignore if repo unloaded

	logger.info(f"Pull operation finished: {message}, Conflicts Detected: {had_conflicts}")
	window._isBusy = False # Pull task done
	window._updateStatusBar(f"Pull finished. {message}", 10000) # Show result longer
	window._updateProgress(100, "Pull complete.")

	if had_conflicts:
		# Show warning if conflicts were detected
		window._showWarning("Pull Conflicts",
							 f"Pull completed, but merge conflicts likely occurred.\n"
							 f"Details: {message}\n"
							 f"Please resolve conflicts manually using standard Git tools.")
		window._repoIsDirty = True # Conflicts always make the repo dirty
		window._updateWidgetStates() # Update UI (e.g., disable further pulls)
	else:
		# Show info message on successful pull without obvious conflicts
		window._showInfo("Pull Finished", message)
		# Re-check dirty status after a successful pull, as merges might still change state
		if window._clonedRepoPath and not window._isBusy:
			logger.debug("Re-checking repository status after pull.")
			window._isBusy = True
			window._updateWidgetStates()
			window._updateStatusBar("Checking repository status after pull...", 5000)
			window._updateProgress(-1, "Checking status...")
			window._githubWorker.startIsDirty(window._clonedRepoPath)
		elif window._clonedRepoPath:
			# If cannot re-check, assume clean (less safe but avoids blocking)
			logger.warning("Could not automatically re-check dirty status after pull (app busy?). Assuming clean.")
			window._repoIsDirty = False
			window._updateWidgetStates()


def on_commit_push_finished(window: 'MainWindow', message: str) -> None:
	"""
	Handles the completion of a commit and push operation.

	- Resets state related to the changes just pushed (parsed data, errors, acceptance).
	- Resets file list colours to default.
	- Updates status bar and shows confirmation message.
	- Refreshes the diff view and updates widget states.

	Args:
		window (MainWindow): The main application window instance.
		message (str): Success message from the commit/push operation.
	"""
	if not window._clonedRepoPath: return # Ignore if repo unloaded

	logger.info(f"Commit/Push operation finished successfully: {message}")
	window._isBusy = False # Task done
	window._updateStatusBar("Commit and push successful.", 5000)
	window._updateProgress(100, "Commit/Push complete.")
	window._showInfo("Commit/Push Successful", message)
	window._repoIsDirty = False # Assume clean after successful push

	# Clear state related to the set of changes just pushed
	window._parsedFileData = None
	window._validationErrors = None
	window._llmResponseArea.clear() # Clear potentially outdated response
	window._promptInput.clear() # Clear prompt that led to these changes
	window._acceptedChangesState.clear() # Reset all acceptance decisions
	window._current_chunk_id_list = [] # Clear chunk metadata
	window._current_chunk_start_block_map = {}
	window._last_clicked_chunk_id = None

	# Reset file list colours back to default
	window._fileListWidget.blockSignals(True)
	for i in range(window._fileListWidget.count()):
		item = window._fileListWidget.item(i)
		if item: item.setForeground(COLOR_DEFAULT)
	window._fileListWidget.blockSignals(False)

	# Refresh diff view to show clean state and update button enables
	diff_view.display_selected_file_diff(window, window._fileListWidget.currentItem())
	window._updateWidgetStates()


def on_list_files_finished(window: 'MainWindow', fileList: List[str]) -> None:
	""" Placeholder: Handles completion of listing files if used as a separate async action. """
	# Currently, file listing is mainly done synchronously or as part of clone/load.
	logger.debug(f"List files finished callback triggered (async). Found {len(fileList)} files.")
	# Potentially update UI or state if listFiles needs to be async in the future
	window._resetTaskState() # Example: Reset busy state if this was a distinct task


def on_read_file_finished(window: 'MainWindow', content: str) -> None:
	""" Placeholder: Handles completion of reading a single file if used as a separate async action. """
	# Currently, file reading is mainly done synchronously or within on_file_contents_read.
	logger.debug(f"Read file finished callback triggered (async). Content length: {len(content)}")
	# Potentially update UI (e.g., display content) or state
	window._resetTaskState() # Example: Reset busy state


# --- LLM Worker Callback Handlers ---

def on_llm_finished(window: 'MainWindow', response: str) -> None:
	"""
	Handles the successful response received from the LLM query worker.

	- Displays the raw response in the 'LLM Response' tab.
	- Resets parsing/validation state and acceptance state for the new response.
	- Resets file list colours.
	- Refreshes the diff view.
	- If this was a correction attempt, automatically triggers parsing.
	- Otherwise, updates the status bar prompting the user to parse.

	Args:
		window (MainWindow): The main application window instance.
		response (str): The raw text response from the LLM.
	"""
	logger.info(f"LLM query finished. Response length: {len(response)}")

	# Check for required MainWindow attributes
	req_attrs: List[str] = [
		'_isBusy', '_updateProgress', '_llmResponseArea', '_bottomTabWidget',
		'_parsedFileData', '_validationErrors', '_correction_attempted',
		'_updateStatusBar', '_updateWidgetStates', '_fileListWidget', '_acceptedChangesState'
	]
	if not all(hasattr(window, attr) for attr in req_attrs):
		logger.error("MainWindow object missing required attributes in on_llm_finished.")
		# Avoid proceeding if critical attributes are missing
		return

	window._isBusy = False # LLM task done
	window._updateProgress(100, "LLM query complete.")
	window._llmResponseArea.setPlainText(response) # Display the raw response

	# Automatically switch focus to the LLM Response tab
	llm_tab_index: int = -1
	for i in range(window._bottomTabWidget.count()):
		if window._bottomTabWidget.tabText(i) == "LLM Response":
			llm_tab_index = i
			break
	if llm_tab_index != -1:
		window._bottomTabWidget.setCurrentIndex(llm_tab_index)
	else:
		# Log if tab not found, but don't stop execution
		logger.warning("Could not find 'LLM Response' tab to switch to automatically.")

	# Reset state associated with previous LLM response / parsing / acceptance
	window._parsedFileData = None
	window._validationErrors = None
	window._acceptedChangesState.clear() # Clear previous acceptance decisions
	window._current_chunk_id_list = [] # Clear chunk metadata
	window._current_chunk_start_block_map = {}
	window._last_clicked_chunk_id = None

	# Reset file list colours back to default
	window._fileListWidget.blockSignals(True)
	for i in range(window._fileListWidget.count()):
		item = window._fileListWidget.item(i)
		if item: item.setForeground(COLOR_DEFAULT)
	window._fileListWidget.blockSignals(False)

	# Refresh diff view (will show original vs placeholder proposed until parsed)
	diff_view.display_selected_file_diff(window, window._fileListWidget.currentItem())

	# Check if this response was from a correction attempt
	if window._correction_attempted:
		# If yes, automatically trigger parsing of this hopefully corrected response
		window._updateStatusBar("LLM correction received. Parsing corrected response...", 10000)
		# Need event_handlers module for this call
		from . import event_handlers # Lazy import okay here
		event_handlers.handle_parse_and_validate(window)
	else:
		# If it was a normal response, prompt user to parse
		window._updateStatusBar("LLM query successful. Click 'Parse & Validate' to process the response.", 5000)
		window._updateWidgetStates() # Update button states (e.g., enable Parse button)


# --- File Worker Callback Handlers ---

def on_file_contents_read(window: "MainWindow", fileContents: Dict[str, str], userInstruction: str) -> None:
	"""
	Handles completion of reading selected file contents.

	- Caches the original file contents read.
	- Resets acceptance state as a new LLM cycle is starting.
	- Updates the diff view (showing original content).
	- Builds the full prompt using the instruction and file contents.
	- Triggers the LLM worker to query the API with the built prompt.

	Args:
		window (MainWindow): The main application window instance.
		fileContents (Dict[str, str]): Dictionary mapping relative file paths to their content.
		userInstruction (str): The instruction provided by the user.
	"""
	if not window._isBusy: return # Ignore if task was cancelled or app no longer busy

	logger.info(f"File reading finished ({len(fileContents)} files read). Proceeding to query LLM...")
	window._originalFileContents = fileContents # Store/cache the content just read

	# Reset acceptance state when starting a new LLM query cycle based on new context/instruction
	window._acceptedChangesState.clear()
	window._current_chunk_id_list = []
	window._current_chunk_start_block_map = {}
	window._last_clicked_chunk_id = None

	# Update diff view for the currently focused file now that its original content is cached
	diff_view.display_selected_file_diff(window, window._fileListWidget.currentItem())

	# Get LLM model name from configuration
	try:
		modelName: str = window._configManager.getConfigValue('General', 'DefaultLlmModel', fallback='gemini-1.5-flash-latest') or 'gemini-1.5-flash-latest'
	except ConfigurationError as e:
		window._showError("Configuration Error", f"Could not read LLM model name from configuration: {e}")
		window._resetTaskState() # Reset busy state
		return

	# Build the full prompt using the LLMInterface helper
	try:
		# Ensure the LLM interface instance exists on the window object
		if hasattr(window, '_llmInterfaceInstance'):
			prompt: str = window._llmInterfaceInstance.buildPrompt(userInstruction, fileContents)
			logger.debug(f"Built prompt for LLM (length: {len(prompt)} chars).")
		else:
			# This indicates an initialisation problem
			raise AttributeError("LLM interface instance not found on main window object.")
	except Exception as e:
		# Catch errors during prompt building (e.g., config issues, unexpected errors)
		window._showError("Prompt Building Error", f"Failed to build the prompt for the LLM: {e}")
		window._resetTaskState() # Reset busy state
		return

	# Send the built prompt to the LLM worker thread
	window._updateStatusBar("Sending request to LLM...")
	window._updateProgress(-1, "Sending request to LLM...") # Indeterminate progress
	window._llmWorker.startQuery(modelName, prompt)


def on_parsing_finished(window: 'MainWindow', parsedData: Dict[str, str], validationResults: Dict[str, List[str]]) -> None:
	"""
	Handles the results received from the FileWorker after parsing and validation.

	- Performs path normalization to strip known spurious prefixes (e.g., "path/to/").
	- Updates the main window's state with the normalized parsed data and validation errors.
	- Ensures original content is cached for all files mentioned in the normalized parsed data.
	- Logs validation results and updates the status bar.
	- Adds any genuinely new files (found in parsed data but not previously in the repo list)
	  to the file list widget.
	- Updates the colours of items in the file list widget based on whether they are new,
	  changed+valid, changed+invalid, or unchanged.
	- Initializes the acceptance state dictionary for any newly relevant files.
	- Refreshes the diff view for the currently selected file.
	- Updates widget enabled states.

	Args:
		window (MainWindow): The main application window instance.
		parsedData (Dict[str, str]): Raw dictionary parsed from LLM response (potentially incorrect paths).
		validationResults (Dict[str, List[str]]): Dictionary mapping raw file paths to lists of validation errors.
	"""
	# Check if repository is still loaded
	if not window._clonedRepoPath:
		logger.warning("on_parsing_finished called but no repository path is set. Aborting update.")
		window._resetTaskState() # Reset state if repo unloaded during parse
		return

	logger.info(f"Raw parsing results received. Parsed items: {len(parsedData)}. Validation Errors: {len(validationResults)}")

	# --- Path Normalization Step ---
	# Create new dictionaries to store normalized results
	normalizedParsedData: Dict[str, str] = {}
	normalizedValidationResults: Dict[str, List[str]] = {}
	# Get the set of known relative paths currently in the file list widget
	known_repo_files: Set[str] = set(window._fileListWidget.item(i).text() for i in range(window._fileListWidget.count()))
	prefix_to_strip: str = KNOWN_SPURIOUS_PREFIX
	prefix_len: int = len(prefix_to_strip)

	# Iterate through the raw parsed data from the LLM
	for llm_path, content in parsedData.items():
		normalized_path: str = llm_path # Default to the original path

		# Check if the path starts with the known problematic prefix
		if llm_path.startswith(prefix_to_strip):
			# Try stripping the prefix
			potential_correct_path: str = llm_path[prefix_len:]
			# Check if the stripped path matches a file known to be in the repository
			if potential_correct_path in known_repo_files:
				# If it matches, use the stripped path as the normalized path
				logger.warning(f"Normalizing LLM path: Stripped '{prefix_to_strip}' from '{llm_path}' -> '{potential_correct_path}' as it matches a known file.")
				normalized_path = potential_correct_path
			else:
				# If stripping doesn't match a known file, assume the prefix might be intentional
				# (e.g., LLM genuinely creating a new 'path/to/' directory). Keep original path.
				logger.warning(f"LLM path '{llm_path}' starts with '{prefix_to_strip}' but stripped path '{potential_correct_path}' not found in repo file list. Keeping original LLM path.")
				normalized_path = llm_path # Keep the path as provided by LLM

		# Store the content using the (potentially) normalized path key
		normalizedParsedData[normalized_path] = content
		# If there were validation errors for the original path, associate them with the normalized path
		if llm_path in validationResults:
			normalizedValidationResults[normalized_path] = validationResults[llm_path]

	# Update MainWindow state with the processed, normalized data
	window._parsedFileData = normalizedParsedData
	window._validationErrors = normalizedValidationResults if normalizedValidationResults else None # Use None if empty
	logger.info(f"Path normalization complete. Final items to process: {len(window._parsedFileData)}. Final Validation Errors: {len(window._validationErrors or {})}")
	# --- End Path Normalization ---


	window._isBusy = False # Mark parsing task as complete

	# --- Ensure Original Content is Loaded (Post-Normalization) ---
	# Guarantees original content is available for diffing against normalized paths
	if window._clonedRepoPath and window._parsedFileData:
		# Import constant locally if needed, or ensure it's accessible
		from .diff_view import MAX_DIFF_FILE_SIZE
		logger.debug("Ensuring original content is cached for all (normalized) parsed file paths...")
		for file_path in window._parsedFileData.keys(): # Iterate over normalized keys
			# Check cache using sentinel value
			if window._originalFileContents.get(file_path, "__NOT_CHECKED__") == "__NOT_CHECKED__":
				full_path = os.path.join(window._clonedRepoPath, file_path)
				if os.path.exists(full_path) and os.path.isfile(full_path):
					try:
						# Load content, handling potential size limits or read errors
						if os.path.getsize(full_path) > MAX_DIFF_FILE_SIZE:
							window._originalFileContents[file_path] = f"<File too large (>{MAX_DIFF_FILE_SIZE // 1024} KB)>"
							logger.warning(f"Original file '{file_path}' too large for diff cache.")
						else:
							with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
								window._originalFileContents[file_path] = f.read()
							logger.debug(f"Cached original content for '{file_path}' post-parse.")
					except Exception as e:
						# Cache error message if reading fails
						window._originalFileContents[file_path] = f"<Error reading file: {e}>"
						logger.error(f"Error reading original file '{file_path}' post-parse: {e}", exc_info=True)
				else:
					# Mark as None if file doesn't exist (it's genuinely new according to LLM)
					window._originalFileContents[file_path] = None
					logger.debug(f"Original file '{file_path}' confirmed non-existent post-parse (new file).")
	# --- End Original Content Load ---

	# --- Log Validation Results and Update Status Bar ---
	status_msg: str = ""
	if window._validationErrors:
		# Format and log detailed validation errors
		log_message: List[str] = ["--- Validation Failed ---"]
		error_files: Set[str] = set() # Use set for unique filenames in summary
		for file_path, errors in window._validationErrors.items(): # Iterate normalized results
			error_files.add(os.path.basename(file_path)) # Add base name for summary
			log_message.append(f"  File: {file_path}") # Log normalized path
			for error in errors:
				log_message.append(f"    * {error}")
		log_message.append("-------------------------")
		window._appendLogMessage("\n".join(log_message)) # Send to GUI log

		# Prepare summary message for dialog and status bar
		error_summary: str = (f"Validation failed for {len(window._validationErrors)} file(s).\n"
							  f"Check Application Log tab for details.\n\n"
							  f"Files with errors:\n - {chr(10)} - ".join(sorted(list(error_files)))) # Use newline char
		window._showWarning("Code Validation Failed", error_summary) # Show dialog
		status_msg = f"Parsed. Validation FAILED ({len(window._validationErrors)} file(s))."
	else:
		# Report validation success
		file_count_msg: str = f"{len(window._parsedFileData)} file(s)" if window._parsedFileData else "No changes"
		status_msg = f"Parsed: {file_count_msg} found. Validation OK."
		window._appendLogMessage("--- Validation OK ---")
		# Reset correction flag only on successful validation
		window._correction_attempted = False

	# Update status bar and progress
	window._updateStatusBar(status_msg, 10000)
	window._updateProgress(100, "Parse & Validate complete.")

	# --- Update File List Widget (Add New Files, Set Colours) ---
	# Get current set of files displayed
	current_files_in_widget: Set[str] = set(window._fileListWidget.item(i).text() for i in range(window._fileListWidget.count()))
	new_files_added: bool = False # Flag if any items were added

	window._fileListWidget.blockSignals(True) # Prevent signals during batch update

	# Add items for files present in the (normalized) parsed data but not yet in the list widget
	if window._parsedFileData:
		for filePath in sorted(window._parsedFileData.keys()): # Use normalized keys
			if filePath not in current_files_in_widget:
				newItem = QListWidgetItem(filePath)
				# Colour will be set in the next loop
				window._fileListWidget.addItem(newItem)
				new_files_added = True
				logger.info(f"Added file to list based on LLM response: '{filePath}'")

	# Now iterate through *all* items currently in the widget to set their colours
	for i in range(window._fileListWidget.count()):
		item: Optional[QListWidgetItem] = window._fileListWidget.item(i)
		if not item: continue
		file_path: str = item.text() # Path is potentially normalized now
		item_color: QColor = COLOR_DEFAULT # Default colour

		# Determine if the file is considered new based on LLM output AND absence of original content
		# Use the potentially normalized file_path to check caches and results
		is_newly_added_by_llm: bool = (
			window._parsedFileData is not None and
			file_path in window._parsedFileData and
			window._originalFileContents.get(file_path) is None # Check original cache status
		)

		if is_newly_added_by_llm:
			# Mark file as new (Blue)
			item_color = COLOR_NEW_FILE
			# Initialize acceptance state for this new file if it doesn't exist
			if file_path not in window._acceptedChangesState:
				window._acceptedChangesState[file_path] = {}
		elif window._parsedFileData and file_path in window._parsedFileData:
			# File exists (or was thought to exist) and LLM proposed changes for it
			original_content = window._originalFileContents.get(file_path)
			proposed_content = window._parsedFileData[file_path] # Should exist if check passed

			# Check if original content was unreadable or if content differs
			is_unreadable: bool = isinstance(original_content, str) and original_content.startswith("<")
			is_different: bool = original_content != proposed_content

			if is_unreadable or is_different:
				# There are proposed changes or original was unreadable
				if window._validationErrors and file_path in window._validationErrors:
					# Mark as having validation errors (Red)
					item_color = COLOR_VALIDATION_ERROR
				else:
					# Mark as having proposed, valid changes (Yellow/Orange)
					item_color = COLOR_PROPOSED
				# Initialize acceptance state if needed
				if file_path not in window._acceptedChangesState:
					window._acceptedChangesState[file_path] = {}
			# else: File content is identical, colour remains COLOR_DEFAULT
		# else: File exists but wasn't mentioned in LLM output, colour remains COLOR_DEFAULT

		# Apply the determined colour
		item.setForeground(item_color)

	# Re-sort the list if new files were added
	if new_files_added:
		window._fileListWidget.sortItems()

	window._fileListWidget.blockSignals(False) # Re-enable signals
	# --- End File List Update ---

	# Refresh the diff display for the currently focused item
	# This will now use the potentially normalized file path and updated state
	diff_view.display_selected_file_diff(window, window._fileListWidget.currentItem())
	window._updateWidgetStates() # Update button states based on parse/validation outcome


def on_saving_finished(window: 'MainWindow', savedFilesRelativePaths: List[str]) -> None:
	"""
	Handles the completion of saving file(s) to disk.

	- Updates status bar and progress.
	- Updates the original content cache for saved files.
	- Sets the colour of saved file items in the list to green.
	- Marks the repository as dirty.
	- Clears parsed data, validation errors, and acceptance state appropriately,
	  distinguishing between "Save All" and "Save Accepted" operations.
	- Refreshes the diff view and updates widget states.

	Args:
		window (MainWindow): The main application window instance.
		savedFilesRelativePaths (List[str]): List of relative paths that were successfully saved.
	"""
	if not window._clonedRepoPath: return # Ignore if repo unloaded

	logger.info(f"Saving operation finished. Successfully saved files: {savedFilesRelativePaths}")
	window._isBusy = False # Saving task done
	num_saved: int = len(savedFilesRelativePaths)
	status_msg: str = f"Changes saved locally ({num_saved} file{'s' if num_saved != 1 else ''})."
	window._updateStatusBar(status_msg, 5000)
	window._updateProgress(100, "Saving complete.")

	if savedFilesRelativePaths:
		# Check if this save likely resulted from "Save All" (parsed data would still exist before clearing)
		# or "Save Accepted" (parsed data might be None if cleared previously, or only 1 file saved).
		# A simple heuristic: if _parsedFileData still exists, assume it was Save All context.
		was_save_all_operation: bool = window._parsedFileData is not None

		# --- Update Original Content Cache ---
		# When saving, the saved content becomes the new 'original' for subsequent diffs
		if was_save_all_operation:
			# If saving all, the content came directly from _parsedFileData
			for rel_path in savedFilesRelativePaths:
				if rel_path in window._parsedFileData: # Should always be true here
					window._originalFileContents[rel_path] = window._parsedFileData[rel_path]
		elif num_saved == 1:
			# If saving accepted for one file, content was generated manually. Re-read file to update cache.
			saved_rel_path: str = savedFilesRelativePaths[0]
			full_saved_path: str = os.path.join(window._clonedRepoPath, saved_rel_path)
			try:
				# Read the content that was just written to disk
				with open(full_saved_path, 'r', encoding='utf-8') as f:
					saved_content: str = f.read()
				window._originalFileContents[saved_rel_path] = saved_content
				logger.debug(f"Updated original content cache by re-reading '{saved_rel_path}' after Save Accepted.")
			except Exception as e:
				# Log error but continue - cache might be stale, but not critical failure
				logger.error(f"Failed to re-read saved file '{saved_rel_path}' to update cache: {e}")
		# --- End Cache Update ---

		# --- Update File List Colours ---
		window._fileListWidget.blockSignals(True)
		for saved_rel_path in savedFilesRelativePaths:
			item: Optional[QListWidgetItem] = _find_list_widget_item(window._fileListWidget, saved_rel_path)
			if item:
				item.setForeground(COLOR_SAVED) # Set colour to green
			else:
				# This might happen if file was new and added/saved in one go? Check list logic.
				logger.warning(f"Could not find list widget item for recently saved file: {saved_rel_path}")
		window._fileListWidget.blockSignals(False)
		# --- End Colour Update ---

		# --- State Cleanup ---
		window._repoIsDirty = True # Saving always makes the repo dirty until committed

		if was_save_all_operation:
			# If "Save All" was clicked, clear parsed data, errors, and ALL acceptance states
			# as this concludes the processing of the entire LLM response batch.
			logger.info("Clearing parsed data, validation errors, and all acceptance states after 'Save All'.")
			window._parsedFileData = None
			window._validationErrors = None
			window._acceptedChangesState.clear()
			window._current_chunk_id_list = []
			window._current_chunk_start_block_map = {}
			window._last_clicked_chunk_id = None
			window._showInfo("Save Successful", f"{num_saved} file(s) saved/updated in\n'{window._clonedRepoPath}'.")
		elif num_saved == 1 :
			# If "Save Accepted" was clicked (heuristic: num_saved=1), clear acceptance state
			# ONLY for the file just saved. Other files might still have pending/accepted changes.
			saved_file: str = savedFilesRelativePaths[0]
			if saved_file in window._acceptedChangesState:
				del window._acceptedChangesState[saved_file]
				logger.info(f"Cleared acceptance state for individually saved file: {saved_file}")
			# Also clear parsed data/errors - assumes saving one file completes the 'intent' for that LLM run.
			# User needs to re-run LLM/parse for other files if needed.
			window._parsedFileData = None
			window._validationErrors = None
			# Don't clear _last_clicked_chunk_id here, diff refresh will handle it if needed
			window._showInfo("Save Accepted Successful", f"Accepted changes saved for:\n'{saved_file}'")
		else:
			# Handle unexpected cases (e.g., num_saved > 1 but was_save_all_operation was false?)
			logger.warning(f"Unexpected state in on_saving_finished: num_saved={num_saved}, was_save_all_operation={was_save_all_operation}. Clearing all state as precaution.")
			window._parsedFileData = None
			window._validationErrors = None
			window._acceptedChangesState.clear()
			window._current_chunk_id_list = []
			window._current_chunk_start_block_map = {}
			window._last_clicked_chunk_id = None
			window._showInfo("Save Operation Complete", f"{num_saved} file(s) were saved/updated.")

		# Refresh diff view after saving
		diff_view.display_selected_file_diff(window, window._fileListWidget.currentItem())
	else:
		# No files were listed as saved (might happen if input dict was empty)
		logger.info("Saving finished, but no files were reported as saved.")
		# Don't clear state if nothing was actually saved

	# Update button states (e.g., Commit button should now be enabled if repo is dirty)
	window._updateWidgetStates()


# --- Error Handling Callbacks ---

def handle_worker_error(window: 'MainWindow', errorMessage: str, worker_name: str) -> None:
	""" Handles generic, unexpected errors reported by worker threads. """
	logger.critical(f"Unexpected error signal received from {worker_name}: {errorMessage}", exc_info=True)
	window._resetTaskState() # Reset busy state
	# Display a generic critical error message
	window._showError("Unexpected Background Task Error",
					  f"A critical internal error occurred in the {worker_name}:\n{errorMessage}\n\n"
					  f"Please check the Application Log tab for more details.")
	# Log the error prominently in the GUI log
	window._appendLogMessage(f"CRITICAL ERROR ({worker_name}): {errorMessage}")


def handle_github_error(window: 'MainWindow', errorMessage: str) -> None:
	""" Handles specific errors related to Git or GitHub operations. """
	logger.error(f"GitHub operation failed: {errorMessage}")
	# Check if the error likely occurred during the initial clone/load phase
	is_load_error: bool = any(s in errorMessage.lower() for s in [
		"clone", "load", "not found", "authentication failed",
		"valid git repo", "invalid repository", "not a git repo"
	])

	window._resetTaskState() # Always reset busy state on error
	window._showError("Git/GitHub Operation Error", errorMessage) # Show user the error
	window._appendLogMessage(f"GIT ERROR: {errorMessage}") # Log error

	# If it was a load/clone error, reset the entire repository state in the UI
	if is_load_error:
		logger.info("Resetting repository-related UI state due to load/clone error.")
		window._clonedRepoPath = None
		window._fileListWidget.clear()
		window._repoIsDirty = False
		window._originalFileContents.clear()
		window._parsedFileData = None
		window._validationErrors = None
		window._acceptedChangesState.clear() # Reset acceptance
		window._current_chunk_id_list = [] # Reset chunk metadata
		window._current_chunk_start_block_map = {}
		window._last_clicked_chunk_id = None
		window._originalCodeArea.clear() # Clear diff views
		window._proposedCodeArea.clear()
		window._llmResponseArea.clear() # Clear related areas
		window._promptInput.clear()
		window._selectedFiles = [] # Clear file selection
		window._updateWidgetStates() # Update UI to reflect no repo loaded


def handle_llm_error(window: 'MainWindow', errorMessage: str) -> None:
	""" Handles errors related to LLM configuration or API calls. """
	logger.error(f"LLM operation failed: {errorMessage}")
	window._resetTaskState() # Reset busy state
	# Display specific LLM/Config error title
	window._showError("LLM / Configuration Error", errorMessage)
	# Show error message also in the LLM response area for context
	window._llmResponseArea.setPlainText(f"--- LLM Interaction Error ---\n{errorMessage}")
	window._appendLogMessage(f"LLM ERROR: {errorMessage}")
	# Do not clear acceptance state here, user might fix config and re-parse


def handle_file_processing_error(window: 'MainWindow', errorMessage: str) -> None:
	"""
	Handles errors during file processing (parsing, validation, saving).
	Includes logic to potentially trigger an LLM self-correction attempt on parsing errors.
	"""
	logger.error(f"File processing operation failed: {errorMessage}")

	# Check if the error is specifically a ParsingError
	# Use lower case check for robustness
	is_parsing_error: bool = "parsingerror:" in errorMessage.lower()

	# Determine if a correction retry is possible and appropriate
	can_retry: bool = (
		is_parsing_error and # Must be a parsing error
		not window._correction_attempted # And correction hasn't been tried yet for this response
	)

	if can_retry:
		# --- Attempt LLM Self-Correction ---
		logger.warning("Initial parsing failed due to format error. Attempting LLM self-correction.")
		window._correction_attempted = True # Mark that we are now trying correction
		window._updateStatusBar("Initial parsing failed. Requesting LLM correction...", 0) # Update status (permanent)
		window._appendLogMessage(f"PARSE ERROR: {errorMessage}. Requesting LLM correction...")
		window._updateProgress(-1, "Requesting LLM correction...") # Show indeterminate progress
		window._isBusy = True # Set busy again for the correction LLM call
		window._updateWidgetStates() # Update UI

		try:
			# Gather necessary info for the correction prompt
			original_bad_response: str = window._llmResponseArea.toPlainText()
			original_instruction: str = window._promptInput.toPlainText()
			expected_format: str = window._configManager.getConfigValue('General', 'ExpectedOutputFormat', fallback='json') or 'json'
			model_name: str = window._configManager.getConfigValue('General', 'DefaultLlmModel', fallback='gemini-1.5-flash-latest') or 'gemini-1.5-flash-latest'

			# Basic checks for required info
			if not original_bad_response: raise ValueError("Missing original LLM response needed for correction.")
			if not original_instruction: raise ValueError("Missing original user instruction needed for correction context.")

			# Build the correction prompt using the LLM interface helper
			if hasattr(window, '_llmInterfaceInstance'):
				correction_prompt: str = window._llmInterfaceInstance.build_correction_prompt(
					original_bad_output=original_bad_response,
					original_instruction=original_instruction,
					expected_format=expected_format
				)
				logger.debug(f"Built correction prompt (length: {len(correction_prompt)} chars).")
			else:
				raise AttributeError("LLM interface instance not found on main window.")

			# Trigger the LLM worker with the correction task and specific temperature
			window._llmWorker.startCorrectionQuery(model_name, correction_prompt, CORRECTION_RETRY_TEMPERATURE)
			# State will be handled by on_llm_finished when the correction response arrives

		except (ConfigurationError, ValueError, LLMError, AttributeError, Exception) as e:
			# Handle errors during the setup/triggering of the correction call
			logger.critical(f"Failed to initiate LLM correction query: {e}", exc_info=True)
			window._resetTaskState() # Reset busy state as correction call failed
			window._showError("Correction Setup Error", f"Could not initiate LLM correction attempt: {e}")
			window._appendLogMessage(f"CRITICAL: Failed to start correction query: {e}")
			window._correction_attempted = False # Allow user to potentially try again manually (e.g., after fixing config)
		# --- End Correction Attempt ---
	else:
		# --- Handle Non-Retryable Errors or Failed Correction ---
		error_title: str = "File Processing Error"
		log_prefix: str = "FILE ERROR"
		display_message: str = errorMessage # Default message

		if is_parsing_error:
			# It was a parsing error, but either already retried or retries disabled
			if window._correction_attempted:
				# Correction was attempted but failed (this handler called again implies failure)
				logger.error("LLM self-correction attempt also failed to produce parsable output.")
				log_prefix = "LLM CORRECTION FAILED"
				error_title = "LLM Correction Failed"
				display_message = (f"The LLM failed to correct the output format after the initial parsing error.\n"
								   f"Last Error Reported:\n{errorMessage}")
			else:
				# Parsing error, but retries not applicable
				log_prefix = "PARSE ERROR (Final)"
				error_title = "Parsing Error"
				display_message = f"Failed to parse the LLM response.\nError details:\n{errorMessage}"

		# Log the final error and show message box
		window._appendLogMessage(f"{log_prefix}: {errorMessage}")
		window._resetTaskState() # Reset busy state
		window._showError(error_title, display_message)

		# Clear potentially invalid parsed data and acceptance state if error occurred during parsing phase
		if is_parsing_error:
			window._parsedFileData = None
			window._validationErrors = None
			window._acceptedChangesState.clear() # Reset acceptance on final parse failure
			window._current_chunk_id_list = []
			window._current_chunk_start_block_map = {}
			window._last_clicked_chunk_id = None
			# Refresh diff view to clear potentially misleading proposed content
			diff_view.display_selected_file_diff(window, window._fileListWidget.currentItem())
			window._updateWidgetStates() # Update UI state

# --- END: gui/callback_handlers.py ---