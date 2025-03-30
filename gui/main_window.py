# gui/main_window.py
# Updated to use .codebaseignore

"""
Main application window module for the GUI application.

This module defines the primary window interface and coordinates all user
interactions, background tasks, and visual updates. It handles:
- Repository management (clone, pull, commit)
- File selection and display (using .codebaseignore for initial filtering)
- LLM interactions and response processing
- Code validation and diff viewing
- Error handling and status updates

The window uses multiple worker threads to prevent UI freezing during
long-running operations.
"""

# Standard library imports
import os
import logging
import difflib
import html
from typing import Optional, Dict, List, Tuple

# Qt imports
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit,
    QListWidget, QProgressBar, QStatusBar,
    QMessageBox, QSplitter, QFileDialog,
    QInputDialog, QTabWidget, QListWidgetItem
)
from PySide6.QtCore import Qt, Slot, Signal
from PySide6.QtGui import QIcon, QFont

# Local imports
from core.config_manager import ConfigManager
from core.exceptions import (
    ConfigurationError
)
from core.github_handler import GitHubHandler
from core.llm_interface import LLMInterface
from gui.threads import GitHubWorker, LLMWorker, FileWorker
from gui.gui_utils import QtLogHandler

# Initialize logging
logger: logging.Logger = logging.getLogger(__name__)

# Constants for UI styling
HTML_COLOR_ADDED_BG = "#e6ffed"
HTML_COLOR_DELETED_BG = "#ffeef0"
HTML_COLOR_PLACEHOLDER_BG = "#f8f9fa"
HTML_COLOR_LINE_NUM = "#6c757d"
HTML_COLOR_TEXT = "#212529"
HTML_FONT_FAMILY = "'Courier New', Courier, monospace"
HTML_FONT_SIZE = "9pt"
CORRECTION_RETRY_TEMPERATURE = 0.4  # Lower temperature for correction attempts

class MainWindow(QMainWindow):
    """
    Main application window implementing the primary user interface.

    Coordinates all user interactions, background tasks, and visual updates.
    Manages multiple worker threads for long-running operations.

    Signals:
        signalLogMessage (str): Emitted to update the log display
    """

    signalLogMessage = Signal(str)

    def __init__(self: 'MainWindow', configManager: ConfigManager, parent: Optional[QWidget] = None) -> None:
        """
        Initialize the main window.

        Args:
            configManager: Configuration manager instance
            parent: Optional parent widget
        """
        super().__init__(parent)
        self._configManager = configManager

        # Initialize state variables
        self._selectedFiles = [] # List of relative paths
        self._originalFileContents = {} # Cache of original file contents {rel_path: content}
        self._clonedRepoPath = None
        self._parsedFileData = None # {rel_path: proposed_content}
        self._validationErrors = None # {rel_path: [error_messages]}
        self._isBusy = False
        self._repoIsDirty = False
        self._is_syncing_scroll = False
        self._correction_attempted = False

        # Initialize core handlers
        self._githubHandlerInstance = GitHubHandler()
        self._llmInterfaceInstance = LLMInterface(configManager=self._configManager)

        logger.info("Initializing MainWindow...")
        self._setupUI()
        self._loadInitialSettings()

        # Initialize workers
        self._githubWorker = GitHubWorker(parent=self)
        self._llmWorker = LLMWorker(parent=self, configManager=self._configManager)
        self._fileWorker = FileWorker(parent=self)

        self._connectSignals()
        self._updateWidgetStates()
        self._setupGuiLogging()

        logger.info("MainWindow initialized.")

    # --- UI Setup ---
    def _setupUI(self: 'MainWindow') -> None:
        """Sets up the user interface layout and widgets."""
        logger.debug("Setting up UI elements.")
        self.setWindowTitle("Colonel Code - LLM Code Updater")
        iconPath = os.path.join('resources', 'app_icon.png')
        if os.path.exists(iconPath): self.setWindowIcon(QIcon(iconPath))
        else: logger.warning(f"Application icon not found at: {iconPath}")

        self._centralWidget = QWidget()
        self.setCentralWidget(self._centralWidget)
        self._mainLayout = QVBoxLayout(self._centralWidget)

        # --- Top: Repo Input and Controls ---
        repoLayout = QHBoxLayout()
        repoLabel = QLabel("GitHub Repo URL / Local Path:")
        self._repoUrlInput = QLineEdit()
        self._repoUrlInput.setPlaceholderText("https://github.com/user/repo.git or /path/to/local/repo")
        self._repoUrlInput.setToolTip("Enter the URL of the GitHub repository (HTTPS or SSH) or the full path to an existing local repository.")
        self._browseButton = QPushButton("Browse...")
        self._browseButton.setToolTip("Browse for a local repository folder.")
        self._cloneButton = QPushButton("Clone / Load Repo")
        self._cloneButton.setToolTip("Clone the remote repository or load the selected local repository.")
        repoLayout.addWidget(repoLabel)
        repoLayout.addWidget(self._repoUrlInput, 1)
        repoLayout.addWidget(self._browseButton)
        repoLayout.addWidget(self._cloneButton)
        self._mainLayout.addLayout(repoLayout)

        # --- Middle: File List and Prompt/LLM Interaction ---
        middleSplitter = QSplitter(Qt.Orientation.Horizontal)

        # Middle Left: File List
        fileListLayout = QVBoxLayout()
        fileListLabel = QLabel("Select Files for Context:")
        self._fileListWidget = QListWidget()
        self._fileListWidget.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self._fileListWidget.setToolTip("Select one or more files (Ctrl/Cmd+Click or Shift+Click) to include their content in the prompt sent to the LLM. Focus on one file (single click) to view its diff below.")
        fileListLayout.addWidget(fileListLabel)
        fileListLayout.addWidget(self._fileListWidget)
        fileListWidgetContainer = QWidget()
        fileListWidgetContainer.setLayout(fileListLayout)
        middleSplitter.addWidget(fileListWidgetContainer)

        # Middle Right: Prompt Input and LLM Buttons
        promptLayout = QVBoxLayout()
        promptLabel = QLabel("LLM Instruction / Prompt:")
        self._promptInput = QTextEdit()
        self._promptInput.setPlaceholderText("Enter your instructions for code modification based on selected files...")
        self._promptInput.setToolTip("Describe the changes you want the LLM to make to the selected files.")
        llmInteractionLayout = QHBoxLayout() # Buttons remain here
        self._sendToLlmButton = QPushButton("Send to LLM")
        self._sendToLlmButton.setToolTip("Send the instruction and selected file contents to the LLM for processing.")
        self._pasteResponseButton = QPushButton("Paste LLM Response")
        self._pasteResponseButton.setToolTip("Manually paste a response from an external LLM into the 'LLM Response' tab below.")
        llmInteractionLayout.addWidget(self._sendToLlmButton)
        llmInteractionLayout.addWidget(self._pasteResponseButton)
        llmInteractionLayout.addStretch(1)
        promptLayout.addWidget(promptLabel)
        promptLayout.addWidget(self._promptInput, stretch=1) # Prompt input takes most space
        promptLayout.addLayout(llmInteractionLayout) # Add buttons below prompt
        # LLM Response Area is MOVED to bottom tabs
        promptWidgetContainer = QWidget()
        promptWidgetContainer.setLayout(promptLayout)
        middleSplitter.addWidget(promptWidgetContainer)

        middleSplitter.setSizes([300, 600]) # Adjust initial sizes if needed
        self._mainLayout.addWidget(middleSplitter, stretch=1)

        # --- Bottom: Action Buttons and Tabs ---
        bottomLayout = QVBoxLayout()
        actionLayout = QHBoxLayout()
        self._parseButton = QPushButton("Parse & Validate")
        self._parseButton.setToolTip("Parse the LLM response (from the tab below), extract code changes, and validate syntax.")
        self._saveFilesButton = QPushButton("Save Changes Locally")
        self._saveFilesButton.setToolTip("Save the validated, proposed changes to the local files in the repository.")
        self._commitPushButton = QPushButton("Commit & Push")
        self._commitPushButton.setToolTip("Commit the currently staged changes in the local repository and push them to the default remote/branch.")
        actionLayout.addWidget(self._parseButton)
        actionLayout.addWidget(self._saveFilesButton)
        actionLayout.addWidget(self._commitPushButton)
        actionLayout.addStretch(1)
        bottomLayout.addLayout(actionLayout)

        self._bottomTabWidget = QTabWidget()
        self._bottomTabWidget.setToolTip("View diffs, LLM responses, and application logs.")

        # Tab 1: Side-by-Side Diff (for focused file)
        diffWidget = QWidget()
        diffLayout = QVBoxLayout(diffWidget)
        diffSplitter = QSplitter(Qt.Orientation.Horizontal)
        codeFont = QFont(HTML_FONT_FAMILY.split(',')[0].strip("'"))
        codeFont.setStyleHint(QFont.StyleHint.Monospace)
        codeFont.setPointSize(int(HTML_FONT_SIZE.replace('pt','')))
        originalLayout = QVBoxLayout()
        originalLayout.addWidget(QLabel("Original Code (Focused File):"))
        self._originalCodeArea = QTextEdit()
        self._originalCodeArea.setReadOnly(True)
        self._originalCodeArea.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self._originalCodeArea.setFont(codeFont)
        self._originalCodeArea.setToolTip("Shows the original content of the file currently focused in the list above.")
        originalContainer = QWidget()
        originalContainer.setLayout(originalLayout)
        diffSplitter.addWidget(originalContainer)
        proposedLayout = QVBoxLayout()
        proposedLayout.addWidget(QLabel("Proposed Code (Focused File):"))
        self._proposedCodeArea = QTextEdit()
        self._proposedCodeArea.setReadOnly(True)
        self._proposedCodeArea.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self._proposedCodeArea.setFont(codeFont)
        self._proposedCodeArea.setToolTip("Shows the proposed changes (after parsing) or indicates status.")
        proposedContainer = QWidget()
        proposedContainer.setLayout(proposedLayout)
        diffSplitter.addWidget(proposedContainer)
        diffSplitter.setSizes([400, 400])
        diffLayout.addWidget(diffSplitter)
        self._bottomTabWidget.addTab(diffWidget, "Side-by-Side Diff")

        # Tab 2: LLM Response
        llmResponseWidget = QWidget()
        llmResponseLayout = QVBoxLayout(llmResponseWidget)
        self._llmResponseArea = QTextEdit() # The moved widget
        self._llmResponseArea.setPlaceholderText("LLM response will appear here, or paste response and click 'Parse & Validate'")
        self._llmResponseArea.setReadOnly(False)
        self._llmResponseArea.setToolTip("Displays the raw response from the LLM or allows pasting a response.")
        llmResponseLayout.addWidget(self._llmResponseArea)
        self._bottomTabWidget.addTab(llmResponseWidget, "LLM Response")

        # Tab 3: Application Log
        self._appLogArea = QTextEdit()
        self._appLogArea.setReadOnly(True)
        self._appLogArea.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        logFont = QFont("monospace")
        logFont.setPointSize(10)
        self._appLogArea.setFont(logFont)
        self._appLogArea.setToolTip("Shows detailed application logs, including errors and status updates.")
        self._bottomTabWidget.addTab(self._appLogArea, "Application Log")

        bottomLayout.addWidget(self._bottomTabWidget, stretch=1)
        self._mainLayout.addLayout(bottomLayout, stretch=1)

        # --- Status Bar ---
        self._statusBar = QStatusBar()
        self.setStatusBar(self._statusBar)
        self._progressBar = QProgressBar()
        self._progressBar.setVisible(False)
        self._progressBar.setTextVisible(True)
        self._progressBar.setRange(0, 100)
        self._progressBar.setValue(0)
        self._progressBar.setFormat("%p%")
        self._progressBar.setToolTip("Shows the progress of background operations.")
        self._statusBar.addPermanentWidget(self._progressBar)

        self.setGeometry(100, 100, 1100, 850)
        logger.debug("UI setup complete.")

    # --- Load/Save Settings ---
    def _loadInitialSettings(self: 'MainWindow') -> None:
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
        try:
            logger.debug(f"Attempting to save last repo path: {repoPath}")
            self._configManager.setConfigValue('General', 'LastRepoPath', repoPath)
            logger.info(f"Saved last repository path to config: {repoPath}")
        except ConfigurationError as e:
            logger.error(f"Failed to save LastRepoPath to config: {e}")
        except Exception as e:
            logger.error(f"Unexpected error saving last repo path: {e}", exc_info=True)

    # --- Signal Connections ---
    def _connectSignals(self: 'MainWindow') -> None:
        logger.debug("Connecting signals to slots.")
        self._browseButton.clicked.connect(self._handleBrowseRepo)
        self._cloneButton.clicked.connect(self._handleCloneRepo)

        # Connect itemSelectionChanged for multi-selection state update
        # Connect currentItemChanged for updating diff view based on focus
        self._fileListWidget.itemSelectionChanged.connect(self._handleSelectionChange)
        self._fileListWidget.currentItemChanged.connect(self._handleCurrentItemChanged) # Handles focus change for diff

        self._sendToLlmButton.clicked.connect(self._handleSendToLlm)
        self._pasteResponseButton.clicked.connect(self._handlePasteResponse)
        self._parseButton.clicked.connect(self._handleParseAndValidate)
        self._saveFilesButton.clicked.connect(self._handleSaveChanges)
        self._commitPushButton.clicked.connect(self._handleCommitPush)

        # Worker signals
        self._githubWorker.statusUpdate.connect(self._updateStatusBar)
        self._githubWorker.progressUpdate.connect(self._updateProgress)
        self._githubWorker.errorOccurred.connect(self._handleWorkerError)
        self._githubWorker.gitHubError.connect(self._handleGitHubError)
        self._githubWorker.cloneFinished.connect(self._onCloneFinished)
        self._githubWorker.commitPushFinished.connect(self._onCommitPushFinished)
        self._githubWorker.isDirtyFinished.connect(self._onIsDirtyFinished)
        self._githubWorker.pullFinished.connect(self._onPullFinished)

        self._llmWorker.statusUpdate.connect(self._updateStatusBar)
        self._llmWorker.progressUpdate.connect(self._updateProgress)
        self._llmWorker.errorOccurred.connect(self._handleWorkerError)
        self._llmWorker.llmError.connect(self._handleLLMError)
        self._llmWorker.llmQueryFinished.connect(self._onLlmFinished)

        self._fileWorker.statusUpdate.connect(self._updateStatusBar)
        self._fileWorker.progressUpdate.connect(self._updateProgress)
        self._fileWorker.errorOccurred.connect(self._handleWorkerError)
        self._fileWorker.fileProcessingError.connect(self._handleFileProcessingError)
        self._fileWorker.parsingFinished.connect(self._onParsingFinished)
        self._fileWorker.savingFinished.connect(self._onSavingFinished)
        self._fileWorker.fileContentsRead.connect(self._onFileContentsRead)

        # Internal signals
        self.signalLogMessage.connect(self._appendLogMessage)

        # Scroll synchronization
        orig_scrollbar = self._originalCodeArea.verticalScrollBar()
        prop_scrollbar = self._proposedCodeArea.verticalScrollBar()
        orig_scrollbar.valueChanged.connect(self._syncScrollProposedFromOriginal)
        prop_scrollbar.valueChanged.connect(self._syncScrollOriginalFromProposed)

        logger.debug("Signal connections established.")

    # --- GUI Logging ---
    def _setupGuiLogging(self: 'MainWindow') -> None:
        try:
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
        except ImportError:
            logger.error("QtLogHandler import failed. GUI logging disabled.")
        except Exception as e:
            logger.error(f"Failed to setup GUI logging handler: {e}", exc_info=True)

    # --- Slots (Event Handlers) ---
    @Slot()
    def _handleBrowseRepo(self: 'MainWindow') -> None:
        startDir = self._repoUrlInput.text() or os.path.expanduser("~")
        directory = QFileDialog.getExistingDirectory(self, "Select Local Repository Folder", startDir)
        if directory:
            self._repoUrlInput.setText(directory)

    @Slot()
    def _handleCloneRepo(self: 'MainWindow') -> None:
        # Guard against busy state first
        if self._isBusy:
            self._showWarning("Busy", "Another task is currently running. Please wait.")
            return

        # Get and validate repo URL/path
        repoUrlOrPath = self._repoUrlInput.text().strip()
        if not repoUrlOrPath:
            self._showError("Repository Missing", "Please enter a repository URL or select a local path.")
            return

        # Determine clone target path
        try:
            if os.path.isdir(repoUrlOrPath):
                # Use the provided path directly if it's already a directory
                cloneTargetFullPath = os.path.abspath(repoUrlOrPath)
            else:
                # Construct a path in the default clone directory
                defaultCloneDir = self._configManager.getConfigValue('General', 'DefaultCloneDir', fallback='./cloned_repos')
                cloneBaseDir = os.path.abspath(defaultCloneDir)
                os.makedirs(cloneBaseDir, exist_ok=True)
                # Generate a safe directory name from the URL/path
                repoName = os.path.basename(repoUrlOrPath.rstrip('/'))
                repoName = repoName[:-4] if repoName.endswith('.git') else repoName
                safeRepoName = "".join(c for c in repoName if c.isalnum() or c in ('-', '_')).strip() or "repository"
                cloneTargetFullPath = os.path.join(cloneBaseDir, safeRepoName)
        except ConfigurationError as e:
            self._showError("Configuration Error", f"Could not determine clone directory from config: {e}")
            return
        except OSError as e:
            self._showError("Path Error", f"Could not create clone directory '{cloneBaseDir}': {e}")
            return
        except Exception as e:
            self._showError("Path Error", f"Could not determine target path for cloning: {e}")
            return

        # Start clone operation
        self._isBusy = True
        self._updateWidgetStates()
        self._updateStatusBar("Loading/Cloning repository...")
        self._updateProgress(-1, "Starting clone/load...")

        # Clear previous state
        self._clonedRepoPath = None
        self._fileListWidget.clear()
        self._selectedFiles = []
        self._originalFileContents.clear()
        self._parsedFileData = None
        self._validationErrors = None
        self._originalCodeArea.clear()
        self._proposedCodeArea.clear()
        self._llmResponseArea.clear()
        self._promptInput.clear()

        # Start clone worker
        self._githubWorker.startClone(repoUrlOrPath, cloneTargetFullPath, None) # Auth token not used here

    # --- Handle selection state update separately ---
    @Slot()
    def _handleSelectionChange(self: 'MainWindow') -> None:
        """Update the internal list of selected files when selection changes."""
        selectedItems = self._fileListWidget.selectedItems()
        self._selectedFiles = sorted([item.text() for item in selectedItems])
        logger.debug(f"Selection changed. Currently selected: {len(self._selectedFiles)} files.")
        # Diff view update is handled by _handleCurrentItemChanged

    # --- Handle focused item change for diff display ---
    @Slot(QListWidgetItem, QListWidgetItem)
    def _handleCurrentItemChanged(self: 'MainWindow', current: Optional[QListWidgetItem], previous: Optional[QListWidgetItem]) -> None:
        """Handle changes in the *currently focused* item to update the diff view."""
        if self._isBusy: return
        # logger.debug(f"Current item changed. New focus: {current.text() if current else 'None'}") # Too verbose
        self._displaySelectedFileDiff(current, previous)

    # --- Diff display logic (uses focused item) ---
    @Slot(QListWidgetItem, QListWidgetItem)
    def _displaySelectedFileDiff(self: 'MainWindow', current: Optional[QListWidgetItem], previous: Optional[QListWidgetItem]) -> None:
        """Displays the diff for the currently focused file item."""
        _ = previous; # Not used currently
        if self._isBusy: return # Avoid updates during critical operations

        self._originalCodeArea.clear()
        self._proposedCodeArea.clear()

        if not current:
            self._updateStatusBar("Select a file to view diff.", 3000)
            self._syncScrollbars()
            return

        filePath: str = current.text()

        # Ensure original content is loaded if missing (e.g., after parse)
        if filePath not in self._originalFileContents and self._clonedRepoPath:
            full_path = os.path.join(self._clonedRepoPath, filePath)
            if os.path.exists(full_path) and os.path.isfile(full_path):
                try:
                    # Limit file size to read, e.g., 1MB to prevent memory issues
                    MAX_DIFF_FILE_SIZE = 1 * 1024 * 1024
                    if os.path.getsize(full_path) > MAX_DIFF_FILE_SIZE:
                         logger.warning(f"Original file {filePath} too large for diff view ({os.path.getsize(full_path)} bytes). Skipping read.")
                         self._originalFileContents[filePath] = f"<File too large to display in diff (>{MAX_DIFF_FILE_SIZE // 1024} KB)>"
                    else:
                        with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
                            self._originalFileContents[filePath] = f.read()
                        logger.debug(f"Lazily loaded original content for {filePath}")
                except Exception as e:
                    logger.error(f"Error reading original file {filePath} for diff: {e}", exc_info=True)
                    self._originalFileContents[filePath] = f"<Error reading file: {e}>"
            else:
                 # If the file doesn't exist locally, it might be a new file proposed by LLM
                 self._originalFileContents[filePath] = None # Explicitly mark as non-existent originally
                 logger.debug(f"Original file {filePath} not found locally or is not a file.")

        original_content = self._originalFileContents.get(filePath, None)
        proposed_content = None
        is_new_file = False
        status_msg = f"Displaying Diff: {filePath}"
        validation_info = ""

        # Determine validation status string
        if self._validationErrors and filePath in self._validationErrors:
            count = len(self._validationErrors[filePath])
            validation_info = f" - <font color='red'><b>Validation Failed ({count} errors)</b></font>"
        elif self._parsedFileData is not None and filePath in self._parsedFileData and self._validationErrors is not None:
            # Only show OK if parsed data exists for this file AND there are no validation errors overall for this file
            validation_info = " - <font color='green'>Validation OK</font>"

        # Determine proposed content based on parsed data
        if self._parsedFileData is not None:
            if filePath in self._parsedFileData:
                proposed_content = self._parsedFileData[filePath]
                if original_content is None: # Original didn't exist or couldn't be read
                    is_new_file = True
                    original_content = "" # Treat as diff against empty
                    status_msg += " - New File"
                elif original_content == proposed_content:
                    status_msg += " - Original == Proposed (No Changes)"
                else:
                    status_msg += " - Original vs Proposed"
            elif original_content is not None:
                 # File exists, but wasn't in parsed data (no change proposed by LLM)
                 proposed_content = original_content # Show original on both sides
                 status_msg += " - Original (No Changes Proposed)"
                 validation_info = "" # No validation status needed if no changes proposed
            else:
                 # File path from list widget doesn't exist in original or proposed (edge case)
                 proposed_content = "(File details unavailable)"
                 original_content = proposed_content
                 validation_info = ""
                 status_msg += " - (Error: Content unavailable)"
        elif original_content is not None:
            # No parsed data YET, show original vs placeholder
            proposed_content = "<No proposed changes yet. Send to LLM and Parse response.>" # More explicit placeholder
            status_msg += " - Original (Awaiting LLM Response & Parse)" # Update status too
            validation_info = ""
        else:
            # No original content loaded (e.g., before clone or file doesn't exist)
            original_content = "(Content not loaded or file is new)"
            proposed_content = "<No proposed changes yet. Send to LLM and Parse response.>" # Use same explicit placeholder
            status_msg += " - (Awaiting Context / LLM Response & Parse)"
            validation_info = ""

        # Generate and display HTML diff
        # Handle potential large content causing performance issues
        try:
            # Limit lines processed for diff generation if content is huge
            MAX_DIFF_LINES = 5000
            original_lines = (original_content or "").splitlines()
            proposed_lines = (proposed_content or "").splitlines()

            if len(original_lines) > MAX_DIFF_LINES or len(proposed_lines) > MAX_DIFF_LINES:
                 logger.warning(f"Content of {filePath} too long ({len(original_lines)}/{len(proposed_lines)} lines), truncating diff comparison to {MAX_DIFF_LINES} lines.")
                 original_html = f"<p style='color:orange;'>Diff truncated for performance ({MAX_DIFF_LINES} lines shown).</p>" + self._generate_diff_html(original_lines[:MAX_DIFF_LINES], proposed_lines[:MAX_DIFF_LINES], is_new_file)[0]
                 proposed_html = f"<p style='color:orange;'>Diff truncated for performance ({MAX_DIFF_LINES} lines shown).</p>" + self._generate_diff_html(original_lines[:MAX_DIFF_LINES], proposed_lines[:MAX_DIFF_LINES], is_new_file)[1]
            else:
                 original_html, proposed_html = self._generate_diff_html(original_lines, proposed_lines, is_new_file)

        except Exception as e:
            logger.error(f"Error generating HTML diff for {filePath}: {e}", exc_info=True)
            original_html = f"<body><p style='color:red;'>Error generating diff: {html.escape(str(e))}</p></body>"
            proposed_html = "<body><p style='color:red;'>Error generating diff.</p></body>"

        # Block signals during HTML set to prevent recursive scroll sync
        orig_sb = self._originalCodeArea.verticalScrollBar()
        prop_sb = self._proposedCodeArea.verticalScrollBar()
        orig_sb.blockSignals(True)
        prop_sb.blockSignals(True)

        # Use setHtml which is generally better for rich text
        self._originalCodeArea.setHtml(original_html)
        self._proposedCodeArea.setHtml(proposed_html)

        orig_sb.blockSignals(False)
        prop_sb.blockSignals(False)

        self._updateStatusBar(status_msg + validation_info, 10000)
        self._syncScrollbars() # Sync scrollbars after content is set

    def _generate_diff_html(self: 'MainWindow', original_lines: List[str], proposed_lines: List[str], is_new_file: bool) -> Tuple[str, str]:
        """Generates side-by-side HTML diff for two lists of strings."""
        # Define base HTML structure and CSS styles
        html_style = (f"<style>body{{margin:0;padding:0;font-family:{HTML_FONT_FAMILY};font-size:{HTML_FONT_SIZE};color:{HTML_COLOR_TEXT};background-color:#fff;}}"
                      f".line{{display:flex;white-space:pre;min-height:1.2em;border-bottom:1px solid #eee;}}"
                      f".line-num{{flex:0 0 40px;text-align:right;padding-right:10px;color:{HTML_COLOR_LINE_NUM};background-color:#f1f1f1;user-select:none;border-right:1px solid #ddd;}}"
                      f".line-content{{flex-grow:1;padding-left:10px;}}"
                      f".equal{{background-color:#fff;}}.delete{{background-color:{HTML_COLOR_DELETED_BG};}}"
                      f".insert{{background-color:{HTML_COLOR_ADDED_BG};}}"
                      f".placeholder{{background-color:{HTML_COLOR_PLACEHOLDER_BG};color:#aaa;font-style:italic;}}"
                      f".new-file-placeholder{{background-color:{HTML_COLOR_DELETED_BG};color:#aaa;font-style:italic;text-align:center;}}" # Style for new file placeholder
                      f"</style>")

        original_html_body = []
        proposed_html_body = []

        def format_line(num: Optional[int], content: str, css_class: str) -> str:
            """Helper function to format a single line of HTML diff."""
            # Escape content and handle spaces for HTML preformatted text
            escaped_content = html.escape(content).replace(" ", "&nbsp;") or "&nbsp;"
            num_str = str(num) if num is not None else "&nbsp;" # Use number if provided, else non-breaking space
            return f'<div class="line {css_class}"><div class="line-num">{num_str}</div><div class="line-content">{escaped_content}</div></div>'

        if is_new_file:
            # Special case for new files: show placeholder on left, all inserted lines on right
            original_html_body.append('<div class="line new-file-placeholder"><div class="line-num">&nbsp;</div><div class="line-content">&lt;New File&gt;</div></div>')
            for i, line in enumerate(proposed_lines):
                proposed_html_body.append(format_line(i + 1, line, 'insert'))
        else:
            # Use difflib for generating diff operations
            matcher = difflib.SequenceMatcher(None, original_lines, proposed_lines, autojunk=False)
            o_num, p_num = 1, 1 # Line numbers for original and proposed

            for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                # Iterate through the segments identified by the opcode
                max_len = max(i2 - i1, j2 - j1)
                for i in range(max_len):
                    o_idx, p_idx = i1 + i, j1 + i
                    o_line, p_line = "", ""
                    o_css, p_css = "placeholder", "placeholder" # Default to placeholder style
                    o_ln, p_ln = None, None # Line numbers initially None

                    if tag == 'equal':
                        # Lines are the same in both versions
                        if o_idx < i2: o_line, o_css, o_ln = original_lines[o_idx], 'equal', o_num; o_num += 1
                        if p_idx < j2: p_line, p_css, p_ln = proposed_lines[p_idx], 'equal', p_num; p_num += 1
                    elif tag == 'delete':
                        # Line exists only in the original version
                        if o_idx < i2: o_line, o_css, o_ln = original_lines[o_idx], 'delete', o_num; o_num += 1
                        p_line, p_css, p_ln = "", 'placeholder', None # Empty placeholder on the proposed side
                    elif tag == 'insert':
                        # Line exists only in the proposed version
                        o_line, o_css, o_ln = "", 'placeholder', None # Empty placeholder on the original side
                        if p_idx < j2: p_line, p_css, p_ln = proposed_lines[p_idx], 'insert', p_num; p_num += 1
                    elif tag == 'replace':
                        # Line is modified between versions
                        if o_idx < i2: o_line, o_css, o_ln = original_lines[o_idx], 'delete', o_num; o_num += 1
                        else: o_line, o_css, o_ln = "", 'placeholder', None # Placeholder if original side is shorter
                        if p_idx < j2: p_line, p_css, p_ln = proposed_lines[p_idx], 'insert', p_num; p_num += 1
                        else: p_line, p_css, p_ln = "", 'placeholder', None # Placeholder if proposed side is shorter

                    # Append formatted lines to respective HTML bodies
                    original_html_body.append(format_line(o_ln, o_line, o_css))
                    proposed_html_body.append(format_line(p_ln, p_line, p_css))

        # Combine style, body, and closing tags for the final HTML
        final_original_html = html_style + "<body>\n" + "\n".join(original_html_body) + "\n</body>"
        final_proposed_html = html_style + "<body>\n" + "\n".join(proposed_html_body) + "\n</body>"

        return final_original_html, final_proposed_html

    # --- Send to LLM (Use potentially multiple selected files) ---
    @Slot()
    def _handleSendToLlm(self: 'MainWindow') -> None:
        if self._isBusy: self._showWarning("Busy", "Another task is currently running. Please wait."); return
        userInstruction: str = self._promptInput.toPlainText().strip()
        if not userInstruction: self._showError("LLM Instruction Missing", "Please enter instructions for the LLM."); return
        if not self._clonedRepoPath: self._showError("Repository Not Loaded", "Please load a repository before sending to the LLM."); return

        # _selectedFiles is updated by _handleSelectionChange
        if not self._selectedFiles:
            reply = QMessageBox.question(self, "No Files Selected",
                                       "No files are selected to provide context to the LLM. Proceed without file context?",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                      QMessageBox.StandardButton.Cancel)
            if reply == QMessageBox.StandardButton.Cancel: return
            file_context_msg = "without file context"
            plural = '' # For status message consistency
            file_count = 0
        else:
            file_count = len(self._selectedFiles)
            plural = 's' if file_count > 1 else ''
            file_context_msg = f"with context from {file_count} file{plural}"

        logger.info(f"Preparing to send instructions to LLM {file_context_msg}.")

        self._correction_attempted = False
        self._isBusy = True
        self._updateWidgetStates()
        self._originalFileContents.clear() # Clear old cache before reading new selection
        self._parsedFileData = None
        self._validationErrors = None
        self._originalCodeArea.clear()
        self._proposedCodeArea.clear()
        self._llmResponseArea.clear()
        self._updateStatusBar(f"Reading {file_count} file{plural} for LLM context...");
        self._updateProgress(-1, f"Reading {file_count} file{plural}...")
        # Pass the list (potentially multiple items) to the worker
        self._fileWorker.startReadFileContents(self._clonedRepoPath, self._selectedFiles, userInstruction)

    # --- File Contents Read ---
    @Slot(dict, str)
    def _onFileContentsRead(self: 'MainWindow', fileContents: Dict[str, str], userInstruction: str) -> None:
        if not self._isBusy: return # Avoid processing if task was somehow cancelled

        logger.info(f"File reading finished ({len(fileContents)} files). Querying LLM...")
        self._originalFileContents = fileContents # Store original contents
        self._displaySelectedFileDiff(self._fileListWidget.currentItem(), None) # Update diff for focused file

        try:
            modelName = self._configManager.getConfigValue('General', 'DefaultLlmModel', fallback='gemini-1.5-flash-latest') or 'gemini-1.5-flash-latest'
        except ConfigurationError as e:
            self._showError("Config Error", f"Could not read LLM model from config: {e}")
            self._resetTaskState()
            return
        try:
            prompt = self._llmInterfaceInstance.buildPrompt(userInstruction, fileContents)
            logger.debug(f"Built prompt for LLM (length: {len(prompt)} chars).")
        except Exception as e:
            self._showError("Prompt Error", f"Failed to build prompt for LLM: {e}")
            self._resetTaskState()
            return

        self._updateStatusBar("Sending request to LLM...");
        self._updateProgress(-1, "Sending to LLM...")
        # Send original query
        self._llmWorker.startQuery(modelName, prompt)

    # --- Paste Response (Reset correction flag, switch tab) ---
    @Slot()
    def _handlePasteResponse(self: 'MainWindow') -> None:
        if self._isBusy: self._showWarning("Busy", "Another operation is in progress."); return

        self._llmResponseArea.clear()
        self._parsedFileData = None
        self._validationErrors = None
        # Clear only proposed area, keep original area based on focus
        self._proposedCodeArea.clear()
        # Don't clear originalFileContents here, it holds the baseline

        # Switch to the LLM Response tab
        llm_tab_index = -1
        for i in range(self._bottomTabWidget.count()):
            if self._bottomTabWidget.tabText(i) == "LLM Response":
                llm_tab_index = i
                break
        if llm_tab_index != -1:
            self._bottomTabWidget.setCurrentIndex(llm_tab_index)
        else:
            logger.warning("Could not find 'LLM Response' tab to switch to.")

        self._llmResponseArea.setFocus()
        # Reset correction flag
        self._correction_attempted = False
        self._updateStatusBar("Paste LLM response into the 'LLM Response' tab, then click 'Parse & Validate'.", 5000)
        self._displaySelectedFileDiff(self._fileListWidget.currentItem(), None) # Refresh diff view to show placeholder
        self._updateWidgetStates()

    # --- Parse & Validate ---
    @Slot()
    def _handleParseAndValidate(self: 'MainWindow') -> None:
        if self._isBusy: self._showWarning("Busy", "Another task is currently running. Please wait."); return

        llmResponse: str = self._llmResponseArea.toPlainText().strip()
        if not llmResponse: self._showError("Empty Response", "The LLM Response area is empty. Cannot parse."); return

        try:
            expectedFormat = self._configManager.getConfigValue('General', 'ExpectedOutputFormat', fallback='json') or 'json'
        except ConfigurationError as e:
            self._showError("Config Error", f"Could not read expected output format from config: {e}")
            return

        logger.info(f"Requesting parse & validate (format: {expectedFormat})...")
        self._isBusy = True
        self._updateWidgetStates()
        self._updateStatusBar(f"Parsing response ({expectedFormat})...", 5000)
        self._updateProgress(-1, f"Parsing {expectedFormat}...")
        self._parsedFileData = None
        self._validationErrors = None
        # Clear only proposed area before parsing
        self._proposedCodeArea.clear()
        # Keep original area showing focused file's original content
        self._fileWorker.startParsing(llmResponse, expectedFormat)

    # --- Save Changes ---
    @Slot()
    def _handleSaveChanges(self: 'MainWindow') -> None:
        if self._isBusy: self._showWarning("Busy", "Another task is currently running. Please wait."); return
        if self._parsedFileData is None: self._showError("No Data", "No parsed data available. Please parse a valid LLM response first."); return
        if self._validationErrors: self._showError("Validation Errors", "Cannot save changes when validation errors exist. Check the logs and potentially ask the LLM to correct the response."); return
        if not self._clonedRepoPath or not os.path.isdir(self._clonedRepoPath): self._showError("Invalid Repository Path", "The loaded repository path is invalid or inaccessible."); return

        fileCount = len(self._parsedFileData)
        if fileCount == 0: self._showInfo("No Changes to Save", "The parsed LLM response indicated no files needed modification."); return

        # Confirmation dialog
        reply = QMessageBox.question(self, 'Confirm Save',
                                   f"This will overwrite {fileCount} file(s) in the local repository:\n'{self._clonedRepoPath}'\n\nProceed with saving?",
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                   QMessageBox.StandardButton.Cancel)
        if reply == QMessageBox.StandardButton.Cancel: return

        logger.info(f"Requesting save of {fileCount} files...")
        self._isBusy = True
        self._updateWidgetStates()
        self._updateStatusBar("Saving files locally...")
        self._updateProgress(-1, "Saving files...")
        self._fileWorker.startSaving(self._clonedRepoPath, self._parsedFileData)

    # --- Commit & Push ---
    @Slot()
    def _handleCommitPush(self: 'MainWindow') -> None:
        if self._isBusy: self._showWarning("Busy", "Another task is currently running. Please wait."); return
        if not self._clonedRepoPath or not os.path.isdir(self._clonedRepoPath): self._showError("Invalid Repository Path", "The loaded repository path is invalid or inaccessible."); return

        # Check dirty status immediately before commit attempt
        try:
            is_currently_dirty = self._githubHandlerInstance.isDirty(self._clonedRepoPath)
            self._repoIsDirty = is_currently_dirty # Update internal state
        except Exception as e:
            self._showError("Git Status Error", f"Could not check repository status before commit: {e}")
            return

        if not self._repoIsDirty:
            self._showInfo("No Changes to Commit", "The repository is clean. There are no changes to commit and push.")
            self._updateWidgetStates()
            return

        # Get commit message
        try:
            defaultMsg = self._configManager.getConfigValue('GitHub', 'DefaultCommitMessage', fallback="LLM Update via ColonelCode")
        except ConfigurationError as e:
            logger.warning(f"Could not read default commit message from config: {e}")
            defaultMsg = "LLM Update via ColonelCode"
        commitMessage, ok = QInputDialog.getText(self, "Commit Message", "Enter commit message:", QLineEdit.EchoMode.Normal, defaultMsg)
        if not ok or not commitMessage.strip():
            self._showWarning("Commit Cancelled", "Commit message was empty or the dialog was cancelled.")
            return
        commitMessage = commitMessage.strip()

        # Get remote/branch details
        try:
            remote = self._configManager.getConfigValue('GitHub', 'DefaultRemoteName', fallback='origin') or 'origin'
            branch = self._configManager.getConfigValue('GitHub', 'DefaultBranchName', fallback='main') or 'main'
        except ConfigurationError as e:
            self._showError("Config Error", f"Could not read Git remote/branch settings from config: {e}")
            return

        # Confirmation dialog
        reply = QMessageBox.question(self, 'Confirm Commit & Push',
                                   f"Commit changes and push to remote '{remote}/{branch}'?\n\nCommit Message:\n'{commitMessage}'",
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                   QMessageBox.StandardButton.Cancel)
        if reply == QMessageBox.StandardButton.Cancel: return

        logger.info(f"Requesting commit and push to {remote}/{branch}...")
        self._isBusy = True
        self._updateWidgetStates()
        self._updateStatusBar("Committing and pushing changes...")
        self._updateProgress(-1, "Commit/Push...")
        self._githubWorker.startCommitPush(self._clonedRepoPath, commitMessage, remote, branch)

    # --- Worker Thread Callback Slots ---
    @Slot(int, str)
    def _updateProgress(self: 'MainWindow', value: int, message: str) -> None:
        """Updates the progress bar and status message."""
        if not self._isBusy:
            self._progressBar.setVisible(False)
            return

        self._progressBar.setVisible(True)
        if value == -1: # Indeterminate progress
            self._progressBar.setRange(0, 0) # Makes it indeterminate visually
            self._progressBar.setFormat(message or "Working...")
        elif 0 <= value <= 100: # Determinate progress
            self._progressBar.setRange(0, 100)
            self._progressBar.setValue(value)
            # Ensure format string handles percentage correctly
            format_str = f"{message} (%p%)" if message else "%p%"
            self._progressBar.setFormat(format_str)
        else: # Hide progress bar for invalid values or completion
            self._progressBar.setVisible(False)
            self._progressBar.setRange(0, 100)
            self._progressBar.setValue(0)
            self._progressBar.setFormat("%p%") # Reset format

        # Optionally update status bar if message provided
        if message:
            self._updateStatusBar(message)


    # --- _onCloneFinished (MODIFIED to use .codebaseignore and robust parsing) ---
    @Slot(str, list)
    def _onCloneFinished(self: 'MainWindow', repoPath: str, fileList: list) -> None:
        """
        Handles the completion of the repository clone/load operation.
        Loads repository information, populates the file list, and applies
        rules from '.codebaseignore' to set the initial file selection.
        """
        logger.info(f"Clone/Load finished successfully. Path: {repoPath}, Files: {len(fileList)}")
        self._isBusy = False
        self._clonedRepoPath = repoPath
        self._parsedFileData = None
        self._validationErrors = None
        self._originalFileContents.clear()
        self._llmResponseArea.clear()
        self._originalCodeArea.clear()
        self._proposedCodeArea.clear()
        self._promptInput.clear()
        self._saveLastRepoPath(repoPath)
        self._updateStatusBar(f"Repository loaded ({len(fileList)} files). Applying ignore rules...", 5000) # Updated status

        # --- .codebaseignore Handling ---
        codebase_ignore_filename: str = '.codebaseignore'
        codebase_ignore_path = os.path.join(repoPath, codebase_ignore_filename)
        matches = None # Function to check if a path matches ignore rules

        try:
            if os.path.exists(codebase_ignore_path) and os.path.isfile(codebase_ignore_path):
                parser_used = None
                # Try using 'gitignore_parser' (hyphen library, parse method) first
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
                            matches = None # Ensure matches is None if parsing didn't yield a callable
                    else:
                         logger.debug(f"'gitignore_parser' module lacks callable 'parse' attribute.")
                         matches = None
                except ImportError:
                    logger.debug("'gitignore-parser' (hyphen) library not found, trying 'gitignore_parser' (underscore).")
                    matches = None
                except Exception as e_parse:
                    logger.error(f"Error using 'gitignore_parser.parse()' for {codebase_ignore_filename}: {e_parse}", exc_info=True)
                    matches = None # Ensure matches is None on error

                # If the first method failed, try 'gitignore_parser' (underscore library, parse_gitignore function)
                if matches is None:
                    try:
                        from gitignore_parser import parse_gitignore
                        logger.debug(f"Found 'parse_gitignore' function from gitignore_parser module.")
                        # This function takes the path directly
                        matches = parse_gitignore(codebase_ignore_path)
                        if callable(matches):
                             parser_used = "parse_gitignore()"
                             logger.info(f"Loaded rules from {codebase_ignore_filename} using parse_gitignore()")
                        else:
                             logger.warning(f"parse_gitignore() did not return a callable for {codebase_ignore_filename}.")
                             matches = None
                    except ImportError:
                        logger.warning(f"Neither 'gitignore-parser' nor 'gitignore_parser' library seems to be installed correctly or provides expected functions.")
                        self._appendLogMessage(f"WARNING: No suitable gitignore parsing library found. Cannot apply {codebase_ignore_filename} rules.")
                    except Exception as e_func:
                        logger.error(f"Error using 'parse_gitignore()' function for {codebase_ignore_filename}: {e_func}", exc_info=True)
                        self._appendLogMessage(f"ERROR: Failed parsing {codebase_ignore_filename} with parse_gitignore(): {e_func}")
                        matches = None

                if not parser_used and matches is None:
                     logger.error(f"Failed to load or parse {codebase_ignore_filename} using available methods.")
                     self._appendLogMessage(f"ERROR: Could not parse {codebase_ignore_filename}. Check library installations and file content.")

            else:
                logger.info(f"'{codebase_ignore_filename}' not found in repository root. All files will be selected by default.")
                # No need to append log message here, info is sufficient

        except Exception as e_top:
            # Catch any unexpected errors during the whole process
             logger.error(f"Unexpected error during {codebase_ignore_filename} handling: {e_top}", exc_info=True)
             self._appendLogMessage(f"ERROR: Unexpected error handling {codebase_ignore_filename}: {e_top}")
             matches = None # Ensure matches is None on error
        # --- End .codebaseignore Handling ---

        # Populate the file list widget
        self._fileListWidget.clear()
        self._fileListWidget.addItems(sorted(fileList)) # Add all tracked files first

        # --- Set default selection based on .codebaseignore ---
        selected_files_init = []
        ignored_count = 0
        total_count = self._fileListWidget.count()

        # Block signals temporarily to avoid excessive logging/updates during selection
        self._fileListWidget.blockSignals(True)

        for i in range(total_count):
            item = self._fileListWidget.item(i)
            file_path_relative = item.text()
            # Construct absolute path for matching
            # Ensure repoPath is absolute for robust matching
            abs_repo_path = os.path.abspath(repoPath)
            file_path_absolute = os.path.join(abs_repo_path, file_path_relative)

            should_select = True # Select by default
            if matches and callable(matches): # Check if 'matches' callable was successfully created
                try:
                    if matches(file_path_absolute):
                        should_select = False # Ignore if matched by .codebaseignore
                        ignored_count += 1
                        # Optional: logger.debug(f"Ignoring file based on {codebase_ignore_filename}: {file_path_relative}")
                except Exception as e_match:
                    # Log errors during matching but continue otherwise
                    logger.warning(f"Error matching file '{file_path_relative}' against {codebase_ignore_filename} rules: {e_match}")

            item.setSelected(should_select) # Set selection state directly
            if should_select:
                selected_files_init.append(file_path_relative)

        # Re-enable signals
        self._fileListWidget.blockSignals(False)
        # --- End default selection ---

        # Explicitly update the internal state AFTER setting selection programmatically
        self._selectedFiles = sorted(selected_files_init) # Store the list of initially selected files
        logger.info(f"Initial file selection complete. Ignored {ignored_count}/{total_count} files based on {codebase_ignore_filename}. Selected: {len(self._selectedFiles)} files.")
        self._updateStatusBar(f"Repository loaded. Initial selection set ({len(self._selectedFiles)}/{total_count} files). Checking status...", 5000)


        # Automatically check dirty status after successful load
        if not self._isBusy and self._clonedRepoPath:
            self._isBusy = True # Set busy for the dirty check
            self._updateWidgetStates() # Reflect busy state
            self._updateProgress(-1, "Checking repository status...")
            self._githubWorker.startIsDirty(self._clonedRepoPath)
        else:
            # If already busy (shouldn't happen here ideally) or no repo path
            logger.warning("Cannot start dirty check after clone/load operation finished.")
            self._updateWidgetStates() # Still update states


    @Slot(bool)
    def _onIsDirtyFinished(self: 'MainWindow', is_dirty: bool) -> None:
        if not self._clonedRepoPath: return # Avoid updates if repo was unloaded somehow

        logger.info(f"Repository dirty status check completed: {is_dirty}")
        self._repoIsDirty = is_dirty
        self._isBusy = False # Finished the dirty check task
        status_msg = "Repository status: Dirty (Uncommitted changes exist)" if is_dirty else "Repository status: Clean"
        self._updateStatusBar(status_msg, 5000)
        self._updateProgress(100, "Status check complete.") # Mark progress as complete
        self._updateWidgetStates() # Update button enable/disable states

    # --- LLM Finished - Handle Correction Response, Switch Tab ---
    @Slot(str)
    def _onLlmFinished(self: 'MainWindow', response: str) -> None:
        """Handles the successful response from the LLM query, including correction attempts."""
        logger.info(f"LLM query finished. Response length: {len(response)}")
        # Note: _isBusy was already set by the LLM worker finishing.
        # We just need to update UI elements based on the result.
        self._updateProgress(100, "LLM query complete.")
        self._llmResponseArea.setPlainText(response); # Always display the latest response

        # Switch to the LLM Response tab for user visibility
        llm_tab_index = -1
        for i in range(self._bottomTabWidget.count()):
            if self._bottomTabWidget.tabText(i) == "LLM Response":
                llm_tab_index = i
                break
        if llm_tab_index != -1:
            self._bottomTabWidget.setCurrentIndex(llm_tab_index)
        else:
             logger.warning("Could not find 'LLM Response' tab to switch to automatically.")


        # Reset parsing/validation state as new response arrived
        self._parsedFileData = None
        self._validationErrors = None
        self._proposedCodeArea.clear() # Clear proposed diff until parsed
        self._displaySelectedFileDiff(self._fileListWidget.currentItem(), None) # Show original against blank proposed

        if self._correction_attempted:
            # This was the response to a correction request
            self._updateStatusBar("LLM correction received. Parsing corrected response...", 10000)
            # Automatically trigger parsing again now that _isBusy is False
            self._handleParseAndValidate() # This will use the new content in _llmResponseArea
        else:
            # This was the response to the initial query
            self._updateStatusBar("LLM query successful. Click 'Parse & Validate' to process the response.", 5000)
            # Ensure isBusy is False before updating states
            self._isBusy = False
            self._updateWidgetStates() # Update state now that response is available and we are not busy

    # --- Parsing Finished - Ensure original content loaded, refresh diff ---
    @Slot(dict, dict)
    def _onParsingFinished(self: 'MainWindow', parsedData: Dict[str, str], validationResults: Dict[str, List[str]]) -> None:
        """Handles the result of parsing and validation, ensuring diff view is accurate."""
        if not self._clonedRepoPath: return # Avoid updates if repo unloaded

        logger.info(f"Parsing finished. Parsed items: {len(parsedData)}. Validation Errors: {len(validationResults)}")
        self._isBusy = False # Parsing task is done
        self._parsedFileData = parsedData
        self._validationErrors = validationResults if validationResults else None # Store None if empty dict

        # Ensure original content is loaded for all parsed files (important for diff)
        if self._clonedRepoPath and self._parsedFileData:
            logger.debug("Ensuring original content is cached for parsed files before displaying diff...")
            for file_path in self._parsedFileData.keys():
                if file_path not in self._originalFileContents:
                    full_path = os.path.join(self._clonedRepoPath, file_path)
                    if os.path.exists(full_path) and os.path.isfile(full_path):
                        try:
                            # Reuse size check from diff display
                            MAX_DIFF_FILE_SIZE = 1 * 1024 * 1024
                            if os.path.getsize(full_path) > MAX_DIFF_FILE_SIZE:
                                logger.warning(f"Original file {file_path} too large ({os.path.getsize(full_path)} bytes). Storing placeholder.")
                                self._originalFileContents[file_path] = f"<File too large (>{MAX_DIFF_FILE_SIZE // 1024} KB)>"
                            else:
                                with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
                                    self._originalFileContents[file_path] = f.read()
                                logger.debug(f"Loaded original content for {file_path} after parse.")
                        except Exception as e:
                            logger.error(f"Error reading original file {file_path} after parse: {e}", exc_info=True)
                            self._originalFileContents[file_path] = f"<Error reading file: {e}>"
                    else:
                        # Mark as non-existent if it wasn't in cache and doesn't exist now
                        self._originalFileContents[file_path] = None
                        logger.debug(f"Original file {file_path} not found locally after parse (likely new file).")

        # Log validation results and update status
        if self._validationErrors:
            log_message = ["--- Validation Failed ---"]
            error_files = set() # Use a set for unique filenames
            for file_path, errors in self._validationErrors.items():
                error_files.add(os.path.basename(file_path))
                log_message.append(f"  File: {file_path}")
                for error in errors:
                    log_message.append(f"    * {error}")
            log_message.append("-------------------------")
            self._appendLogMessage("\n".join(log_message))
            error_summary = f"Validation failed for {len(self._validationErrors)} file(s).\nCheck Application Log tab for details.\n\nFiles with errors:\n - " + "\n - ".join(sorted(list(error_files)))
            self._showWarning("Code Validation Failed", error_summary)
            status_msg = f"Response parsed. Validation FAILED ({len(self._validationErrors)} file(s))."
        else:
            file_count_msg = f"{len(parsedData)} files found" if parsedData else "No changes found"
            status_msg = f"Response parsed: {file_count_msg}. Validation OK."
            self._appendLogMessage("--- Validation OK ---")
            # Clear correction flag ONLY on successful validation
            self._correction_attempted = False

        self._updateStatusBar(status_msg, 10000)
        self._updateProgress(100, "Parse & Validate complete.")

        # Add any new files mentioned in the parsed data to the list widget
        current_files_in_widget = set(self._fileListWidget.item(i).text() for i in range(self._fileListWidget.count()))
        new_files_added_to_widget = False
        if self._parsedFileData:
            self._fileListWidget.blockSignals(True) # Block signals during add
            for filePath in sorted(self._parsedFileData.keys()):
                if filePath not in current_files_in_widget:
                    newItem = QListWidgetItem(filePath)
                    # Optionally set tooltip or icon for new files
                    self._fileListWidget.addItem(newItem)
                    new_files_added_to_widget = True
            if new_files_added_to_widget:
                self._fileListWidget.sortItems() # Keep list sorted
            self._fileListWidget.blockSignals(False) # Re-enable signals

        # Refresh the diff display for the currently focused item
        self._displaySelectedFileDiff(self._fileListWidget.currentItem(), None)
        self._updateWidgetStates() # Update button states based on parse/validation outcome


    @Slot(list)
    def _onSavingFinished(self: 'MainWindow', savedFiles: list) -> None:
        if not self._clonedRepoPath: return # Avoid updates if repo unloaded

        logger.info(f"Saving finished successfully. Saved files: {len(savedFiles)}")
        self._isBusy = False # Saving task done
        self._updateStatusBar(f"Changes saved locally ({len(savedFiles)} files).", 5000)
        self._updateProgress(100, "Saving complete.")

        if savedFiles:
            self._showInfo("Save Successful", f"{len(savedFiles)} file(s) saved/updated in\n'{self._clonedRepoPath}'.")
            self._repoIsDirty = True # Saving makes the repo dirty
            # Update the original content cache with the newly saved content
            if self._parsedFileData:
                for saved_path in savedFiles:
                    if saved_path in self._parsedFileData:
                        self._originalFileContents[saved_path] = self._parsedFileData[saved_path]
            self._parsedFileData = None # Clear parsed data after successful save
            self._validationErrors = None # Clear validation errors too
            self._displaySelectedFileDiff(self._fileListWidget.currentItem(), None) # Refresh diff to show saved state
        else:
            logger.info("Saving finished, but no files were listed as saved (potentially an issue or no actual changes needed saving).")
            # Optionally show info even if savedFiles is empty, if parsedData existed before
            if self._parsedFileData is not None:
                 self._showInfo("Save Complete", "Processing complete, but no files reported as saved.")
                 self._parsedFileData = None # Clear anyway
                 self._validationErrors = None
                 self._displaySelectedFileDiff(self._fileListWidget.currentItem(), None)

        self._updateWidgetStates() # Update button states (commit should be enabled now)

    @Slot(str)
    def _onCommitPushFinished(self: 'MainWindow', message: str) -> None:
        if not self._clonedRepoPath: return # Avoid updates if repo unloaded

        logger.info(f"Commit/Push finished: {message}")
        self._isBusy = False # Task done
        self._updateStatusBar("Commit and push successful.", 5000)
        self._updateProgress(100, "Commit/Push complete.")
        self._showInfo("Commit/Push Successful", message)
        self._repoIsDirty = False # Assume clean after successful push
        # Clear state related to the previous change set
        self._originalCodeArea.clear()
        self._proposedCodeArea.clear()
        self._parsedFileData = None
        self._validationErrors = None
        self._llmResponseArea.clear()
        self._promptInput.clear() # Clear prompt after successful workflow? Optional.
        self._displaySelectedFileDiff(self._fileListWidget.currentItem(), None) # Clear diff
        self._updateWidgetStates() # Update buttons (commit should be disabled)


    @Slot(str, bool)
    def _onPullFinished(self: 'MainWindow', message: str, had_conflicts: bool) -> None:
        if not self._clonedRepoPath: return # Avoid updates if repo unloaded

        logger.info(f"Pull finished: {message}, Conflicts: {had_conflicts}")
        self._isBusy = False # Task done
        self._updateStatusBar(f"Pull finished. {message}", 10000)
        self._updateProgress(100, "Pull complete.")

        if had_conflicts:
            self._showWarning("Pull Conflicts", f"Pull completed, but merge conflicts likely occurred.\nDetails: {message}\nPlease resolve conflicts manually using Git tools.")
            self._repoIsDirty = True # Conflicts make it dirty
            self._updateWidgetStates() # Update UI based on dirty state
        else:
            self._showInfo("Pull Finished", message)
            # Re-check dirty status after a successful pull without known conflicts
            if self._clonedRepoPath and not self._isBusy:
                self._isBusy = True # Set busy for the dirty check
                self._updateWidgetStates() # Reflect busy state
                self._updateStatusBar("Checking repository status after pull...", 5000)
                self._updateProgress(-1, "Checking status...")
                self._githubWorker.startIsDirty(self._clonedRepoPath)
                # State will be updated fully by _onIsDirtyFinished when it returns
            elif self._clonedRepoPath:
                # Fallback if we cannot start the check for some reason
                logger.warning("Could not automatically re-check dirty status after pull.")
                self._repoIsDirty = False # Assume clean if we can't check
                self._updateWidgetStates()


    # --- Error Handling Slots ---
    @Slot(str)
    def _handleWorkerError(self: 'MainWindow', errorMessage: str) -> None:
        """Handles generic, unexpected errors from worker threads."""
        logger.critical(f"Unexpected worker thread error: {errorMessage}", exc_info=True) # Log stack trace
        self._resetTaskState() # Reset busy state etc.
        self._showError("Unexpected Background Task Error", f"A critical internal error occurred in a background task:\n{errorMessage}")
        self._appendLogMessage(f"CRITICAL ERROR: {errorMessage}")

    @Slot(str)
    def _handleGitHubError(self: 'MainWindow', errorMessage: str) -> None:
        """Handles specific errors related to GitHub operations."""
        logger.error(f"GitHub operation failed: {errorMessage}")
        # Check if it was a clone/load related error - affects whether we clear repo state
        is_load_error = any(s in errorMessage.lower() for s in ["clone", "load", "not found", "authentication failed", "valid git repo", "invalid repository"])

        self._resetTaskState() # Reset busy state regardless
        self._showError("Git/GitHub Error", errorMessage) # Use consistent title
        self._appendLogMessage(f"GIT ERROR: {errorMessage}")

        if is_load_error:
            # Reset repo-specific state fully if loading/cloning failed
            logger.info("Resetting repository state due to load/clone error.")
            self._clonedRepoPath = None
            self._fileListWidget.clear()
            self._repoIsDirty = False
            self._originalFileContents.clear()
            self._parsedFileData = None
            self._validationErrors = None
            self._originalCodeArea.clear()
            self._proposedCodeArea.clear()
            self._llmResponseArea.clear()
            self._promptInput.clear()
            self._selectedFiles = []
            self._updateWidgetStates() # Update UI to reflect no repo loaded


    @Slot(str)
    def _handleLLMError(self: 'MainWindow', errorMessage: str) -> None:
        """Handles errors related to LLM configuration or API calls."""
        logger.error(f"LLM operation failed: {errorMessage}")
        self._resetTaskState() # Reset busy state
        self._showError("LLM/Configuration Error", errorMessage)
        self._llmResponseArea.setPlainText(f"--- LLM Error ---\n{errorMessage}") # Show error in response area
        self._appendLogMessage(f"LLM ERROR: {errorMessage}")

    # --- Handle File Processing Error (potentially trigger LLM correction) ---
    @Slot(str)
    def _handleFileProcessingError(self: 'MainWindow', errorMessage: str) -> None:
        """Handles file processing errors, potentially triggering an LLM correction retry."""
        logger.error(f"File processing failed: {errorMessage}")
        # Note: _isBusy should already be False as the worker emitted error signal

        # Check if it's a parsing error and if we haven't tried correcting yet
        is_parsing_error = errorMessage.startswith("ParsingError:")
        can_retry = not self._correction_attempted and is_parsing_error

        if can_retry:
            logger.warning("Initial parsing failed. Attempting LLM self-correction.")
            self._correction_attempted = True # Mark that we are trying now
            self._updateStatusBar("Initial parsing failed. Requesting LLM correction...", 0) # Persistent message
            self._appendLogMessage(f"PARSE ERROR: {errorMessage}. Requesting LLM correction...")
            self._updateProgress(-1, "Requesting correction...")
            self._isBusy = True # Set busy again for the correction call
            self._updateWidgetStates()

            try:
                original_bad_response = self._llmResponseArea.toPlainText() # Get the full bad response
                original_instruction = self._promptInput.toPlainText() # Get original instruction
                expected_format = self._configManager.getConfigValue('General', 'ExpectedOutputFormat', fallback='json') or 'json'
                model_name = self._configManager.getConfigValue('General', 'DefaultLlmModel', fallback='gemini-1.5-flash-latest') or 'gemini-1.5-flash-latest'

                # Check if we have the necessary components for correction
                if not original_bad_response:
                    raise ValueError("Cannot attempt correction without the original LLM response.")
                if not original_instruction:
                    # Maybe get default instruction or fail? For now, fail.
                    raise ValueError("Cannot attempt correction without the original user instruction.")


                # Build the correction prompt
                correction_prompt = self._llmInterfaceInstance.build_correction_prompt(
                    original_bad_output=original_bad_response,
                    original_instruction=original_instruction,
                    expected_format=expected_format
                )
                logger.debug(f"Built correction prompt (length: {len(correction_prompt)} chars).")

                # Trigger LLMWorker with correction task and lower temperature
                self._llmWorker.startCorrectionQuery(model_name, correction_prompt, CORRECTION_RETRY_TEMPERATURE)
                # Do not call _resetTaskState or _showError here, wait for correction result (_onLlmFinished)

            except (ConfigurationError, ValueError, Exception) as e:
                # Error during the setup for the correction call itself
                logger.critical(f"Failed to initiate LLM correction query: {e}", exc_info=True)
                self._resetTaskState() # Reset state after this internal error
                self._showError("Correction Error", f"Could not initiate LLM correction attempt: {e}")
                self._appendLogMessage(f"CRITICAL: Failed to start correction query: {e}")
                self._correction_attempted = False # Allow trying again if user manually edits + parses

        else:
            # Not a parsing error, or correction already attempted/failed - show original error
            if is_parsing_error and self._correction_attempted:
                logger.error("LLM correction attempt also failed to produce parsable output.")
                self._appendLogMessage(f"LLM CORRECTION FAILED: {errorMessage}")
                error_title = "LLM Correction Failed"
                error_message = f"The LLM failed to correct the output format.\nOriginal Parse Error:\n{errorMessage}"
            else:
                 error_title = "File Processing Error"
                 error_message = errorMessage
                 self._appendLogMessage(f"FILE/PARSE ERROR (Final): {errorMessage}")


            self._resetTaskState() # Reset busy state
            self._showError(error_title, error_message)

            # Clear potentially invalid parsed data if error occurred during parsing phase
            if is_parsing_error:
                self._parsedFileData = None; self._validationErrors = None
                # Clear only proposed area on final parse error
                self._proposedCodeArea.clear()
                self._displaySelectedFileDiff(self._fileListWidget.currentItem(), None) # Refresh diff
                self._updateWidgetStates()


    # --- Utility Methods ---
    def _updateWidgetStates(self: 'MainWindow') -> None:
        """Enable/disable widgets based on the current application state."""
        repoLoaded = self._clonedRepoPath is not None and os.path.isdir(self._clonedRepoPath)
        responseAvailable = bool(self._llmResponseArea.toPlainText().strip())
        parsedDataAvailable = self._parsedFileData is not None
        parsedDataHasContent = parsedDataAvailable and bool(self._parsedFileData) # Check if dict has items
        validationPassed = parsedDataAvailable and self._validationErrors is None
        # Use the stored state for dirty status, updated by callbacks
        repoIsActuallyDirty = repoLoaded and self._repoIsDirty
        enabledIfNotBusy = not self._isBusy

        # Top section
        self._repoUrlInput.setEnabled(enabledIfNotBusy)
        self._browseButton.setEnabled(enabledIfNotBusy)
        self._cloneButton.setEnabled(enabledIfNotBusy)

        # Middle section
        self._fileListWidget.setEnabled(enabledIfNotBusy and repoLoaded)
        self._promptInput.setEnabled(enabledIfNotBusy and repoLoaded)
        self._sendToLlmButton.setEnabled(enabledIfNotBusy and repoLoaded)
        self._pasteResponseButton.setEnabled(enabledIfNotBusy) # Allow pasting anytime not busy

        # Bottom section Actions
        self._parseButton.setEnabled(enabledIfNotBusy and responseAvailable)
        self._saveFilesButton.setEnabled(enabledIfNotBusy and parsedDataHasContent and repoLoaded and validationPassed)
        self._commitPushButton.setEnabled(enabledIfNotBusy and repoLoaded and repoIsActuallyDirty)

        # Bottom section Tabs/Areas
        self._llmResponseArea.setReadOnly(self._isBusy) # Make readonly while busy


    def _resetTaskState(self: 'MainWindow') -> None:
        """Resets the busy flag and updates UI elements after a task finishes or fails."""
        logger.debug("Resetting task state (busy=False).")
        self._isBusy = False
        self._correction_attempted = False # Also reset correction flag on any task reset
        self._updateWidgetStates() # Update button states etc.
        self._updateProgress(101, "") # Value > 100 hides the progress bar
        self._updateStatusBar("Idle.")

    def _updateStatusBar(self: 'MainWindow', message: str, timeout: int = 0) -> None:
        """Updates the status bar message, ensuring it exists."""
        if hasattr(self, '_statusBar') and self._statusBar:
            self._statusBar.showMessage(message, timeout)
        else:
            logger.warning(f"Attempted to update status bar before it was initialized. Message: {message}")

    def _showError(self: 'MainWindow', title: str, message: str) -> None:
        """Displays a critical error message box."""
        logger.error(f"{title}: {message}")
        QMessageBox.critical(self, title, str(message)) # Ensure message is string

    def _showWarning(self: 'MainWindow', title: str, message: str) -> None:
        """Displays a warning message box."""
        logger.warning(f"{title}: {message}")
        QMessageBox.warning(self, title, str(message)) # Ensure message is string

    def _showInfo(self: 'MainWindow', title: str, message: str) -> None:
        """Displays an informational message box."""
        logger.info(f"Info Dialog: {title} - {message}")
        QMessageBox.information(self, title, str(message)) # Ensure message is string

    @Slot(str)
    def _appendLogMessage(self: 'MainWindow', message: str) -> None:
        """Appends a message to the GUI log area."""
        if hasattr(self, '_appLogArea') and self._appLogArea:
            # Append plain text; assumes logger already formatted it
            self._appLogArea.appendPlainText(message)
            # Optional: Auto-scroll to bottom
            # sb = self._appLogArea.verticalScrollBar()
            # sb.setValue(sb.maximum())
        # Do not log here, as this is called *by* the logger

    # --- Scroll Synchronization ---
    @Slot(int)
    def _syncScrollProposedFromOriginal(self, value: int) -> None:
        """Syncs the proposed code area scrollbar when the original one moves."""
        if not self._is_syncing_scroll:
            self._is_syncing_scroll = True
            self._proposedCodeArea.verticalScrollBar().setValue(value)
            self._is_syncing_scroll = False

    @Slot(int)
    def _syncScrollOriginalFromProposed(self, value: int) -> None:
        """Syncs the original code area scrollbar when the proposed one moves."""
        if not self._is_syncing_scroll:
            self._is_syncing_scroll = True
            self._originalCodeArea.verticalScrollBar().setValue(value)
            self._is_syncing_scroll = False

    def _syncScrollbars(self) -> None:
        """Forces synchronization of scrollbars, typically after loading new content."""
        if not self._is_syncing_scroll:
            self._is_syncing_scroll = True
            # Sync proposed from original as the primary direction
            orig_val = self._originalCodeArea.verticalScrollBar().value()
            self._proposedCodeArea.verticalScrollBar().setValue(orig_val)
            self._is_syncing_scroll = False

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
            workers = [self._githubWorker, self._llmWorker, self._fileWorker]
            for worker in workers:
                if worker and worker.isRunning():
                    logger.debug(f"Requesting quit for {worker.__class__.__name__}...")
                    worker.requestInterruption() # Request interruption politely first
                    # Give slightly more time for graceful exit
                    if not worker.wait(2000): # Wait up to 2 seconds
                        logger.warning(f"{worker.__class__.__name__} did not finish after interruption request and wait. Termination may not be clean.")
                        # Avoid hard terminate if possible as it can corrupt state
                        # worker.terminate()

            logger.info("Shutdown sequence complete. Closing application window.")
            super().closeEvent(event) # Accept the close event

# Ensure the script can be run directly if needed for testing (though main.py is entry point)
if __name__ == '__main__':
    import sys
    from PySide6.QtWidgets import QApplication
    # Basic setup for standalone testing
    app = QApplication(sys.argv)
    # Requires a dummy ConfigManager for standalone run
    config = ConfigManager('dummy_config.ini', '.env')
    window = MainWindow(config)
    window.show()
    sys.exit(app.exec())