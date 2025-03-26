# --- START: main.py ---
# main.py
"""
Main application entry point.
Initialises logging, configuration, the GUI, and starts the Qt event loop.
"""
import sys
import logging
import os # For path manipulation if needed
from PySide6.QtWidgets import QApplication, QMessageBox # Import QMessageBox for error display
from core.config_manager import ConfigManager
from core.exceptions import ConfigurationError, BaseApplicationError
from gui.main_window import MainWindow # Assuming MainWindow is implemented here
from utils.logger_setup import setupLogging

# --- Constants ---
# Adhering to user preference for explicit initialisation
CONFIG_FILE_PATH: str = 'config.ini'
ENV_FILE_PATH: str = '.env'

def main() -> None:
	"""Main application entry point."""
	# Setup logging first (basic console logging initially)
	# TODO: Enhance setupLogging to potentially get log dir/level from config *after* loading
	#       Currently uses defaults defined in logger_setup.py
	logger: logging.Logger = setupLogging(logToConsole=True, logToFile=True) # Enable file logging by default
	logger.info("================ Application Starting ================")

	configManager: ConfigManager = ConfigManager(CONFIG_FILE_PATH, ENV_FILE_PATH)
	try:
		# Load sensitive data (API keys) from .env first for security
		configManager.loadEnv() # .env is optional, won't raise error if missing unless required later

		# Load non-sensitive settings from config.ini
		configManager.loadConfig() # config.ini is also optional by default

		# Now that config might be loaded, potentially reconfigure logger if needed
		# Example: Update file log level based on config
		fileLogLevelName = configManager.getConfigValue('Logging', 'FileLogLevel', fallback='INFO')
		logDir = configManager.getConfigValue('Logging', 'LogDirectory', fallback='logs')
		logFileName = configManager.getConfigValue('Logging', 'LogFileName', fallback='app_log.log')
		fileLogLevel = getattr(logging, fileLogLevelName.upper(), logging.INFO)
		# Re-setup logger with potentially updated file logging params
		logger = setupLogging(logToConsole=True, logToFile=True, logFileLevel=fileLogLevel, logDir=logDir, logFileName=logFileName)
		logger.info("Configuration loaded. Logger potentially reconfigured.")

		# Check for essential configuration/secrets needed immediately
		# Example: Check for Gemini API Key
		apiKey = configManager.getEnvVar('GEMINI_API_KEY', required=True) # Make it required here
		if not apiKey:
			# This case should be caught by required=True, but as a safeguard:
			raise ConfigurationError("GEMINI_API_KEY is missing in environment variables or .env file.")

		logger.info("Essential configuration validated.")

	except ConfigurationError as e:
		errorMessage = f"Fatal Configuration Error: {e}\nPlease check your '{ENV_FILE_PATH}' and '{CONFIG_FILE_PATH}' files.\nApplication cannot continue."
		logger.critical(errorMessage, exc_info=True)
		# Show message box *before* QApplication is necessarily running
		tempApp = QApplication.instance() # Check if already exists
		if not tempApp:
				tempApp = QApplication(sys.argv) # Create temporary instance for message box
		QMessageBox.critical(None, "Configuration Error", errorMessage)
		sys.exit(1) # Use non-zero exit code for errors
	except Exception as e: # Catch unexpected errors during startup
		errorMessage = f"An unexpected critical error occurred during initialisation: {e}"
		logger.critical(errorMessage, exc_info=True)
		# Show message box if possible
		tempApp = QApplication.instance()
		if not tempApp:
				tempApp = QApplication(sys.argv)
		QMessageBox.critical(None, "Fatal Error", errorMessage)
		sys.exit(1)

	# --- GUI Initialisation ---
	# Ensure QApplication instance exists (might have been created for error msg)
	app: QApplication = QApplication.instance()
	if not app:
			app = QApplication(sys.argv)

	# TODO: Add application icon loading/setting here
	# app.setWindowIcon(QIcon(os.path.join('resources', 'app_icon.png')))

	# Pass the config manager to the main window
	try:
		mainWindow: MainWindow = MainWindow(configManager) # MainWindow needs implementing
		# # TODO: Set window title, initial size etc.
		mainWindow.setWindowTitle("LLM Code Updater")
		mainWindow.show()
	except Exception as e:
		# Catch errors specifically during MainWindow initialisation
		errorMessage = f"Failed to initialise the main application window: {e}"
		logger.critical(errorMessage, exc_info=True)
		QMessageBox.critical(None, "GUI Initialisation Error", errorMessage)
		sys.exit(1)

	logger.info("Main window displayed. Starting Qt event loop.")
	try:
		exitCode: int = app.exec()
		logger.info(f"Application finished with exit code: {exitCode}")
		sys.exit(exitCode)
	except Exception as e:
		# Catch unhandled exceptions escaping the event loop (less common)
		logger.critical(f"An unhandled exception occurred in the Qt event loop: {e}", exc_info=True)
		# Attempt graceful shutdown/logging if possible, then exit
		QMessageBox.critical(None, "Fatal Runtime Error", f"A critical error occurred: {e}")
		sys.exit(1) # Use non-zero exit code for errors

if __name__ == "__main__":
	# Enforce running from script entry point
	main()
# --- END: main.py ---