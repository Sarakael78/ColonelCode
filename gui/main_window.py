# Updated Codebase/gui/main_window.py
# --- START: gui/main_window.py ---
# gui/main_window.py
"""
Defines the main application window, its layout, widgets, and connections.
Orchestrates user interactions and delegates tasks to core logic via threads.
"""
import os
import logging
from PySide6.QtWidgets import (
	QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
	QPushButton, QTextEdit, QListWidget, QProgressBar, QStatusBar,
	QMessageBox, QSplitter, QFileDialog, QInputDialog # Added QFileDialog, QInputDialog
)
from PySide6.QtCore import Qt, Slot, Signal # Import necessary Qt core components
from PySide6.QtGui import QIcon # For application icon

# Import configuration, exceptions, and handlers
from core.config_manager import ConfigManager
from core.exceptions import ConfigurationError, ParsingError, BaseApplicationError, GitHubError
from core.github_handler import GitHubHandler # Still needed for isDirty check
from core.llm_interface import LLMInterface # Needed for prompt building

# Import worker threads
from gui.threads import GitHubWorker, LLMWorker, FileWorker

# Import custom logger setup and potentially GUI handler
from utils.logger_setup import setupLogging
from gui.gui_utils import QtLogHandler # Assuming this exists for GUI logging

logger: logging.Logger = logging.getLogger(__name__)

class MainWindow(QMainWindow):
	"""
	The main window class for the LLM Code Updater application.
	"""
	# Signal for internal GUI logging
	signalLogMessage = Signal(str)

	# Adhering to user preference for explicit initialisation
	_configManager: ConfigManager = None
	_centralWidget: QWidget = None
	_mainLayout: QVBoxLayout = None
	_repoUrlInput: QLineEdit = None
	_browseButton: QPushButton = None
	_cloneButton: QPushButton = None
	_fileListWidget: QListWidget = None
	_promptInput: QTextEdit = None
	_sendToLlmButton: QPushButton = None
	_pasteResponseButton: QPushButton = None
	_llmResponseArea: QTextEdit = None
	_parseButton: QPushButton = None
	_saveFilesButton: QPushButton = None
	_commitPushButton: QPushButton = None
	_logArea: QTextEdit = None
	_statusBar: QStatusBar = None
	_progressBar: QProgressBar = None

	# Store paths and state
	_clonedRepoPath: str | None = None
	_selectedFiles: list[str] = []
	_parsedFileData: Optional[Dict[str, str]] = None # Store parsed data {filepath: content}
	_isBusy: bool = False # Track if a background task is running
	_repoIsDirty: bool = False # Track repository dirty state

	# Worker threads
	_githubWorker: GitHubWorker = None
	_llmWorker: LLMWorker = None
	_fileWorker: FileWorker = None

	# Core handlers (instantiated for sync checks or passed to workers)
	_githubHandlerInstance: GitHubHandler = None
	_llmInterfaceInstance: LLMInterface = None


	def __init__(self: 'MainWindow', configManager: ConfigManager, parent: QWidget | None = None) -> None:
		"""
		Initialises the MainWindow.

		Args:
			configManager (ConfigManager): The application's configuration manager instance.
			parent (QWidget | None): Optional parent widget.
		"""
		super().__init__(parent)
		self._configManager = configManager
		self._selectedFiles = []
		self._clonedRepoPath = None
		self._parsedFileData = None
		self._isBusy = False
		self._repoIsDirty = False

		# Store references to core handlers
		# GitHubHandler needed for synchronous isDirty check
		self._githubHandlerInstance = GitHubHandler()
		# LLMInterface needed for synchronous prompt building before worker starts
		self._llmInterfaceInstance = LLMInterface(configManager=self._configManager) # Pass config

		logger.info("Initialising MainWindow...")

		# Setup UI elements first
		self._setupUI()

		# Initialise worker thread instances (pass handlers if needed)
		self._githubWorker = GitHubWorker(parent=self) # Pass parent for auto-cleanup
		self._llmWorker = LLMWorker(parent=self, configManager=self._configManager) # Pass config
		self._fileWorker = FileWorker(parent=self)

		# Then connect signals from UI elements and workers
		self._connectSignals()

		# Set initial state
		self._updateWidgetStates()

		# Setup logging to include GUI handler
		self._setupGuiLogging()

		logger.info("MainWindow initialised.")


	def _setupUI(self: 'MainWindow') -> None:
		"""Sets up the user interface layout and widgets."""
		logger.debug("Setting up UI elements.")
		self.setWindowTitle("Colonol Code - LLM Code Updater")
		# Set Application Icon (replace 'app_icon.png' with your actual icon path/name)
		iconPath = os.path.join('resources', 'app_icon.png') # Assuming icon is in resources folder
		if os.path.exists(iconPath):
				self.setWindowIcon(QIcon(iconPath))
		else:
				logger.warning(f"Application icon not found at: {iconPath}")


		self._centralWidget = QWidget()
		self.setCentralWidget(self._centralWidget)

		self._mainLayout = QVBoxLayout(self._centralWidget)

		# --- Top Section: Repo Input ---
		repoLayout = QHBoxLayout()
		repoLabel = QLabel("GitHub Repo URL / Local Path:")
		self._repoUrlInput = QLineEdit()
		self._repoUrlInput.setPlaceholderText("[https://github.com/user/repo.git](https://github.com/user/repo.git) or /path/to/local/repo")
		# Store button references as members
		self._browseButton = QPushButton("Browse...")
		self._cloneButton = QPushButton("Clone / Load Repo")
		repoLayout.addWidget(repoLabel)
		repoLayout.addWidget(self._repoUrlInput, 1) # Stretch input field
		repoLayout.addWidget(self._browseButton)
		repoLayout.addWidget(self._cloneButton)
		self._mainLayout.addLayout(repoLayout)

		# --- Middle Section: File Selection & Prompt ---
		middleSplitter = QSplitter(Qt.Orientation.Horizontal)

		# File List (Left Side)
		fileListLayout = QVBoxLayout()
		fileListLabel = QLabel("Select Files for Context:")
		self._fileListWidget = QListWidget()
		self._fileListWidget.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection) # Allow multi-select easily
		fileListLayout.addWidget(fileListLabel)
		fileListLayout.addWidget(self._fileListWidget)
		fileListWidgetContainer = QWidget()
		fileListWidgetContainer.setLayout(fileListLayout)
		middleSplitter.addWidget(fileListWidgetContainer)

		# Prompt & LLM Interaction (Right Side)
		promptLayout = QVBoxLayout()
		promptLabel = QLabel("LLM Instruction / Prompt:")
		self._promptInput = QTextEdit()
		self._promptInput.setPlaceholderText("Enter your instructions for code modification...")

		llmInteractionLayout = QHBoxLayout()
		# self._generatePromptButton = QPushButton("Generate Full Prompt") # Optional helper - deferred
		self._sendToLlmButton = QPushButton("Send to LLM")
		self._pasteResponseButton = QPushButton("Paste LLM Response")
		self._llmResponseArea = QTextEdit()
		self._llmResponseArea.setPlaceholderText("LLM response will appear here, or paste response and click 'Parse'")
		self._llmResponseArea.setReadOnly(False) # Allow pasting

		# llmInteractionLayout.addWidget(self._generatePromptButton)
		llmInteractionLayout.addWidget(self._sendToLlmButton)
		llmInteractionLayout.addWidget(self._pasteResponseButton)
		llmInteractionLayout.addStretch(1) # Push buttons left

		promptLayout.addWidget(promptLabel)
		promptLayout.addWidget(self._promptInput, stretch=1)
		promptLayout.addLayout(llmInteractionLayout)
		promptLayout.addWidget(QLabel("LLM Response:"))
		promptLayout.addWidget(self._llmResponseArea, stretch=2)
		promptWidgetContainer = QWidget()
		promptWidgetContainer.setLayout(promptLayout)
		middleSplitter.addWidget(promptWidgetContainer)

		middleSplitter.setSizes([300, 600]) # Adjust initial size ratio
		self._mainLayout.addWidget(middleSplitter, stretch=1)

		# --- Bottom Section: Actions & Log ---
		bottomSplitter = QSplitter(Qt.Orientation.Vertical)

		# Action Buttons
		actionLayout = QHBoxLayout()
		self._parseButton = QPushButton("Parse Response")
		self._saveFilesButton = QPushButton("Save Changes Locally")
		self._commitPushButton = QPushButton("Commit & Push")
		actionLayout.addWidget(self._parseButton)
		actionLayout.addWidget(self._saveFilesButton)
		actionLayout.addWidget(self._commitPushButton)
		actionLayout.addStretch(1) # Push buttons left
		actionWidgetContainer = QWidget()
		actionWidgetContainer.setLayout(actionLayout)
		bottomSplitter.addWidget(actionWidgetContainer)


		# Log Area
		logLayout = QVBoxLayout()
		logLabel = QLabel("Application Log:")
		self._logArea = QTextEdit()
		self._logArea.setReadOnly(True)
		self._logArea.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap) # Prevent wrapping for readability
		logLayout.addWidget(logLabel)
		logLayout.addWidget(self._logArea, 1) # Allow log area to stretch
		logWidgetContainer = QWidget()
		logWidgetContainer.setLayout(logLayout)
		bottomSplitter.addWidget(logWidgetContainer)

		bottomSplitter.setSizes([50, 250]) # Adjust initial sizes
		self._mainLayout.addWidget(bottomSplitter, stretch=1)

		# --- Status Bar & Progress Bar ---
		self._statusBar = QStatusBar()
		self.setStatusBar(self._statusBar)
		self._progressBar = QProgressBar()
		self._progressBar.setVisible(False)
		self._progressBar.setTextVisible(True) # Show percentage text
		self._progressBar.setRange(0, 100) # Use 0-100 for percentage, 0 means indeterminate
		self._progressBar.setValue(0)
		self._progressBar.setFormat("%p%") # Show percentage
		self._statusBar.addPermanentWidget(self._progressBar)

		self.setGeometry(100, 100, 1000, 800) # Adjusted initial size
		logger.debug("UI setup complete.")


	def _connectSignals(self: 'MainWindow') -> None:
		"""Connects widget signals and worker signals to slots."""
		logger.debug("Connecting signals to slots.")

		# --- UI Element Signals ---
		self._browseButton.clicked.connect(self._handleBrowseRepo)
		self._cloneButton.clicked.connect(self._handleCloneRepo)
		self._sendToLlmButton.clicked.connect(self._handleSendToLlm)
		self._pasteResponseButton.clicked.connect(self._handlePasteResponse) # Simple action
		self._parseButton.clicked.connect(self._handleParseResponse)
		self._saveFilesButton.clicked.connect(self._handleSaveChanges)
		self._commitPushButton.clicked.connect(self._handleCommitPush)
		self._fileListWidget.itemSelectionChanged.connect(self._handleFileSelectionChanged)

		# --- Worker Thread Signals ---
		# GitHubWorker
		self._githubWorker.statusUpdate.connect(self._updateStatusBar)
		self._githubWorker.progressUpdate.connect(self._updateProgress) # Connect new progress signal
		self._githubWorker.errorOccurred.connect(self._handleWorkerError) # Unexpected errors
		self._githubWorker.gitHubError.connect(self._handleGitHubError) # Expected Git/GitHub errors
		self._githubWorker.cloneFinished.connect(self._onCloneFinished)
		self._githubWorker.commitPushFinished.connect(self._onCommitPushFinished)
		self._githubWorker.isDirtyFinished.connect(self._onIsDirtyFinished) # Signal for isDirty result
		# Add connections for listFilesFinished, readFileFinished if used directly

		# LLMWorker
		self._llmWorker.statusUpdate.connect(self._updateStatusBar)
		self._llmWorker.progressUpdate.connect(self._updateProgress)
		self._llmWorker.errorOccurred.connect(self._handleWorkerError)
		self._llmWorker.llmError.connect(self._handleLLMError) # Expected LLM/Config errors
		self._llmWorker.llmQueryFinished.connect(self._onLlmFinished)

		# FileWorker
		self._fileWorker.statusUpdate.connect(self._updateStatusBar)
		self._fileWorker.progressUpdate.connect(self._updateProgress)
		self._fileWorker.errorOccurred.connect(self._handleWorkerError)
		self._fileWorker.fileProcessingError.connect(self._handleFileProcessingError) # Expected File/Parsing errors
		self._fileWorker.parsingFinished.connect(self._onParsingFinished)
		self._fileWorker.savingFinished.connect(self._onSavingFinished)
		self._fileWorker.fileContentsRead.connect(self._onFileContentsRead) # Signal with read file contents

		# --- Custom Logging Signal ---
		self.signalLogMessage.connect(self._appendLogMessage)

		logger.debug("Signal connections established.")

	def _setupGuiLogging(self: 'MainWindow') -> None:
		"""Adds a handler to the root logger that emits signals to the GUI log area."""
		try:
			# Assume QtLogHandler exists and accepts a signal emitter callable
			guiHandler = QtLogHandler(self.signalLogMessage.emit) # Pass the emit method

			# Get log level from config for the GUI handler if desired
			guiLogLevelName = self._configManager.getConfigValue('Logging', 'GuiLogLevel', fallback='INFO')
			guiLogLevel = getattr(logging, guiLogLevelName.upper(), logging.INFO)
			guiHandler.setLevel(guiLogLevel)

			# Add formatting
			logFormat = self._configManager.getConfigValue('Logging', 'GuiLogFormat', fallback='%(asctime)s - %(levelname)s - %(message)s')
			dateFormat = self._configManager.getConfigValue('Logging', 'GuiLogDateFormat', fallback='%H:%M:%S')
			formatter = logging.Formatter(logFormat, datefmt=dateFormat)
			guiHandler.setFormatter(formatter)

			# Add handler to the root logger
			logging.getLogger().addHandler(guiHandler)
			logger.info(f"GUI logging handler added with level {logging.getLevelName(guiLogLevel)}.")
		except ImportError:
			logger.error("Could not import QtLogHandler from gui.gui_utils. GUI logging disabled.")
		except Exception as e:
			logger.error(f"Failed to setup GUI logging: {e}", exc_info=True)

	# --- Slots (Event Handlers) ---

	@Slot()
	def _handleBrowseRepo(self: 'MainWindow') -> None:
		"""Opens a directory dialog to select a local repository path."""
		directory = QFileDialog.getExistingDirectory(
			self,
			"Select Local Repository Folder",
			self._repoUrlInput.text() or os.path.expanduser("~") # Start in current input or home
		)
		if directory:
			self._repoUrlInput.setText(directory)

	@Slot()
	def _handleCloneRepo(self: 'MainWindow') -> None:
		"""Initiates the repository cloning/loading process via GitHubWorker."""
		if self._isBusy:
			self._showWarning("Busy", "A background task is already running.")
			return

		repoUrlOrPath: str = self._repoUrlInput.text().strip()
		if not repoUrlOrPath:
			self._showError("Repository Missing", "Please enter a valid GitHub repository URL or local path.")
			return

		# Determine clone target directory (inside configured base dir)
		try:
			# Check if input is already a local path
			if os.path.isdir(repoUrlOrPath):
				# If it's a directory, use it directly as the target path
				cloneTargetFullPath = os.path.abspath(repoUrlOrPath)
				logger.info(f"Input appears to be a local path: {cloneTargetFullPath}")
			else:
				# Assume it's a URL, construct path from base dir and repo name
				defaultCloneDir = self._configManager.getConfigValue('General', 'DefaultCloneDir', fallback='./cloned_repos')
				cloneBaseDir = os.path.abspath(defaultCloneDir)
				if not os.path.exists(cloneBaseDir):
						os.makedirs(cloneBaseDir, exist_ok=True)

				# Use repo name for sub-directory, handle potential naming issues
				repoName = os.path.basename(repoUrlOrPath.rstrip('/'))
				if repoName.endswith('.git'):
						repoName = repoName[:-4]
				if not repoName or repoName == '.': repoName = "repository" # Fallback name
				# Basic sanitization for directory name
				repoName = "".join(c for c in repoName if c.isalnum() or c in ('-', '_')).strip()
				if not repoName: repoName = "repository" # Final fallback

				cloneTargetFullPath = os.path.join(cloneBaseDir, repoName)
				logger.info(f"Input appears to be a URL. Target path: {cloneTargetFullPath}")

		except Exception as e:
			self._showError("Configuration Error", f"Could not determine clone path: {e}")
			logger.error(f"Error determining clone path: {e}", exc_info=True)
			return

		logger.info(f"Requesting load/clone of '{repoUrlOrPath}' into '{cloneTargetFullPath}'")
		self._isBusy = True
		self._updateWidgetStates()
		self._updateStatusBar("Initiating repository load/clone...")
		self._updateProgress(-1, "Starting...") # Show indeterminate progress bar

		# Get GitHub token (informational only for clone, potentially used by underlying Git for push)
		githubToken: Optional[str] = self._configManager.getEnvVar('GITHUB_TOKEN')

		# Initiate the cloning using the worker thread
		self._githubWorker.startClone(repoUrlOrPath, cloneTargetFullPath, githubToken)


	@Slot()
	def _handleFileSelectionChanged(self: 'MainWindow') -> None:
		"""Updates the internal list of selected files and widget states."""
		selectedItems = self._fileListWidget.selectedItems()
		self._selectedFiles = sorted([item.text() for item in selectedItems]) # Store sorted
		logger.debug(f"Selected files updated: {len(self._selectedFiles)} files")
		# Call _updateWidgetStates to reflect changes (e.g., enabling Send to LLM)
		self._updateWidgetStates()


	@Slot()
	def _handleSendToLlm(self: 'MainWindow') -> None:
		"""
		Starts the process of sending to LLM:
		1. Triggers FileWorker to read selected file contents in the background.
		2. Once files are read (_onFileContentsRead is called), triggers LLMWorker.
		"""
		if self._isBusy:
			self._showWarning("Busy", "A background task is already running.")
			return

		userInstruction: str = self._promptInput.toPlainText().strip()
		if not userInstruction:
			self._showError("LLM Instruction Missing", "Please enter instructions for the LLM.")
			return
		if not self._clonedRepoPath:
			self._showError("Repository Not Loaded", "Please clone or load a repository first.")
			return
		if not self._selectedFiles:
			logger.warning("No files selected. Sending prompt without file context.")
			# Proceed without files, fileContents dict will be empty

		logger.info("Initiating LLM request: Starting file read...")
		self._isBusy = True
		self._updateWidgetStates()
		self._updateStatusBar("Reading selected files...")
		self._updateProgress(-1, "Reading files...") # Show indeterminate progress bar

		# Trigger FileWorker to read files in the background
		# Pass the instruction along so it's available when file reading finishes
		self._fileWorker.startReadFileContents(self._clonedRepoPath, self._selectedFiles, userInstruction)


	@Slot(dict, str) # fileContents, userInstruction
	def _onFileContentsRead(self: 'MainWindow', fileContents: Dict[str, str], userInstruction: str) -> None:
		"""
		Callback slot triggered when FileWorker finishes reading file contents.
		Now builds the prompt and triggers the LLMWorker.
		"""
		logger.info(f"File reading finished. {len(fileContents)} files read. Proceeding with LLM query.")
		# Note: _isBusy is still True

		# Get LLM API Key and model name from config
		try:
			apiKey = self._configManager.getEnvVar('GEMINI_API_KEY', required=True) # Error if missing
			modelName = self._configManager.getConfigValue('General', 'DefaultLlmModel', fallback='gemini-pro')
			if not apiKey: # Should be caught by required=True, but double-check
				raise ConfigurationError("GEMINI_API_KEY environment variable not found.")
		except ConfigurationError as e:
			self._showError("Configuration Error", str(e))
			self._resetTaskState() # Reset busy state on config error
			return

		try:
			# Build the prompt using the fetched contents (synchronous, should be fast)
			prompt = self._llmInterfaceInstance.buildPrompt(userInstruction, fileContents)
		except Exception as e:
			self._showError("Prompt Building Error", f"Failed to construct LLM prompt: {e}")
			logger.error(f"Failed to construct LLM prompt: {e}", exc_info=True)
			self._resetTaskState() # Reset busy state
			return

		# Now start the LLM query worker
		self._updateStatusBar("Sending request to LLM...")
		self._updateProgress(-1, "Sending to LLM...") # Keep progress indeterminate

		# Initiate LLM query using the worker thread
		self._llmWorker.startQuery(apiKey, modelName, prompt) # Pass only needed args


	@Slot()
	def _handlePasteResponse(self: 'MainWindow') -> None:
		"""Allows user to manually paste response, then trigger parse."""
		self._llmResponseArea.clear() # Clear previous content
		self._llmResponseArea.setFocus()
		self._updateStatusBar("Paste the LLM response in the text area, then click 'Parse Response'.", 5000)


	@Slot()
	def _handleParseResponse(self: 'MainWindow') -> None:
		"""Initiates parsing the LLM response via FileWorker."""
		if self._isBusy:
			self._showWarning("Busy", "A background task is already running.")
			return

		llmResponse: str = self._llmResponseArea.toPlainText().strip()
		if not llmResponse:
			self._showError("No Response Found", "LLM Response area is empty. Cannot parse.")
			return

		# Determine expected format (e.g., JSON from config)
		try:
				expectedFormat = self._configManager.getConfigValue('General', 'ExpectedOutputFormat', fallback='json')
		except ConfigurationError as e:
				self._showError("Configuration Error", f"Could not read expected output format: {e}")
				return

		logger.info(f"Requesting LLM response parsing (format: {expectedFormat})...")
		self._isBusy = True
		self._updateWidgetStates()
		self._updateStatusBar(f"Initiating response parsing ({expectedFormat})...")
		self._updateProgress(-1, f"Parsing {expectedFormat}...") # Indeterminate progress

		# Initiate parsing using the worker thread
		self._fileWorker.startParsing(llmResponse, expectedFormat)

	@Slot()
	def _handleSaveChanges(self: 'MainWindow') -> None:
		"""Initiates saving the parsed changes to the local filesystem via FileWorker."""
		if self._isBusy:
			self._showWarning("Busy", "A background task is already running.")
			return

		if not self._parsedFileData:
			self._showError("No Data to Save", "No parsed data available. Please parse a valid LLM response first.")
			return
		if not self._clonedRepoPath or not os.path.isdir(self._clonedRepoPath):
			self._showError("Invalid Repository Path", "Cloned repository path is not valid or not set.")
			return

		fileCount = len(self._parsedFileData)
		reply = QMessageBox.question(self, 'Confirm Save',
									 f"This will overwrite {fileCount} file(s) in:\n'{self._clonedRepoPath}'\n\nAre you sure you want to proceed?",
									 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
									 QMessageBox.StandardButton.Cancel)

		if reply == QMessageBox.StandardButton.Cancel:
			return

		logger.info(f"Requesting save of {fileCount} files to {self._clonedRepoPath}...")
		self._isBusy = True
		self._updateWidgetStates()
		self._updateStatusBar("Initiating file saving...")
		self._updateProgress(-1, "Saving files...") # Indeterminate progress

		# Initiate saving using the worker thread
		self._fileWorker.startSaving(self._clonedRepoPath, self._parsedFileData)

	@Slot()
	def _handleCommitPush(self: 'MainWindow') -> None:
		"""
		Initiates staging, committing, and pushing changes via GitHubWorker,
		after checking for changes and prompting for a commit message.
		"""
		if self._isBusy:
			self._showWarning("Busy", "A background task is already running.")
			return

		if not self._clonedRepoPath or not os.path.isdir(self._clonedRepoPath):
			self._showError("Invalid Repository Path", "Cloned repository path is not valid or not set.")
			return

		# --- Check if repository is dirty (has changes) ---
		try:
			# This is a synchronous check, should be reasonably fast
			self._repoIsDirty = self._githubHandlerInstance.isDirty(self._clonedRepoPath)
			if not self._repoIsDirty:
				self._showInfo("No Changes", "No changes detected in the repository to commit.")
				self._updateWidgetStates() # Ensure button state reflects clean repo
				return
		except GitHubError as e:
			self._showError("Git Status Error", f"Could not determine repository status: {e}")
			return
		except Exception as e:
			self._showError("Error", f"An unexpected error occurred checking repository status: {e}")
			return

		# --- Prompt for Commit Message ---
		defaultCommitMessage = self._configManager.getConfigValue('GitHub', 'DefaultCommitMessage', fallback="LLM Auto-Update via Colonol Code")
		commitMessage, ok = QInputDialog.getText(
				self,
				"Commit Message",
				"Enter the commit message:",
				QLineEdit.EchoMode.Normal,
				defaultCommitMessage # Pre-fill with default
		)

		if not ok or not commitMessage.strip():
			self._showWarning("Commit Cancelled", "Commit message was empty or action was cancelled.")
			return
		commitMessage = commitMessage.strip() # Use the entered message

		# --- Get Git settings from config ---
		try:
			remoteName = self._configManager.getConfigValue('GitHub', 'DefaultRemoteName', fallback='origin')
			branchName = self._configManager.getConfigValue('GitHub', 'DefaultBranchName', fallback='main')
			# githubToken = self._configManager.getEnvVar('GITHUB_TOKEN') # Token no longer needed here
		except ConfigurationError as e:
			self._showError("Configuration Error", f"Could not read Git settings: {e}")
			return

		# --- Confirmation Dialog ---
		reply = QMessageBox.question(self, 'Confirm Commit & Push',
									 f"This will commit all current changes in:\n'{self._clonedRepoPath}'\nand attempt to push to '{remoteName}/{branchName}'.\n\nCommit Message: '{commitMessage}'\n\nAre you sure?",
									 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
									 QMessageBox.StandardButton.Cancel)

		if reply == QMessageBox.StandardButton.Cancel:
			return

		# --- Start Worker Task ---
		logger.info(f"Requesting commit and push for {self._clonedRepoPath}...")
		self._isBusy = True
		self._updateWidgetStates()
		self._updateStatusBar("Initiating commit and push...")
		self._updateProgress(-1, "Starting commit/push...") # Indeterminate progress

		# Initiate commit/push using the worker thread
		self._githubWorker.startCommitPush(self._clonedRepoPath, commitMessage, remoteName, branchName)


	# --- Worker Thread Callback Slots ---

	@Slot(int, str) # percentage, message
	def _updateProgress(self: 'MainWindow', value: int, message: str) -> None:
		"""Updates the progress bar value and status message based on worker signals."""
		if not self._isBusy: # Don't update if no task is active
			self._progressBar.setVisible(False)
			return

		self._progressBar.setVisible(True)
		if value == -1: # Indeterminate
			self._progressBar.setRange(0, 0)
			self._progressBar.setFormat("Busy...") # Custom text for indeterminate
		elif value >= 0 and value <= 100:
			self._progressBar.setRange(0, 100)
			self._progressBar.setValue(value)
			self._progressBar.setFormat("%p%") # Show percentage
		else: # Task finished or invalid value
			self._progressBar.setVisible(False)
			self._progressBar.setValue(0)
			self._progressBar.setRange(0,100)
			self._progressBar.setFormat("%p%")

		# Update status bar message as well, unless message is empty
		if message:
			self._updateStatusBar(message)


	@Slot(str, list) # repoPath, fileList
	def _onCloneFinished(self: 'MainWindow', repoPath: str, fileList: list) -> None:
		"""Handles the successful completion of the cloning/loading process."""
		logger.info(f"Clone/Load finished successfully. Path: {repoPath}, Files: {len(fileList)}")
		self._isBusy = False # Mark as not busy first
		self._clonedRepoPath = repoPath # Store the confirmed path
		self._parsedFileData = None # Reset parsed data when repo changes
		self._llmResponseArea.clear() # Clear previous LLM response
		self._updateStatusBar(f"Repository loaded ({len(fileList)} files). Checking status...", 5000)
		self._fileListWidget.clear()
		self._fileListWidget.addItems(sorted(fileList)) # Populate sorted list

		# Immediately check dirty status after loading (this will set _isBusy=True again)
		self._githubWorker.startIsDirty(self._clonedRepoPath)


	@Slot(bool) # is_dirty
	def _onIsDirtyFinished(self: 'MainWindow', is_dirty: bool) -> None:
		"""Handles the result of the isDirty check."""
		logger.info(f"Repository dirty status check completed: {is_dirty}")
		self._repoIsDirty = is_dirty
		# Reset status bar from "Checking status..." only if no other task started
		# Reset _isBusy flag AFTER the check is done
		self._isBusy = False
		self._updateStatusBar("Idle.", 5000)
		self._updateProgress(0,"") # Reset progress bar
		self._updateWidgetStates() # Update button states (e.g., Commit button)


	@Slot(str) # LLM response string
	def _onLlmFinished(self: 'MainWindow', response: str) -> None:
		"""Handles the successful completion of the LLM query."""
		logger.info(f"LLM query finished successfully. Response length: {len(response)}")
		self._isBusy = False
		self._updateStatusBar("LLM query successful.", 5000)
		self._updateProgress(100, "LLM query complete.")
		self._llmResponseArea.setPlainText(response)
		self._parsedFileData = None # Clear previous parse result
		self._updateWidgetStates()


	@Slot(dict) # parsed data dict
	def _onParsingFinished(self: 'MainWindow', parsedData: dict) -> None:
		"""Handles the successful completion of the LLM response parsing."""
		logger.info(f"Parsing finished successfully. Parsed items: {len(parsedData)}")
		self._isBusy = False
		self._parsedFileData = parsedData # Store for saving
		self._updateStatusBar(f"Response parsed successfully ({len(parsedData)} files found).", 5000)
		self._updateProgress(100, "Parsing complete.")
		self._updateWidgetStates()
		# Visually indicate parsed files/changes
		if parsedData:
			self._appendLogMessage("--- Parsed Files to be Saved ---")
			for filename in sorted(parsedData.keys()): # Log sorted
				self._appendLogMessage(f"- {filename}")
			self._appendLogMessage("------------------------------")
		else:
			self._appendLogMessage("--- Parsing Result: No files found in response ---")


	@Slot(list) # list of saved file paths
	def _onSavingFinished(self: 'MainWindow', savedFiles: list) -> None:
		"""Handles the successful completion of saving files."""
		logger.info(f"Saving finished successfully. Saved files: {len(savedFiles)}")
		self._isBusy = False
		self._updateStatusBar(f"Changes saved locally ({len(savedFiles)} files).", 5000)
		self._updateProgress(100, "Saving complete.")
		self._showInfo("Save Successful", f"{len(savedFiles)} file(s) were saved or updated in\n'{self._clonedRepoPath}'.")
		# self._parsedFileData = None # Keep parsed data in case user wants to commit now
		self._repoIsDirty = True # Assume saving makes repo dirty
		self._updateWidgetStates()


	@Slot(str) # success message string
	def _onCommitPushFinished(self: 'MainWindow', message: str) -> None:
		"""Handles the successful completion of the commit and push process."""
		logger.info(f"Commit/Push finished successfully: {message}")
		self._isBusy = False
		self._updateStatusBar("Commit and push successful.", 5000)
		self._updateProgress(100, "Commit/Push complete.")
		self._showInfo("Commit/Push Successful", message)
		self._repoIsDirty = False # Assume commit/push leaves repo clean
		self._updateWidgetStates()

	# --- Error Handling Slots ---

	@Slot(str)
	def _handleWorkerError(self: 'MainWindow', errorMessage: str) -> None:
		"""Generic handler for unexpected errors reported by worker threads."""
		logger.error(f"Unexpected worker thread error: {errorMessage}")
		self._resetTaskState() # Use helper to reset state
		self._showError("Unexpected Background Task Error", errorMessage)

	@Slot(str)
	def _handleGitHubError(self: 'MainWindow', errorMessage: str) -> None:
		"""Handler for specific Git/GitHub errors reported by GitHubWorker."""
		logger.error(f"GitHub operation failed: {errorMessage}")
		is_load_error = "clone" in errorMessage.lower() or "load" in errorMessage.lower() or "not found" in errorMessage.lower()
		self._resetTaskState()
		self._showError("GitHub Error", errorMessage)
		# Specific handling: if clone failed, reset repo path and state
		if is_load_error:
			self._clonedRepoPath = None
			self._fileListWidget.clear()
			self._repoIsDirty = False
			self._updateWidgetStates() # Update state after resetting path

	@Slot(str)
	def _handleLLMError(self: 'MainWindow', errorMessage: str) -> None:
		"""Handler for specific LLM/Configuration errors reported by LLMWorker."""
		logger.error(f"LLM operation failed: {errorMessage}")
		self._resetTaskState()
		self._showError("LLM/Configuration Error", errorMessage)
		self._llmResponseArea.setPlainText(f"Error:\n{errorMessage}") # Show error in response area

	@Slot(str)
	def _handleFileProcessingError(self: 'MainWindow', errorMessage: str) -> None:
		"""Handler for specific File/Parsing errors reported by FileWorker."""
		logger.error(f"File processing failed: {errorMessage}")
		is_parsing_error = "parsing" in errorMessage.lower() or "code block" in errorMessage.lower() or "unsafe" in errorMessage.lower()
		self._resetTaskState()
		self._showError("File Processing/Parsing Error", errorMessage)
		# If parsing failed, clear parsed data
		if is_parsing_error:
				self._parsedFileData = None
				self._updateWidgetStates()


	# --- Utility Methods ---

	def _updateWidgetStates(self: 'MainWindow') -> None:
		"""Enables/disables widgets based on the application's current state."""
		repoLoaded = self._clonedRepoPath is not None and os.path.isdir(self._clonedRepoPath)
		# filesSelected = bool(self._selectedFiles) # File selection not strictly required for LLM
		responseAvailable = bool(self._llmResponseArea.toPlainText().strip())
		parsedDataAvailable = self._parsedFileData is not None and isinstance(self._parsedFileData, dict) and len(self._parsedFileData) > 0
		repoIsPotentiallyDirty = repoLoaded and self._repoIsDirty # Use cached dirty state

		# Enable/disable based on busy state first
		enabledIfNotBusy = not self._isBusy

		self._repoUrlInput.setEnabled(enabledIfNotBusy)
		self._browseButton.setEnabled(enabledIfNotBusy)
		self._cloneButton.setEnabled(enabledIfNotBusy)
		self._fileListWidget.setEnabled(enabledIfNotBusy and repoLoaded)
		self._promptInput.setEnabled(enabledIfNotBusy and repoLoaded)
		# Send to LLM enabled if repo loaded and not busy (file selection is optional)
		self._sendToLlmButton.setEnabled(enabledIfNotBusy and repoLoaded)
		self._pasteResponseButton.setEnabled(enabledIfNotBusy)
		self._llmResponseArea.setEnabled(enabledIfNotBusy) # Keep enabled for pasting
		self._parseButton.setEnabled(enabledIfNotBusy and responseAvailable)
		self._saveFilesButton.setEnabled(enabledIfNotBusy and parsedDataAvailable and repoLoaded)
		self._commitPushButton.setEnabled(enabledIfNotBusy and repoLoaded and repoIsPotentiallyDirty)


	def _resetTaskState(self: 'MainWindow') -> None:
		"""Resets progress bar and status bar after a task completes or fails."""
		self._isBusy = False
		# Don't reset dirty status here, let _onIsDirtyFinished or commit handle it
		self._updateWidgetStates()
		self._updateProgress(0, "Task finished or failed.") # Explicitly hide/reset progress bar
		self._updateStatusBar("Idle.")


	def _updateStatusBar(self: 'MainWindow', message: str, timeout: int = 0) -> None:
		"""Updates the status bar message (thread-safe via signals)."""
		self._statusBar.showMessage(message, timeout)


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
		"""Appends a message to the GUI log area (thread-safe via signal)."""
		self._logArea.append(message)
		# Optional: Scroll to the bottom
		# self._logArea.verticalScrollBar().setValue(self._logArea.verticalScrollBar().maximum())


	def closeEvent(self: 'MainWindow', event) -> None:
		"""Handles the window close event."""
		if self._isBusy:
			reply = QMessageBox.question(self, 'Confirm Exit',
										 "A background task is currently running. Exiting now might cause issues.\nAre you sure you want to exit?",
										 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
										 QMessageBox.StandardButton.Cancel)
			if reply == QMessageBox.StandardButton.Cancel:
				event.ignore()
				return

		# Attempt graceful shutdown of worker threads if they are running
		# QThread.quit() is advisory; use stop flags if threads have long loops.
		# wait() gives threads time to finish event processing.
		logger.info("Attempting graceful shutdown of worker threads...")
		workers = [self._githubWorker, self._llmWorker, self._fileWorker]
		for worker in workers:
			if worker and worker.isRunning():
				worker_name = worker.__class__.__name__
				logger.debug(f"Requesting quit for {worker_name}...")
				worker.quit() # Request event loop termination
				if not worker.wait(1500): # Wait max 1.5 sec
						logger.warning(f"{worker_name} did not finish gracefully. Forcing termination (may be unsafe).")
						worker.terminate() # Force terminate if quit/wait fails

		logger.info("Close event accepted. Application shutting down.")
		super().closeEvent(event)

# --- END: gui/main_window.py ---