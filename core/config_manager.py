# Updated Codebase/core/config_manager.py
# --- START: core/config_manager.py ---
# core/config_manager.py
"""
Manages loading and accessing application configuration from various sources.
Prioritises environment variables (via .env file) for secrets,
and uses a configuration file (config.ini) for non-sensitive settings.
Includes functionality to save configuration changes back to the .ini file.
"""

import os
import configparser
from dotenv import load_dotenv
from typing import Optional, Any, List # Import List
import logging

# Relative import within the same package - ensure project structure allows this
# If running scripts directly within core/, this might fail. Run from project root.
from .exceptions import ConfigurationError

# Get a logger instance specific to this module
logger: logging.Logger = logging.getLogger(__name__)

class ConfigManager:
	"""
	Handles loading and providing access to configuration parameters.
	Loads from .env files and .ini files, and allows saving changes to .ini.
	"""
	_config: configparser.ConfigParser
	_envLoaded: bool
	_configLoaded: bool
	_configLoadAttempted: bool # Track if loadConfig was called
	_configLoadError: Optional[Exception] = None # Store load error
	_envFilePath: Optional[str]
	_configFilePath: Optional[str]

	def __init__(self: 'ConfigManager', configFilePath: Optional[str] = 'config.ini', envFilePath: Optional[str] = '.env') -> None:
		"""
		Initialises the ConfigManager.

		Args:
			configFilePath (Optional[str]): Path to the .ini configuration file.
			envFilePath (Optional[str]): Path to the .env file for environment variables.
		"""
		# Use interpolation=None to disable interpolation globally for this parser instance
		self._config = configparser.ConfigParser(interpolation=None)
		self._envLoaded = False
		self._configLoaded = False
		self._configLoadAttempted = False
		self._configLoadError = None
		self._envFilePath = envFilePath
		self._configFilePath = configFilePath
		logger.debug(f"ConfigManager initialised with config file: '{configFilePath}', env file: '{envFilePath}'")

	def loadEnv(self: 'ConfigManager', override: bool = False) -> bool:
		"""
		Loads environment variables from the .env file specified during initialisation.
		Existing environment variables will NOT be overwritten unless override is True.

		Args:
			override (bool): Whether to override existing system environment variables
							 with values from the .env file. Defaults to False.

		Returns:
			bool: True if the .env file was found and loaded successfully, False otherwise.

		Raises:
			ConfigurationError: If there's an OS error checking or processing the .env file.
		"""
		if not self._envFilePath:
			logger.info("No .env file path specified. Skipping loading from .env file.")
			return False
		try:
			if os.path.exists(self._envFilePath):
				logger.info(f"Loading environment variables from: {self._envFilePath}")
				load_dotenv_success = load_dotenv(dotenv_path=self._envFilePath, override=override, verbose=True)
				self._envLoaded = load_dotenv_success
				if not load_dotenv_success:
					logger.warning(f".env file found at '{self._envFilePath}' but `load_dotenv` returned False. File might be empty or have format issues.")
				else:
					logger.debug(f"Successfully processed environment variables from {self._envFilePath}.")
				return self._envLoaded
			else:
				logger.warning(f".env file not found at specified path: {self._envFilePath}. Skipping.")
				return False
		except Exception as e:
			logger.error(f"Failed to load .env file from '{self._envFilePath}': {e}", exc_info=True)
			raise ConfigurationError(f"Error processing .env file '{self._envFilePath}': {e}") from e

	def loadConfig(self: 'ConfigManager') -> None:
		"""
		Loads configuration settings from the .ini file specified during initialisation.

		Raises:
			ConfigurationError: If the specified .ini file exists but is unreadable or has parsing errors.
		"""
		self._configLoadAttempted = True
		self._configLoaded = False
		self._configLoadError = None

		if not self._configFilePath:
			logger.info("No configuration file path specified. Relying on defaults or environment variables.")
			return

		try:
			if os.path.exists(self._configFilePath):
				logger.info(f"Loading configuration from: {self._configFilePath}")
				# Re-initialize parser with interpolation disabled
				self._config = configparser.ConfigParser(interpolation=None)
				readFiles: List[str] = self._config.read(self._configFilePath, encoding='utf-8')
				if not readFiles:
					err_msg = f"Config file exists at '{self._configFilePath}' but could not be read or parsed by configparser."
					logger.error(err_msg)
					self._configLoadError = ConfigurationError(err_msg)
					raise self._configLoadError
				self._configLoaded = True
				logger.debug(f"Successfully loaded configuration from {self._configFilePath}")
			else:
				logger.warning(f"Configuration file not found: {self._configFilePath}. Proceeding without it.")
		except configparser.Error as e:
			logger.error(f"Failed to parse configuration file '{self._configFilePath}': {e}", exc_info=True)
			self._configLoadError = e
			raise ConfigurationError(f"Error parsing config file '{self._configFilePath}': {e}") from e
		except Exception as e:
			logger.error(f"Failed to read configuration file '{self._configFilePath}': {e}", exc_info=True)
			self._configLoadError = e
			raise ConfigurationError(f"Error reading config file '{self._configFilePath}': {e}") from e

	def getEnvVar(self: 'ConfigManager', varName: str, defaultValue: Optional[str] = None, required: bool = False) -> Optional[str]:
		"""
		Retrieves an environment variable.

		Args:
			varName (str): The name of the environment variable.
			defaultValue (Optional[str]): The value to return if the variable is not found (and not required).
			required (bool): If True, raises ConfigurationError if the variable is not set.

		Returns:
			Optional[str]: The value of the environment variable, or the defaultValue.

		Raises:
			ConfigurationError: If required=True and the environment variable is not found.
		"""
		value = os.getenv(varName)
		if value is None:
			if required:
				errMsg = f"Required environment variable '{varName}' is not set."
				logger.error(errMsg)
				raise ConfigurationError(errMsg)
			return defaultValue
		return value

	def getConfigValue(self: 'ConfigManager', section: str, key: str, fallback: Optional[Any] = None, required: bool = False) -> Optional[Any]:
		"""
		Retrieves a configuration value from the loaded .ini file, disabling interpolation.

		Args:
			section (str): The section name in the .ini file.
			key (str): The key name within the section.
			fallback (Optional[Any]): Value to return if key/section not found (and not required). Defaults to None.
			required (bool): If True, raises ConfigurationError if value not found. Defaults to False.

		Returns:
			Optional[Any]: The raw configuration value (as string), or fallback.

		Raises:
			ConfigurationError: If required and value not found, or if config failed to load earlier.
		"""
		if self._configLoadAttempted and not self._configLoaded and self._configLoadError:
			err_ctx = f"config file '{self._configFilePath}' failed to load properly earlier."
			logger.error(f"Attempted to get config value '{section}/{key}' but {err_ctx}")
			raise ConfigurationError(f"Cannot retrieve config value; configuration file '{self._configFilePath}' failed to load. Error: {self._configLoadError}") from self._configLoadError

		valueExists = self._configLoaded and self._config.has_section(section) and self._config.has_option(section, key)

		if required and not valueExists:
			errMsg = f"Required configuration value '{key}' not found in section '{section}'."
			if self._configFilePath:
				try:
					file_exists_check = os.path.isfile(self._configFilePath)
				except Exception: file_exists_check = False
				if file_exists_check and self._configLoaded: errMsg += f" Checked in '{self._configFilePath}'."
				elif file_exists_check and not self._configLoaded: errMsg += f" Config file '{self._configFilePath}' exists but failed to load (Error: {self._configLoadError})."
				else: errMsg += f" Config file '{self._configFilePath}' not found or not accessible."
			elif self._configLoadAttempted: errMsg += " No config file path was specified, or load was attempted without a path."
			else: errMsg += " Configuration was not loaded."
			logger.error(errMsg)
			raise ConfigurationError(errMsg)

		if valueExists:
			try:
				# Use get with raw=True to disable interpolation
				# Note: If ConfigParser was init with interpolation=None, raw=True is redundant but safe.
				value = self._config.get(section, key, fallback=None, raw=True)
				# Remove potential inline comments manually if needed (raw=True doesn't handle this)
				if value is not None and isinstance(value, str):
						if '#' in value: value = value.split('#', 1)[0].strip()
						if ';' in value: value = value.split(';', 1)[0].strip()
				logger.debug(f"Accessed raw config value '{section}/{key}'. Value: '{value}'")
				return value
			except (configparser.NoSectionError, configparser.NoOptionError) as e:
				# Should not happen if valueExists is True, handle defensively
				logger.error(f"Internal error retrieving existing raw config value '{section}/{key}': {e}")
				raise ConfigurationError(f"Internal error: Could not get raw config value '{section}/{key}' despite checks.") from e
		else:
			logger.debug(f"Raw config value '{section}/{key}' not found, using fallback: {fallback}")
			return fallback


	def getConfigValueInt(self: 'ConfigManager', section: str, key: str, fallback: Optional[int] = None, required: bool = False) -> Optional[int]:
		valueStr = self.getConfigValue(section, key, fallback=None, required=required)
		if valueStr is None: return fallback
		try:
			return int(valueStr)
		except (ValueError, TypeError) as e:
			errMsg = f"Configuration value '{section}/{key}' ('{valueStr}') is not a valid integer."
			logger.error(errMsg)
			raise ConfigurationError(errMsg) from e

	def getConfigValueBool(self: 'ConfigManager', section: str, key: str, fallback: Optional[bool] = None, required: bool = False) -> Optional[bool]:
		valueStr = self.getConfigValue(section, key, fallback=None, required=required)
		if valueStr is None: return fallback
		valueLower = valueStr.strip().lower()
		if valueLower in ['true', 'yes', 'on', '1']: return True
		if valueLower in ['false', 'no', 'off', '0']: return False
		errMsg = f"Configuration value '{section}/{key}' ('{valueStr}') is not a valid boolean (use 1/yes/true/on or 0/no/false/off)."
		logger.error(errMsg)
		raise ConfigurationError(errMsg)

	def getConfigValueFloat(self: 'ConfigManager', section: str, key: str, fallback: Optional[float] = None, required: bool = False) -> Optional[float]:
		valueStr = self.getConfigValue(section, key, fallback=None, required=required)
		if valueStr is None: return fallback
		try:
			return float(valueStr)
		except (ValueError, TypeError) as e:
			errMsg = f"Configuration value '{section}/{key}' ('{valueStr}') is not a valid float."
			logger.error(errMsg)
			raise ConfigurationError(errMsg) from e

	# --- NEW: Method to save config changes ---
	def setConfigValue(self: 'ConfigManager', section: str, key: str, value: str) -> None:
		"""
		Sets a configuration value in memory and attempts to save it back to the .ini file.

		Args:
			section (str): The section name in the .ini file.
			key (str): The key name within the section.
			value (str): The string value to set.

		Raises:
			ConfigurationError: If the configuration file path is not set, if the config
								was not loaded successfully, or if there's an error writing
								the file.
		"""
		if not self._configFilePath:
			errMsg = "Cannot save configuration: No configuration file path was specified during initialisation."
			logger.error(errMsg)
			raise ConfigurationError(errMsg)

		if not self._configLoaded and self._configLoadError:
			errMsg = f"Cannot save configuration: The configuration file '{self._configFilePath}' failed to load initially. Error: {self._configLoadError}"
			logger.error(errMsg)
			raise ConfigurationError(errMsg) from self._configLoadError
		elif not self._configLoaded and not self._configLoadAttempted:
			# If config wasn't loaded because it didn't exist, allow creating/saving.
			logger.info(f"Config file '{self._configFilePath}' was not loaded (likely didn't exist). Will attempt to create/save.")
			# Ensure the parser is initialised
			if not self._config: self._config = configparser.ConfigParser(interpolation=None)


		try:
			# Ensure the section exists in the config object
			if not self._config.has_section(section):
				logger.debug(f"Adding new section '{section}' to configuration.")
				self._config.add_section(section)

			# Set the value in the config object
			logger.debug(f"Setting config value in memory: [{section}] {key} = {value}")
			self._config.set(section, key, value)

			# Write the entire configuration back to the file
			logger.info(f"Saving configuration changes to: {self._configFilePath}")
			with open(self._configFilePath, 'w', encoding='utf-8') as configfile:
				self._config.write(configfile)
			logger.debug(f"Successfully saved configuration to {self._configFilePath}")
			# Mark config as loaded if it wasn't before (e.g., file created)
			self._configLoaded = True
			self._configLoadError = None # Clear any previous load error

		except configparser.Error as e: # Errors during section creation or setting
			errMsg = f"Error updating configuration in memory for [{section}] {key}: {e}"
			logger.error(errMsg, exc_info=True)
			raise ConfigurationError(errMsg) from e
		except IOError as e: # Errors during file writing
			errMsg = f"Failed to write configuration file '{self._configFilePath}': {e}"
			logger.error(errMsg, exc_info=True)
			raise ConfigurationError(errMsg) from e
		except Exception as e: # Catch any other unexpected errors
			errMsg = f"An unexpected error occurred while saving configuration: {e}"
			logger.error(errMsg, exc_info=True)
			raise ConfigurationError(errMsg) from e
	# --- END NEW METHOD ---

	# --- Properties (Unchanged) ---
	@property
	def isEnvLoaded(self: 'ConfigManager') -> bool:
		return self._envLoaded

	@property
	def isConfigLoaded(self: 'ConfigManager') -> bool:
		return self._configLoaded

# --- END: core/config_manager.py ---