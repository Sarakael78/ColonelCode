# Updated Codebase/gui/signal_connections.py
# --- START: gui/signal_connections.py ---
# gui/signal_connections.py
"""
Module responsible for connecting signals to slots in the MainWindow.
"""

from PySide6.QtWidgets import QMainWindow, QListWidgetItem
from PySide6.QtCore import Slot, Signal, Qt, QUrl # Import QUrl
from typing import Optional, Dict, List, Tuple, Any

import logging

from . import event_handlers
from . import callback_handlers
from . import diff_view

logger = logging.getLogger(__name__)

from typing import TYPE_CHECKING
if TYPE_CHECKING:
	from .main_window import MainWindow

def connect_signals(window: 'MainWindow') -> None:
	""" Connects all signals to their corresponding slots. """
	logger.debug("Connecting signals to slots.")

	# --- Internal Window Signals ---
	window.signalLogMessage.connect(window._appendLogMessage)

	# --- UI Widget Signals ---
	window._browseButton.clicked.connect(lambda: event_handlers.handle_browse_repo(window))
	window._cloneButton.clicked.connect(lambda: event_handlers.handle_clone_load_repo(window))

	# File List Signals
	window._fileListWidget.itemSelectionChanged.connect(lambda: event_handlers.handle_file_selection_change(window))
	window._fileListWidget.currentItemChanged.connect(lambda item, prev: diff_view.handle_current_item_change_for_diff(window, item, prev))

	# LLM Interaction Signals
	window._sendToLlmButton.clicked.connect(lambda: event_handlers.handle_send_to_llm(window))
	window._pasteResponseButton.clicked.connect(lambda: event_handlers.handle_paste_response(window))
	window._llmResponseArea.textChanged.connect(window._updateWidgetStates)

	# Action Button Signals
	window._parseButton.clicked.connect(lambda: event_handlers.handle_parse_and_validate(window))
	# --- ADDED CONNECTION for new button ---
	window._saveAcceptedButton.clicked.connect(window._handle_save_accepted) # Connect direct slot in MainWindow
	# --- END ADDED ---
	window._saveFilesButton.clicked.connect(lambda: event_handlers.handle_save_changes(window)) # Keep original
	window._commitPushButton.clicked.connect(lambda: event_handlers.handle_commit_push(window))

	# --- Diff View Interaction ---
	# Connected in ui_setup.py: window._proposedCodeArea.anchorClicked.connect(window._handle_diff_anchor_click)

	# --- Worker Signals ---
	# GitHub Worker
	window._githubWorker.statusUpdate.connect(window._updateStatusBar)
	window._githubWorker.progressUpdate.connect(window._updateProgress)
	window._githubWorker.errorOccurred.connect(lambda msg: callback_handlers.handle_worker_error(window, msg, "GitHubWorker"))
	window._githubWorker.gitHubError.connect(lambda msg: callback_handlers.handle_github_error(window, msg))
	window._githubWorker.cloneFinished.connect(lambda path, files: callback_handlers.on_clone_load_finished(window, path, files))
	window._githubWorker.commitPushFinished.connect(lambda msg: callback_handlers.on_commit_push_finished(window, msg))
	window._githubWorker.isDirtyFinished.connect(lambda is_dirty: callback_handlers.on_is_dirty_finished(window, is_dirty))
	window._githubWorker.pullFinished.connect(lambda msg, conflicts: callback_handlers.on_pull_finished(window, msg, conflicts))
	window._githubWorker.listFilesFinished.connect(lambda files: callback_handlers.on_list_files_finished(window, files))
	window._githubWorker.readFileFinished.connect(lambda content: callback_handlers.on_read_file_finished(window, content))

	# LLM Worker
	window._llmWorker.statusUpdate.connect(window._updateStatusBar)
	window._llmWorker.progressUpdate.connect(window._updateProgress)
	window._llmWorker.errorOccurred.connect(lambda msg: callback_handlers.handle_worker_error(window, msg, "LLMWorker"))
	window._llmWorker.llmError.connect(lambda msg: callback_handlers.handle_llm_error(window, msg))
	window._llmWorker.llmQueryFinished.connect(lambda response: callback_handlers.on_llm_finished(window, response))

	# File Worker
	window._fileWorker.statusUpdate.connect(window._updateStatusBar)
	window._fileWorker.progressUpdate.connect(window._updateProgress)
	window._fileWorker.errorOccurred.connect(lambda msg: callback_handlers.handle_worker_error(window, msg, "FileWorker"))
	window._fileWorker.fileProcessingError.connect(lambda msg: callback_handlers.handle_file_processing_error(window, msg))
	window._fileWorker.parsingFinished.connect(lambda data, errors: callback_handlers.on_parsing_finished(window, data, errors))
	window._fileWorker.savingFinished.connect(lambda files: callback_handlers.on_saving_finished(window, files)) # Existing handler should work
	window._fileWorker.fileContentsRead.connect(lambda contents, instruction: callback_handlers.on_file_contents_read(window, contents, instruction))

	# --- UI Helper Signals (Scroll Sync) ---
	orig_scrollbar = window._originalCodeArea.verticalScrollBar()
	prop_scrollbar = window._proposedCodeArea.verticalScrollBar()
	orig_scrollbar.valueChanged.connect(lambda val: diff_view.sync_scroll_proposed_from_original(window, val))
	prop_scrollbar.valueChanged.connect(lambda val: diff_view.sync_scroll_original_from_proposed(window, val))

	logger.debug("Signal connections established.")

# --- END: gui/signal_connections.py ---