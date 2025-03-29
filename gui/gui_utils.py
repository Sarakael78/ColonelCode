# Updated Codebase/gui/gui_utils.py
# --- START: gui/gui_utils.py ---
# gui/gui_utils.py
"""
Utility functions and classes specific to the GUI components.
Includes the custom logging handler for directing logs to the GUI.
"""

import logging
import sys # Import sys for stderr fallback
from typing import Callable, Optional
from PySide6.QtCore import QObject, Signal # Removed Slot as it's not used here

class QtLogHandler(logging.Handler, QObject):
	"""
	A custom logging handler that emits Qt signals with formatted log messages.
	Inherits from logging.Handler and QObject.
	"""
	# No explicit Signal definition needed here as the emitter is passed in.

	# Store the callable that will emit the signal (e.g., self.signalLogMessage.emit)
	_signal_emitter: Optional[Callable[[str], None]] = None

	# --- CORRECTED __init__ ---
	# Accepts the emitter callable and an optional QObject parent separately.
	def __init__(self: 'QtLogHandler', signal_emitter: Optional[Callable[[str], None]] = None, parent: Optional[QObject] = None) -> None:
		"""
		Initialiser for the QtLogHandler.

		Args:
			signal_emitter (Optional[Callable[[str], None]]): The callable (e.g., signal.emit) to call with the formatted log message.
			parent (QObject, optional): Parent QObject. Defaults to None.
		"""
		# Initialise base classes correctly
		logging.Handler.__init__(self)
		# Pass ONLY the parent QObject (or None) to the QObject initialiser
		QObject.__init__(self, parent)
		# Store the signal emitter callable
		self._signal_emitter = signal_emitter
	# --- END CORRECTION ---

	def emit(self: 'QtLogHandler', record: logging.LogRecord) -> None:
		"""
		Formats the log record and emits it via the stored signal emitter callable.

		Args:
			record (logging.LogRecord): The log record to process.
		"""
		# Check if an emitter callable was provided
		if not self._signal_emitter:
			# Handle case where no emitter was given (maybe log to stderr?)
			# Ensure sys is imported if using stderr here
			print(f"QtLogHandler Error: No signal emitter configured. Log Record: {record}", file=sys.stderr)
			return

		try:
			# Use the formatter attached to this handler (set during setup)
			msg = self.format(record)
			# Call the stored signal emitter callable
			self._signal_emitter(msg)
		except Exception:
			# Fallback in case of formatting errors etc.
			self.handleError(record)

	# Optional: Implement close() if resources need cleanup
	# def close(self) -> None:
	#     logging.Handler.close(self)

# --- END: gui/gui_utils.py ---