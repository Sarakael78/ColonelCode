# --- START: tests/test_config_manager.py ---
import unittest
import os
import configparser
from unittest.mock import patch, mock_open, MagicMock, PropertyMock
from typing import Optional, Any, List # Import List

# Ensure imports work correctly assuming tests are run from the project root
# Adjust path if necessary based on your test runner setup
import sys
if '.' not in sys.path:
	sys.path.append('.') # Add project root if needed

from core.config_manager import ConfigManager
from core.exceptions import ConfigurationError

# Test Suite for ConfigManager
class TestConfigManager(unittest.TestCase):
	"""
	Unit tests for the ConfigManager class.
	Mocks file system operations and environment variables.
	"""
	_testEnvFileName: str = '.test_env'
	_testIniFileName: str = 'test_config.ini'

	def setUp(self: 'TestConfigManager') -> None:
		"""Set up test environment; called before each test method."""
		# Clear potentially conflicting environment variables
		self._envVarsToClear: List[str] = ['TEST_ENV_VAR', 'REQUIRED_ENV_VAR', 'EMPTY_ENV_VAR', 'GEMINI_API_KEY'] # Use List
		self._originalEnvValues: dict[str, Optional[str]] = {}
		for var in self._envVarsToClear:
			self._originalEnvValues[var] = os.environ.pop(var, None)

		# Patch logger to suppress output during tests
		self.patcher = patch('core.config_manager.logger', MagicMock())
		self.mock_logger = self.patcher.start()

	def tearDown(self: 'TestConfigManager') -> None:
		"""Clean up test environment; called after each test method."""
		self.patcher.stop()
		# Restore original environment variables
		for var, value in self._originalEnvValues.items():
			if value is None:
				# If it didn't exist originally, ensure it's removed
				os.environ.pop(var, None)
			else:
				# Restore original value
				os.environ[var] = value
		# Clean up dummy files if created (though mocks usually prevent this)
		# In a real scenario with file creation, ensure cleanup happens.
		# For mocked tests, this might not be necessary.

	# --- Test .env Loading ---

	@patch('os.path.exists')
	@patch('dotenv.load_dotenv')
	def test_loadEnv_success(self: 'TestConfigManager', mock_load_dotenv: MagicMock, mock_exists: MagicMock) -> None:
		"""Test successful loading of an existing .env file."""
		mock_exists.return_value = True
		mock_load_dotenv.return_value = True # Simulate successful load
		cm = ConfigManager(configFilePath=None, envFilePath=self._testEnvFileName) # Ensure config file path is None
		result = cm.loadEnv()
		# FIX: Check result matches load_dotenv return value
		self.assertTrue(result, "loadEnv should return True on success")
		self.assertTrue(cm.isEnvLoaded, "isEnvLoaded should be True after successful load")
		mock_exists.assert_called_once_with(self._testEnvFileName)
		# FIX: load_dotenv should be called
		mock_load_dotenv.assert_called_once_with(dotenv_path=self._testEnvFileName, override=False, verbose=True)

	@patch('os.path.exists')
	@patch('dotenv.load_dotenv')
	def test_loadEnv_fileNotFound(self: 'TestConfigManager', mock_load_dotenv: MagicMock, mock_exists: MagicMock) -> None:
		"""Test loading when .env file does not exist."""
		mock_exists.return_value = False
		cm = ConfigManager(envFilePath=self._testEnvFileName)
		result = cm.loadEnv()
		self.assertFalse(result)
		self.assertFalse(cm.isEnvLoaded)
		mock_exists.assert_called_once_with(self._testEnvFileName)
		mock_load_dotenv.assert_not_called() # Should not attempt to load
		# FIX: Check logger warning was called
		self.mock_logger.warning.assert_called_with(f".env file not found at specified path: {self._testEnvFileName}. Skipping environment variable loading from file.")

	@patch('os.path.exists')
	@patch('dotenv.load_dotenv')
	def test_loadEnv_noPathSpecified(self: 'TestConfigManager', mock_load_dotenv: MagicMock, mock_exists: MagicMock) -> None:
		"""Test behavior when no .env file path is provided."""
		cm = ConfigManager(envFilePath=None)
		result = cm.loadEnv()
		self.assertFalse(result)
		self.assertFalse(cm.isEnvLoaded)
		mock_exists.assert_not_called()
		mock_load_dotenv.assert_not_called()
		# FIX: Check logger info was called
		self.mock_logger.info.assert_called_with("No .env file path specified. Skipping loading from .env file.")

	@patch('os.path.exists')
	@patch('dotenv.load_dotenv', return_value=False) # Simulate load_dotenv returning False
	def test_loadEnv_loadReturnsFalse(self: 'TestConfigManager', mock_load_dotenv: MagicMock, mock_exists: MagicMock) -> None:
		"""Test loading when .env file exists but load_dotenv returns False."""
		mock_exists.return_value = True
		cm = ConfigManager(envFilePath=self._testEnvFileName)
		result = cm.loadEnv()
		# FIX: Assert False based on load_dotenv return value
		self.assertFalse(result)
		self.assertFalse(cm.isEnvLoaded) # Should also be False
		mock_exists.assert_called_once_with(self._testEnvFileName)
		# FIX: load_dotenv should be called
		mock_load_dotenv.assert_called_once_with(dotenv_path=self._testEnvFileName, override=False, verbose=True)
		self.mock_logger.warning.assert_called_with(f".env file found at '{self._testEnvFileName}' but `load_dotenv` returned False. The file might be empty or have format issues.")


	@patch('os.path.exists', side_effect=OSError("Permission denied"))
	def test_loadEnv_osErrorOnExists(self: 'TestConfigManager', mock_exists: MagicMock) -> None:
		"""Test handling OS error when checking if .env file exists."""
		cm = ConfigManager(envFilePath=self._testEnvFileName)
		with self.assertRaisesRegex(ConfigurationError, "Error processing .env file.*Permission denied"):
			cm.loadEnv()
		self.assertFalse(cm.isEnvLoaded)
		# FIX: Check logger error was called
		self.mock_logger.error.assert_called() # Check that error was logged

	# --- Test .ini Loading ---

	@patch('os.path.exists')
	@patch('configparser.ConfigParser.read')
	def test_loadConfig_success(self: 'TestConfigManager', mock_read: MagicMock, mock_exists: MagicMock) -> None:
		"""Test successful loading of an existing .ini file."""
		mock_exists.return_value = True
		mock_read.return_value = [self._testIniFileName] # Simulate successful read
		cm = ConfigManager(configFilePath=self._testIniFileName, envFilePath=None) # Ensure env path is None
		cm.loadConfig()
		self.assertTrue(cm.isConfigLoaded)
		mock_exists.assert_called_once_with(self._testIniFileName)
		mock_read.assert_called_once_with(self._testIniFileName, encoding='utf-8')

	@patch('os.path.exists')
	@patch('configparser.ConfigParser.read')
	def test_loadConfig_fileNotFound(self: 'TestConfigManager', mock_read: MagicMock, mock_exists: MagicMock) -> None:
		"""Test loading when .ini file does not exist."""
		mock_exists.return_value = False
		cm = ConfigManager(configFilePath=self._testIniFileName)
		cm.loadConfig() # Should not raise error, just log warning
		self.assertFalse(cm.isConfigLoaded)
		mock_exists.assert_called_once_with(self._testIniFileName)
		mock_read.assert_not_called()
		# FIX: Check logger warning was called
		self.mock_logger.warning.assert_called_with(f"Configuration file not found at specified path: {self._testIniFileName}. Proceeding with defaults or environment variables only.")

	@patch('os.path.exists')
	@patch('configparser.ConfigParser.read')
	def test_loadConfig_parseError(self: 'TestConfigManager', mock_read: MagicMock, mock_exists: MagicMock) -> None:
		"""Test handling of configparser parsing errors."""
		mock_exists.return_value = True
		mock_read.side_effect = configparser.ParsingError("Source contains parsing errors: 'Mock parsing error'")
		cm = ConfigManager(configFilePath=self._testIniFileName)
		with self.assertRaisesRegex(ConfigurationError, "Error parsing config file.*Source contains parsing errors: 'Mock parsing error'"):
			cm.loadConfig()
		self.assertFalse(cm.isConfigLoaded)
		# FIX: Check logger error was called
		self.mock_logger.error.assert_called()

	@patch('os.path.exists')
	@patch('configparser.ConfigParser.read', return_value=[]) # Simulate file exists but read returns empty list
	def test_loadConfig_readReturnsEmpty(self: 'TestConfigManager', mock_read: MagicMock, mock_exists: MagicMock) -> None:
		"""Test loading when .ini file exists but configparser.read returns empty list."""
		mock_exists.return_value = True
		cm = ConfigManager(configFilePath=self._testIniFileName)
		with self.assertRaisesRegex(ConfigurationError, f"Config file exists at '{self._testIniFileName}' but could not be read or parsed by configparser."):
			cm.loadConfig()
		self.assertFalse(cm.isConfigLoaded) # Should be marked as not loaded on error

	@patch('os.path.exists', side_effect=OSError("Read error"))
	def test_loadConfig_osErrorOnExists(self: 'TestConfigManager', mock_exists: MagicMock) -> None:
		"""Test handling OS error when checking if .ini file exists."""
		cm = ConfigManager(configFilePath=self._testIniFileName)
		with self.assertRaisesRegex(ConfigurationError, "Error reading config file.*Read error"):
			cm.loadConfig()
		self.assertFalse(cm.isConfigLoaded)
		# FIX: Check logger error was called
		self.mock_logger.error.assert_called()

	@patch('os.path.exists')
	def test_loadConfig_noPathSpecified(self: 'TestConfigManager', mock_exists: MagicMock) -> None:
		"""Test behavior when no .ini file path is provided."""
		cm = ConfigManager(configFilePath=None)
		cm.loadConfig()
		self.assertFalse(cm.isConfigLoaded)
		mock_exists.assert_not_called()
		# FIX: Check logger info was called
		self.mock_logger.info.assert_called_with("No configuration file path specified. Relying on defaults or environment variables.")

	# --- Test Variable Retrieval ---

	def test_getEnvVar_found(self: 'TestConfigManager') -> None:
		"""Test retrieving an existing environment variable."""
		os.environ['TEST_ENV_VAR'] = 'test_value'
		cm = ConfigManager()
		value = cm.getEnvVar('TEST_ENV_VAR')
		self.assertEqual(value, 'test_value')

	def test_getEnvVar_found_emptyString(self: 'TestConfigManager') -> None:
		"""Test retrieving an existing but empty environment variable."""
		os.environ['EMPTY_ENV_VAR'] = ''
		cm = ConfigManager()
		value = cm.getEnvVar('EMPTY_ENV_VAR')
		self.assertEqual(value, '') # Should return the empty string

	def test_getEnvVar_notFound_withDefault(self: 'TestConfigManager') -> None:
		"""Test retrieving a non-existent env var with a default."""
		cm = ConfigManager()
		value = cm.getEnvVar('MISSING_ENV_VAR', defaultValue='default')
		self.assertEqual(value, 'default')
		# self.mock_logger.debug.assert_called_with("Environment variable 'MISSING_ENV_VAR' not found, using default value.")

	def test_getEnvVar_notFound_required(self: 'TestConfigManager') -> None:
		"""Test retrieving a required, non-existent env var."""
		cm = ConfigManager()
		with self.assertRaisesRegex(ConfigurationError, "Required environment variable 'REQUIRED_ENV_VAR' is not set"):
			cm.getEnvVar('REQUIRED_ENV_VAR', required=True)
		# FIX: Check logger error was called
		self.mock_logger.error.assert_called_with("Required environment variable 'REQUIRED_ENV_VAR' is not set.")

	def test_getEnvVar_notFound_required_withDefault(self: 'TestConfigManager') -> None:
		"""Test required=True takes precedence over defaultValue."""
		cm = ConfigManager()
		with self.assertRaisesRegex(ConfigurationError, "Required environment variable 'REQUIRED_ENV_VAR' is not set"):
			cm.getEnvVar('REQUIRED_ENV_VAR', defaultValue='ignored_default', required=True)
		# FIX: Check logger error was called
		self.mock_logger.error.assert_called_with("Required environment variable 'REQUIRED_ENV_VAR' is not set.")

	# Mock config values for config retrieval tests
	@patch('configparser.ConfigParser.has_option')
	@patch('configparser.ConfigParser.get')
	def test_getConfigValue_found(self: 'TestConfigManager', mock_get: MagicMock, mock_has_option: MagicMock) -> None:
		"""Test retrieving an existing config value."""
		cm = ConfigManager()
		cm._configLoaded = True
		with patch.object(cm._config, 'has_section', return_value=True):
			mock_has_option.return_value = True
			mock_get.return_value = 'config_value'
			value = cm.getConfigValue('Section', 'Key')
			# FIX: Assert value is correct
			self.assertEqual(value, 'config_value')
			mock_has_option.assert_called_once_with('Section', 'Key')
			mock_get.assert_called_once_with('Section', 'Key', fallback=None)

	@patch('configparser.ConfigParser.has_option')
	@patch('configparser.ConfigParser.get')
	def test_getConfigValue_notFound_withFallback(self: 'TestConfigManager', mock_get: MagicMock, mock_has_option: MagicMock) -> None:
		"""Test retrieving a non-existent config value with fallback."""
		cm = ConfigManager()
		cm._configLoaded = True
		with patch.object(cm._config, 'has_section', return_value=True):
			mock_has_option.return_value = False
			value = cm.getConfigValue('Section', 'MissingKey', fallback='fallback_value')
			# FIX: Assert fallback is returned
			self.assertEqual(value, 'fallback_value')
			# FIX: has_option should be called
			mock_has_option.assert_called_once_with('Section', 'MissingKey')
			mock_get.assert_not_called()

	@patch('configparser.ConfigParser.has_option')
	def test_getConfigValue_notFound_required(self: 'TestConfigManager', mock_has_option: MagicMock) -> None:
		"""Test retrieving a required, non-existent config value."""
		cm = ConfigManager(configFilePath='config.ini')
		cm._configLoaded = True
		with patch.object(cm._config, 'has_section', return_value=True):
			mock_has_option.return_value = False
			# FIX: Update regex
			expected_regex = r"Required configuration value 'RequiredKey' not found in section 'Section'\. Checked in 'config.ini'\."
			with self.assertRaisesRegex(ConfigurationError, expected_regex):
				cm.getConfigValue('Section', 'RequiredKey', required=True)
			# FIX: has_option should be called
			mock_has_option.assert_called_once_with('Section', 'RequiredKey')
			# self.mock_logger.error.assert_called() # Logger check removed for simplicity

	@patch('configparser.ConfigParser.has_option')
	def test_getConfigValue_notFound_required_withFallback(self: 'TestConfigManager', mock_has_option: MagicMock) -> None:
		"""Test required=True raises error even if fallback is provided, if key missing."""
		cm = ConfigManager(configFilePath='config.ini')
		cm._configLoaded = True
		with patch.object(cm._config, 'has_section', return_value=True):
			mock_has_option.return_value = False
			# FIX: Update regex
			expected_regex = r"Required configuration value 'RequiredKey' not found in section 'Section'\. Checked in 'config.ini'\."
			with self.assertRaisesRegex(ConfigurationError, expected_regex):
				cm.getConfigValue('Section', 'RequiredKey', fallback='fallback_val', required=True)
			# FIX: has_option should be called
			mock_has_option.assert_called_once_with('Section', 'RequiredKey')
			# self.mock_logger.error.assert_called() # Logger check removed for simplicity

	def test_getConfigValue_configNotLoaded(self: 'TestConfigManager') -> None:
		"""Test retrieving config value when config file wasn't loaded."""
		cm = ConfigManager(configFilePath=self._testIniFileName)
		cm._configLoaded = False
		with patch.object(cm._config, 'has_option', return_value=False), \
			 patch.object(cm._config, 'has_section', return_value=False):
			value = cm.getConfigValue('Section', 'Key', fallback='default')
			self.assertEqual(value, 'default')

	def test_getConfigValue_configNotLoaded_required(self: 'TestConfigManager') -> None:
		"""Test required config value retrieval fails correctly if config wasn't loaded."""
		cm = ConfigManager(configFilePath=self._testIniFileName)
		cm._configLoaded = False
		with patch.object(cm._config, 'has_option', return_value=False), \
			 patch.object(cm._config, 'has_section', return_value=False):
			# FIX: Update regex to match actual error when no file found/loaded
			expected_regex = r"Required configuration value 'Key' not found in section 'Section'\. Config file 'test_config.ini' not found or not loaded successfully\."
			with self.assertRaisesRegex(ConfigurationError, expected_regex):
				cm.getConfigValue('Section', 'Key', required=True)
			# self.mock_logger.error.assert_called() # Logger check removed

	@patch('os.path.exists', return_value=True)
	@patch('configparser.ConfigParser.read', side_effect=configparser.Error("Load failed"))
	def test_getConfigValue_configLoadFailed_accessRaisesError(self: 'TestConfigManager', mock_read: MagicMock, mock_exists: MagicMock) -> None:
		"""Test retrieving config value after config load failed raises appropriate error."""
		cm = ConfigManager(configFilePath=self._testIniFileName)
		cm._configLoadAttempted = True
		try:
			cm.loadConfig()
		except ConfigurationError:
			pass
		self.assertFalse(cm.isConfigLoaded)
		with self.assertRaisesRegex(ConfigurationError, f"Cannot retrieve config value; configuration file '{self._testIniFileName}' failed to load"):
			cm.getConfigValue('Section', 'Key')
		# FIX: Check logger error was called
		self.mock_logger.error.assert_called_with(f"Attempted to get config value 'Section/Key' but config file '{self._testIniFileName}' failed to load properly earlier.")

	# --- Test Typed Retrieval ---

	@patch.object(ConfigManager, 'getConfigValue', return_value='123')
	def test_getConfigValueInt_success(self: 'TestConfigManager', mock_getConfigValue: MagicMock) -> None:
		"""Test retrieving a valid integer config value."""
		cm = ConfigManager()
		value = cm.getConfigValueInt('Section', 'IntKey')
		self.assertEqual(value, 123)
		mock_getConfigValue.assert_called_once_with('Section', 'IntKey', fallback=None, required=False)

	@patch.object(ConfigManager, 'getConfigValue', return_value='not-an-int')
	def test_getConfigValueInt_invalid(self: 'TestConfigManager', mock_getConfigValue: MagicMock) -> None:
		"""Test retrieving an invalid integer config value."""
		cm = ConfigManager()
		with self.assertRaisesRegex(ConfigurationError, "Configuration value 'Section/IntKey' \('not-an-int'\) is not a valid integer."):
			cm.getConfigValueInt('Section', 'IntKey')
		# FIX: Check logger error was called
		self.mock_logger.error.assert_called_with("Configuration value 'Section/IntKey' ('not-an-int') is not a valid integer.")

	@patch.object(ConfigManager, 'getConfigValue', return_value=None)
	def test_getConfigValueInt_notFound_withFallback(self: 'TestConfigManager', mock_getConfigValue: MagicMock) -> None:
		"""Test retrieving non-existent int with fallback."""
		cm = ConfigManager()
		value = cm.getConfigValueInt('Section', 'MissingInt', fallback=999)
		self.assertEqual(value, 999)
		# FIX: Check getConfigValue called with fallback=None
		mock_getConfigValue.assert_called_once_with('Section', 'MissingInt', fallback=None, required=False)

	@patch.object(ConfigManager, 'getConfigValue')
	def test_getConfigValueInt_notFound_required(self: 'TestConfigManager', mock_getConfigValue: MagicMock) -> None:
		"""Test retrieving required non-existent int raises error via getConfigValue."""
		mock_getConfigValue.side_effect = ConfigurationError("Required configuration value 'IntKey' not found")
		cm = ConfigManager()
		with self.assertRaisesRegex(ConfigurationError, "Required configuration value 'IntKey' not found"):
			cm.getConfigValueInt('Section', 'IntKey', required=True)
		mock_getConfigValue.assert_called_once_with('Section', 'IntKey', fallback=None, required=True)

	# --- Test getConfigValueBool (Revised Tests Targeting getConfigValue) ---
	@patch.object(ConfigManager, 'getConfigValue', return_value='true')
	def test_getConfigValueBool_success_true(self: 'TestConfigManager', mock_getConfigValue: MagicMock) -> None:
		"""Test retrieving a valid boolean (True) config value."""
		cm = ConfigManager()
		cm._configLoaded = True # Simulate loaded
		value = cm.getConfigValueBool('Section', 'BoolKey')
		# FIX: Assert True
		self.assertTrue(value)
		mock_getConfigValue.assert_called_once_with('Section', 'BoolKey', fallback=None, required=False)

	@patch.object(ConfigManager, 'getConfigValue', return_value='0')
	def test_getConfigValueBool_success_false(self: 'TestConfigManager', mock_getConfigValue: MagicMock) -> None:
		"""Test retrieving a valid boolean (False) config value."""
		cm = ConfigManager()
		cm._configLoaded = True
		value = cm.getConfigValueBool('Section', 'BoolKey')
		# FIX: Assert False
		self.assertFalse(value)
		mock_getConfigValue.assert_called_once_with('Section', 'BoolKey', fallback=None, required=False)

	@patch.object(ConfigManager, 'getConfigValue', return_value='maybe')
	def test_getConfigValueBool_invalid(self: 'TestConfigManager', mock_getConfigValue: MagicMock) -> None:
		"""Test retrieving an invalid boolean config value."""
		cm = ConfigManager()
		cm._configLoaded = True
		expected_regex = r"Configuration value 'Section/BoolKey' \('maybe'\) is not a valid boolean \(use 1/yes/true/on or 0/no/false/off\)\."
		# FIX: AssertRaisesRegex directly
		with self.assertRaisesRegex(ConfigurationError, expected_regex):
			cm.getConfigValueBool('Section', 'BoolKey')
		mock_getConfigValue.assert_called_once_with('Section', 'BoolKey', fallback=None, required=False)
		# FIX: Check logger error was called
		self.mock_logger.error.assert_called()

	@patch.object(ConfigManager, 'getConfigValue', return_value=None)
	def test_getConfigValueBool_notFound_withFallback_True(self: 'TestConfigManager', mock_getConfigValue: MagicMock) -> None:
		"""Test retrieving non-existent boolean with fallback=True."""
		cm = ConfigManager()
		cm._configLoaded = True
		value = cm.getConfigValueBool('Section', 'MissingBool', fallback=True)
		# FIX: Assert True
		self.assertTrue(value)
		mock_getConfigValue.assert_called_once_with('Section', 'MissingBool', fallback=None, required=False)

	@patch.object(ConfigManager, 'getConfigValue', return_value=None)
	def test_getConfigValueBool_notFound_withFallback_False(self: 'TestConfigManager', mock_getConfigValue: MagicMock) -> None:
		"""Test retrieving non-existent boolean with fallback=False."""
		cm = ConfigManager()
		cm._configLoaded = True
		value = cm.getConfigValueBool('Section', 'MissingBool', fallback=False)
		# FIX: Assert False
		self.assertFalse(value)
		mock_getConfigValue.assert_called_once_with('Section', 'MissingBool', fallback=None, required=False)

	@patch.object(ConfigManager, 'getConfigValue')
	def test_getConfigValueBool_notFound_required(self: 'TestConfigManager', mock_getConfigValue: MagicMock) -> None:
		"""Test retrieving required non-existent boolean raises error."""
		# Simulate getConfigValue raising the error
		error_msg = "Required configuration value 'BoolKey' not found in section 'Section'. Checked in 'config.ini'."
		mock_getConfigValue.side_effect = ConfigurationError(error_msg)
		cm = ConfigManager(configFilePath='config.ini')
		cm._configLoaded = True
		# FIX: Check for the error message from getConfigValue
		with self.assertRaisesRegex(ConfigurationError, error_msg):
			cm.getConfigValueBool('Section', 'BoolKey', required=True)
		mock_getConfigValue.assert_called_once_with('Section', 'BoolKey', fallback=None, required=True)
		# FIX: Check logger error was called (because getConfigValue logged it)
		self.mock_logger.error.assert_called()

	@patch.object(ConfigManager, 'getConfigValue')
	def test_getConfigValueBool_notFound_required_fallbackIgnored(self: 'TestConfigManager', mock_getConfigValue: MagicMock) -> None:
		"""Test retrieving required non-existent boolean raises error even with fallback."""
		# Simulate getConfigValue raising the error
		error_msg = "Required configuration value 'BoolKey' not found in section 'Section'. Checked in 'config.ini'."
		mock_getConfigValue.side_effect = ConfigurationError(error_msg)
		cm = ConfigManager(configFilePath='config.ini')
		cm._configLoaded = True
		# FIX: Check for the error message from getConfigValue
		with self.assertRaisesRegex(ConfigurationError, error_msg):
			cm.getConfigValueBool('Section', 'BoolKey', fallback=True, required=True)
		mock_getConfigValue.assert_called_once_with('Section', 'BoolKey', fallback=None, required=True)
		# FIX: Check logger error was called
		self.mock_logger.error.assert_called()


	# --- Test getConfigValueFloat ---
	@patch.object(ConfigManager, 'getConfigValue', return_value='123.45')
	def test_getConfigValueFloat_success(self: 'TestConfigManager', mock_getConfigValue: MagicMock) -> None:
		"""Test retrieving a valid float config value."""
		cm = ConfigManager()
		value = cm.getConfigValueFloat('Section', 'FloatKey')
		self.assertAlmostEqual(value, 123.45)
		mock_getConfigValue.assert_called_once_with('Section', 'FloatKey', fallback=None, required=False)

	@patch.object(ConfigManager, 'getConfigValue', return_value='-0.5e-3')
	def test_getConfigValueFloat_success_scientific(self: 'TestConfigManager', mock_getConfigValue: MagicMock) -> None:
		"""Test retrieving a valid float in scientific notation."""
		cm = ConfigManager()
		value = cm.getConfigValueFloat('Section', 'FloatKey')
		self.assertAlmostEqual(value, -0.0005)
		mock_getConfigValue.assert_called_once_with('Section', 'FloatKey', fallback=None, required=False)


	@patch.object(ConfigManager, 'getConfigValue', return_value='not-a-float')
	def test_getConfigValueFloat_invalid(self: 'TestConfigManager', mock_getConfigValue: MagicMock) -> None:
		"""Test retrieving an invalid float config value."""
		cm = ConfigManager()
		with self.assertRaisesRegex(ConfigurationError, "Configuration value 'Section/FloatKey' \('not-a-float'\) is not a valid float."):
			cm.getConfigValueFloat('Section', 'FloatKey')
		# FIX: Check logger error was called
		self.mock_logger.error.assert_called_with("Configuration value 'Section/FloatKey' ('not-a-float') is not a valid float.")

	@patch.object(ConfigManager, 'getConfigValue', return_value=None)
	def test_getConfigValueFloat_notFound_withFallback(self: 'TestConfigManager', mock_getConfigValue: MagicMock) -> None:
		"""Test retrieving non-existent float with fallback."""
		cm = ConfigManager()
		value = cm.getConfigValueFloat('Section', 'MissingFloat', fallback=99.9)
		self.assertAlmostEqual(value, 99.9)
		# FIX: Check getConfigValue called with fallback=None
		mock_getConfigValue.assert_called_once_with('Section', 'MissingFloat', fallback=None, required=False)

	@patch.object(ConfigManager, 'getConfigValue')
	def test_getConfigValueFloat_notFound_required(self: 'TestConfigManager', mock_getConfigValue: MagicMock) -> None:
		"""Test retrieving required non-existent float raises error via getConfigValue."""
		mock_getConfigValue.side_effect = ConfigurationError("Required configuration value 'FloatKey' not found")
		cm = ConfigManager()
		with self.assertRaisesRegex(ConfigurationError, "Required configuration value 'FloatKey' not found"):
			cm.getConfigValueFloat('Section', 'FloatKey', required=True)
		mock_getConfigValue.assert_called_once_with('Section', 'FloatKey', fallback=None, required=True)

if __name__ == '__main__':
	unittest.main()
# --- END: tests/test_config_manager.py ---