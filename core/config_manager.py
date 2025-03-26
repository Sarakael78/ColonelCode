# --- START: core/config_manager.py ---
# core/config_manager.py
"""
Manages loading and accessing application configuration from various sources.
Prioritises environment variables (via .env file) for secrets,
and uses a configuration file (config.ini) for non-sensitive settings.
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
	Loads from .env files and .ini files.
	"""
	# Adhering to user preference for explicit initialisation
	_config: configparser.ConfigParser = configparser.ConfigParser()
	_envLoaded: bool = False
	_configLoaded: bool = False
	_envFilePath: Optional[str] = None
	_configFilePath: Optional[str] = None

	def __init__(self: 'ConfigManager', configFilePath: Optional[str] = 'config.ini', envFilePath: Optional[str] = '.env') -> None:
		"""
		Initialises the ConfigManager.

		Args:
			configFilePath (Optional[str]): Path to the .ini configuration file.
			envFilePath (Optional[str]): Path to the .env file for environment variables.
		"""
		self._config = configparser.ConfigParser() # Ensure fresh parser on init
		self._envLoaded = False
		self._configLoaded = False
		self._envFilePath = envFilePath
		self._configFilePath = configFilePath
		logger.debug(f"ConfigManager initialised with config file: '{configFilePath}', env file: '{envFilePath}'")

	def loadEnv(self: 'ConfigManager', override: bool = False) -> bool:
		"""
		Loads environment variables from the .env file specified during initialisation.

		Existing environment variables will NOT be overwritten unless override is True.
		It's generally recommended to load .env before accessing environment variables.

		Args:
			override (bool): Whether to override existing system environment variables
			                 with values from the .env file. Defaults to False.

		Returns:
			bool: True if the .env file was found and loaded successfully, False otherwise.

		Raises:
			ConfigurationError: If the specified .env file path is invalid or unreadable,
			                    though `python-dotenv` might just return False.
		"""
		if self._envFilePath:
			try:
				# Check if the file exists before attempting to load
				if os.path.exists(self._envFilePath):
					logger.info(f"Loading environment variables from: {self._envFilePath}")
					# Use find_dotenv to potentially locate .env in parent directories if needed,
					# though explicit path is usually preferred for clarity.
					# actualEnvPath = find_dotenv(filename=self._envFilePath, raise_error_if_not_found=False)
					actualEnvPath = self._envFilePath # Use provided path directly

					if actualEnvPath and os.path.exists(actualEnvPath):
						self._envLoaded = load_dotenv(dotenv_path=actualEnvPath, override=override, verbose=True)
						if not self._envLoaded:
							logger.warning(f".env file found at '{actualEnvPath}' but `load_dotenv` returned False. It might be empty or have format issues.")
						else:
							logger.debug(f"Successfully processed environment variables from {actualEnvPath}")
						return self._envLoaded
					else:
						logger.warning(f".env file not found at derived or specified path: {actualEnvPath or self._envFilePath}. Skipping.")
						self._envLoaded = False
						return False

				else:
					logger.warning(f".env file not found at specified path: {self._envFilePath}. Skipping environment variable loading from file.")
					self._envLoaded = False # Mark as not loaded since file was absent
					return False
			except Exception as e:
				# Catching broader exceptions during file access/dotenv processing
				logger.error(f"Failed to load .env file from '{self._envFilePath}': {e}", exc_info=True)
				raise ConfigurationError(f"Error processing .env file '{self._envFilePath}': {e}") from e
		else:
			logger.info("No .env file path specified. Skipping loading from .env file.")
			self._envLoaded = False # No path means nothing to load
			return False

	def loadConfig(self: 'ConfigManager') -> None:
		"""
		Loads configuration settings from the .ini file specified during initialisation.

		Raises:
			ConfigurationError: If the specified .ini file path is invalid, unreadable,
			                    or contains parsing errors.
		"""
		if self._configFilePath:
			try:
				# Check if the file exists before attempting to read
				if os.path.exists(self._configFilePath):
					logger.info(f"Loading configuration from: {self._configFilePath}")
					readFiles: List[str] = self._config.read(self._configFilePath, encoding='utf-8') # Use List
					if not readFiles:
						# This case means the file exists but couldn't be parsed or was empty
						raise ConfigurationError(f"Config file exists at '{self._configFilePath}' but could not be read or parsed by configparser.")
					self._configLoaded = True
					logger.debug(f"Successfully loaded configuration from {self._configFilePath}")
				else:
					logger.warning(f"Configuration file not found at specified path: {self._configFilePath}. Proceeding with defaults or environment variables only.")
					self._configLoaded = False # Mark as not loaded
			except configparser.Error as e:
				logger.error(f"Failed to parse configuration file '{self._configFilePath}': {e}", exc_info=True)
				raise ConfigurationError(f"Error parsing config file '{self._configFilePath}': {e}") from e
			except Exception as e:
				# Catch other potential issues like file permission errors
				logger.error(f"Failed to read configuration file '{self._configFilePath}': {e}", exc_info=True)
				raise ConfigurationError(f"Error reading config file '{self._configFilePath}': {e}") from e
		else:
			logger.info("No configuration file path specified. Relying on defaults or environment variables.")
			self._configLoaded = False # No path means nothing to load

	def getEnvVar(self: 'ConfigManager', varName: str, defaultValue: Optional[str] = None, required: bool = False) -> Optional[str]:
		"""
		Retrieves an environment variable.

		Args:
			varName (str): The name of the environment variable.
			defaultValue (Optional[str]): The value to return if the variable is not found (and not required).
			required (bool): If True, raises ConfigurationError if the variable is not set.

		Returns:
			Optional[str]: The value of the environment variable, or the defaultValue if not set/required.

		Raises:
			ConfigurationError: If required=True and the environment variable is not found.
		"""
		value: Optional[str] = os.getenv(varName)
		if value is None:
			if required:
				errMsg: str = f"Required environment variable '{varName}' is not set."
				logger.error(errMsg)
				raise ConfigurationError(errMsg)
			else:
				# logger.debug(f"Environment variable '{varName}' not found, using default value.")
				return defaultValue
		# logger.debug(f"Accessed environment variable '{varName}'. Found: Yes")
		return value


	def getConfigValue(self: 'ConfigManager', section: str, key: str, fallback: Optional[Any] = None, required: bool = False) -> Optional[Any]:
		"""
		Retrieves a configuration value from the loaded .ini file.

		Args:
			section (str): The section name in the .ini file (e.g., 'General').
			key (str): The key name within the section.
			fallback (Optional[Any]): The value to return if the key/section is not found.
			                         Defaults to None.
			required (bool): If True, raises ConfigurationError if the value is not found
			                 and no fallback is provided (or fallback is None). Defaults to False.

		Returns:
			Optional[Any]: The configuration value (as string), or the fallback if not found.

		Raises:
			ConfigurationError: If required=True and the value is not found (and fallback is None).
			ConfigurationError: If the configuration file was specified but failed to load.
		"""
		# Check if config loading was attempted and failed
		if self._configFilePath and not self._configLoaded and os.path.exists(self._configFilePath):
			logger.error(f"Attempted to get config value '{section}/{key}' but config file '{self._configFilePath}' failed to load properly earlier.")
			raise ConfigurationError(f"Cannot retrieve config value; configuration file '{self._configFilePath}' failed to load.")

		# Proceed to get the value using configparser's logic which includes fallback
		value: Optional[str] = self._config.get(section, key, fallback=fallback)

		# Handle the 'required' flag specifically if fallback mechanism resulted in None
		# Note: configparser.get treats fallback=None differently than missing key.
		# We check if the option actually exists if value is None after the get call.
		valueExists = self._config.has_option(section, key)

		if not valueExists and value is None: # If key truly missing and fallback was None or didn't apply
				if required:
						errMsg: str = f"Required configuration value '{key}' not found in section '{section}' of the configuration file ('{self._configFilePath or 'Not Specified'}') and no fallback provided."
						logger.error(errMsg)
						raise ConfigurationError(errMsg)
				else:
						# Value is None, not required, return the fallback (which was None)
						# logger.debug(f"Config value '{section}/{key}' not found, using fallback (None).")
						return fallback # Explicitly return the fallback

		# logger.debug(f"Accessed config value '{section}/{key}'. Value: '{value}'")
		# TODO: Add more validation logic here? E.g., check if value is empty string if required?
		return value

	# --- Convenience methods for typed retrieval ---

	def getConfigValueInt(self: 'ConfigManager', section: str, key: str, fallback: Optional[int] = None, required: bool = False) -> Optional[int]:
		""" Convenience method to get an integer config value. """
		valueStr: Optional[str] = self.getConfigValue(section, key, fallback=str(fallback) if fallback is not None else None, required=required)
		if valueStr is None:
				# If required was true, getConfigValue would have raised error.
				# If not required, valueStr is None because key was missing and fallback was None.
				return fallback # Return the original integer fallback

		try:
				return int(valueStr)
		except (ValueError, TypeError) as e:
				errMsg: str = f"Configuration value '{section}/{key}' ('{valueStr}') is not a valid integer."
				logger.error(errMsg)
				# Re-raise as ConfigurationError if parsing fails
				raise ConfigurationError(errMsg) from e

	def getConfigValueBool(self: 'ConfigManager', section: str, key: str, fallback: Optional[bool] = None, required: bool = False) -> Optional[bool]:
		""" Convenience method to get a boolean config value. """
		# We need to handle the case where the key might be missing entirely, separate from parsing errors.
		if not self._config.has_option(section, key):
				if required and fallback is None:
						errMsg: str = f"Required boolean configuration value '{key}' not found in section '{section}'."
						logger.error(errMsg)
						raise ConfigurationError(errMsg)
				else:
						# logger.debug(f"Boolean config value '{section}/{key}' not found, using fallback: {fallback}")
						return fallback # Return the provided boolean fallback

		# Key exists, try to parse it using configparser's robust method
		try:
				# Note: fallback here within getboolean is less flexible than our external fallback logic
				return self._config.getboolean(section, key)
		except ValueError as e:
				valueStr: Optional[str] = self._config.get(section, key, fallback=None) # Get raw value for error msg
				errMsg: str = f"Configuration value '{section}/{key}' ('{valueStr}') is not a valid boolean (use 1/yes/true/on or 0/no/false/off)."
				logger.error(errMsg)
				raise ConfigurationError(errMsg) from e

	# # TODO: Implement getConfigValueFloat if needed.
	# # TODO: Consider adding validation for retrieved values (e.g., check if paths exist).

	@property
	def isEnvLoaded(self: 'ConfigManager') -> bool:
		"""Returns True if the .env file was found and successfully processed."""
		return self._envLoaded

	@property
	def isConfigLoaded(self: 'ConfigManager') -> bool:
		"""Returns True if the .ini configuration file was successfully loaded."""
		return self._configLoaded
# --- END: core/config_manager.py ---