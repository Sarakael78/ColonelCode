# --- START: tests/test_llm_interface.py ---
import unittest
import time # Keep time for potential use, though sleep is patched
from unittest.mock import patch, MagicMock, PropertyMock, call
from typing import Dict, List, Optional, Any # For type hints

# Ensure imports work correctly assuming tests are run from the project root
import sys
if '.' not in sys.path:
    sys.path.append('.') # Add project root if needed

# --- Mock classes/objects for google.generativeai structures ---
# These mimic the structure needed for the tests.

class MockBlockReason:
    def __init__(self, name=""):
        self.name = name

class MockSafetyRating:
    def __init__(self, category_name="UNKNOWN", probability_name="UNKNOWN"):
        # Using PropertyMock to allow setting .name in tests if needed
        self.category = MagicMock()
        type(self.category).name = PropertyMock(return_value=category_name)
        self.probability = MagicMock()
        type(self.probability).name = PropertyMock(return_value=probability_name)

class MockPromptFeedback:
    def __init__(self, block_reason=None, safety_ratings=None):
        self.block_reason = block_reason
        self.safety_ratings = safety_ratings if safety_ratings is not None else []

class MockFinishReason:
    def __init__(self, name="STOP"):
        self.name = name

class MockPart:
    def __init__(self, text=""):
        self.text = text

class MockContent:
    def __init__(self, parts=None):
        self.parts = parts if parts is not None else []

class MockCandidate:
    def __init__(self, finish_reason=None, safety_ratings=None, content=None):
        self.finish_reason = finish_reason if finish_reason else MockFinishReason(name='STOP')
        self.safety_ratings = safety_ratings if safety_ratings is not None else []
        # Ensure content structure is correct
        if content is None:
            self.content = MockContent(parts=[])
        elif isinstance(content, MockContent):
             self.content = content
        elif isinstance(content, list): # Assume list of parts
             self.content = MockContent(parts=content)
        elif isinstance(content, str): # Assume text string
             self.content = MockContent(parts=[MockPart(text=content)])
        else:
             self.content = MockContent(parts=[]) # Default empty

class MockGenAIResponse:
    """ Simulates GenerateContentResponse more closely for testing text access"""
    def __init__(self, candidates=None, prompt_feedback=None):
        self.candidates = candidates if candidates is not None else []
        self.prompt_feedback = prompt_feedback

    @property
    def text(self):
        """Simulate text property access, raising errors appropriately."""
        # 1. Check prompt feedback first (highest priority block)
        if self.prompt_feedback and self.prompt_feedback.block_reason:
            # Simulate google.generativeai.types.BlockedPromptException
            # We use ValueError here as mocking the exact exception type across modules is complex,
            # but the code under test should catch this and wrap it in LLMError.
            # The actual llm_interface code catches the real exception type.
            raise BlockedPromptExceptionMock(self) # Use custom mock exception

        # 2. Check if candidates exist
        if not self.candidates:
            # This might happen if the API returns an empty response for other reasons
            raise ValueError("MockGenAIResponse: Response has no candidates.") # Or simulate specific API error

        # 3. Check the first candidate's finish reason
        candidate = self.candidates[0]
        # Use name attribute for comparison as we mocked the enum objects
        if candidate.finish_reason.name != 'STOP':
            # Simulate google.generativeai.types.StopCandidateException
            raise StopCandidateExceptionMock(candidate) # Use custom mock exception

        # 4. Check if content/parts exist if finish reason is STOP
        if not hasattr(candidate, 'content') or not candidate.content or not candidate.content.parts:
            # Finished normally but no content parts
            # The real library might return empty string here, or raise an error depending on context.
            # Let's simulate returning empty string in this case, and let the calling code handle it.
            # Or raise a specific value error if preferred for testing empty response handling
            # raise ValueError("MockGenAIResponse: Content has no parts, but finish reason was STOP.")
             return "" # Simulate empty text for STOP finish with no parts

        # 5. Join parts if everything is okay
        return "".join(part.text for part in candidate.content.parts if hasattr(part, 'text'))

    @property
    def parts(self):
        # Simulate parts access - return parts from the first candidate if available
        if self.candidates and hasattr(self.candidates[0], 'content') and self.candidates[0].content:
             return self.candidates[0].content.parts
        return []

# --- Custom Mock Exceptions to simulate library behavior ---
# We define these simple exception classes to be raised by the mock response's .text property
# This avoids needing to mock the complex exception types from the actual libraries directly.
# The code under test (llm_interface.py) should catch the *real* exceptions.
class BlockedPromptExceptionMock(Exception):
    def __init__(self, response):
        self.response = response
        super().__init__(f"Mock BlockedPromptException: Reason {response.prompt_feedback.block_reason.name}")

class StopCandidateExceptionMock(Exception):
     def __init__(self, candidate):
        # Store the candidate itself, similar to the real exception
        self.args = (candidate,) # Put candidate in args tuple
        super().__init__(f"Mock StopCandidateException: Reason {candidate.finish_reason.name}")


# --- Test Suite ---
# Use patch decorators for cleaner mocking of dependencies within the module under test
@patch('core.llm_interface.genai') # Patch the imported genai alias in llm_interface
@patch('core.llm_interface.ConfigManager') # Patch ConfigManager where it's imported
@patch('core.llm_interface.time') # Patch time where it's imported
@patch('core.llm_interface.logger') # Patch logger where it's imported
class TestLLMInterface(unittest.TestCase):
    """
    Unit tests for the LLMInterface class.
    Mocks dependencies using unittest.mock.patch.
    """

    # Provide mocked objects to the test methods via arguments from decorators
    def setUp(self: 'TestLLMInterface', mock_logger: MagicMock, mock_time: MagicMock, mock_ConfigManager: MagicMock, mock_genai_in_module: MagicMock) -> None:
        """Set up test fixtures using injected mocks."""

        # Store mocks if needed for assertions later
        self.mock_logger = mock_logger
        self.mock_time = mock_time # Contains sleep mock
        self.mock_ConfigManager = mock_ConfigManager
        self.mock_genai = mock_genai_in_module # The alias used within llm_interface

        # Create a mock instance for ConfigManager return value
        self.mock_config_instance = MagicMock()
        self.mock_ConfigManager.return_value = self.mock_config_instance

        # Mock the GenerativeModel class and instance retrieved from genai
        self.mock_model_instance = MagicMock(spec=['generate_content', 'count_tokens'])
        self.mock_genai.GenerativeModel.return_value = self.mock_model_instance

        # Mock the specific exceptions we expect llm_interface to handle
        # These need to be mock *types* that can be caught
        # Note: Patching the *actual* exception classes is complex.
        # Instead, we ensure the code catches the *real* exception types from google.api_core.exceptions
        # and we simulate those being raised by the mocked generate_content if needed.
        # For internal simulation (like MockGenAIResponse raising errors), we use our simple mock exceptions.
        # For testing the except blocks in queryLlmApi, generate_content mock needs to raise actual/mocked google_exceptions.
        self.mock_google_exceptions = MagicMock()
        self.mock_google_exceptions.PermissionDenied = type('PermissionDeniedMock', (Exception,), {})
        self.mock_google_exceptions.InvalidArgument = type('InvalidArgumentMock', (Exception,), {})
        self.mock_google_exceptions.ResourceExhausted = type('ResourceExhaustedMock', (Exception,), {})
        self.mock_google_exceptions.GoogleAPIError = type('GoogleAPIErrorMock', (Exception,), {})

        # --- Patch google_exceptions *within* llm_interface ---
        # This is tricky; patching imported names requires care.
        # It's often easier to mock the function that *raises* the exception.
        # We will configure self.mock_model_instance.generate_content.side_effect in specific tests.


        # Configure default return values for ConfigManager mocks
        self.mock_config_instance.getConfigValue.side_effect = self._get_config_value
        self.mock_config_instance.getConfigValueInt.side_effect = self._get_config_int
        self.mock_config_instance.getConfigValueFloat.side_effect = self._get_config_float
        self.apiKey = "dummy_api_key_from_config" # Simulate key coming from config
        # Default behavior for getEnvVar: return key if requested, else None
        self.mock_config_instance.getEnvVar.side_effect = lambda key, required=False, **kwargs: self.apiKey if key == 'GEMINI_API_KEY' else None


        # Instantiate the class under test AFTER patching dependencies
        from core.llm_interface import LLMInterface # Import here after patches
        self.LLMInterface = LLMInterface # Store class for potential direct tests
        self.interface = self.LLMInterface(configManager=self.mock_config_instance)

        # Reset api_configured flag which might persist across instantiations if not careful
        # (though __init__ should handle this)
        self.interface._api_configured = False


        # Test constants
        self.modelName = "gemini-test"
        self.instruction = "Refactor this code."
        self.fileContents: Dict[str, str] = {
            "main.py": "print('old code')",
            "utils.py": "# Utility functions"
        }

    # Helper to simulate ConfigManager behavior more dynamically
    def _get_config_value(self, section, key, fallback=None, required=False):
        # Allow overriding in specific tests using configure_mock
        config_map = {
            ('General', 'ExpectedOutputFormat'): 'json',
            ('General', 'DefaultLlmModel'): self.modelName,
        }
        value = config_map.get((section, key), fallback)
        if required and value is None:
             # Simulate ConfigurationError if required and not found
             from core.exceptions import ConfigurationError
             raise ConfigurationError(f"Required config missing: {section}/{key}")
        return value

    def _get_config_int(self, section, key, fallback=None, required=False):
        config_map = {
            ('LLM', 'MaxOutputTokens'): 8000,
            ('LLM', 'MaxTokensPerFileInPrompt'): 0, # Default disabled
            ('LLM', 'MaxCharsPerFileInPrompt'): 0, # Default disabled
        }
        value = config_map.get((section, key), fallback)
        if required and value is None:
             from core.exceptions import ConfigurationError
             raise ConfigurationError(f"Required config missing: {section}/{key}")
        # Simulate returning None if key exists but value is not int (simplification)
        return int(value) if value is not None else None


    def _get_config_float(self, section, key, fallback=None, required=False):
        config_map = {
            ('LLM', 'Temperature'): 0.6,
        }
        value = config_map.get((section, key), fallback)
        if required and value is None:
             from core.exceptions import ConfigurationError
             raise ConfigurationError(f"Required config missing: {section}/{key}")
        return float(value) if value is not None else None


    def tearDown(self: 'TestLLMInterface') -> None:
        """Ensure patches are stopped."""
        # Patching via decorator handles stopping automatically.
        pass

    # --- Test buildPrompt (Less likely to change significantly) ---

    def test_buildPrompt_structure_and_content(self: 'TestLLMInterface', mock_logger: MagicMock, mock_time: MagicMock, mock_ConfigManager: MagicMock, mock_genai_in_module: MagicMock) -> None:
        """Test the overall structure and content of the generated prompt."""
        prompt = self.interface.buildPrompt(self.instruction, self.fileContents)
        # Assertions remain largely the same, check key parts
        self.assertIn("## User Instruction:", prompt)
        self.assertIn(self.instruction, prompt)
        self.assertIn("--- START FILE: main.py ---", prompt)
        self.assertIn("print('old code')", prompt)
        self.assertIn("## Required Output Format:", prompt)
        self.assertIn("```json", prompt)

    # --- Test queryLlmApi (Focus of the changes) ---

    def test_queryLlmApi_success_firstTry(self: 'TestLLMInterface', mock_logger: MagicMock, mock_time: MagicMock, mock_ConfigManager: MagicMock, mock_genai_in_module: MagicMock) -> None:
        """Test a successful LLM API query on the first attempt."""
        response_text = '```json\n{"main.py": "print(\'new code\')"}\n```'
        mock_candidate = MockCandidate(
             finish_reason=MockFinishReason(name='STOP'), # Use mock enum instance
             content=MockContent(parts=[MockPart(text=response_text)])
        )
        mock_response = MockGenAIResponse(
             candidates=[mock_candidate],
             prompt_feedback=MockPromptFeedback() # Ensure prompt_feedback is not None
        )
        self.mock_model_instance.generate_content.return_value = mock_response

        prompt = "test prompt"
        # Call without apiKey argument
        result_text = self.interface.queryLlmApi(prompt, self.modelName)

        self.assertEqual(result_text, response_text)
        # Check configure was called (implicitly via _get_model_instance)
        self.mock_genai.configure.assert_called_once_with(api_key=self.apiKey)
        # Check generate_content call arguments
        self.mock_model_instance.generate_content.assert_called_once()
        args, kwargs = self.mock_model_instance.generate_content.call_args
        self.assertEqual(args[0], prompt) # First arg is the prompt
        gen_config = kwargs.get('generation_config')
        self.assertIsNotNone(gen_config)
        self.assertEqual(gen_config.temperature, 0.6) # Check configured value
        self.assertEqual(gen_config.max_output_tokens, 8000)
        self.assertEqual(kwargs.get('safety_settings'), []) # Default empty list from _load_safety_settings mock
        self.mock_time.sleep.assert_not_called()

    def test_queryLlmApi_success_onRetry(self: 'TestLLMInterface', mock_logger: MagicMock, mock_time: MagicMock, mock_ConfigManager: MagicMock, mock_genai_in_module: MagicMock) -> None:
        """Test a successful LLM API query after one retry."""
        response_text = '```json\n{"main.py": "print(\'new code\')"}\n```'
        mock_candidate_success = MockCandidate(
            finish_reason=MockFinishReason(name='STOP'),
            content=MockContent(parts=[MockPart(text=response_text)])
        )
        mock_response_success = MockGenAIResponse(
            candidates=[mock_candidate_success],
            prompt_feedback=MockPromptFeedback()
        )
        # Simulate a retryable API error on the first call
        # Use the mock GoogleAPIError we defined for testing purposes
        retryable_error = self.mock_google_exceptions.GoogleAPIError("Service Unavailable")

        self.mock_model_instance.generate_content.side_effect = [
            retryable_error,
            mock_response_success
        ]

        prompt = "test prompt"
        result_text = self.interface.queryLlmApi(prompt, self.modelName)

        self.assertEqual(result_text, response_text)
        self.mock_genai.configure.assert_called_once()
        self.assertEqual(self.mock_model_instance.generate_content.call_count, 2)
        # Check that sleep was called between retries
        self.mock_time.sleep.assert_called_once_with(RETRY_DELAY_SECONDS)

    def test_queryLlmApi_failure_allRetries(self: 'TestLLMInterface', mock_logger: MagicMock, mock_time: MagicMock, mock_ConfigManager: MagicMock, mock_genai_in_module: MagicMock) -> None:
        """Test LLM API query failure after all retries."""
        error_message = "Persistent API Error"
        # Simulate a retryable error that persists
        persistent_error = self.mock_google_exceptions.GoogleAPIError(error_message)
        self.mock_model_instance.generate_content.side_effect = persistent_error

        prompt = "test prompt"
        # Import locally to avoid potential circular dependency issues at module level
        from core.exceptions import LLMError
        # Check for the final wrapped LLMError
        expected_regex = f"LLM API query failed after {MAX_RETRIES + 1} attempts.*Last error \\(GoogleAPIErrorMock\\): {error_message}"
        with self.assertRaisesRegex(LLMError, expected_regex):
            self.interface.queryLlmApi(prompt, self.modelName)

        self.assertEqual(self.mock_model_instance.generate_content.call_count, MAX_RETRIES + 1)
        self.assertEqual(self.mock_time.sleep.call_count, MAX_RETRIES)


    def test_queryLlmApi_missingApiKey(self: 'TestLLMInterface', mock_logger: MagicMock, mock_time: MagicMock, mock_ConfigManager: MagicMock, mock_genai_in_module: MagicMock) -> None:
        """Test query attempt when API key is missing in config."""
        # Configure mock getEnvVar to simulate missing key
        self.mock_config_instance.getEnvVar.side_effect = lambda key, required=False, **kwargs: ConfigurationError(f"Required environment variable '{key}' is not set.") if key == 'GEMINI_API_KEY' and required else None

        prompt = "test prompt"
        from core.exceptions import ConfigurationError # Import locally
        with self.assertRaisesRegex(ConfigurationError, "Required environment variable 'GEMINI_API_KEY' is not set"):
             # Calling queryLlmApi should trigger _get_model_instance -> _configure_api_key
             self.interface.queryLlmApi(prompt, self.modelName)

        # Ensure configure and generate_content were not called
        self.mock_genai.configure.assert_not_called()
        self.mock_model_instance.generate_content.assert_not_called()

    def test_queryLlmApi_invalidApiKey_permissionDenied(self: 'TestLLMInterface', mock_logger: MagicMock, mock_time: MagicMock, mock_ConfigManager: MagicMock, mock_genai_in_module: MagicMock) -> None:
        """Test handling PermissionDenied (e.g., invalid API key) - should not retry."""
        error_message = "API key not valid"
        # Simulate PermissionDenied being raised by generate_content
        self.mock_model_instance.generate_content.side_effect = self.mock_google_exceptions.PermissionDenied(error_message)

        prompt = "test prompt"
        from core.exceptions import LLMError # Import locally
        # Expect LLMError wrapping the permission denied message
        with self.assertRaisesRegex(LLMError, f"LLM API key is likely invalid or lacks permissions.*{error_message}"):
            self.interface.queryLlmApi(prompt, self.modelName)

        # Should fail on the first attempt, no retries
        self.mock_model_instance.generate_content.assert_called_once()
        self.mock_time.sleep.assert_not_called()


    def test_queryLlmApi_emptyResponseText(self: 'TestLLMInterface', mock_logger: MagicMock, mock_time: MagicMock, mock_ConfigManager: MagicMock, mock_genai_in_module: MagicMock) -> None:
        """Test handling an API response that finishes STOP but has empty/whitespace text."""
        mock_candidate_empty = MockCandidate(
            finish_reason=MockFinishReason(name='STOP'),
            content=MockContent(parts=[]) # Simulate empty parts list
        )
        # Simulate response where .text property will return ""
        mock_response = MockGenAIResponse(
            candidates=[mock_candidate_empty],
            prompt_feedback=MockPromptFeedback()
        )
        self.mock_model_instance.generate_content.return_value = mock_response

        prompt = "test prompt"
        from core.exceptions import LLMError # Import locally
        # Updated llm_interface raises error immediately for empty response
        with self.assertRaisesRegex(LLMError, "LLM returned an empty or whitespace-only response"):
            self.interface.queryLlmApi(prompt, self.modelName)
        # Should fail on first attempt, no retry for this specific case
        self.mock_model_instance.generate_content.assert_called_once()
        self.mock_time.sleep.assert_not_called()


    def test_queryLlmApi_finishReasonOther(self: 'TestLLMInterface', mock_logger: MagicMock, mock_time: MagicMock, mock_ConfigManager: MagicMock, mock_genai_in_module: MagicMock) -> None:
        """Test handling an API response with finish reason OTHER."""
        mock_candidate_other = MockCandidate(finish_reason=MockFinishReason(name='OTHER'))
        # Simulate response where .text access will raise StopCandidateExceptionMock
        mock_response = MockGenAIResponse(
            candidates=[mock_candidate_other],
            prompt_feedback=MockPromptFeedback()
        )
        # Mock generate_content to return this response object
        self.mock_model_instance.generate_content.return_value = mock_response

        prompt = "test prompt"
        from core.exceptions import LLMError # Import locally
        # The code should catch StopCandidateException and raise LLMError
        with self.assertRaisesRegex(LLMError, "LLM generation stopped unexpectedly. Reason: OTHER"):
            self.interface.queryLlmApi(prompt, self.modelName)
        self.mock_model_instance.generate_content.assert_called_once() # No retry for OTHER


    def test_queryLlmApi_finishReasonSafety_candidate(self: 'TestLLMInterface', mock_logger: MagicMock, mock_time: MagicMock, mock_ConfigManager: MagicMock, mock_genai_in_module: MagicMock) -> None:
        """Test handling finish reason SAFETY (candidate block)."""
        mock_candidate_safety = MockCandidate(
            finish_reason=MockFinishReason(name='SAFETY'),
            safety_ratings=[MockSafetyRating('HATE_SPEECH', 'MEDIUM')]
        )
        mock_response = MockGenAIResponse(
            candidates=[mock_candidate_safety],
            prompt_feedback=MockPromptFeedback()
        )
        self.mock_model_instance.generate_content.return_value = mock_response

        prompt = "potentially unsafe prompt"
        from core.exceptions import LLMError
        # Check for the specific LLMError message for candidate safety block
        expected_regex = "LLM generation stopped unexpectedly. Reason: SAFETY.*Generation blocked due to safety settings.*Adjust safety settings"
        with self.assertRaisesRegex(LLMError, expected_regex):
             self.interface.queryLlmApi(prompt, self.modelName)
        self.mock_model_instance.generate_content.assert_called_once() # No retry for SAFETY
        # Check logger call includes safety details
        self.mock_logger.error.assert_any_call(" Candidate Safety: HATE_SPEECH=MEDIUM")


    def test_queryLlmApi_finishReasonSafety_prompt(self: 'TestLLMInterface', mock_logger: MagicMock, mock_time: MagicMock, mock_ConfigManager: MagicMock, mock_genai_in_module: MagicMock) -> None:
        """Test handling prompt blocked for safety."""
        mock_safety_feedback = MockPromptFeedback(
            block_reason=MockBlockReason(name='SAFETY'),
            safety_ratings=[MockSafetyRating('DANGEROUS_CONTENT', 'HIGH')]
        )
        mock_response = MockGenAIResponse(
            candidates=[], # No candidates when prompt blocked
            prompt_feedback=mock_safety_feedback
        )
        self.mock_model_instance.generate_content.return_value = mock_response

        prompt = "unsafe prompt"
        from core.exceptions import LLMError
        # Check for the specific LLMError message for prompt safety block
        expected_regex = "LLM query blocked due to safety settings in the prompt. Reason: SAFETY.*Adjust safety settings"
        with self.assertRaisesRegex(LLMError, expected_regex):
             self.interface.queryLlmApi(prompt, self.modelName)
        self.mock_model_instance.generate_content.assert_called_once() # No retry for prompt block
        # Check logger call includes prompt feedback details
        self.mock_logger.error.assert_any_call("LLM query blocked due to safety settings in the prompt. Reason: SAFETY. (Rating: DANGEROUS_CONTENT=HIGH)")


    # --- Tests previously skipped ---

    # These still rely on mocking the google.api_core exceptions correctly,
    # which is done via self.mock_google_exceptions for demonstration.
    # The side_effect of generate_content is set to raise these mock exceptions.

    def test_queryLlmApi_apiCallGenericError(self: 'TestLLMInterface', mock_logger: MagicMock, mock_time: MagicMock, mock_ConfigManager: MagicMock, mock_genai_in_module: MagicMock) -> None:
        """Test handling generic exceptions during API interaction after retries."""
        generic_error = Exception("Network Error")
        self.mock_model_instance.generate_content.side_effect = generic_error
        prompt = "test prompt"
        from core.exceptions import LLMError
        with self.assertRaisesRegex(LLMError, f"LLM API query failed after {MAX_RETRIES + 1} attempts.*Last error \\(Exception\\): Network Error"):
            self.interface.queryLlmApi(prompt, self.modelName)
        self.assertEqual(self.mock_model_instance.generate_content.call_count, MAX_RETRIES + 1)
        self.assertEqual(self.mock_time.sleep.call_count, MAX_RETRIES)


    def test_queryLlmApi_genaiSpecificError_ResourceExhausted(self: 'TestLLMInterface', mock_logger: MagicMock, mock_time: MagicMock, mock_ConfigManager: MagicMock, mock_genai_in_module: MagicMock) -> None:
        """Test handling a specific ResourceExhausted error after retries."""
        error_message = "Rate limit exceeded"
        # Simulate generate_content raising the mocked ResourceExhausted
        self.mock_model_instance.generate_content.side_effect = self.mock_google_exceptions.ResourceExhausted(error_message)

        prompt = "test prompt"
        from core.exceptions import LLMError
        # The code catches GoogleAPIError now, so the type in the message should reflect that if ResourceExhausted inherits from it
        # Assuming ResourceExhaustedMock inherits from GoogleAPIErrorMock for testing
        self.mock_google_exceptions.ResourceExhausted = type('ResourceExhaustedMock', (self.mock_google_exceptions.GoogleAPIError,), {})
        self.mock_model_instance.generate_content.side_effect = self.mock_google_exceptions.ResourceExhausted(error_message)

        expected_regex = f"LLM API query failed after {MAX_RETRIES + 1} attempts.*Last error \\(ResourceExhaustedMock\\): {error_message}"
        with self.assertRaisesRegex(LLMError, expected_regex):
            self.interface.queryLlmApi(prompt, self.modelName)
        self.assertEqual(self.mock_model_instance.generate_content.call_count, MAX_RETRIES + 1)
        self.assertEqual(self.mock_time.sleep.call_count, MAX_RETRIES)


if __name__ == '__main__':
    unittest.main()

# --- END: tests/test_llm_interface.py ---