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
from typing import List 

# Define standard formats - can be customised via config or arguments
DEFAULT_LOG_FORMAT: str = '%(asctime)s - %(name)s - %(levelname)s - %(module)s:%(lineno)d - %(message)s'
DEFAULT_DATE_FORMAT: str = '%Y-%m-%d %H:%M:%S'


def setupLogging(
	logLevel: int = logging.DEBUG,
	logToConsole: bool = True,
	logToFile: bool = True, # Defaulting to True, often useful
	logFileName: str = 'app.log',
	logFileLevel: int = logging.DEBUG,
	logDir: str = 'logs', # Default log directory
	maxBytes: int = 10*1024*1024, # 10 MB
	backupCount: int = 5,
	logFormat: str = DEFAULT_LOG_FORMAT,
	dateFormat: str = DEFAULT_DATE_FORMAT
) -> logging.Logger:
	"""
	Configures the root logger for the application.

	Sets up console and/or file logging handlers with specified levels and formats.
	Removes existing handlers before adding new ones to prevent duplication.

	Args:
		logLevel (int): The minimum logging level for the root logger (default: DEBUG).
		logToConsole (bool): Whether to add a handler to log messages to the console (stderr).
		logToFile (bool): Whether to add a handler to log messages to a rotating file.
		logFileName (str): The name of the log file (used if logToFile is True).
		logFileLevel (int): The minimum logging level for the file handler.
		logDir (str): The directory where the log file should be stored.
		maxBytes (int): The maximum size in bytes before the log file rotates.
		backupCount (int): The number of backup log files to keep.
		logFormat (str): The logging format string.
		dateFormat (str): The date format string for the formatter.

	Returns:
		logging.Logger: The configured root logger instance.
	"""
	# Declare list locally
	logHandlers: List[logging.Handler] = []

	formatter: logging.Formatter = logging.Formatter(logFormat, datefmt=dateFormat)

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
			# Use os.path.abspath to handle relative paths robustly
			absLogDir = os.path.abspath(logDir)
			if not os.path.exists(absLogDir):
				os.makedirs(absLogDir, exist_ok=True)

			logFilePath: str = os.path.join(absLogDir, logFileName)

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
			print(f"ERROR: Failed to configure file logging to '{os.path.join(logDir, logFileName)}': {e}", file=sys.stderr)
			# Log using root logger if console handler was added
			if logToConsole:
				logging.getLogger().error(f"Failed to configure file logging: {e}", exc_info=False)


	# Get the root logger and configure it
	rootLogger: logging.Logger = logging.getLogger()
	rootLogger.setLevel(logLevel)

	# Clear existing handlers before adding new ones (important if re-configuring)
	if rootLogger.hasHandlers():
		# Explicitly copy list before iterating for removal
		existingHandlers: List[logging.Handler] = rootLogger.handlers[:]
		for handler in existingHandlers:
			rootLogger.removeHandler(handler)

	# Add the newly configured handlers
	for handler in logHandlers:
		rootLogger.addHandler(handler)

	if logHandlers: # Only log if handlers were successfully added
		rootLogger.info(f"Logging initialised (Root Level: {logging.getLevelName(rootLogger.level)}). Console: {logToConsole}, File: {logToFile} (Level: {logging.getLevelName(logFileLevel)} in '{os.path.join(logDir, logFileName)}').")
	else:
		print("WARNING: Logging initialisation completed but no handlers were configured.", file=sys.stderr)

	return rootLogger

# --- END: utils/logger_setup.py ---