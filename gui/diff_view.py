# gui/diff_view.py
"""
Module responsible for generating and displaying the side-by-side diff view
in the MainWindow, and handling related interactions like scroll synchronization.
"""
import difflib
import html
import logging
import os
from typing import Optional, List, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
	from .main_window import MainWindow

from PySide6.QtWidgets import QListWidgetItem, QTextEdit

# Constants for UI styling (Copied from main_window.py)
HTML_COLOR_ADDED_BG = "#e6ffed"
HTML_COLOR_DELETED_BG = "#ffeef0"
HTML_COLOR_PLACEHOLDER_BG = "#f8f9fa"
HTML_COLOR_LINE_NUM = "#6c757d"
HTML_COLOR_TEXT = "#212529"

# --- ADDED LINES ---
HTML_FONT_FAMILY = "'Courier New', Courier, monospace" # Copied from ui_setup.py
HTML_FONT_SIZE = "9pt" # Copied from ui_setup.py
# --- END ADDED LINES ---


# Type hint for MainWindow to avoid circular import if necessary
# if TYPE_CHECKING:
#    from .main_window import MainWindow

logger = logging.getLogger(__name__)

# Maximum file size (in bytes) to attempt reading for diff view
# to prevent memory/performance issues.
MAX_DIFF_FILE_SIZE = 1 * 1024 * 1024 # 1MB

# Maximum number of lines to process for diff generation if content is huge
MAX_DIFF_LINES = 5000


def handle_current_item_change_for_diff(window: 'MainWindow', current: Optional[QListWidgetItem], previous: Optional[QListWidgetItem]) -> None:
	"""
	Handles changes in the *currently focused* file list item to update the diff view.
	Wrapper function to call the main display logic.

	Args:
		window: The MainWindow instance.
		current: The newly focused QListWidgetItem (or None).
		previous: The previously focused QListWidgetItem (or None).
	"""
	# Check if the window object exists and if it's busy
	if not hasattr(window, '_isBusy') or window._isBusy:
		return
	display_selected_file_diff(window, current)

def display_selected_file_diff(window: 'MainWindow', current_item: Optional[QListWidgetItem]) -> None:
	"""
	Displays the diff for the currently focused file item in the side-by-side view.
	Loads original content if necessary and compares against parsed/proposed content.

	Args:
		window: The MainWindow instance.
		current_item: The currently focused QListWidgetItem (or None).
	"""
	# Check if the window object exists and if it's busy
	if not hasattr(window, '_isBusy') or window._isBusy: return # Avoid updates during critical operations

	# Ensure UI elements exist before trying to clear or update them
	if not hasattr(window, '_originalCodeArea') or not hasattr(window, '_proposedCodeArea'):
		logger.error("Diff view areas not found on MainWindow.")
		return

	# Clear previous diff content
	window._originalCodeArea.clear()
	window._proposedCodeArea.clear()

	if not current_item:
		if hasattr(window, '_updateStatusBar'):
			window._updateStatusBar("Select a file to view diff.", 3000)
		sync_scrollbars(window) # Ensure scrollbars are reset/synced
		return

	filePath: str = current_item.text()
	logger.debug(f"Updating diff view for focused file: {filePath}")

	# Ensure necessary attributes exist on the window object
	if not hasattr(window, '_originalFileContents') or not hasattr(window, '_clonedRepoPath'):
		logger.error("Required attributes missing for diff view update.")
		return

	# --- Ensure Original Content is Available ---
	# Check cache first
	original_content: Optional[str] = window._originalFileContents.get(filePath, "__NOT_CHECKED__") # Use sentinel value

	# If not checked yet, try loading it (lazy loading)
	if original_content == "__NOT_CHECKED__":
		if window._clonedRepoPath:
			full_path = os.path.join(window._clonedRepoPath, filePath)
			if os.path.exists(full_path) and os.path.isfile(full_path):
				try:
					file_size = os.path.getsize(full_path)
					if file_size > MAX_DIFF_FILE_SIZE:
						logger.warning(f"Original file '{filePath}' too large for diff view ({file_size} bytes). Storing placeholder.")
						original_content = f"<File too large to display in diff (>{MAX_DIFF_FILE_SIZE // 1024} KB)>"
					else:
						with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
							original_content = f.read()
						logger.debug(f"Lazily loaded original content for {filePath} into cache.")
					# Store in cache even if placeholder or loaded
					window._originalFileContents[filePath] = original_content
				except Exception as e:
					logger.error(f"Error reading original file '{filePath}' for diff: {e}", exc_info=True)
					original_content = f"<Error reading file: {e}>"
					window._originalFileContents[filePath] = original_content # Cache the error state
			else:
				# If the file doesn't exist locally, it might be a new file proposed by LLM
				# Mark as explicitly non-existent in the cache
				original_content = None
				window._originalFileContents[filePath] = None
				logger.debug(f"Original file '{filePath}' not found locally or is not a file.")
		else:
			# No repo path, cannot load
			original_content = None
			window._originalFileContents[filePath] = None # Mark as not checkable/non-existent

	# --- Determine Proposed Content and Status ---
	proposed_content: Optional[str] = None
	is_new_file: bool = False
	status_msg: str = f"Displaying Diff: {filePath}"
	validation_info: str = ""

	parsed_data_exists = hasattr(window, '_parsedFileData') and window._parsedFileData is not None
	validation_errors_exist = hasattr(window, '_validationErrors') and window._validationErrors is not None

	# Get validation status string
	if validation_errors_exist and filePath in window._validationErrors:
		count = len(window._validationErrors[filePath])
		validation_info = f" - <font color='red'><b>Validation Failed ({count} error{'s' if count != 1 else ''})</b></font>"
	elif parsed_data_exists and filePath in window._parsedFileData and validation_errors_exist:
		# Show OK only if parsed data exists AND validation passed for this file
		validation_info = " - <font color='green'>Validation OK</font>"

	# Determine proposed content based on state
	if parsed_data_exists:
		if filePath in window._parsedFileData:
			proposed_content = window._parsedFileData[filePath]
			# Check if original_content is None (meaning file didn't exist or couldn't be read)
			if original_content is None:
				is_new_file = True
				original_content = "" # Treat as diff against empty for display
				status_msg += " - New File"
			# Check if original content is a placeholder indicating read error/too large
			elif isinstance(original_content, str) and original_content.startswith("<"):
				status_msg += " - Original Unreadable vs Proposed" # Can't reliably compare
			elif original_content == proposed_content:
				status_msg += " - Original == Proposed (No Changes)"
			else:
				status_msg += " - Original vs Proposed"
		elif original_content is not None and not isinstance(original_content, str) and original_content.startswith("<"):
            # Original exists but has read error/too large, no proposed changes
			proposed_content = original_content # Show original placeholder on both sides
			status_msg += " - Original (Unreadable, No Changes Proposed)"
			validation_info = ""
		elif original_content is not None:
			# File exists, readable, but wasn't in parsed data (no change proposed by LLM)
			proposed_content = original_content # Show original on both sides
			status_msg += " - Original (No Changes Proposed)"
			validation_info = "" # No validation status needed if no changes proposed
		else:
			# File path from list widget doesn't exist in original or proposed (edge case)
			proposed_content = "(File details unavailable)"
			original_content = proposed_content # Show same placeholder on both sides
			validation_info = ""
			status_msg += " - (Error: Content unavailable)"
	elif original_content is not None and not isinstance(original_content, str) and original_content.startswith("<"):
		# No parsed data YET, show original placeholder vs proposed placeholder
		proposed_content = "<No proposed changes yet. Send to LLM and Parse response.>"
		status_msg += " - Original (Unreadable, Awaiting LLM Response & Parse)"
		validation_info = ""
	elif original_content is not None:
		# No parsed data YET, show original vs placeholder
		proposed_content = "<No proposed changes yet. Send to LLM and Parse response.>"
		status_msg += " - Original (Awaiting LLM Response & Parse)"
		validation_info = ""
	else:
		# No original content loaded (e.g., before clone or file doesn't exist)
		original_content = "(Content not loaded or file is new)"
		proposed_content = "<No proposed changes yet. Send to LLM and Parse response.>"
		status_msg += " - (Awaiting Context / LLM Response & Parse)"
		validation_info = ""

	# --- Generate and Display HTML Diff ---
	original_html = ""
	proposed_html = ""
	try:
		# Ensure content variables are strings before splitting
		original_lines = (original_content or "").splitlines()
		proposed_lines = (proposed_content or "").splitlines()

		# Limit lines processed if content is huge
		if len(original_lines) > MAX_DIFF_LINES or len(proposed_lines) > MAX_DIFF_LINES:
			logger.warning(f"Content of '{filePath}' too long ({len(original_lines)}/{len(proposed_lines)} lines), truncating diff comparison to {MAX_DIFF_LINES} lines.")
			truncated_orig_lines = original_lines[:MAX_DIFF_LINES]
			truncated_prop_lines = proposed_lines[:MAX_DIFF_LINES]
			trunc_msg_html = f"<p style='color:orange; font-style:italic; padding: 2px 10px;'>Diff truncated for performance ({MAX_DIFF_LINES} lines shown).</p>"
			orig_diff_html, prop_diff_html = _generate_diff_html(truncated_orig_lines, truncated_prop_lines, is_new_file)
			# Prepend the truncation message to the body content
			original_html = orig_diff_html.replace("<body>", "<body>" + trunc_msg_html, 1)
			proposed_html = prop_diff_html.replace("<body>", "<body>" + trunc_msg_html, 1)
		else:
			original_html, proposed_html = _generate_diff_html(original_lines, proposed_lines, is_new_file)

	except Exception as e:
		logger.error(f"Error generating HTML diff for '{filePath}': {e}", exc_info=True)
		error_escaped = html.escape(str(e))
		original_html = f"<body><p style='color:red;'>Error generating diff: {error_escaped}</p></body>"
		proposed_html = "<body><p style='color:red;'>Error generating diff.</p></body>"

	# --- Update UI ---
	# Block signals during HTML set to prevent recursive scroll sync
	orig_sb = window._originalCodeArea.verticalScrollBar()
	prop_sb = window._proposedCodeArea.verticalScrollBar()
	orig_sb_blocked = orig_sb.blockSignals(True)
	prop_sb_blocked = prop_sb.blockSignals(True)

	try:
		window._originalCodeArea.setHtml(original_html)
		window._proposedCodeArea.setHtml(proposed_html)
	finally:
		# Ensure signals are unblocked even if setHtml raises an error
		orig_sb.blockSignals(orig_sb_blocked)
		prop_sb.blockSignals(prop_sb_blocked)

	if hasattr(window, '_updateStatusBar'):
		window._updateStatusBar(status_msg + validation_info, 10000) # Show status longer
	sync_scrollbars(window) # Sync scrollbars after content is set


def _generate_diff_html(original_lines: List[str], proposed_lines: List[str], is_new_file: bool) -> Tuple[str, str]:
	"""
	Generates side-by-side HTML diff view for two lists of strings (code lines).

	Args:
		original_lines: List of strings representing the original file content lines.
		proposed_lines: List of strings representing the proposed file content lines.
		is_new_file: Boolean indicating if the proposed content represents a new file.

	Returns:
		A tuple containing two strings: (original_html, proposed_html).
	"""
	# Define base HTML structure and CSS styles (using constants defined above)
	# Ensure constants are accessible here (they should be defined at module level)
	html_style = (f"<style>body{{margin:0;padding:0;font-family:{HTML_FONT_FAMILY};font-size:{HTML_FONT_SIZE};color:{HTML_COLOR_TEXT};background-color:#fff;}}"
				  f".line{{display:flex;white-space:pre;min-height:1.2em;border-bottom:1px solid #eee;}}"
				  f".line-num{{flex:0 0 40px;text-align:right;padding-right:10px;color:{HTML_COLOR_LINE_NUM};background-color:#f1f1f1;user-select:none;border-right:1px solid #ddd;}}"
				  f".line-content{{flex-grow:1;padding-left:10px;}}"
				  f".equal{{background-color:#fff;}}.delete{{background-color:{HTML_COLOR_DELETED_BG};}}"
				  f".insert{{background-color:{HTML_COLOR_ADDED_BG};}}"
				  f".placeholder{{background-color:{HTML_COLOR_PLACEHOLDER_BG};color:#aaa;font-style:italic;}}"
				  f".new-file-placeholder{{background-color:{HTML_COLOR_DELETED_BG};color:#aaa;font-style:italic;text-align:center;}}" # Style for new file placeholder
				  f"</style>")

	original_html_body_lines: List[str] = []
	proposed_html_body_lines: List[str] = []

	def format_line(num: Optional[int], content: str, css_class: str) -> str:
		"""Helper function to format a single line of HTML diff."""
		# Escape content and handle spaces/tabs for HTML preformatted text
		escaped_content = html.escape(content).replace(" ", "&nbsp;").replace("\t", "&nbsp;" * 4) or "&nbsp;"
		num_str = str(num) if num is not None else "&nbsp;" # Use number if provided, else non-breaking space
		return f'<div class="line {css_class}"><div class="line-num">{num_str}</div><div class="line-content">{escaped_content}</div></div>'

	if is_new_file:
		# Special case for new files: show placeholder on left, all inserted lines on right
		original_html_body_lines.append('<div class="line new-file-placeholder"><div class="line-num">&nbsp;</div><div class="line-content">&lt;New File&gt;</div></div>')
		for i, line in enumerate(proposed_lines):
			proposed_html_body_lines.append(format_line(i + 1, line, 'insert'))
	else:
		# Use difflib for generating diff operations
		# autojunk=False is important for code diffs to avoid treating lines like comments as junk
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
				original_html_body_lines.append(format_line(o_ln, o_line, o_css))
				proposed_html_body_lines.append(format_line(p_ln, p_line, p_css))

	# Combine style, body, and closing tags for the final HTML
	final_original_html = html_style + "<body>\n" + "\n".join(original_html_body_lines) + "\n</body>"
	final_proposed_html = html_style + "<body>\n" + "\n".join(proposed_html_body_lines) + "\n</body>"

	return final_original_html, final_proposed_html


# --- Scroll Synchronization Functions ---

def sync_scroll_proposed_from_original(window: 'MainWindow', value: int) -> None:
	"""Syncs the proposed code area scrollbar when the original one moves."""
	if not window._is_syncing_scroll:
		window._is_syncing_scroll = True
		if hasattr(window, '_proposedCodeArea'):
			window._proposedCodeArea.verticalScrollBar().setValue(value)
		window._is_syncing_scroll = False

def sync_scroll_original_from_proposed(window: 'MainWindow', value: int) -> None:
	"""Syncs the original code area scrollbar when the proposed one moves."""
	if not window._is_syncing_scroll:
		window._is_syncing_scroll = True
		if hasattr(window, '_originalCodeArea'):
			window._originalCodeArea.verticalScrollBar().setValue(value)
		window._is_syncing_scroll = False

def sync_scrollbars(window: 'MainWindow') -> None:
	"""
	Forces synchronization of scrollbars, typically after loading new content.
	Reads the value from the original scrollbar and sets the proposed one.
	"""
	if not window._is_syncing_scroll:
		window._is_syncing_scroll = True
		try:
			if hasattr(window, '_originalCodeArea') and hasattr(window, '_proposedCodeArea'):
				orig_val = window._originalCodeArea.verticalScrollBar().value()
				window._proposedCodeArea.verticalScrollBar().setValue(orig_val)
		except Exception as e:
			logger.error(f"Error during manual scrollbar sync: {e}")
		finally:
			window._is_syncing_scroll = False