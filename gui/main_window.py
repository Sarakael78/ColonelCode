# --- START: gui/main_window.py ---
# gui/main_window.py
"""
Defines the main application window, its layout, widgets, and connections.
Orchestrates user interactions and delegates tasks to core logic via threads.
"""
import logging
from PySide6.QtWidgets import (
	QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
	QPushButton, QTextEdit, QListWidget, QProgressBar, QStatusBar, QFileDialog,
	QMessageBox, QSplitter # Consider using QSplitter for layout
)
from PySide6.QtCore import Qt, Slot, Signal # Import necessary Qt core components
from PySide6.QtGui import QAction # For menu items

# Assuming ConfigManager and exception types are needed here
from core.config_manager import ConfigManager
from core.exceptions import BaseApplicationError

# TODO: Import worker threads from gui.threads
# TODO: Import core logic handlers (GitHub, LLM, FileProcessor)

logger: logging.Logger = logging.getLogger(__name__)

class MainWindow(QMainWindow):
	"""
	The main window class for the LLM Code Updater application.
	"""
	# TODO: Define signals for thread communication if needed directly here,
	# or manage them within the thread classes.
	# Example: Signal(str) signalLogMessage = Signal(str)

	# Adhering to user preference for explicit initialisation []
	_configManager: ConfigManager = None
	_centralWidget: QWidget = None
	_mainLayout: QVBoxLayout = None
	_repoUrlInput: QLineEdit = None
	# ... other widgets ...
	_logArea: QTextEdit = None
	_statusBar: QStatusBar = None
	_progressBar: QProgressBar = None
	_fileListWidget: QListWidget = None # Or QTreeView

	# Store paths and state
	_clonedRepoPath: str | None = None
	_selectedFiles: list[str] = []


	def __init__(self: 'MainWindow', configManager: ConfigManager, parent: QWidget | None = None) -> None:
		"""
		Initialises the MainWindow.

		Args:
			configManager (ConfigManager): The application's configuration manager instance.
			parent (QWidget | None): Optional parent widget.
		"""
		super().__init__(parent)
		self._configManager = configManager
		self._selectedFiles = [] # Explicit init

		logger.info("Initialising MainWindow...")
		self._setupUI()
		self._connectSignals()
		# TODO: Initialise worker thread instances (but don't start them yet)
		# self._githubWorker = GitHubWorker(...)
		# self._llmWorker = LLMWorker(...)
		# self._fileWorker = FileWorker(...)
		logger.info("MainWindow initialised.")

	def _setupUI(self: 'MainWindow') -> None:
		"""Sets up the user interface layout and widgets."""
		logger.debug("Setting up UI elements.")
		self._centralWidget = QWidget()
		self.setCentralWidget(self._centralWidget)

		self._mainLayout = QVBoxLayout(self._centralWidget)

		# --- Top Section: Repo Input ---
		repoLayout = QHBoxLayout()
		repoLabel = QLabel("GitHub Repo URL:")
		self._repoUrlInput = QLineEdit()
		self._repoUrlInput.setPlaceholderText("https://github.com/user/repo.git or path/to/local/repo")
		cloneButton = QPushButton("Clone/Load Repo")
		# TODO: Add Browse button for local paths
		repoLayout.addWidget(repoLabel)
		repoLayout.addWidget(self._repoUrlInput)
		repoLayout.addWidget(cloneButton)
		self._mainLayout.addLayout(repoLayout)

		# --- Middle Section: File Selection & Prompt ---
		middleSplitter = QSplitter(Qt.Orientation.Horizontal)

		# File List (Left Side)
		fileListLayout = QVBoxLayout()
		fileListLabel = QLabel("Select Files for Context:")
		self._fileListWidget = QListWidget() # # TODO: Consider QTreeView for better hierarchy
		self._fileListWidget.setSelectionMode(QListWidget.SelectionMode.MultiSelection) # Allow multi-select
		# TODO: Implement logic to populate this list after cloning
		fileListLayout.addWidget(fileListLabel)
		fileListLayout.addWidget(self._fileListWidget)
		fileListWidgetContainer = QWidget() # Container for layout
		fileListWidgetContainer.setLayout(fileListLayout)
		middleSplitter.addWidget(fileListWidgetContainer)

		# Prompt & LLM Interaction (Right Side)
		promptLayout = QVBoxLayout()
		promptLabel = QLabel("LLM Instruction / Prompt:")
		self._promptInput = QTextEdit()
		self._promptInput.setPlaceholderText("Enter your instructions for code modification...")
		llmInteractionLayout = QHBoxLayout()
		generatePromptButton = QPushButton("Generate Full Prompt") # Optional helper
		sendToLlmButton = QPushButton("Send to LLM")
		pasteResponseButton = QPushButton("Paste LLM Response") # Manual input fallback
		self._llmResponseArea = QTextEdit()
		self._llmResponseArea.setPlaceholderText("LLM response will appear here...")
		self._llmResponseArea.setReadOnly(False) # Allow pasting

		llmInteractionLayout.addWidget(generatePromptButton) # # TODO: Connect this button
		llmInteractionLayout.addWidget(sendToLlmButton)
		llmInteractionLayout.addWidget(pasteResponseButton) # # TODO: Connect this button

		promptLayout.addWidget(promptLabel)
		promptLayout.addWidget(self._promptInput, stretch=1) # Allow prompt input to stretch
		promptLayout.addLayout(llmInteractionLayout)
		promptLayout.addWidget(QLabel("LLM Response:"))
		promptLayout.addWidget(self._llmResponseArea, stretch=2) # Allow response area to stretch more
		promptWidgetContainer = QWidget()
		promptWidgetContainer.setLayout(promptLayout)
		middleSplitter.addWidget(promptWidgetContainer)

		middleSplitter.setSizes([200, 500]) # Initial size ratio for file list and prompt area
		self._mainLayout.addWidget(middleSplitter, stretch=1)

		# --- Bottom Section: Actions & Log ---
		bottomSplitter = QSplitter(Qt.Orientation.Vertical)

		# Action Buttons
		actionLayout = QHBoxLayout()
		parseButton = QPushButton("Parse Response")
		saveFilesButton = QPushButton("Save Changes Locally")
		commitPushButton = QPushButton("Commit & Push to GitHub")
		actionLayout.addWidget(parseButton)
		actionLayout.addWidget(saveFilesButton)
		actionLayout.addWidget(commitPushButton)
		actionWidgetContainer = QWidget()
		actionWidgetContainer.setLayout(actionLayout)
		bottomSplitter.addWidget(actionWidgetContainer)


		# Log Area
		logLayout = QVBoxLayout()
		logLabel = QLabel("Application Log:")
		self._logArea = QTextEdit()
		self._logArea.setReadOnly(True)
		# TODO: Implement a custom log handler that writes here (see logger_setup TODO)
		logLayout.addWidget(logLabel)
		logLayout.addWidget(self._logArea)
		logWidgetContainer = QWidget()
		logWidgetContainer.setLayout(logLayout)
		bottomSplitter.addWidget(logWidgetContainer)

		bottomSplitter.setSizes([50, 200]) # Initial sizes for actions and log area
		self._mainLayout.addWidget(bottomSplitter, stretch=1) # Allow bottom section to stretch

		# --- Status Bar & Progress Bar ---
		self._statusBar = QStatusBar()
		self.setStatusBar(self._statusBar)
		self._progressBar = QProgressBar()
		self._progressBar.setVisible(False) # Initially hidden
		self._statusBar.addPermanentWidget(self._progressBar)

		# # TODO: Set initial state (e.g., disable buttons until repo is loaded)
		# self._updateWidgetStates()

		self.setGeometry(100, 100, 900, 700) # Initial position and size
		logger.debug("UI setup complete.")

	def _connectSignals(self: 'MainWindow') -> None:
		"""Connects widget signals to their corresponding slots (methods)."""
		logger.debug("Connecting signals to slots.")
		# --- Find the buttons defined in _setupUI ---
		# This is slightly fragile; storing button references as members is better
		cloneButton = self.findChild(QPushButton, "Clone/Load Repo") # Requires objectName to be set
		sendToLlmButton = self.findChild(QPushButton, "Send to LLM")
		parseButton = self.findChild(QPushButton, "Parse Response")
		saveFilesButton = self.findChild(QPushButton, "Save Changes Locally")
		commitPushButton = self.findChild(QPushButton, "Commit & Push to GitHub")

		# Instead, let's assign names and retrieve them properly, or better, store as members:
		# Example (adjust _setupUI to store button references):
		# self._cloneButton = QPushButton("Clone/Load Repo")
		# repoLayout.addWidget(self._cloneButton)
		# ... and then connect using self._cloneButton.clicked.connect(...)

		# TODO: Refactor _setupUI to store buttons like self._cloneButton, self._sendToLlmButton etc.
		# Assuming buttons are found for now (replace with member access later)
		if cloneButton:
				cloneButton.clicked.connect(self._handleCloneRepo)
		if sendToLlmButton:
				sendToLlmButton.clicked.connect(self._handleSendToLlm)
		if parseButton:
				parseButton.clicked.connect(self._handleParseResponse)
		if saveFilesButton:
				saveFilesButton.clicked.connect(self._handleSaveChanges)
		if commitPushButton:
				commitPushButton.clicked.connect(self._handleCommitPush)

		# Connect file list selection change
		self._fileListWidget.itemSelectionChanged.connect(self._handleFileSelectionChanged)

		# TODO: Connect signals from worker threads to update GUI (e.g., progress, results, errors)
		# Example:
		# self._githubWorker.cloneProgress.connect(self._updateProgressBar)
		# self._githubWorker.cloneFinished.connect(self._onCloneFinished)
		# self._githubWorker.errorOccurred.connect(self._handleWorkerError)
		# ... similar connections for LLM and File workers ...

		# TODO: Connect custom logging handler signal to update self._logArea
		# self.signalLogMessage.connect(self._appendLogMessage) # If signal is defined in MainWindow
		# Or connect directly from a separate logging handler instance

		logger.debug("Signal connections established.")

	# --- Slots (Event Handlers) ---

	@Slot()
	def _handleCloneRepo(self: 'MainWindow') -> None:
		"""Initiates the repository cloning process in a background thread."""
		repoUrlOrPath: str = self._repoUrlInput.text().strip()
		if not repoUrlOrPath:
			self._showError("Repository URL or Path", "Please enter a valid GitHub repository URL or local path.")
			return

		# TODO: Determine if it's a URL or local path
		isLocalPath = os.path.exists(repoUrlOrPath) # Basic check

		# TODO: Get clone directory (use config default, allow user selection?)
		defaultCloneDir = self._configManager.getConfigValue('General', 'DefaultCloneDir', './cloned_repos')
		# For now, use default (ensure it exists)
		cloneTargetDir = os.path.abspath(defaultCloneDir)
		if not os.path.exists(cloneTargetDir):
				os.makedirs(cloneTargetDir, exist_ok=True)

		# Extract repo name for target subdir
		repoName = os.path.basename(repoUrlOrPath)
		if repoName.endswith('.git'):
				repoName = repoName[:-4]
		if not repoName: repoName = "repository" # Fallback name

		self._clonedRepoPath = os.path.join(cloneTargetDir, repoName) # Path where it *will* be cloned

		logger.info(f"Attempting to load/clone '{repoUrlOrPath}' into '{self._clonedRepoPath}'")
		self._updateStatusBar("Cloning repository...")
		self._progressBar.setVisible(True)
		self._progressBar.setRange(0, 0) # Indeterminate progress
		# TODO: Disable relevant UI elements
		# self._updateWidgetStates(isBusy=True)

		# TODO: Get GitHub token if needed (for private repos)
		githubToken = self._configManager.getEnvVar('GITHUB_TOKEN')

		# TODO: Initiate the actual cloning using a worker thread
		# self._githubWorker.startClone(repoUrlOrPath, self._clonedRepoPath, githubToken)

		# --- Placeholder ---
		self._showInfo("Clone/Load", f"# TODO: Implement cloning/loading of '{repoUrlOrPath}' into '{self._clonedRepoPath}' using GitHubHandler in a thread.")
		# Simulate finish for now
		self._onCloneFinished(["file1.py", "subdir/file2.js", ".gitignore"], None) # Dummy data
		# --- End Placeholder ---


	@Slot()
	def _handleFileSelectionChanged(self: 'MainWindow') -> None:
		"""Updates the internal list of selected files."""
		selectedItems = self._fileListWidget.selectedItems()
		self._selectedFiles = [item.text() for item in selectedItems]
		logger.debug(f"Selected files updated: {self._selectedFiles}")
		# TODO: Update UI state if needed (e.g., enable 'Send to LLM' button only if files are selected?)


	@Slot()
	def _handleSendToLlm(self: 'MainWindow') -> None:
		"""Builds the prompt and sends it to the LLM via a background thread."""
		userInstruction: str = self._promptInput.toPlainText().strip()
		if not userInstruction:
			self._showError("LLM Prompt", "Please enter instructions for the LLM.")
			return
		if not self._clonedRepoPath:
			self._showError("LLM Prompt", "Please clone or load a repository first.")
			return
		if not self._selectedFiles:
			self._showWarning("LLM Prompt", "No files selected. Sending prompt without file context.")
			# Decide if this is allowed or should be an error

		logger.info("Preparing to send request to LLM...")
		self._updateStatusBar("Querying LLM...")
		self._progressBar.setVisible(True)
		self._progressBar.setRange(0, 0) # Indeterminate
		# TODO: Disable relevant UI elements
		# self._updateWidgetStates(isBusy=True)

		# TODO: Read content of selected files using GitHubHandler (or directly if local)
		fileContents: dict[str, str] = {}
		try:
			# Example (replace with actual GitHubHandler call)
			for filePath in self._selectedFiles:
				fullPath = os.path.join(self._clonedRepoPath, filePath)
				if os.path.exists(fullPath):
					with open(fullPath, 'r', encoding='utf-8', errors='ignore') as f:
						fileContents[filePath] = f.read()
				else:
					logger.warning(f"Selected file not found: {fullPath}")
			logger.debug(f"Read content for {len(fileContents)} files.")
		except Exception as e:
			self._showError("File Reading Error", f"Failed to read selected file contents: {e}")
			self._resetTaskState()
			return

		# TODO: Get LLM API Key and model name from config
		apiKey = self._configManager.getEnvVar('GEMINI_API_KEY', required=True) # Error if missing
		modelName = self._configManager.getConfigValue('General', 'DefaultLlmModel', fallback='gemini-pro')

		# TODO: Initiate LLM query using LLMInterface in a worker thread
		# self._llmWorker.startQuery(apiKey, modelName, userInstruction, fileContents)

		# --- Placeholder ---
		self._showInfo("Send to LLM", f"# TODO: Implement LLM query using LLMInterface in a thread. Files: {len(fileContents)}")
		# Simulate response for now
		dummyResponse = """
```json
{
  "file1.py": "print('Hello, updated world!')",
  "subdir/file2.js": "// Updated JavaScript file\\nconsole.log('Updated!');",
  "new_feature.py": "# A newly created file by the LLM\\ndef new_function():\\n    pass"
}
"""
self._onLlmFinished(dummyResponse, None)
# --- End Placeholder ---

@Slot()
def _handleParseResponse(self: 'MainWindow') -> None:
	"""Initiates parsing the LLM response in a background thread."""
	llmResponse: str = self._llmResponseArea.toPlainText().strip()
	if not llmResponse:
		self._showError("Parse Response", "LLM Response area is empty. Cannot parse.")
		return

	logger.info("Attempting to parse LLM response...")
	self._updateStatusBar("Parsing LLM response...")
	self._progressBar.setVisible(True)
	self._progressBar.setRange(0, 0)
	# TODO: Disable UI
	# self._updateWidgetStates(isBusy=True)

	# TODO: Determine expected format (e.g., JSON from config or fixed)
	expectedFormat = 'json' # Assuming JSON for now

	# TODO: Initiate parsing using FileProcessor in a worker thread
	# self._fileWorker.startParsing(llmResponse, expectedFormat)

	# --- Placeholder ---
	self._showInfo("Parse Response", "# TODO: Implement response parsing using FileProcessor in a thread.")
	# Simulate result
	try:
			import json
			# Basic extraction (improve this in FileProcessor)
			codeBlockContent = None
			if f"```{expectedFormat}" in llmResponse and "```" in llmResponse.split(f"```{expectedFormat}", 1)[1]:
					codeBlockContent = llmResponse.split(f"```{expectedFormat}", 1)[1].split("```", 1)[0].strip()

			if not codeBlockContent:
					raise ParsingError("Could not find JSON code block.")

			parsedData = json.loads(codeBlockContent)
			if not isinstance(parsedData, dict):
					raise ParsingError("Parsed data is not a dictionary (file map).")
			# Basic validation
			for k, v in parsedData.items():
					if not isinstance(k, str) or not isinstance(v, str):
							raise ParsingError(f"Invalid structure: Key '{k}' or its value is not a string.")

			self._onParsingFinished(parsedData, None)
	except Exception as e:
			self._onParsingFinished(None, f"Parsing failed: {e}")
	# --- End Placeholder ---

@Slot()
def _handleSaveChanges(self: 'MainWindow') -> None:
	"""Initiates saving the parsed changes to the local filesystem (cloned repo)."""
	# # TODO: Check if parsing was successful and yielded data
	# We need to store the parsed data from the _onParsingFinished slot
	# Add a member variable: self._parsedFileData: dict[str, str] | None = None

	if not hasattr(self, '_parsedFileData') or not self._parsedFileData:
		self._showError("Save Changes", "No parsed data available to save. Please parse a valid LLM response first.")
		return
	if not self._clonedRepoPath or not os.path.isdir(self._clonedRepoPath):
		self._showError("Save Changes", "Cloned repository path is not valid or not set.")
		return

	logger.info(f"Attempting to save {len(self._parsedFileData)} files to {self._clonedRepoPath}...")
	self._updateStatusBar("Saving changes locally...")
	self._progressBar.setVisible(True)
	self._progressBar.setRange(0, 0)
	# TODO: Disable UI
	# self._updateWidgetStates(isBusy=True)

	# TODO: Initiate saving using FileProcessor in a worker thread
	# self._fileWorker.startSaving(self._clonedRepoPath, self._parsedFileData)

	# --- Placeholder ---
	self._showInfo("Save Changes", f"# TODO: Implement file saving using FileProcessor in a thread. Target: {self._clonedRepoPath}")
	# Simulate success
	savedFilePaths = list(self._parsedFileData.keys())
	self._onSavingFinished(savedFilePaths, None)
	# --- End Placeholder ---

@Slot()
def _handleCommitPush(self: 'MainWindow') -> None:
	"""Initiates staging, committing, and pushing changes via a background thread."""
	if not self._clonedRepoPath or not os.path.isdir(self._clonedRepoPath):
		self._showError("Commit & Push", "Cloned repository path is not valid or not set.")
		return

	# # TODO: Check if there are actual changes to commit (Git status) - implement in GitHubHandler
	# # TODO: Prompt user for commit message (or use a default/generated one)
	commitMessage: str = "LLM Auto-Update" # Placeholder

	logger.info(f"Attempting to commit and push changes in {self._clonedRepoPath}...")
	self._updateStatusBar("Committing and pushing changes...")
	self._progressBar.setVisible(True)
	self._progressBar.setRange(0, 0)
	# # TODO: Disable UI
	# self._updateWidgetStates(isBusy=True)

	# # TODO: Get Git settings (remote, branch) from config
	remoteName = self._configManager.getConfigValue('GitHub', 'DefaultRemoteName', 'origin')
	branchName = self._configManager.getConfigValue('GitHub', 'DefaultBranchName', 'main')
	githubToken = self._configManager.getEnvVar('GITHUB_TOKEN') # Needed for push to private/HTTPS

	# # TODO: Initiate commit/push using GitHubHandler in a worker thread
	# self._githubWorker.startCommitPush(self._clonedRepoPath, commitMessage, remoteName, branchName, githubToken)

	# --- Placeholder ---
	self._showInfo("Commit & Push", f"# TODO: Implement commit/push using GitHubHandler in a thread. Repo: {self._clonedRepoPath}")
	# Simulate success
	self._onCommitPushFinished("Commit and push successful.", None)
	# --- End Placeholder ---

# --- Worker Thread Callback Slots ---

@Slot(list, str) # Assuming list of files, or error message string
def _onCloneFinished(self: 'MainWindow', fileList: list | None, error: str | None) -> None:
	"""Handles the completion of the cloning process."""
	logger.debug(f"Clone finished. Error: {error}, Files: {len(fileList) if fileList else 'N/A'}")
	self._resetTaskState()
	if error:
		self._showError("Cloning Failed", error)
		self._clonedRepoPath = None # Invalidate path on error
	elif fileList is not None:
		self._updateStatusBar("Repository loaded successfully.", 5000)
		self._fileListWidget.clear()
		self._fileListWidget.addItems(fileList)
		# # TODO: Enable subsequent action buttons
	else:
		# Should not happen if logic is correct, but handle defensively
		self._showError("Cloning Error", "Cloning finished, but no file list or error was returned.")
		self._clonedRepoPath = None


@Slot(str, str) # Assuming LLM response string, or error message string
def _onLlmFinished(self: 'MainWindow', response: str | None, error: str | None) -> None:
	"""Handles the completion of the LLM query."""
	logger.debug(f"LLM query finished. Error: {error}, Response length: {len(response) if response else 'N/A'}")
	self._resetTaskState()
	if error:
		self._showError("LLM Query Failed", error)
		self._llmResponseArea.setPlainText(f"Error:\n{error}")
	elif response is not None:
		self._updateStatusBar("LLM query successful.", 5000)
		self._llmResponseArea.setPlainText(response)
		# # TODO: Enable Parse button
	else:
		self._showError("LLM Query Error", "LLM query finished, but no response or error was returned.")


@Slot(dict, str) # Assuming parsed data dict, or error message string
def _onParsingFinished(self: 'MainWindow', parsedData: dict | None, error: str | None) -> None:
	"""Handles the completion of the LLM response parsing."""
	logger.debug(f"Parsing finished. Error: {error}, Parsed items: {len(parsedData) if parsedData else 'N/A'}")
	self._resetTaskState()
	if error:
		self._showError("Parsing Failed", error)
		self._parsedFileData = None # Clear any previous parsed data
	elif parsedData is not None:
		self._updateStatusBar(f"Response parsed successfully ({len(parsedData)} files found).", 5000)
		self._parsedFileData = parsedData # Store for saving
		# # TODO: Maybe visually indicate parsed files (e.g., in file list?)
		# # TODO: Enable Save button
	else:
		self._showError("Parsing Error", "Parsing finished, but no data or error was returned.")
		self._parsedFileData = None


@Slot(list, str) # Assuming list of saved file paths, or error message string
def _onSavingFinished(self: 'MainWindow', savedFiles: list | None, error: str | None) -> None:
	"""Handles the completion of saving files."""
	logger.debug(f"Saving finished. Error: {error}, Saved files: {len(savedFiles) if savedFiles else 'N/A'}")
	self._resetTaskState()
	if error:
		self._showError("Saving Failed", error)
	elif savedFiles is not None:
		self._updateStatusBar(f"Changes saved locally ({len(savedFiles)} files).", 5000)
		self._showInfo("Save Successful", f"The following files were saved or updated in\n{self._clonedRepoPath}:\n\n" + "\n".join(savedFiles))
		# # TODO: Enable Commit/Push button
		# # TODO: Optionally refresh file list/status?
	else:
		self._showError("Saving Error", "Saving finished, but no file list or error was returned.")


@Slot(str, str) # Assuming success message string, or error message string
def _onCommitPushFinished(self: 'MainWindow', message: str | None, error: str | None) -> None:
	"""Handles the completion of the commit and push process."""
	logger.debug(f"Commit/Push finished. Error: {error}, Message: {message}")
	self._resetTaskState()
	if error:
		self._showError("Commit/Push Failed", error)
	elif message is not None:
		self._updateStatusBar("Commit and push successful.", 5000)
		self._showInfo("Commit/Push Successful", message)
	else:
		# Less likely if logic is correct
		self._showError("Commit/Push Error", "Operation finished, but no message or error was returned.")

@Slot(str)
def _handleWorkerError(self: 'MainWindow', errorMessage: str) -> None:
	"""Generic handler for errors reported by worker threads."""
	logger.error(f"Worker thread reported error: {errorMessage}")
	self._resetTaskState()
	self._showError("Background Task Error", errorMessage)


# --- Utility Methods ---

def _resetTaskState(self: 'MainWindow') -> None:
	"""Resets progress bar and status bar after a task completes or fails."""
	self._progressBar.setVisible(False)
	self._updateStatusBar("Idle.")
	# # TODO: Re-enable UI elements
	# self._updateWidgetStates(isBusy=False)

def _updateStatusBar(self: 'MainWindow', message: str, timeout: int = 0) -> None:
	"""Updates the status bar message."""
	self._statusBar.showMessage(message, timeout)
	logger.debug(f"Status bar updated: {message}")

# # TODO: Implement _updateWidgetStates(isBusy: bool) to enable/disable buttons etc.

def _showError(self: 'MainWindow', title: str, message: str) -> None:
	"""Displays an error message box."""
	logger.error(f"{title}: {message}")
	QMessageBox.critical(self, title, message)

def _showWarning(self: 'MainWindow', title: str, message: str) -> None:
	"""Displays a warning message box."""
	logger.warning(f"{title}: {message}")
	QMessageBox.warning(self, title, message)

def _showInfo(self: 'MainWindow', title: str, message: str) -> None:
	"""Displays an informational message box."""
	logger.info(f"{title}: {message}")
	QMessageBox.information(self, title, message)

@Slot(str)
def _appendLogMessage(self: 'MainWindow', message: str) -> None:
	"""Appends a message to the GUI log area."""
	# # TODO: Ensure this is thread-safe if called directly from other threads
	# Using signals/slots mechanism is the standard Qt way.
	self._logArea.append(message)

def closeEvent(self: 'MainWindow', event) -> None:
	"""Handles the window close event."""
	# # TODO: Add confirmation dialog if tasks are running?
	# # TODO: Ensure worker threads are properly stopped/cleaned up.
	logger.info("Close event triggered. Application shutting down.")
	# Perform cleanup here
	super().closeEvent(event)
# --- END: gui/main_window.py ---