# Updated Codebase/gui/diff_view.py
# --- START: gui/diff_view.py ---
# gui/diff_view.py
"""
Module responsible for generating and displaying the side-by-side diff view
in the MainWindow. Allows navigation between changed chunks using arrow keys,
highlights the focused chunk, and uses cursor positioning for visibility.
Ensures scroll position is maintained during acceptance updates.
"""
import difflib
import html
import logging
import os
import uuid # Used for fallback chunk IDs if needed, though stable IDs preferred
from typing import Optional, List, Tuple, TYPE_CHECKING, Dict, Set

# Qt Imports
from PySide6.QtWidgets import QListWidgetItem, QTextEdit
from PySide6.QtGui import QFont, QColor, QTextCursor # Import QTextCursor
from PySide6.QtCore import QTimer # Import QTimer for delayed actions

# Type hint for MainWindow to avoid circular import issues at runtime
if TYPE_CHECKING:
	from .main_window import MainWindow

# Logger for this module
logger: logging.Logger = logging.getLogger(__name__)

# --- Constants ---

# Style Constants for HTML Diff View
HTML_COLOR_ADDED_BG: str = "#e6ffed" # Background for added lines
HTML_COLOR_DELETED_BG: str = "#ffeef0" # Background for deleted lines
HTML_COLOR_PLACEHOLDER_BG: str = "#f8f9fa" # Background for placeholder lines
HTML_COLOR_LINE_NUM: str = "#6c757d" # Colour for line numbers
HTML_COLOR_TEXT: str = "#212529" # Default text colour
HTML_FONT_FAMILY: str = "'Courier New', Courier, monospace" # Monospace font stack
HTML_FONT_SIZE: str = "9pt" # Font size
HTML_COLOR_ACCEPTED_BG: str = "#cfe2ff" # Light Blue background for accepted chunks
HTML_COLOR_ACTION_LINK: str = "#007bff" # Colour for action links (accept/reject/undo)
HTML_ACTION_SYMBOL_ACCEPT: str = "&#x2714;" # Check mark ✔
HTML_ACTION_SYMBOL_REJECT: str = "&#x2718;" # Cross mark ✘
HTML_ACTION_SYMBOL_UNDO: str = "&#x21A9;" # Undo arrow ↩
HTML_COLOR_FOCUSED_BORDER: str = "#007bff" # Blue border for the currently focused chunk
HTML_STYLE_FOCUSED_CHUNK: str = f"outline: 1px solid {HTML_COLOR_FOCUSED_BORDER}; outline-offset: -1px;" # CSS for focused chunk outline

# Performance/Resource Limits
MAX_DIFF_FILE_SIZE: int = 1 * 1024 * 1024 # 1MB limit for attempting diff generation
MAX_DIFF_LINES: int = 5000 # Limit lines processed for diff if content is huge

# Acceptance State Enum (using integers for simplicity)
ACCEPTANCE_PENDING: int = 0 # Default state, action needed
ACCEPTANCE_ACCEPTED: int = 1 # User accepted the change
ACCEPTANCE_REJECTED: int = 2 # User rejected the change (optional state, can treat pending as rejected)


# --- Helper Functions ---

def _get_current_acceptance_state(window: 'MainWindow', file_path: str) -> Dict[str, int]:
	"""
	Safely retrieves the acceptance state dictionary for a given file path from the MainWindow.

	Args:
		window (MainWindow): The main application window instance.
		file_path (str): The relative path of the file whose state is needed.

	Returns:
		Dict[str, int]: The acceptance state dictionary (chunk_id -> ACCEPTANCE_*) for the file,
						or an empty dictionary if not found or state attribute is missing.
	"""
	if not hasattr(window, '_acceptedChangesState'):
		logger.error("'_acceptedChangesState' attribute missing from MainWindow.")
		return {} # Return empty dict to prevent crashes
	# Return the specific file's state dict, or an empty dict if the file has no state yet
	return window._acceptedChangesState.get(file_path, {})


# --- Main Diff Update Logic ---

def handle_current_item_change_for_diff(window: 'MainWindow', current: Optional[QListWidgetItem], previous: Optional[QListWidgetItem]) -> None:
	"""
	Slot connected to the file list's currentItemChanged signal.
	Updates the diff view when the focused file changes, clearing focus state.

	Args:
		window (MainWindow): The main application window instance.
		current (Optional[QListWidgetItem]): The newly selected list item (or None).
		previous (Optional[QListWidgetItem]): The previously selected list item (or None).
	"""
	# Avoid updates if a background task is running
	if not hasattr(window, '_isBusy') or window._isBusy:
		logger.debug("handle_current_item_change_for_diff: Window busy or not ready, skipping.")
		return

	# Clear focus tracking variables when the selected file changes
	if hasattr(window, '_last_clicked_chunk_id'):
		window._last_clicked_chunk_id = None
		logger.debug("Cleared last focused chunk ID due to file change.")
	if hasattr(window, '_current_chunk_id_list'):
		window._current_chunk_id_list = []
		logger.debug("Cleared current chunk ID list due to file change.")
	if hasattr(window, '_current_chunk_start_block_map'):
		window._current_chunk_start_block_map = {}
		logger.debug("Cleared current chunk start block map due to file change.")

	# Trigger the main diff display update
	display_selected_file_diff(window, current)


def display_selected_file_diff(window: 'MainWindow', current_item: Optional[QListWidgetItem], preserve_scroll: bool = False) -> None:
	"""
	Displays the side-by-side diff for the selected file.

	Generates HTML for original and proposed code, including acceptance controls
	and focus highlighting. Stores metadata about generated chunks (IDs, start blocks).
	Handles scrolling behaviour (preserve position after actions, scroll to focus after navigation).

	Args:
		window (MainWindow): The main application window instance.
		current_item (Optional[QListWidgetItem]): The list item representing the selected file.
		preserve_scroll (bool): If True, attempts to maintain the current scrollbar positions
								after refreshing the HTML content. Typically used after user
								actions like accept/reject within the view. Defaults to False.
	"""
	# Avoid updates if busy
	if not hasattr(window, '_isBusy') or window._isBusy:
		logger.debug("display_selected_file_diff: Window busy or not ready, skipping.")
		return

	# Check for required attributes on the MainWindow instance
	required_attrs: List[str] = [
		'_originalCodeArea', '_proposedCodeArea', '_originalFileContents',
		'_clonedRepoPath', '_parsedFileData', '_validationErrors',
		'_updateStatusBar', '_acceptedChangesState', '_updateWidgetStates',
		'_last_clicked_chunk_id', '_current_chunk_id_list', '_current_chunk_start_block_map'
	]
	if not all(hasattr(window, attr) for attr in required_attrs):
		logger.error("display_selected_file_diff: Required attributes missing on MainWindow. Cannot update diff.")
		return

	# --- Scroll Position Handling ---
	# Store current scroll positions *only if* preservation is requested
	original_scroll_value: int = window._originalCodeArea.verticalScrollBar().value() if preserve_scroll else 0
	proposed_scroll_value: int = window._proposedCodeArea.verticalScrollBar().value() if preserve_scroll else 0
	if preserve_scroll:
		logger.debug(f"Scroll preservation requested. Stored: Original={original_scroll_value}, Proposed={proposed_scroll_value}")

	# --- Clear Previous Content ---
	window._originalCodeArea.clear()
	window._proposedCodeArea.clear()

	# --- Handle No Selection ---
	if not current_item:
		window._updateStatusBar("Select a file to view diff.", 3000)
		sync_scrollbars(window) # Reset scrollbars
		window._updateWidgetStates() # Update button states etc.
		window._current_chunk_id_list = [] # Clear chunk metadata
		window._current_chunk_start_block_map = {}
		return

	# --- Prepare for Diff Generation ---
	filePath: str = current_item.text()
	focused_chunk_id_for_html: Optional[str] = window._last_clicked_chunk_id # Get current focus from main window state
	logger.debug(f"--- Start Diff Update for: {filePath} (Focused Chunk: {focused_chunk_id_for_html}) ---")

	# --- Ensure Original Content is Available ---
	# (Checks cache, loads from file if necessary, handles large files/errors)
	original_content: Optional[str] = window._originalFileContents.get(filePath, "__NOT_CHECKED__")
	if original_content == "__NOT_CHECKED__":
		original_content = None # Assume None initially
		if window._clonedRepoPath:
			full_path: str = os.path.join(window._clonedRepoPath, filePath)
			if os.path.exists(full_path) and os.path.isfile(full_path):
				try:
					file_size: int = os.path.getsize(full_path)
					if file_size > MAX_DIFF_FILE_SIZE:
						original_content = f"<File too large to display in diff (>{MAX_DIFF_FILE_SIZE // 1024} KB)>"
						logger.warning(f"Original file '{filePath}' too large ({file_size} bytes).")
					else:
						with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
							original_content = f.read()
						logger.debug(f"Lazily loaded original content for {filePath}.")
				except Exception as e:
					logger.error(f"Error reading original file '{filePath}' for diff: {e}", exc_info=True)
					original_content = f"<Error reading file: {e}>"
			else:
				# File doesn't exist locally (might be new)
				logger.debug(f"Original file '{filePath}' not found locally (treat as new/None).")
		else:
			# No repo path, cannot load
			logger.warning(f"Cannot load original content for '{filePath}': No repository path.")
		# Cache the result (content, error message, or None)
		window._originalFileContents[filePath] = original_content
	# --- End Original Content ---

	# --- Determine Proposed Content and Status ---
	# (Checks parsed data, compares with original, sets status messages)
	proposed_content: Optional[str] = None
	is_new_file: bool = False
	status_msg: str = f"Diff: {filePath}"
	validation_info: str = ""
	can_accept_changes: bool = False
	parsed_data_exists: bool = window._parsedFileData is not None
	validation_errors_exist: bool = window._validationErrors is not None

	# Determine validation status string
	if validation_errors_exist and filePath in window._validationErrors:
		count = len(window._validationErrors[filePath])
		validation_info = f" - <font color='red'><b>Validation Failed ({count} error{'s' if count != 1 else ''})</b></font>"
	elif parsed_data_exists and filePath in window._parsedFileData and (not validation_errors_exist or filePath not in window._validationErrors):
		validation_info = " - <font color='green'>Validation OK</font>"

	# Determine proposed content based on state
	if parsed_data_exists and filePath in window._parsedFileData:
		proposed_content = window._parsedFileData[filePath]
		if original_content is None:
			is_new_file = True; original_content = ""; status_msg += " - New File"; can_accept_changes = bool(proposed_content)
		elif isinstance(original_content, str) and original_content.startswith("<"):
			status_msg += " - Original Unreadable vs Proposed"; can_accept_changes = True
		elif original_content == proposed_content:
			status_msg += " - No Changes Detected"; can_accept_changes = False
		else:
			status_msg += " - Original vs Proposed"; can_accept_changes = True
	elif original_content is not None and isinstance(original_content, str) and original_content.startswith("<"):
		proposed_content = "<No proposed changes (Original Unreadable).>"; status_msg += " - Original (Unreadable, No Changes Proposed)";
	elif original_content is not None:
		proposed_content = original_content # Show original on both sides if no changes proposed
		status_msg += " - Original (No Changes Proposed)";
	else: # No original content loaded (e.g., before clone) and no parsed data yet
		original_content = "(Content not loaded or file is new)"; proposed_content = "<No proposed changes yet. Send to LLM and Parse response.>"; status_msg += " - (Awaiting Context / LLM Response)";
	# --- End Proposed Content ---

	# --- Generate HTML Diff Content ---
	original_html_body: str = ""
	proposed_html_body: str = ""
	generated_chunk_id_list: List[str] = []
	generated_chunk_block_map: Dict[str, int] = {}
	current_file_acceptance: Dict[str, int] = _get_current_acceptance_state(window, filePath)

	try:
		original_lines: List[str] = (original_content or "").splitlines()
		proposed_lines: List[str] = (proposed_content or "").splitlines()
		logger.debug(f"Generating HTML diff view. Original Lines: {len(original_lines)}, Proposed Lines: {len(proposed_lines)}")

		# Apply line limits if necessary
		trunc_msg_html: str = ""
		if len(original_lines) > MAX_DIFF_LINES or len(proposed_lines) > MAX_DIFF_LINES:
			orig_diff_lines = original_lines[:MAX_DIFF_LINES]
			prop_diff_lines = proposed_lines[:MAX_DIFF_LINES]
			trunc_msg_html = f"<p style='color:orange; font-style:italic; padding: 2px 10px;'>Diff view truncated ({MAX_DIFF_LINES} lines shown).</p>"
			logger.warning(f"Content truncated for diff comparison to {MAX_DIFF_LINES} lines.")
		else:
			orig_diff_lines = original_lines
			prop_diff_lines = proposed_lines

		# Call the generator function
		original_html_body, proposed_html_body, generated_chunk_id_list, generated_chunk_block_map = _generate_diff_html_with_acceptance(
			orig_diff_lines,
			prop_diff_lines,
			is_new_file,
			current_file_acceptance,
			focused_chunk_id_for_html # Pass the focused chunk ID for highlighting
		)

		# Store the generated chunk metadata in MainWindow state
		window._current_chunk_id_list = generated_chunk_id_list
		window._current_chunk_start_block_map = generated_chunk_block_map
		logger.debug(f"Stored chunk metadata: {len(generated_chunk_id_list)} IDs, {len(generated_chunk_block_map)} block mappings.")

	except Exception as e:
		logger.error(f"Error generating HTML diff content for '{filePath}': {e}", exc_info=True)
		error_escaped: str = html.escape(str(e))
		original_html_body = f"<p style='color:red;'>Error generating diff view: {error_escaped}</p>"
		proposed_html_body = f"<p style='color:red;'>Error generating diff view.</p>"
		# Ensure metadata lists are cleared on error
		window._current_chunk_id_list = []
		window._current_chunk_start_block_map = {}

	# Construct full HTML documents
	template: str = getattr(_generate_diff_html_with_acceptance, 'HTML_TEMPLATE', "<!DOCTYPE html><html><head>{style}</head><body>{body}</body></html>")
	style: str = getattr(_generate_diff_html_with_acceptance, 'HTML_STYLE', "<style></style>")
	original_html: str = template.format(style=style, body=trunc_msg_html + original_html_body)
	proposed_html: str = template.format(style=style, body=trunc_msg_html + proposed_html_body)
	# --- End Generate HTML ---

	# --- Update UI Elements ---
	# Block scrollbar signals during update
	orig_sb = window._originalCodeArea.verticalScrollBar()
	prop_sb = window._proposedCodeArea.verticalScrollBar()
	orig_sb_blocked: bool = orig_sb.blockSignals(True)
	prop_sb_blocked: bool = prop_sb.blockSignals(True)

	try:
		# Set the HTML content
		window._originalCodeArea.setHtml(original_html)
		window._proposedCodeArea.setHtml(proposed_html)
		logger.debug("HTML content set in QTextEdit widgets.")

		# --- Scroll Position Restoration (if requested) ---
		if preserve_scroll:
			# Use QTimer to restore scroll position after Qt has processed the setHtml call
			def restore_scroll() -> None:
				# This function runs after a short delay
				logger.debug(f"Attempting to restore scroll positions: Original={original_scroll_value}, Proposed={proposed_scroll_value}")
				# Block signals again temporarily during setValue
				orig_sb.blockSignals(True)
				prop_sb.blockSignals(True)
				try:
					# Clamp value to current maximum to avoid errors if content shrunk
					orig_max: int = orig_sb.maximum()
					prop_max: int = prop_sb.maximum()
					orig_sb.setValue(min(original_scroll_value, orig_max))
					prop_sb.setValue(min(proposed_scroll_value, prop_max))
					logger.debug(f"Scroll positions restored (Max O:{orig_max}, P:{prop_max}).")
				except Exception as e:
					logger.error(f"Error restoring scroll positions: {e}")
				finally:
					# IMPORTANT: Unblock signals after setting value
					orig_sb.blockSignals(orig_sb_blocked) # Restore original block state
					prop_sb.blockSignals(prop_sb_blocked) # Restore original block state
					logger.debug("Scrollbar signals unblocked after restoration attempt.")
			# Schedule the restore_scroll function to run soon
			QTimer.singleShot(0, restore_scroll) # 0ms delay often sufficient

	except Exception as set_html_error:
		# Handle critical errors during setHtml
		logger.critical(f"CRITICAL: Error occurred during setHtml for '{filePath}': {set_html_error}", exc_info=True)
		try:
			# Attempt to display an error message within the text areas
			error_msg_html: str = f"<body><p style='color:red;font-weight:bold;'>Failed to render diff view:<br>{html.escape(str(set_html_error))}</p></body>"
			window._originalCodeArea.setHtml(error_msg_html)
			window._proposedCodeArea.setHtml(error_msg_html)
		except Exception as fallback_err:
			# Log if even the fallback fails
			logger.error(f"Failed even to set fallback error HTML: {fallback_err}")

	finally:
		# Ensure signals are eventually unblocked if timer logic isn't used or fails
		if not preserve_scroll:
			# Unblock immediately only if scroll preservation timer wasn't started
			orig_sb.blockSignals(orig_sb_blocked)
			prop_sb.blockSignals(prop_sb_blocked)
			logger.debug("Scrollbar signals unblocked (no preservation requested).")
		else:
			# Scroll preservation timer will handle unblocking
			logger.debug("Scrollbar signal unblocking deferred to QTimer.")

	# Update status bar and widget states
	window._updateStatusBar(status_msg + validation_info, 10000)
	window._updateWidgetStates() # Update button enables etc.
	logger.debug(f"--- End Diff Update for: {filePath} ---")


# --- Updated Function to Generate HTML (Returns Block Map, No Anchors) ---
def _generate_diff_html_with_acceptance(
	original_lines: List[str],
	proposed_lines: List[str],
	is_new_file: bool,
	acceptance_state: Dict[str, int],
	focused_chunk_id: Optional[str]
) -> Tuple[str, str, List[str], Dict[str, int]]:
	"""
	Generates side-by-side HTML diff body content.

	Includes acceptance controls (links) and focus highlighting based on state.
	Also returns a list of generated chunk IDs in order of appearance and a map
	linking chunk IDs to their approximate starting block (line) number in the
	proposed view HTML structure. Does NOT include surrounding HTML tags (html, head, body).

	Args:
		original_lines: Lines of the original file content.
		proposed_lines: Lines of the proposed file content.
		is_new_file: True if the proposed content represents a new file.
		acceptance_state: Dictionary mapping chunk IDs to their acceptance status (ACCEPTANCE_*).
		focused_chunk_id: The ID of the chunk that should receive focus highlighting, if any.

	Returns:
		Tuple containing:
		- original_html_body (str): HTML content for the left diff pane (body only).
		- proposed_html_body (str): HTML content for the right diff pane (body only).
		- chunk_id_list (List[str]): Ordered list of chunk IDs generated for changes.
		- chunk_start_block_map (Dict[str, int]): Map of chunk ID to starting block index.
	"""
	# Define styles (moved here for access within helper function if needed, or keep global)
	# Using function attributes to keep template/style together without global scope pollution
	_generate_diff_html_with_acceptance.HTML_STYLE = (
		f"<style>body{{margin:0;padding:0;font-family:{HTML_FONT_FAMILY};font-size:{HTML_FONT_SIZE};color:{HTML_COLOR_TEXT};background-color:#fff;}}"
		f".line{{display:flex;white-space:pre;min-height:1.4em;border-bottom:1px solid #eee;align-items:center;}}"
		f".line-num{{flex:0 0 40px;text-align:right;padding:0 10px 0 0;color:{HTML_COLOR_LINE_NUM};background-color:#f1f1f1;user-select:none;border-right:1px solid #ddd; align-self: stretch; display: flex; align-items: center; justify-content: flex-end;}}"
		f".line-content{{flex-grow:1;padding-left:10px;}}"
		f".line-actions{{flex:0 0 55px; padding: 0 5px; text-align:center; align-self: stretch; display: flex; align-items: center; justify-content: space-around; border-left: 1px solid #eee;}}"
		f".action-link{{color:{HTML_COLOR_ACTION_LINK}; text-decoration:none; font-size: 1.2em; cursor:pointer;}} .action-link:hover{{color:#0056b3;}}"
		f".equal{{background-color:#fff;}} .equal .line-actions{{background-color:#fff;}}"
		f".delete{{background-color:{HTML_COLOR_DELETED_BG};}} .delete .line-actions{{background-color:{HTML_COLOR_DELETED_BG};}}"
		f".insert{{background-color:{HTML_COLOR_ADDED_BG};}} .insert .line-actions{{background-color:{HTML_COLOR_ADDED_BG};}}"
		f".placeholder{{background-color:{HTML_COLOR_PLACEHOLDER_BG};color:#aaa;font-style:italic;}} .placeholder .line-actions{{background-color:{HTML_COLOR_PLACEHOLDER_BG};}}"
		f".new-file-placeholder{{background-color:{HTML_COLOR_DELETED_BG};color:#aaa;font-style:italic;text-align:center;}} .new-file-placeholder .line-actions{{background-color:{HTML_COLOR_DELETED_BG};}}"
		f".accepted{{background-color:{HTML_COLOR_ACCEPTED_BG} !important;}} .accepted .line-actions{{background-color:{HTML_COLOR_ACCEPTED_BG} !important;}}" # Blue background
		f".focused-chunk {{ {HTML_STYLE_FOCUSED_CHUNK} }}" # Focus outline
		# Removed anchor style
		f"</style>"
	)
	_generate_diff_html_with_acceptance.HTML_TEMPLATE = "<!DOCTYPE html><html><head><meta charset='UTF-8'>{style}</head><body>\n{body}\n</body></html>"

	# Initialise lists and map for results
	original_html_body_lines: List[str] = []
	proposed_html_body_lines: List[str] = []
	chunk_id_list: List[str] = [] # Stores generated chunk IDs in order
	chunk_start_block_map: Dict[str, int] = {} # Maps chunk ID to its starting block index
	current_prop_block_index: int = 0 # Tracks block index (line number) in the proposed view HTML

	# --- Helper function to format a single line ---
	def format_line_with_actions(num: Optional[int], content: str, base_css_class: str, chunk_id: Optional[str], current_chunk_state: int, is_focused: bool) -> str:
		""" Formats a line with number, content, styles, and action links. """
		escaped_content: str = html.escape(content).replace(" ", "&nbsp;").replace("\t", "&nbsp;" * 4) or "&nbsp;"
		num_str: str = str(num) if num is not None else "&nbsp;"

		# Determine CSS classes based on state
		acceptance_css_class: str = " accepted" if current_chunk_state == ACCEPTANCE_ACCEPTED else ""
		# elif current_chunk_state == ACCEPTANCE_REJECTED: acceptance_css_class = " rejected" # Optional
		focus_css_class: str = " focused-chunk" if is_focused else ""
		final_css_class: str = base_css_class + acceptance_css_class + focus_css_class

		# Generate action links HTML
		action_html: str = ""
		if chunk_id and base_css_class in ['insert', 'delete']: # Only show actions on actual changes
			if current_chunk_state == ACCEPTANCE_PENDING:
				accept_link: str = f'<a href="accept:{chunk_id}" class="action-link" title="Accept Change">{HTML_ACTION_SYMBOL_ACCEPT}</a>'
				reject_link: str = f'<a href="reject:{chunk_id}" class="action-link" title="Reject Change">{HTML_ACTION_SYMBOL_REJECT}</a>'
				action_html = f"{accept_link}&nbsp;{reject_link}"
			else: # Show Undo if already Accepted or Rejected
				undo_link: str = f'<a href="undo:{chunk_id}" class="action-link" title="Undo Decision">{HTML_ACTION_SYMBOL_UNDO}</a>'
				action_html = f"{undo_link}"

		# Include data-chunk attribute for potential future use (e.g., JS interaction)
		chunk_attr: str = f'data-chunk="{chunk_id}"' if chunk_id else ''

		# Construct the line HTML
		# Removed the named anchor <a name="..."></a>
		return (f'<div class="line {final_css_class}" {chunk_attr}>'
				f'<div class="line-num">{num_str}</div>'
				f'<div class="line-content">{escaped_content}</div>'
				f'<div class="line-actions">{action_html}</div>'
				f'</div>')
	# --- End Helper Function ---

	# --- Main Diff Loop ---
	if is_new_file:
		# Handle new file as a single insert chunk
		chunk_id: str = f"insert-0-0-0-{len(proposed_lines)}" # Stable ID based on diff params
		chunk_state: int = acceptance_state.get(chunk_id, ACCEPTANCE_PENDING)
		is_focused_chunk: bool = chunk_id == focused_chunk_id

		# Record chunk metadata
		if chunk_id not in chunk_id_list: chunk_id_list.append(chunk_id)
		chunk_start_block_map[chunk_id] = current_prop_block_index # Starts at block 0

		# Generate HTML lines
		original_html_body_lines.append('<div class="line new-file-placeholder"><div class="line-num">&nbsp;</div><div class="line-content">&lt;New File&gt;</div><div class="line-actions">&nbsp;</div></div>')
		for i, line in enumerate(proposed_lines):
			proposed_html_body_lines.append(format_line_with_actions(i + 1, line, 'insert', chunk_id, chunk_state, is_focused_chunk))
			current_prop_block_index += 1 # Increment block count
	else:
		# Use difflib to compare original and proposed lines
		matcher = difflib.SequenceMatcher(None, original_lines, proposed_lines, autojunk=False)
		o_num, p_num = 1, 1 # Line numbers

		for tag, i1, i2, j1, j2 in matcher.get_opcodes():
			chunk_id: Optional[str] = None
			chunk_state: int = ACCEPTANCE_PENDING
			is_focused_chunk: bool = False
			# Process each type of change (opcode)
			if tag != 'equal':
				# This block represents a change (delete, insert, replace)
				chunk_id = f"{tag}-{i1}-{i2}-{j1}-{j2}" # Generate stable ID
				chunk_state = acceptance_state.get(chunk_id, ACCEPTANCE_PENDING)
				is_focused_chunk = chunk_id == focused_chunk_id

				# Record chunk metadata if not already seen
				if chunk_id not in chunk_id_list:
					chunk_id_list.append(chunk_id)
				# Map chunk ID to the starting block index in the proposed view
				# Important: Do this *before* adding lines for this chunk
				chunk_start_block_map[chunk_id] = current_prop_block_index

			# Iterate through lines affected by this opcode
			max_len: int = max(i2 - i1, j2 - j1)
			for i in range(max_len):
				o_idx, p_idx = i1 + i, j1 + i
				o_line, p_line = "", ""
				o_css, p_css = "placeholder", "placeholder"
				o_ln, p_ln = None, None

				# Determine line content and CSS class based on tag
				if tag == 'equal':
					if o_idx < i2: o_line, o_css, o_ln = original_lines[o_idx], 'equal', o_num; o_num += 1
					if p_idx < j2: p_line, p_css, p_ln = proposed_lines[p_idx], 'equal', p_num; p_num += 1
				elif tag == 'delete':
					if o_idx < i2: o_line, o_css, o_ln = original_lines[o_idx], 'delete', o_num; o_num += 1
					p_line, p_css, p_ln = "", 'placeholder', None # Placeholder on proposed side
				elif tag == 'insert':
					o_line, o_css, o_ln = "", 'placeholder', None # Placeholder on original side
					if p_idx < j2: p_line, p_css, p_ln = proposed_lines[p_idx], 'insert', p_num; p_num += 1
				elif tag == 'replace':
					if o_idx < i2: o_line, o_css, o_ln = original_lines[o_idx], 'delete', o_num; o_num += 1
					else: o_line, o_css, o_ln = "", 'placeholder', None
					if p_idx < j2: p_line, p_css, p_ln = proposed_lines[p_idx], 'insert', p_num; p_num += 1
					else: p_line, p_css, p_ln = "", 'placeholder', None

				# Format the HTML lines using the helper
				original_html_body_lines.append(format_line_with_actions(o_ln, o_line, o_css, None, ACCEPTANCE_PENDING, False)) # Original side never focused, no actions

				# Determine if this specific proposed line belongs to the focused chunk
				# (Handle placeholders within a replace/insert chunk correctly)
				proposed_chunk_id_for_line: Optional[str] = chunk_id if p_css != 'placeholder' else None
				line_is_focused: bool = is_focused_chunk and (proposed_chunk_id_for_line is not None)
				proposed_html_body_lines.append(format_line_with_actions(p_ln, p_line, p_css, proposed_chunk_id_for_line, chunk_state, line_is_focused))

				# Increment block index for every line added to the proposed view body
				current_prop_block_index += 1
	# --- End Diff Loop ---

	# Combine lines into final HTML body strings
	final_original_html_body: str = "\n".join(original_html_body_lines)
	final_proposed_html_body: str = "\n".join(proposed_html_body_lines)

	# Return the HTML bodies and the collected chunk metadata
	return final_original_html_body, final_proposed_html_body, chunk_id_list, chunk_start_block_map
# --- End Generate HTML ---


# --- Scroll Sync Functions --- (unchanged)
def sync_scroll_proposed_from_original(window: 'MainWindow', value: int) -> None:# ...
	if not window._is_syncing_scroll: window._is_syncing_scroll=True;
	if hasattr(window,'_proposedCodeArea'): window._proposedCodeArea.verticalScrollBar().setValue(value); window._is_syncing_scroll=False;
def sync_scroll_original_from_proposed(window: 'MainWindow', value: int) -> None:# ...
	if not window._is_syncing_scroll: window._is_syncing_scroll=True;
	if hasattr(window,'_originalCodeArea'): window._originalCodeArea.verticalScrollBar().setValue(value); window._is_syncing_scroll=False;
def sync_scrollbars(window: 'MainWindow') -> None:# ...
	if not window._is_syncing_scroll: window._is_syncing_scroll=True;
	try:
		if hasattr(window,'_originalCodeArea') and hasattr(window,'_proposedCodeArea'): val=window._originalCodeArea.verticalScrollBar().value(); window._proposedCodeArea.verticalScrollBar().setValue(val);
	except Exception as e: logger.error(f"Err scroll sync: {e}");
	finally: window._is_syncing_scroll=False;


# --- generate_accepted_content --- (unchanged)
def generate_accepted_content(original_lines: List[str], proposed_lines: List[str], acceptance_state: Dict[str, int]) -> Optional[str]:
	# ... (as before) ...
	logger.debug("Gen accepted content..."); final_lines: List[str] = []
	try:
		matcher = difflib.SequenceMatcher(None, original_lines, proposed_lines, autojunk=False)
		for tag, i1, i2, j1, j2 in matcher.get_opcodes():
			chunk_id = f"{tag}-{i1}-{i2}-{j1}-{j2}"; current_state = acceptance_state.get(chunk_id, ACCEPTANCE_PENDING)
			if tag == 'equal': final_lines.extend(original_lines[i1:i2])
			elif tag == 'delete':
				if current_state != ACCEPTANCE_ACCEPTED: final_lines.extend(original_lines[i1:i2])
			elif tag == 'insert':
				if current_state == ACCEPTANCE_ACCEPTED: final_lines.extend(proposed_lines[j1:j2])
			elif tag == 'replace':
				if current_state == ACCEPTANCE_ACCEPTED: final_lines.extend(proposed_lines[j1:j2])
				else: final_lines.extend(original_lines[i1:i2])
		return "\n".join(final_lines)
	except Exception as e: logger.error(f"Error gen accepted content: {e}", exc_info=True); return None
# --- END: gui/diff_view.py ---