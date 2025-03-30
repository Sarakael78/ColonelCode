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
from PySide6.QtGui import QIcon # Import QIcon for setting application icon
from core.config_manager import ConfigManager
from core.exceptions import ConfigurationError
from gui.main_window import MainWindow # Assuming MainWindow is implemented here
from utils.logger_setup import setupLogging

# --- Constants ---
CONFIG_FILE_PATH: str = 'config.ini'
ENV_FILE_PATH: str = '.env'

def configure_logging(config_manager: ConfigManager) -> logging.Logger:
    """Configure logging based on loaded configuration settings."""
    file_log_level_name = config_manager.getConfigValue('Logging', 'FileLogLevel', fallback='DEBUG')
    log_dir = config_manager.getConfigValue('Logging', 'LogDirectory', fallback='logs')
    log_filename = config_manager.getConfigValue('Logging', 'LogFileName', fallback='app_log.log')
    file_log_level = getattr(logging, file_log_level_name.upper(), logging.DEBUG)
    
    return setupLogging(
        logToConsole=True,
        logToFile=True,
        logFileLevel=file_log_level,
        logDir=log_dir,
        logFileName=log_filename
    )

def main() -> None:
	"""Main application entry point."""
	# Initial basic logging setup
	logger: logging.Logger = setupLogging(logToConsole=True, logToFile=True)
	logger.info("================ Application Starting ================")

	configManager: ConfigManager = ConfigManager(CONFIG_FILE_PATH, ENV_FILE_PATH)
	try:
		configManager.loadEnv()
		configManager.loadConfig()
		
		# Reconfigure logging with settings from config
		logger = configure_logging(configManager)
		logger.info("Configuration loaded. Logger reconfigured with settings from config.")

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


	app.setWindowIcon(QIcon(os.path.join('resources', 'app_icon.png')))

	try:
		mainWindow: MainWindow = MainWindow(configManager)
		mainWindow.setWindowTitle("LLM Code Updater")
		
		# Set window geometry from config or use defaults
		width = int(configManager.getConfigValue('GUI', 'WindowWidth', fallback='1024'))
		height = int(configManager.getConfigValue('GUI', 'WindowHeight', fallback='768'))
		mainWindow.resize(width, height)
		
		# Center the window on screen
		screen = app.primaryScreen().geometry()
		mainWindow.setGeometry(
			(screen.width() - width) // 2,
			(screen.height() - height) // 2,
			width,
			height
		)
		
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