# --- START: utils/logger_setup.py ---
# utils/logger_setup.py
"""
Provides a centralised function for configuring the application's logging system.
Sets up handlers (console, file) and formatters.
"""

import logging
import sys
import os
from logging.handlers import RotatingFileHandler
from typing import List # Import List type hint explicitly

# Define a standard format - can be customised further
LOG_FORMAT: str = '%(asctime)s - %(name)s - %(levelname)s - %(module)s:%(lineno)d - %(message)s'
DATE_FORMAT: str = '%Y-%m-%d %H:%M:%S'

# Adhering to user preference for explicit initialisation
logHandlers: List[logging.Handler] = [] # Use List type hint

def setupLogging(
	logLevel: int = logging.INFO,
	logToConsole: bool = True,
	logToFile: bool = True, # Defaulting to True, often useful
	logFileName: str = 'app.log',
	logFileLevel: int = logging.INFO,
	logDir: str = 'logs', # Default log directory
	maxBytes: int = 10*1024*1024, # 10 MB
	backupCount: int = 5
) -> logging.Logger:
	"""
	Configures the root logger for the application.

	Sets up console and/or file logging handlers with specified levels and formats.

	Args:
		logLevel (int): The minimum logging level for the root logger (default: INFO).
		logToConsole (bool): Whether to add a handler to log messages to the console (stderr).
		logToFile (bool): Whether to add a handler to log messages to a rotating file.
		logFileName (str): The name of the log file (used if logToFile is True).
		logFileLevel (int): The minimum logging level for the file handler.
		logDir (str): The directory where the log file should be stored.
		maxBytes (int): The maximum size in bytes before the log file rotates.
		backupCount (int): The number of backup log files to keep.

	Returns:
		logging.Logger: The configured root logger instance.

	# TODO: Implement a custom logging handler (e.g., in gui/gui_utils.py) that emits Qt signals
	      to update a QTextEdit widget in the GUI. Add an option here to attach it.
	"""
	# Using global list as per user style preference example, although direct assignment is more common
	global logHandlers
	logHandlers = [] # Reset handlers each time setup is called (important if re-configuring)

	formatter: logging.Formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

	# Configure Console Handler
	if logToConsole:
		consoleHandler: logging.StreamHandler = logging.StreamHandler(sys.stderr)
		consoleHandler.setFormatter(formatter)
		# Console handler typically uses the root logger's level,
		# but can be set explicitly if needed: consoleHandler.setLevel(logLevel)
		logHandlers.append(consoleHandler)

	# Configure File Handler
	if logToFile:
		try:
			# Ensure log directory exists
			if not os.path.exists(logDir):
				os.makedirs(logDir, exist_ok=True)

			logFilePath: str = os.path.join(logDir, logFileName)

			# Use RotatingFileHandler for better log management
			fileHandler: RotatingFileHandler = RotatingFileHandler(
				logFilePath,
				maxBytes=maxBytes,
				backupCount=backupCount,
				encoding='utf-8'
			)
			fileHandler.setFormatter(formatter)
			fileHandler.setLevel(logFileLevel)
			logHandlers.append(fileHandler)
		except (OSError, IOError) as e:
			# If file logging setup fails, log an error to console (if available)
			# or just print, and continue without file logging.
			fallbackLogger: logging.Logger = logging.getLogger(__name__)
			# Ensure there's at least a console handler temporarily if others failed
			if not any(isinstance(h, logging.StreamHandler) for h in fallbackLogger.handlers):
					fallbackLogger.addHandler(logging.StreamHandler(sys.stderr))
			fallbackLogger.setLevel(logging.ERROR)
			fallbackLogger.error(f"Failed to configure file logging to '{logFilePath}': {e}", exc_info=True)
			# Optionally re-raise or handle differently depending on requirements


	# Get the root logger and configure it
	rootLogger: logging.Logger = logging.getLogger()
	rootLogger.setLevel(logLevel)

	# Clear existing handlers (important if re-configuring, prevents duplicate logs)
	if rootLogger.hasHandlers():
		# Explicitly copy list before iterating for removal
		existingHandlers: List[logging.Handler] = rootLogger.handlers[:] # Use List type hint
		for handler in existingHandlers:
			rootLogger.removeHandler(handler)

	# Add the newly configured handlers
	for handler in logHandlers:
		rootLogger.addHandler(handler)

	if logHandlers: # Only log if handlers were successfully added
		rootLogger.info(f"Logging initialised (Level: {logging.getLevelName(rootLogger.level)}). Console: {logToConsole}, File: {logToFile} (Level: {logging.getLevelName(logFileLevel)} in '{os.path.join(logDir, logFileName)}').")
	else:
		print("WARNING: Logging initialisation completed but no handlers were configured.", file=sys.stderr)

	return rootLogger

# --- END: utils/logger_setup.py ---