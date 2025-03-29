# --- START: gui/gui_utils.py ---
# gui/gui_utils.py
"""
Utility functions and classes specific to the GUI components.
Includes the custom logging handler for directing logs to the GUI.
"""

import logging
from PySide6.QtCore import QObject, Signal, Slot # Import Slot if needed

class QtLogHandler(logging.Handler, QObject):
	"""
	A custom logging handler that emits Qt signals with formatted log messages.
	Inherits from logging.Handler and QObject.
	"""
	# Signal signature: emits the formatted log message string
	logMessageSignal = Signal(str)

	def __init__(self, parent: QObject = None) -> None:
		"""
		Initialiser for the QtLogHandler.

		Args:
			parent (QObject, optional): Parent QObject. Defaults to None.
		"""
		# Initialize both base classes
		logging.Handler.__init__(self)
		QObject.__init__(self, parent)

	def emit(self, record: logging.LogRecord) -> None:
		"""
		Formats the log record and emits it via the signal.

		Args:
			record (logging.LogRecord): The log record to process.
		"""
		try:
			# Use the formatter attached to this handler (set during setup)
			msg = self.format(record)
			# Emit the signal with the formatted message
			self.logMessageSignal.emit(msg)
		except Exception:
			# Fallback in case of formatting errors etc.
			self.handleError(record)

	# Optional: Implement close() if resources need cleanup
	# def close(self) -> None:
	#     logging.Handler.close(self)

# --- END: gui/gui_utils.py ---