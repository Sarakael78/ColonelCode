# Updated Codebase/core/config_manager.py
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
		self._config = configparser.ConfigParser() # Ensure fresh parser on init
		self._envLoaded = False
		self._configLoaded = False
		self._configLoadAttempted = False # Reset flag on init
		self._configLoadError = None # Reset error on init
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
			bool: True if the .env file was found and loaded successfully (or if load_dotenv reports success),
			      False if the file was not found or load_dotenv explicitly returns False.

		Raises:
			ConfigurationError: If there's an OS error checking or processing the .env file.
		"""
		if self._envFilePath:
			try:
				# Check existence once before deciding to call load_dotenv
				fileExists: bool = os.path.exists(self._envFilePath)

				if fileExists:
					logger.info(f"Loading environment variables from: {self._envFilePath}")
					# load_dotenv returns True if file exists and was parsed (even if empty),
					# False if the file does not exist. It raises errors for file access issues.
					# FIX: Store the result of load_dotenv call.
					load_dotenv_success: bool = load_dotenv(dotenv_path=self._envFilePath, override=override, verbose=True)
					# Note: verbose=True logs warnings from dotenv itself if file has issues.

					# FIX: Set _envLoaded based on load_dotenv_success *and* file existence.
					# load_dotenv might return True even if file is just touched but empty.
					# For our purpose, success means the file existed and dotenv didn't fail.
					self._envLoaded = load_dotenv_success # Trust load_dotenv's return for success state

					if not load_dotenv_success:
						# This case is less common if fileExists is True, but respect dotenv's return value.
						# It might indicate an empty file or potential parsing issue handled internally by dotenv.
						# Ensure warning is logged as per test expectation.
						logger.warning(f".env file found at '{self._envFilePath}' but `load_dotenv` returned False. The file might be empty or have format issues.") # [cite: 12] Corrected logging
					else:
						logger.debug(f"Successfully processed environment variables from {self._envFilePath} (dotenv reported success).")

					return self._envLoaded # [cite: 10] Return the actual success status

				else:
					# FIX: Log warning when file not found, as per test expectation.
					logger.warning(f".env file not found at specified path: {self._envFilePath}. Skipping environment variable loading from file.") # [cite: 13] Corrected logging
					self._envLoaded = False # Mark as not loaded since file was absent
					return False
			except Exception as e:
				# Catching broader exceptions during file access/dotenv processing
				# FIX: Log error before raising, as per test expectation.
				logger.error(f"Failed to load .env file from '{self._envFilePath}': {e}", exc_info=True) # [cite: 14] Corrected logging
				self._envLoaded = False # Ensure state reflects failure
				raise ConfigurationError(f"Error processing .env file '{self._envFilePath}': {e}") from e
		else:
			# FIX: Log info when no path specified, as per test expectation.
			logger.info("No .env file path specified. Skipping loading from .env file.") # [cite: 15] Corrected logging
			self._envLoaded = False # No path means nothing to load
			return False

	def loadConfig(self: 'ConfigManager') -> None:
		"""
		Loads configuration settings from the .ini file specified during initialisation.

		Raises:
			ConfigurationError: If the specified .ini file path exists but is unreadable,
			                    or contains parsing errors. Does not raise error if the file
			                    simply does not exist (only logs a warning).
		"""
		self._configLoadAttempted = True # Mark that loading was attempted
		self._configLoaded = False # Assume failure until success
		self._configLoadError = None # Clear previous error

		if self._configFilePath:
			try:
				# Check if the file exists before attempting to read
				if os.path.exists(self._configFilePath):
					logger.info(f"Loading configuration from: {self._configFilePath}")
					# Clear previous config state before reading
					self._config = configparser.ConfigParser()
					readFiles: List[str] = self._config.read(self._configFilePath, encoding='utf-8') # Use List
					if not readFiles:
						# This case means the file exists but couldn't be parsed or was empty according to configparser
						# FIX: Log error before raising, as per test expectation.
						err_msg = f"Config file exists at '{self._configFilePath}' but could not be read or parsed by configparser." # [cite: 17]
						logger.error(err_msg) # [cite: 18] Corrected logging
						self._configLoadError = ConfigurationError(err_msg) # Store specific error
						raise self._configLoadError
					self._configLoaded = True # Set loaded flag ONLY on successful read
					logger.debug(f"Successfully loaded configuration from {self._configFilePath}")
				else:
					# FIX: Log warning when file not found, as per test expectation.
					logger.warning(f"Configuration file not found at specified path: {self._configFilePath}. Proceeding with defaults or environment variables only.") # [cite: 19] Corrected logging
					# _configLoaded remains False
			except configparser.Error as e:
				# FIX: Log error before raising, as per test expectation.
				logger.error(f"Failed to parse configuration file '{self._configFilePath}': {e}", exc_info=True) # [cite: 20] Corrected logging
				self._configLoadError = e # Store error
				# _configLoaded remains False
				raise ConfigurationError(f"Error parsing config file '{self._configFilePath}': {e}") from e
			except Exception as e:
				# Catch other potential issues like file permission errors
				# FIX: Log error before raising, as per test expectation.
				logger.error(f"Failed to read configuration file '{self._configFilePath}': {e}", exc_info=True) # [cite: 21] Corrected logging
				self._configLoadError = e # Store error
				# _configLoaded remains False
				raise ConfigurationError(f"Error reading config file '{self._configFilePath}': {e}") from e
		else:
			# FIX: Log info when no path specified, as per test expectation.
			logger.info("No configuration file path specified. Relying on defaults or environment variables.") # [cite: 22] Corrected logging
			# _configLoaded remains False

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
				errMsg: str = f"Required environment variable '{varName}' is not set." # [cite: 23]
				# FIX: Log error before raising, as per test expectation.
				logger.error(errMsg) # [cite: 24] Corrected logging
				raise ConfigurationError(errMsg)
			else:
				# logger.debug(f"Environment variable '{varName}' not found, using default value: {defaultValue}")
				return defaultValue
		# logger.debug(f"Accessed environment variable '{varName}'. Value: '{value}'")
		return value


	def getConfigValue(self: 'ConfigManager', section: str, key: str, fallback: Optional[Any] = None, required: bool = False) -> Optional[Any]:
		"""
		Retrieves a configuration value from the loaded .ini file.

		Args:
			section (str): The section name in the .ini file (e.g., 'General').
			key (str): The key name within the section.
			fallback (Optional[Any]): The value to return if the key/section is not found
			                         (and required is False). Defaults to None.
			required (bool): If True, raises ConfigurationError if the value is not found.
			                 Takes precedence over fallback. Defaults to False.

		Returns:
			Optional[Any]: The configuration value (as string), or the fallback if not found and not required.

		Raises:
			ConfigurationError: If required=True and the value is not found.
			ConfigurationError: If the configuration file was specified and existed but failed to load.
		"""
		# Check if config loading was attempted and failed previously
		if self._configLoadAttempted and not self._configLoaded and self._configLoadError:
			# FIX: Log error before raising, as per test expectation.
			err_ctx = f"config file '{self._configFilePath}' failed to load properly earlier."
			logger.error(f"Attempted to get config value '{section}/{key}' but {err_ctx}") # [cite: 27] Corrected logging context
			raise ConfigurationError(f"Cannot retrieve config value; configuration file '{self._configFilePath}' failed to load. Error: {self._configLoadError}") from self._configLoadError

		# Check if the option exists within the loaded config
		valueExists: bool = False
		if self._configLoaded:
			# Check if section exists first to avoid NoSectionError in has_option
			if self._config.has_section(section):
				valueExists = self._config.has_option(section, key)
			else:
				# Section doesn't exist, log a debug message maybe?
				# logger.debug(f"Section '{section}' not found in config file.")
				valueExists = False

		# FIX: If required and the key does not exist (or section doesn't exist), raise error *before* considering fallback. # [cite: 28]
		if required and not valueExists:
			errMsg: str = f"Required configuration value '{key}' not found in section '{section}'." # [cite: 29]
			# Provide context based on file status
			if self._configFilePath:
				# Check if file exists vs. file loaded but key missing
				try:
					# Use a more reliable check, os.path.exists can have race conditions or permission issues
					file_exists_check = os.path.isfile(self._configFilePath)
				except Exception:
					file_exists_check = False # Assume not accessible if check fails

				if file_exists_check and self._configLoaded:
					errMsg += f" Checked in '{self._configFilePath}'." # [cite: 30]
				elif file_exists_check and not self._configLoaded:
					# This case means file exists but load failed (error stored)
					errMsg += f" Config file '{self._configFilePath}' exists but failed to load (Error: {self._configLoadError})." # [cite: 31] Added error context
				else: # File path specified but doesn't exist or isn't a file
					errMsg += f" Config file '{self._configFilePath}' not found or not accessible." # [cite: 32] Clarified message
			# FIX: Match test regex more closely? This part depends heavily on the *exact* regex in the test case.
			elif self._configLoadAttempted: # No path specified, but load was attempted
				errMsg += " No config file path was specified, or load was attempted without a path." # [cite: 33] Adjusted phrasing
			else: # Load not even attempted
				errMsg += " Configuration was not loaded." # [cite: 34] Simplified message
			# FIX: Log error before raising, as per test expectation.
			logger.error(errMsg) # [cite: 36] Corrected logging
			raise ConfigurationError(errMsg)

		# If the key exists, get its value
		if valueExists:
			# configparser.get returns string; fallback here is less critical if valueExists is True
			# Pass None as internal fallback to get the raw value or raise if something goes wrong internally
			try:
				value: Optional[str] = self._config.get(section, key, fallback=None) # [cite: 37]
				# logger.debug(f"Accessed config value '{section}/{key}'. Value: '{value}'")
				return value
			except (configparser.NoSectionError, configparser.NoOptionError) as e:
				# Should not happen if valueExists is True, but handle defensively
				logger.error(f"Internal error retrieving existing config value '{section}/{key}': {e}")
				# This indicates a logic error, maybe re-raise or handle differently
				raise ConfigurationError(f"Internal error: Could not get config value '{section}/{key}' despite checks.") from e
		else:
			# Key doesn't exist, and it wasn't required. Return the user's fallback.
			# logger.debug(f"Config value '{section}/{key}' not found, using fallback: {fallback}")
			return fallback # [cite: 38]

	# --- Convenience methods for typed retrieval ---

	def getConfigValueInt(self: 'ConfigManager', section: str, key: str, fallback: Optional[int] = None, required: bool = False) -> Optional[int]:
		""" Convenience method to get an integer config value. """
		# Call base getter, ensuring `required` is checked first.
		# Provide None as fallback here, handle explicit int fallback below. # [cite: 39]
		valueStr: Optional[str] = self.getConfigValue(section, key, fallback=None, required=required) # [cite: 40]

		if valueStr is None:
			# If required=True, getConfigValue would have raised an error.
			# If not required and valueStr is None, the key was missing, return the int fallback. # [cite: 41]
			return fallback # [cite: 42]

		try:
			return int(valueStr)
		except (ValueError, TypeError) as e:
				errMsg: str = f"Configuration value '{section}/{key}' ('{valueStr}') is not a valid integer." # [cite: 43]
				# FIX: Log error before raising, as per test expectation.
				logger.error(errMsg) # [cite: 44] Corrected logging
				# Re-raise as ConfigurationError if parsing fails
				raise ConfigurationError(errMsg) from e

	def getConfigValueBool(self: 'ConfigManager', section: str, key: str, fallback: Optional[bool] = None, required: bool = False) -> Optional[bool]:
		""" Convenience method to get a boolean config value. """
		# Check existence and requirement using the base method first.
		# Provide None as fallback here. # [cite: 45]
		valueStr: Optional[str] = self.getConfigValue(section, key, fallback=None, required=required)

		if valueStr is None:
				# If required=True, getConfigValue would have raised an error.
				# If not required and valueStr is None, the key was missing, return the bool fallback. # [cite: 46]
				return fallback # [cite: 47]

		# Value exists (as string), try to parse it using configparser's robust method
		# Map common boolean strings manually for robustness, configparser's getboolean is strict
		valueLower = valueStr.strip().lower()
		if valueLower in ['true', 'yes', 'on', '1']:
			return True
		elif valueLower in ['false', 'no', 'off', '0']:
			return False
		else:
			# Error during boolean conversion
			errMsg: str = f"Configuration value '{section}/{key}' ('{valueStr}') is not a valid boolean (use 1/yes/true/on or 0/no/false/off)." # [cite: 48] Adjusted error logic slightly
			# FIX: Log error before raising, as per test expectation.
			logger.error(errMsg) # [cite: 49] Corrected logging
			raise ConfigurationError(errMsg)


	def getConfigValueFloat(self: 'ConfigManager', section: str, key: str, fallback: Optional[float] = None, required: bool = False) -> Optional[float]:
		"""
		Convenience method to get a float config value.

		Args:
			section (str): The section name in the .ini file.
			key (str): The key name within the section.
			fallback (Optional[float]): The value to return if the key is not found (and not required). Defaults to None.
			required (bool): If True, raises ConfigurationError if the key is not found. Defaults to False.

		Returns:
			Optional[float]: The configuration value as a float, or the fallback.

		Raises:
			ConfigurationError: If required and key not found, or if the value cannot be converted to float.
		"""
		# Call base getter, ensuring `required` is checked first. # [cite: 50]
		# Provide None as fallback here, handle explicit float fallback below.
		valueStr: Optional[str] = self.getConfigValue(section, key, fallback=None, required=required) # [cite: 51]

		if valueStr is None:
			# If required=True, getConfigValue would have raised an error.
			# If not required and valueStr is None, the key was missing, return the float fallback. # [cite: 52]
			return fallback # [cite: 53]

		try:
				return float(valueStr)
		except (ValueError, TypeError) as e:
				errMsg: str = f"Configuration value '{section}/{key}' ('{valueStr}') is not a valid float." # [cite: 54]
				# FIX: Log error before raising, as per test expectation.
				logger.error(errMsg) # [cite: 55] Corrected logging
				raise ConfigurationError(errMsg) from e


	@property
	def isEnvLoaded(self: 'ConfigManager') -> bool:
		"""Returns True if the .env file was found and successfully processed by `load_dotenv`."""
		return self._envLoaded

	@property
	def isConfigLoaded(self: 'ConfigManager') -> bool:
		"""Returns True if the .ini configuration file was successfully loaded."""
		return self._configLoaded
# --- END: core/config_manager.py ---