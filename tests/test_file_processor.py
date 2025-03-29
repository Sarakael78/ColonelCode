# --- START: tests/test_file_processor.py ---
import unittest
import os
import json
#import yaml # Required if testing YAML
from unittest.mock import patch, mock_open, call, MagicMock, ANY
from typing import Dict, List # For type hints

# Attempt to import yaml safely for conditional testing
try:
	import yaml
	PYYAML_AVAILABLE = True
except ImportError:
	PYYAML_AVAILABLE = False


# Ensure imports work correctly assuming tests are run from the project root
# Adjust path if necessary based on your test runner setup
import sys
if '.' not in sys.path:
	sys.path.append('.') # Add project root if needed

from core.file_processor import FileProcessor, INVALID_PATH_CHARS_REGEX
from core.exceptions import ParsingError, FileProcessingError

# Test Suite for FileProcessor
class TestFileProcessor(unittest.TestCase):
	'''
	Unit tests for the FileProcessor class.
	Mocks file system operations (`os`, `open`).
	'''

	def setUp(self: 'TestFileProcessor') -> None:
		'''Set up test fixtures, if any.'''
		self.processor = FileProcessor()
		# Use a relative path for testing simplicity, ensure mocks handle it
		self.testDir = './fake/repo/path'
		self.absTestDir = os.path.abspath(self.testDir) # Absolute path for comparison

		# Patch logger to suppress output during tests
		self.patcher = patch('core.file_processor.logger', MagicMock())
		self.mock_logger = self.patcher.start()

	def tearDown(self: 'TestFileProcessor') -> None:
		"""Stop logger patching."""
		self.patcher.stop()

	# --- Test extractCodeBlock ---

	def test_extractCodeBlock_json_success(self: 'TestFileProcessor') -> None:
		'''Test extracting a valid JSON code block.'''
		# Define response using standard strings and \n to avoid markdown conflicts
		response = (
			"Some text before.\n"
			"```json\n"
			"{\n"
			'  "file.py": "print(\'hello\')"\n'
			"}\n"
			"```\n"
			"Some text after.\n"
		)
		expected = '{\n  "file.py": "print(\'hello\')"\n}'
		result = self.processor.extractCodeBlock(response, language='json')
		self.assertEqual(result, expected)

	def test_extractCodeBlock_json_extra_whitespace(self: 'TestFileProcessor') -> None:
		'''Test extracting JSON with extra whitespace around fences and language tag.'''
		response = "  ```  json   \n{\"key\": \"value\"}\n```  "
		expected = '{"key": "value"}'
		result = self.processor.extractCodeBlock(response, language='json')
		self.assertEqual(result, expected)

	def test_extractCodeBlock_no_language_tag_finds_generic(self: 'TestFileProcessor') -> None:
		'''Test extracting a block with no language tag using generic match (language='').'''
		response = "Text\n```\nDATA\n```\nText"
		expected = 'DATA'
		# Pass empty string for language to match generic block
		result = self.processor.extractCodeBlock(response, language='')
		self.assertEqual(result, expected)
		# Check if log message was generated (flexible check)
		self.mock_logger.info.assert_any_call(unittest.mock.ANY) # Basic check it logged something

	def test_extractCodeBlock_specific_lang_requested_falls_back_to_generic(self: 'TestFileProcessor') -> None:
		'''Test requesting specific language finds generic block if specific fails.'''
		response = "Explanation...\n```\n{\n'data.txt': 'content'\n}\n```\n"
		expected = "{\n'data.txt': 'content'\n}"
		# Request json, but it's missing language tag, should find generic via fallback
		result = self.processor.extractCodeBlock(response, language='json')
		self.assertEqual(result, expected)
		# FIX: Check for the specific warning message indicating line search failed
		self.mock_logger.warning.assert_any_call("Could not find fenced code block using line search. Attempting regex fallback...")
		# FIX: Check info message for regex fallback success
		self.mock_logger.info.assert_any_call("Successfully extracted 'generic (fallback)' code block using generic regex fallback. Length: 26")


	def test_extractCodeBlock_multiple_blocks_first_match_specific(self: 'TestFileProcessor') -> None:
		'''Test extracting the first matching specific block if multiple exist.'''
		response = "```json\nFIRST\n```\nSome text\n```json\nSECOND\n```"
		expected = 'FIRST'
		result = self.processor.extractCodeBlock(response, language='json')
		self.assertEqual(result, expected)
		# Check log message based on line search
		self.mock_logger.info.assert_called_with("Successfully extracted 'json' code block using line search. Length: 5")

	def test_extractCodeBlock_multiple_blocks_first_match_generic(self: 'TestFileProcessor') -> None:
		'''Test extracting the first generic block when multiple generic blocks exist.'''
		response = "```\nFIRST\n```\nSome text\n```\nSECOND\n```"
		expected = 'FIRST'
		result = self.processor.extractCodeBlock(response, language='') # Request generic
		self.assertEqual(result, expected)
		# Check log message based on line search
		self.mock_logger.info.assert_called_with("Successfully extracted 'generic' code block using line search. Length: 5")


	def test_extractCodeBlock_mixed_blocks_specific_wins(self: 'TestFileProcessor') -> None:
		'''Test extracting specific block even if generic block appears first.'''
		response = "```\nGENERIC\n```\nSome text\n```json\nSPECIFIC\n```"
		expected = 'SPECIFIC'
		result = self.processor.extractCodeBlock(response, language='json') # Request specific
		self.assertEqual(result, expected)
		# Check log message based on line search (which finds specific first)
		self.mock_logger.info.assert_called_with("Successfully extracted 'json' code block using line search. Length: 8")

	def test_extractCodeBlock_noBlockFound(self: 'TestFileProcessor') -> None:
		'''Test response with no code block.'''
		response = "Just plain text explanation."
		result = self.processor.extractCodeBlock(response, language='json')
		self.assertIsNone(result)
		# Check for the final error message after all methods fail
		self.mock_logger.error.assert_any_call("Could not find a fenced code block matching '```json' or generic '```' using any method.")


	def test_extractCodeBlock_emptyBlock(self: 'TestFileProcessor') -> None:
		'''Test response with an empty code block.'''
		response = "```json\n\n```"
		result = self.processor.extractCodeBlock(response, language='json')
		self.assertEqual(result, "") # Empty string is valid extraction
		# Check log message based on line search
		self.mock_logger.info.assert_called_with("Successfully extracted 'json' code block using line search. Length: 0")


	def test_extractCodeBlock_differentLanguage_no_match(self: 'TestFileProcessor') -> None:
		'''Test requesting 'json' when only 'python' block exists using regex fallback.'''
		response = "```python\nprint('hi')\n```"
		result = self.processor.extractCodeBlock(response, language='json')
		self.assertEqual(result, "print('hi')")
		self.mock_logger.warning.assert_any_call("Could not find fenced code block using line search. Attempting regex fallback...")
		# FIX: Check info message for regex fallback success (now reports 'generic (fallback)')
		self.mock_logger.info.assert_any_call("Successfully extracted 'generic (fallback)' code block using generic regex fallback. Length: 10")


	def test_extractCodeBlock_case_insensitive_language(self: 'TestFileProcessor') -> None:
		'''Test language matching is case-insensitive.'''
		response = "```JSON\n{}\n```"
		expected = "{}"
		result = self.processor.extractCodeBlock(response, language='json')
		self.assertEqual(result, expected)
		# Check log message based on line search
		self.mock_logger.info.assert_called_with("Successfully extracted 'json' code block using line search. Length: 2")


	# --- Test _is_safe_relative_path ---

	def test_is_safe_relative_path_valid(self: 'TestFileProcessor') -> None:
		self.assertTrue(self.processor._is_safe_relative_path("file.txt"))
		self.assertTrue(self.processor._is_safe_relative_path("subdir/file.txt"))
		self.assertTrue(self.processor._is_safe_relative_path("subdir\\file.txt")) # Allow windows sep internally
		self.assertTrue(self.processor._is_safe_relative_path(".config/settings"))
		self.mock_logger.warning.assert_not_called()

	def test_is_safe_relative_path_invalid_absolute_unix(self: 'TestFileProcessor') -> None:
		self.assertFalse(self.processor._is_safe_relative_path("/etc/passwd"))
		# FIX: Update expected log message
		self.mock_logger.warning.assert_called_with("Path validation failed: Path '/etc/passwd' appears absolute.")

	def test_is_safe_relative_path_invalid_absolute_win(self: 'TestFileProcessor') -> None:
		# FIX: Assert False for C:\Windows based on updated logic
		self.assertFalse(self.processor._is_safe_relative_path("C:\\Windows"))
		self.mock_logger.warning.assert_any_call("Path validation failed: Path 'C:\\Windows' appears absolute.")
		# Test UNC Path
		self.mock_logger.reset_mock() # Reset mock for next assert
		self.assertFalse(self.processor._is_safe_relative_path("\\\\server\\share"))
		self.mock_logger.warning.assert_called_with("Path validation failed: Path '\\\\server\\share' appears absolute.")

	def test_is_safe_relative_path_invalid_traversal_simple(self: 'TestFileProcessor') -> None:
		self.assertFalse(self.processor._is_safe_relative_path("../file.txt"))
		self.mock_logger.warning.assert_called_with("Path validation failed: Path '../file.txt' contains '..' component.")

	def test_is_safe_relative_path_invalid_traversal_nested(self: 'TestFileProcessor') -> None:
		self.assertFalse(self.processor._is_safe_relative_path("subdir/../../file.txt"))
		self.mock_logger.warning.assert_called_with("Path validation failed: Path 'subdir/../../file.txt' contains '..' component.")

	def test_is_safe_relative_path_invalid_traversal_mixed_sep(self: 'TestFileProcessor') -> None:
		self.assertFalse(self.processor._is_safe_relative_path("subdir\\..\\../file.txt"))
		self.mock_logger.warning.assert_called_with("Path validation failed: Path 'subdir\\..\\../file.txt' contains '..' component.")

	def test_is_safe_relative_path_invalid_traversal_after_norm(self: 'TestFileProcessor') -> None:
		# This specific case is caught by normpath check
		self.assertFalse(self.processor._is_safe_relative_path("subdir/../sub/../../file.txt"))
		# FIX: Ensure the 'contains ..' warning is asserted correctly as the primary failure reason
		self.mock_logger.warning.assert_any_call("Path validation failed: Path 'subdir/../sub/../../file.txt' contains '..' component.")
		# Remove assertion for normpath warning as the first check catches it

	def test_is_safe_relative_path_invalid_chars(self: 'TestFileProcessor') -> None:
		self.assertFalse(self.processor._is_safe_relative_path("file:name.txt"))
		self.mock_logger.warning.assert_called_with("Path validation failed: Path 'file:name.txt' contains invalid character (':').")
		self.mock_logger.reset_mock()
		self.assertFalse(self.processor._is_safe_relative_path("file<>.txt"))
		self.mock_logger.warning.assert_called_with("Path validation failed: Path 'file<>.txt' contains invalid character ('<').")
		self.mock_logger.reset_mock()
		self.assertFalse(self.processor._is_safe_relative_path("file\0name.txt"))
		# FIX: Update assertion for null byte representation in log
		self.mock_logger.warning.assert_called_with("Path validation failed: Path 'file\\x00name.txt' contains invalid character ('\\x00').")

	def test_is_safe_relative_path_empty_or_none(self: 'TestFileProcessor') -> None:
		self.assertFalse(self.processor._is_safe_relative_path(""))
		self.mock_logger.warning.assert_called_with("Path validation failed: Path is not a non-empty string.")
		self.assertFalse(self.processor._is_safe_relative_path(None))
		self.mock_logger.warning.assert_called_with("Path validation failed: Path is not a non-empty string.")

	# --- Test parseStructuredOutput ---

	def test_parseStructuredOutput_json_success(self: 'TestFileProcessor') -> None:
		'''Test parsing a valid JSON string with safe paths.'''
		jsonString = '{"a.py": "content a", "b/c.txt": "content b"}'
		expected: Dict[str, str] = {"a.py": "content a", "b/c.txt": "content b"}
		result = self.processor.parseStructuredOutput(jsonString, format='json')
		self.assertEqual(result, expected)
		self.mock_logger.info.assert_called_with("Successfully parsed and validated 'json' data. Found 2 file entries.")

	def test_parseStructuredOutput_json_invalid(self: 'TestFileProcessor') -> None:
		'''Test parsing invalid JSON.'''
		invalidJsonString = '{"a.py": "content a", "b/c.txt": }' # Missing value
		# FIX: Update regex to match the actual error message format from parsing attempts
		expected_regex = r"Invalid JSON detected: Expecting value: line 1 column 34 \(char 33\)\. Stripping.*failed.*Expecting value: line 1 column 34 \(char 33\)"
		with self.assertRaisesRegex(ParsingError, expected_regex):
			self.processor.parseStructuredOutput(invalidJsonString, format='json')
		self.mock_logger.error.assert_called()

	def test_parseStructuredOutput_json_wrongStructure_notDict(self: 'TestFileProcessor') -> None:
		'''Test parsing JSON that is not a dictionary.'''
		jsonString = '["a.py", "b.py"]' # List instead of dict
		with self.assertRaisesRegex(ParsingError, "Parsed data is not a dictionary"):
			self.processor.parseStructuredOutput(jsonString, format='json')
		self.mock_logger.error.assert_called_with("Parsed data is not a dictionary as expected. Found type: list")

	def test_parseStructuredOutput_json_wrongStructure_badKeys_type(self: 'TestFileProcessor') -> None:
		'''Test parsing JSON dict with non-string keys.'''
		invalid_dict = {123: "content"}
		with patch('json.loads', return_value=invalid_dict):
			jsonString = '{123: "content"}'
			# FIX: Update regex to match the exact error message from validation
			with self.assertRaisesRegex(ParsingError, "Invalid structure: Dictionary key 123 is not a safe relative path."):
				self.processor.parseStructuredOutput(jsonString, format='json')
			self.mock_logger.warning.assert_called_with("Path validation failed: Path is not a non-empty string.")

	def test_parseStructuredOutput_json_wrongStructure_badKeys_empty(self: 'TestFileProcessor') -> None:
		'''Test parsing JSON dict with empty string key.'''
		jsonString = '{"": "content"}'
		with self.assertRaisesRegex(ParsingError, "Invalid structure: Dictionary key '' is not a safe relative path."):
			self.processor.parseStructuredOutput(jsonString, format='json')
		self.mock_logger.warning.assert_called_with("Path validation failed: Path is not a non-empty string.")


	def test_parseStructuredOutput_json_wrongStructure_badValues(self: 'TestFileProcessor') -> None:
		'''Test parsing JSON dict with non-string values.'''
		jsonString = '{"a.py": ["list", "content"]}' # Value is list, not string
		with self.assertRaisesRegex(ParsingError, "Value for key 'a.py' is not a string"):
			self.processor.parseStructuredOutput(jsonString, format='json')
		self.mock_logger.error.assert_called_with("Invalid structure: Value for key 'a.py' is not a string (type: list).")


	def test_parseStructuredOutput_json_wrongStructure_unsafePath_absolute(self: 'TestFileProcessor') -> None:
		'''Test parsing JSON dict with an absolute path key.'''
		jsonString = '{"/abs/path.py": "content"}'
		# FIX: Update regex for exact error message
		with self.assertRaisesRegex(ParsingError, "Invalid structure: Dictionary key '/abs/path.py' is not a safe relative path."):
			self.processor.parseStructuredOutput(jsonString, format='json')
		self.mock_logger.warning.assert_called_with("Path validation failed: Path '/abs/path.py' appears absolute.")

	def test_parseStructuredOutput_json_wrongStructure_unsafePath_traversal(self: 'TestFileProcessor') -> None:
		'''Test parsing JSON dict with a path traversal key.'''
		jsonString = '{"../etc/passwd": "content"}'
		# FIX: Update regex for exact error message
		with self.assertRaisesRegex(ParsingError, "Invalid structure: Dictionary key '../etc/passwd' is not a safe relative path."):
			self.processor.parseStructuredOutput(jsonString, format='json')
		self.mock_logger.warning.assert_called_with("Path validation failed: Path '../etc/passwd' contains '..' component.")

	# Add similar tests for 'yaml' format if PyYAML is used/installed
	@unittest.skipUnless(PYYAML_AVAILABLE, "PyYAML not available")
	def test_parseStructuredOutput_yaml_success(self: 'TestFileProcessor') -> None:
		'''Test parsing valid YAML (requires PyYAML).'''
		yamlString = "a.py: content a\nb/c.txt: content b\n"
		expected: Dict[str, str] = {"a.py": "content a", "b/c.txt": "content b"}
		result = self.processor.parseStructuredOutput(yamlString, format='yaml')
		self.assertEqual(result, expected)
		self.mock_logger.info.assert_called_with("Successfully parsed and validated 'yaml' data. Found 2 file entries.")

	@unittest.skipUnless(PYYAML_AVAILABLE, "PyYAML not available")
	def test_parseStructuredOutput_yaml_invalid(self: 'TestFileProcessor') -> None:
		'''Test parsing invalid YAML (requires PyYAML).'''
		invalidYamlString = "a.py: content a\n- b/c.txt: content b\n" # Malformed
		with self.assertRaisesRegex(ParsingError, "Invalid YAML detected"):
			self.processor.parseStructuredOutput(invalidYamlString, format='yaml')
		self.mock_logger.error.assert_called()

	@unittest.skipUnless(PYYAML_AVAILABLE, "PyYAML not available")
	def test_parseStructuredOutput_yaml_wrongStructure_unsafePath_absolute(self: 'TestFileProcessor') -> None:
		'''Test parsing YAML dict with an absolute path key.'''
		yamlString = "'/abs/path.py': content"
		# FIX: Update regex for exact error message
		with self.assertRaisesRegex(ParsingError, "Invalid structure: Dictionary key '/abs/path.py' is not a safe relative path."):
			self.processor.parseStructuredOutput(yamlString, format='yaml')
		self.mock_logger.warning.assert_called_with("Path validation failed: Path '/abs/path.py' appears absolute.")

	@unittest.skipUnless(PYYAML_AVAILABLE, "PyYAML not available")
	def test_parseStructuredOutput_yaml_wrongStructure_unsafePath_traversal(self: 'TestFileProcessor') -> None:
		'''Test parsing YAML dict with a path traversal key.'''
		yamlString = "'../secret': content"
		# FIX: Update regex for exact error message
		with self.assertRaisesRegex(ParsingError, "Invalid structure: Dictionary key '../secret' is not a safe relative path."):
			self.processor.parseStructuredOutput(yamlString, format='yaml')
		self.mock_logger.warning.assert_called_with("Path validation failed: Path '../secret' contains '..' component.")

	# FIX: Adjust YAML unavailable test
	@unittest.skipIf(PYYAML_AVAILABLE, "PyYAML is available, skipping unavailable test")
	def test_parseStructuredOutput_yaml_unavailable_skipped(self: 'TestFileProcessor') -> None:
		"""Test parsing YAML when PyYAML is not installed (skipped if installed)."""
		# This version will only run if PyYAML is NOT available
		yamlString = "a.py: content a"
		with self.assertRaisesRegex(ParsingError, "PyYAML library is not installed"):
			self.processor.parseStructuredOutput(yamlString, format='yaml')
		self.mock_logger.error.assert_called_with("Parsing format 'yaml' requested, but PyYAML library is not installed or failed to import. Please install it (`pip install pyyaml`).")


	def test_parseStructuredOutput_unsupportedFormat(self: 'TestFileProcessor') -> None:
		'''Test requesting an unsupported format.'''
		with self.assertRaisesRegex(NotImplementedError, "Parsing for format 'xml' is not implemented"):
			self.processor.parseStructuredOutput("data", format='xml')
		self.mock_logger.error.assert_called()

	# --- Test saveFilesToDisk ---

	@patch('os.path.realpath')
	@patch('os.path.isdir')
	@patch('os.path.exists')
	@patch('os.makedirs')
	@patch('builtins.open', new_callable=mock_open)
	def test_saveFilesToDisk_success(
		self: 'TestFileProcessor', mock_file_open: MagicMock, mock_makedirs: MagicMock,
		mock_exists: MagicMock, mock_isdir: MagicMock, mock_realpath: MagicMock
	) -> None:
		'''Test saving multiple files successfully.'''
		base_dir = self.absTestDir
		mock_isdir.side_effect = lambda p: os.path.abspath(p) == base_dir
		mock_exists.side_effect = lambda p: os.path.abspath(p) == base_dir

		# FIX: Corrected realpath mocking
		def fixed_realpath_side_effect(path_arg):
			norm_path = os.path.normpath(path_arg)
			abs_path = os.path.abspath(path_arg) # Get absolute path for comparison
			if abs_path == base_dir:
				return base_dir
			# Simulate resolving paths within the base directory
			elif abs_path.startswith(base_dir + os.sep):
				# Return the absolute path as if resolution was successful within base
				return abs_path
			else:
				# If path is outside base_dir (e.g., self.testDir relative path), return base_dir
				# Or handle other specific cases as needed.
				return base_dir
		mock_realpath.side_effect = fixed_realpath_side_effect

		fileData: Dict[str, str] = {
			"file1.txt": "content1",
			"subdir/file2.py": "content2",
			"subdir\\file3.win": "content3"
		}
		expectedSavedFiles = ["file1.txt", "subdir/file2.py", "subdir\\file3.win"]
		expectedFullPaths = [
			os.path.join(base_dir, 'file1.txt'),
			os.path.join(base_dir, 'subdir', 'file2.py'),
			os.path.join(base_dir, 'subdir', 'file3.win')
		]

		result = self.processor.saveFilesToDisk(self.testDir, fileData) # Pass original relative/absolute path

		self.assertEqual(sorted(result), sorted(expectedSavedFiles))
		mock_realpath.assert_any_call(self.testDir) # Initial call on outputDir
		# Check realpath called on final combined paths
		mock_realpath.assert_any_call(os.path.normpath(os.path.join(base_dir, "file1.txt")))
		mock_realpath.assert_any_call(os.path.normpath(os.path.join(base_dir, "subdir", "file2.py")))
		mock_realpath.assert_any_call(os.path.normpath(os.path.join(base_dir, "subdir", "file3.win")))

		subdir_path = os.path.normpath(os.path.join(base_dir, 'subdir'))
		mock_makedirs.assert_called_once_with(subdir_path, exist_ok=True)

		expectedOpenCalls = [
			call(os.path.normpath(expectedFullPaths[0]), 'w', encoding='utf-8'),
			call(os.path.normpath(expectedFullPaths[1]), 'w', encoding='utf-8'),
			call(os.path.normpath(expectedFullPaths[2]), 'w', encoding='utf-8'),
		]
		mock_file_open.assert_has_calls(expectedOpenCalls, any_order=True)

		handle = mock_file_open()
		expectedWriteCalls = [
			call('content1'),
			call('content2'),
			call('content3'),
		]
		handle.write.assert_has_calls(expectedWriteCalls, any_order=True)
		self.mock_logger.info.assert_called_with(f"Successfully saved {len(expectedSavedFiles)} files.")


	@patch('os.path.isdir', return_value=False)
	def test_saveFilesToDisk_outputDirNotDir(self: 'TestFileProcessor', mock_isdir: MagicMock) -> None:
		'''Test saving when the output directory exists but is not a directory.'''
		fileData = {"file1.txt": "content1"}
		with self.assertRaisesRegex(FileProcessingError, "Output directory .* does not exist or is not a directory"):
			self.processor.saveFilesToDisk(self.testDir, fileData)
		mock_isdir.assert_called_once_with(self.testDir)
		self.mock_logger.error.assert_called_with(f"Output directory '{self.testDir}' does not exist or is not a directory.")

	@patch('os.path.isdir', return_value=False)
	@patch('os.path.exists', return_value=False)
	def test_saveFilesToDisk_outputDirNotFound(self: 'TestFileProcessor', mock_exists: MagicMock, mock_isdir: MagicMock) -> None:
		'''Test saving when the output directory doesn't exist.'''
		fileData = {"file1.txt": "content1"}
		with self.assertRaisesRegex(FileProcessingError, "Output directory .* does not exist or is not a directory"):
			self.processor.saveFilesToDisk(self.testDir, fileData)
		mock_isdir.assert_called_once_with(self.testDir)
		self.mock_logger.error.assert_called_with(f"Output directory '{self.testDir}' does not exist or is not a directory.")


	@patch('os.path.realpath')
	@patch('os.path.isdir', return_value=True)
	def test_saveFilesToDisk_invalidPath_traversal_detected_at_save(
		self: 'TestFileProcessor', mock_isdir: MagicMock, mock_realpath: MagicMock
	) -> None:
		'''Test saving rejects path if realpath resolves outside base dir.'''
		base_dir = self.absTestDir
		fileData = {"../outside.txt": "hacker content"}
		unsafe_relative_path = "../outside.txt"

		# Simulate realpath: base returns base, unsafe path returns path outside base
		def realpath_side_effect(path_arg):
			norm_path = os.path.normpath(path_arg)
			abs_path = os.path.abspath(path_arg)
			if abs_path == base_dir:
				return base_dir
			# Check if the path being resolved is the potentially unsafe one
			if os.path.normpath(os.path.join(base_dir, unsafe_relative_path)) == norm_path:
				return os.path.abspath('/fake/outside/outside.txt')
			else: # Assume safe resolution within base dir otherwise
				return os.path.join(base_dir, os.path.basename(norm_path))
		mock_realpath.side_effect = realpath_side_effect

		# FIX: Update regex to match the earlier failure from _is_safe_relative_path
		expected_regex = "Invalid structure: Dictionary key '\\.\\./outside\\.txt' is not a safe relative path."
		with self.assertRaisesRegex(ParsingError, expected_regex):
			# Parsing happens implicitly before saving in a real workflow,
			# but saveFilesToDisk re-validates. Simulate calling save directly.
			# We need parseStructuredOutput to succeed first for saveFilesToDisk to be called with this data.
			# Simulate valid parsing but invalid path data.
			with patch.object(self.processor, '_is_safe_relative_path', side_effect=self.processor._is_safe_relative_path): # Wrap to allow inspection
					# This will fail inside saveFilesToDisk's internal check
					self.processor.saveFilesToDisk(self.testDir, fileData)

		# FIX: Check the warning log from _is_safe_relative_path
		self.mock_logger.warning.assert_any_call("Path validation failed: Path '../outside.txt' contains '..' component.")


	@patch('os.path.realpath')
	@patch('os.path.isdir', return_value=True)
	@patch('os.path.exists', return_value=True)
	@patch('os.makedirs')
	@patch('builtins.open', side_effect=OSError("Permission denied"))
	def test_saveFilesToDisk_writeOSError(
		self: 'TestFileProcessor', mock_file_open: MagicMock, mock_makedirs: MagicMock,
		mock_exists: MagicMock, mock_isdir: MagicMock, mock_realpath: MagicMock
	) -> None:
		'''Test handling of OSErrors during file writing (raises exception).'''
		base_dir = self.absTestDir
		def fixed_realpath_side_effect(path_arg):
			abs_path = os.path.abspath(path_arg)
			if abs_path == base_dir: return base_dir
			if abs_path.startswith(base_dir + os.sep): return abs_path
			return base_dir # Fallback
		mock_realpath.side_effect = fixed_realpath_side_effect

		fileData = {"file1.txt": "content1"}
		fullPath = os.path.normpath(os.path.join(base_dir, 'file1.txt'))

		# FIX: Update regex to match the actual FileProcessingError raised
		expected_regex = f"OS error writing file '{fullPath}': Permission denied"
		with self.assertRaisesRegex(FileProcessingError, expected_regex):
			self.processor.saveFilesToDisk(self.testDir, fileData)
		mock_file_open.assert_called_once_with(fullPath, 'w', encoding='utf-8')
		self.mock_logger.error.assert_called_with(f"OS error writing file '{fullPath}': Permission denied", exc_info=True)


	@patch('os.path.realpath')
	@patch('os.path.isdir', return_value=True)
	@patch('os.path.exists', return_value=False)
	@patch('os.makedirs', side_effect=OSError("Cannot create dir"))
	@patch('builtins.open', new_callable=mock_open)
	def test_saveFilesToDisk_makeDirsError(
		self: 'TestFileProcessor', mock_file_open: MagicMock, mock_makedirs: MagicMock,
		mock_exists: MagicMock, mock_isdir: MagicMock, mock_realpath: MagicMock
	) -> None:
		'''Test handling of OSErrors during directory creation (raises exception).'''
		base_dir = self.absTestDir
		def fixed_realpath_side_effect(path_arg):
			abs_path = os.path.abspath(path_arg)
			if abs_path == base_dir: return base_dir
			if abs_path.startswith(base_dir + os.sep): return abs_path
			return base_dir # Fallback
		mock_realpath.side_effect = fixed_realpath_side_effect

		fileData = {"newdir/file1.txt": "content1"}
		dirPath = os.path.normpath(os.path.join(base_dir, 'newdir'))
		filePath = os.path.normpath(os.path.join(dirPath, 'file1.txt'))

		# FIX: Update regex to match the actual error raised by saveFilesToDisk
		expected_error_regex = f"OS error creating directory '{dirPath}': Cannot create dir"
		with self.assertRaisesRegex(FileProcessingError, expected_error_regex):
			self.processor.saveFilesToDisk(self.testDir, fileData)

		mock_makedirs.assert_called_once_with(dirPath, exist_ok=True)
		mock_file_open.assert_not_called()
		# FIX: Check log message for the underlying OS error
		self.mock_logger.error.assert_any_call(f"OS error creating directory '{dirPath}': Cannot create dir")


if __name__ == '__main__':
	unittest.main()
# --- END: tests/test_file_processor.py ---