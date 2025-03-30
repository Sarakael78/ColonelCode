# Updated Codebase/gui/ui_setup.py
# --- START: gui/ui_setup.py ---
# gui/ui_setup.py
"""
Module responsible for creating and laying out the UI widgets
for the MainWindow.
"""

import os
from PySide6.QtWidgets import (
	QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
	QLabel, QLineEdit, QPushButton, QTextEdit,
	QListWidget, QProgressBar, QStatusBar,
	QSplitter, QTabWidget, QTextBrowser  # Add QTextBrowser import
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon
import logging

logger = logging.getLogger(__name__)

# Constants for UI styling (Copied from main_window.py)
HTML_FONT_FAMILY = "'Courier New', Courier, monospace"
HTML_FONT_SIZE = "9pt"

def setup_ui(window: QMainWindow) -> None:
	"""
	Sets up the user interface layout and widgets for the main window.

	Args:
		window: The QMainWindow instance to set up.
	"""
	logger.debug("Setting up UI elements.")
	window.setWindowTitle("Colonel Code - LLM Code Updater")
	iconPath = os.path.join('resources', 'app_icon.png')
	if os.path.exists(iconPath):
		window.setWindowIcon(QIcon(iconPath))
	else:
		logger.warning(f"Application icon not found at: {iconPath}")

	window._centralWidget = QWidget()
	window.setCentralWidget(window._centralWidget)
	window._mainLayout = QVBoxLayout(window._centralWidget)

	# --- Top: Repo Input and Controls ---
	repoLayout = QHBoxLayout()
	repoLabel = QLabel("GitHub Repo URL / Local Path:")
	window._repoUrlInput = QLineEdit()
	window._repoUrlInput.setPlaceholderText("https://github.com/user/repo.git or /path/to/local/repo")
	window._repoUrlInput.setToolTip("Enter the URL of the GitHub repository (HTTPS or SSH) or the full path to an existing local repository.")
	window._browseButton = QPushButton("Browse...")
	window._browseButton.setToolTip("Browse for a local repository folder.")
	window._cloneButton = QPushButton("Clone / Load Repo")
	window._cloneButton.setToolTip("Clone the remote repository or load the selected local repository.")
	repoLayout.addWidget(repoLabel)
	repoLayout.addWidget(window._repoUrlInput, 1)
	repoLayout.addWidget(window._browseButton)
	repoLayout.addWidget(window._cloneButton)
	window._mainLayout.addLayout(repoLayout)

	# --- Middle: File List and Prompt/LLM Interaction ---
	middleSplitter = QSplitter(Qt.Orientation.Horizontal)

	# Middle Left: File List
	fileListLayout = QVBoxLayout()
	fileListLabel = QLabel("Select Files for Context:")
	window._fileListWidget = QListWidget()
	window._fileListWidget.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
	window._fileListWidget.setToolTip("Select one or more files (Ctrl/Cmd+Click or Shift+Click) to include their content in the prompt sent to the LLM. Focus on one file (single click) to view its diff below.")
	fileListLayout.addWidget(fileListLabel)
	fileListLayout.addWidget(window._fileListWidget)
	fileListWidgetContainer = QWidget()
	fileListWidgetContainer.setLayout(fileListLayout)
	middleSplitter.addWidget(fileListWidgetContainer)

	# Middle Right: Prompt Input and LLM Buttons
	promptLayout = QVBoxLayout()
	promptLabel = QLabel("LLM Instruction / Prompt:")
	window._promptInput = QTextEdit()
	window._promptInput.setPlaceholderText("Enter your instructions for code modification based on selected files...")
	window._promptInput.setToolTip("Describe the changes you want the LLM to make to the selected files.")
	llmInteractionLayout = QHBoxLayout() # Buttons remain here
	window._sendToLlmButton = QPushButton("Send to LLM")
	window._sendToLlmButton.setToolTip("Send the instruction and selected file contents to the LLM for processing.")
	window._pasteResponseButton = QPushButton("Paste LLM Response")
	window._pasteResponseButton.setToolTip("Manually paste a response from an external LLM into the 'LLM Response' tab below.")
	llmInteractionLayout.addWidget(window._sendToLlmButton)
	llmInteractionLayout.addWidget(window._pasteResponseButton)
	llmInteractionLayout.addStretch(1)
	promptLayout.addWidget(promptLabel)
	promptLayout.addWidget(window._promptInput, stretch=1) # Prompt input takes most space
	promptLayout.addLayout(llmInteractionLayout) # Add buttons below prompt
	promptWidgetContainer = QWidget()
	promptWidgetContainer.setLayout(promptLayout)
	middleSplitter.addWidget(promptWidgetContainer)

	middleSplitter.setSizes([300, 600]) # Adjust initial sizes if needed
	window._mainLayout.addWidget(middleSplitter, stretch=1)

	# --- Bottom: Action Buttons and Tabs ---
	bottomLayout = QVBoxLayout()
	actionLayout = QHBoxLayout()
	window._parseButton = QPushButton("Parse & Validate")
	window._parseButton.setToolTip("Parse the LLM response (from the tab below), extract code changes, and validate syntax.")
	# --- ADDED BUTTON ---
	window._saveAcceptedButton = QPushButton("Save Accepted (Current File)")
	window._saveAcceptedButton.setToolTip("Save only the changes you have manually accepted in the diff view for the currently focused file.")
	# --- END ADDED BUTTON ---
	window._saveFilesButton = QPushButton("Save All Validated Changes") # Renamed slightly for clarity
	window._saveFilesButton.setToolTip("Save ALL validated, proposed changes (for ALL files modified by the LLM) to the local repository.") # Updated tooltip
	window._commitPushButton = QPushButton("Commit & Push")
	window._commitPushButton.setToolTip("Commit the currently STAGED changes in the local repository and push them to the default remote/branch (Does NOT stage automatically).")
	actionLayout.addWidget(window._parseButton)
	actionLayout.addWidget(window._saveAcceptedButton) # Add the new button
	actionLayout.addWidget(window._saveFilesButton)
	actionLayout.addWidget(window._commitPushButton)
	actionLayout.addStretch(1)
	bottomLayout.addLayout(actionLayout)

	window._bottomTabWidget = QTabWidget()
	window._bottomTabWidget.setToolTip("View diffs, LLM responses, and application logs.")

	# Tab 1: Side-by-Side Diff (for focused file)
	diffWidget = QWidget()
	diffLayout = QVBoxLayout(diffWidget)
	diffSplitter = QSplitter(Qt.Orientation.Horizontal)
	codeFont = QFont(HTML_FONT_FAMILY.split(',')[0].strip("'"))
	codeFont.setStyleHint(QFont.StyleHint.Monospace)
	try:
		codeFont.setPointSize(int(HTML_FONT_SIZE.replace('pt','')))
	except ValueError:
		logger.warning(f"Could not parse font size '{HTML_FONT_SIZE}'. Using default.")
		codeFont.setPointSize(10) # Default size

	originalLayout = QVBoxLayout()
	originalLayout.addWidget(QLabel("Original Code (Focused File):"))
	window._originalCodeArea = QTextEdit()
	window._originalCodeArea.setReadOnly(True)
	window._originalCodeArea.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
	window._originalCodeArea.setFont(codeFont)
	window._originalCodeArea.setToolTip("Shows the original content of the file currently focused in the list above.")
	window._originalCodeArea.setObjectName("originalCodeArea") # Add object name
	originalLayout.addWidget(window._originalCodeArea)
	originalContainer = QWidget()
	originalContainer.setLayout(originalLayout)
	originalContainer.setObjectName("originalCodeContainer")
	diffSplitter.addWidget(originalContainer)

	proposedLayout = QVBoxLayout()
	proposedLayout.addWidget(QLabel("Proposed Code (Accept Changes Below):")) # Update label
	window._proposedCodeArea = QTextBrowser()  # Change to QTextBrowser
	window._proposedCodeArea.setReadOnly(True) # Keep read-only, interaction via HTML content
	window._proposedCodeArea.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
	window._proposedCodeArea.setFont(codeFont)
	window._proposedCodeArea.setToolTip("Shows the proposed changes. Use controls within this view to accept/reject individual changes before saving.")
	window._proposedCodeArea.setObjectName("proposedCodeArea") # Add object name
	# --- Add link anchor handling ---
	window._proposedCodeArea.setOpenLinks(False) # Prevent default link opening
	window._proposedCodeArea.anchorClicked.connect(window._handle_diff_anchor_click) # Connect to handler in MainWindow
	# --- End link anchor handling ---
	proposedLayout.addWidget(window._proposedCodeArea)
	proposedContainer = QWidget()
	proposedContainer.setLayout(proposedLayout)
	proposedContainer.setObjectName("proposedCodeContainer")
	diffSplitter.addWidget(proposedContainer)


	diffSplitter.setSizes([400, 400])
	diffLayout.addWidget(diffSplitter)
	window._bottomTabWidget.addTab(diffWidget, "Side-by-Side Diff")

	# Tab 2: LLM Response
	llmResponseWidget = QWidget()
	llmResponseLayout = QVBoxLayout(llmResponseWidget)
	window._llmResponseArea = QTextEdit() # The moved widget
	window._llmResponseArea.setPlaceholderText("LLM response will appear here, or paste response and click 'Parse & Validate'")
	window._llmResponseArea.setReadOnly(False) # Initially editable for paste
	window._llmResponseArea.setToolTip("Displays the raw response from the LLM or allows pasting a response.")
	llmResponseLayout.addWidget(window._llmResponseArea)
	window._bottomTabWidget.addTab(llmResponseWidget, "LLM Response")

	# Tab 3: Application Log
	window._appLogArea = QTextEdit()
	window._appLogArea.setReadOnly(True)
	window._appLogArea.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
	logFont = QFont("monospace")
	logFont.setPointSize(10)
	window._appLogArea.setFont(logFont)
	window._appLogArea.setToolTip("Shows detailed application logs, including errors and status updates.")
	window._bottomTabWidget.addTab(window._appLogArea, "Application Log")

	bottomLayout.addWidget(window._bottomTabWidget, stretch=1)
	window._mainLayout.addLayout(bottomLayout, stretch=1)

	# --- Status Bar ---
	window._statusBar = QStatusBar()
	window.setStatusBar(window._statusBar)
	window._progressBar = QProgressBar()
	window._progressBar.setVisible(False)
	window._progressBar.setTextVisible(True)
	window._progressBar.setRange(0, 100)
	window._progressBar.setValue(0)
	window._progressBar.setFormat("%p%")
	window._progressBar.setToolTip("Shows the progress of background operations.")
	window._statusBar.addPermanentWidget(window._progressBar)

	window.setGeometry(100, 100, 1100, 850) # Set default geometry
	logger.debug("UI setup complete.")

# --- END: gui/ui_setup.py ---