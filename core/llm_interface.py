"""
Handles interaction with the Large Language Model (LLM) API.
Includes building prompts with token-based truncation (preferred) or
character-based truncation (fallback) and querying the API
(e.g., Google Gemini) with configurable safety settings and retry logic.
Includes logic for building a correction prompt.
"""
import logging
import time  # For retry delay

# Google API imports
import google.generativeai as genai
from google.generativeai.types import (
    GenerationConfig,
    PartDict,
    GenerateContentResponse,
    BlockedPromptException,
    StopCandidateException
)
from google.generativeai.types.safety_types import (
    HarmCategory,
    HarmBlockThreshold
)
from google.api_core import exceptions as google_exceptions

# Python standard library imports
from typing import Dict, Optional, List, Tuple, Union

# Local imports
from .exceptions import LLMError, ConfigurationError
from .config_manager import ConfigManager

logger: logging.Logger = logging.getLogger(__name__)

# Constants for retry logic
MAX_RETRIES = 1  # Number of retries (1 means try original + 1 retry = 2 attempts total)
RETRY_DELAY_SECONDS = 2  # Delay between retries

# Mappings from config string to enums
HARM_CATEGORY_MAP = {
    "HARM_CATEGORY_HARASSMENT": HarmCategory.HARM_CATEGORY_HARASSMENT,
    "HARM_CATEGORY_HATE_SPEECH": HarmCategory.HARM_CATEGORY_HATE_SPEECH,
    "HARM_CATEGORY_SEXUALLY_EXPLICIT": HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
    "HARM_CATEGORY_DANGEROUS_CONTENT": HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
}

HARM_THRESHOLD_MAP = {
    "BLOCK_NONE": HarmBlockThreshold.BLOCK_NONE,
    "BLOCK_LOW_AND_ABOVE": HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
    "BLOCK_MEDIUM_AND_ABOVE": HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    "BLOCK_ONLY_HIGH": HarmBlockThreshold.BLOCK_ONLY_HIGH,
}


class LLMInterface:
    """
    Provides methods to build prompts and interact with an LLM API.
    Includes configuration for generation parameters, safety settings,
    token/character prompt truncation, and retry logic.
    """
    _configManager: ConfigManager  # Type hint for clarity
    _model_instance_cache: Dict[str, genai.GenerativeModel] = {}  # Cache models per name
    _api_configured: bool = False  # Track if API key has been configured in this instance

    def __init__(self: 'LLMInterface', configManager: Optional[ConfigManager] = None) -> None:
        """ Initialises the LLMInterface. """
        self._configManager = configManager if configManager is not None else ConfigManager()
        self._model_instance_cache = {}  # Clear cache on init
        self._api_configured = False  # Reset flag on init
        logger.debug("LLMInterface initialised.")

    def _configure_api_key(self: 'LLMInterface') -> None:
        """Configures the genai API key if not already done."""
        if self._api_configured:
            return

        try:
            apiKey = self._configManager.getEnvVar('GEMINI_API_KEY', required=True)
            genai.configure(api_key=apiKey)
            self._api_configured = True
            logger.debug("Configured google-generativeai API key.")
        except ConfigurationError as e:
            logger.error(f"API Key configuration failed: {e}")
            raise e

    def _get_model_instance(self: 'LLMInterface', modelName: str, configure_api: bool = True) -> Optional[genai.GenerativeModel]:
        """ Instantiates or retrieves a cached GenerativeModel instance. """
        try:
            if configure_api:
                self._configure_api_key()
            if modelName in self._model_instance_cache:
                return self._model_instance_cache[modelName]
            try:
                model = genai.GenerativeModel(modelName)
                self._model_instance_cache[modelName] = model
                logger.info(f"Instantiated GenerativeModel: '{modelName}'")
                return model
            except ValueError as e:
                errMsg = f"Failed to instantiate GenerativeModel '{modelName}': {e}"
                logger.error(errMsg)
                raise LLMError(errMsg) from e
        except ConfigurationError as e:
            raise e
        except Exception as e:
            errMsg = f"Failed to instantiate GenerativeModel '{modelName}': {e}"
            logger.error(errMsg, exc_info=True)
            raise LLMError(errMsg) from e

    def _count_tokens(self: 'LLMInterface', modelName: str, content: Union[str, List[Union[str, PartDict]]]) -> Optional[int]:
        """ Counts tokens for the given content using the specified model. """
        if not content:
            logger.debug(
                f"Content provided to _count_tokens for model '{modelName}' "
                "is empty. Returning 0 tokens."
            )
            return 0

        try:
            model = self._get_model_instance(modelName, configure_api=True)
            if not model:
                logger.error(f"Model instance '{modelName}' unavailable for token counting.")
                return None

            response = model.count_tokens(content)
            return response.total_tokens

        except ConfigurationError as e:
            logger.error(f"Configuration error during token counting setup: {e}")
            return None

        except google_exceptions.PermissionDenied as e:
            logger.error(
                f"Permission denied counting tokens for model '{modelName}'. "
                f"Check API key validity/permissions: {e}",
                exc_info=False
            )
            return None

        except google_exceptions.GoogleAPIError as e:
            logger.error(
                f"API error counting tokens for model '{modelName}': {e}",
                exc_info=False
            )
            return None

        except ValueError as e:
            logger.error(
                f"Invalid value error counting tokens for model '{modelName}': {e}",
                exc_info=False
            )
            # Special handling for empty content error
            if "content' argument must not be empty" in str(e):
                logger.warning(
                    "Caught empty content ValueError in _count_tokens despite check; "
                    "returning 0."
                )
                return 0
            return None

        except Exception as e:
            logger.error(
                f"Unexpected error counting tokens for model '{modelName}': {e}",
                exc_info=True
            )
            return None

    def _truncate_content_by_tokens(self: 'LLMInterface', modelName: str, content: str, max_tokens: int) -> Tuple[str, Optional[int], int]:
        """ Truncates content to fit within a maximum token limit using binary search. """
        initial_tokens = self._count_tokens(modelName, content)
        if initial_tokens is None:
            logger.warning(f"Token counting failed for content (length {len(content)}). Cannot perform token-based truncation.")
            return content, None, 0
        if initial_tokens <= max_tokens:
            return content, initial_tokens, 0
        logger.warning(f"Content (length {len(content)}, tokens ~{initial_tokens}) exceeds token limit ({max_tokens}). Truncating...")
        low, high, best_len, best_token_count = 0, len(content), 0, Optional[int]
        max_iterations, iteration, token_counting_failed_during_search = 20, 0, False
        while low <= high and iteration < max_iterations:
            iteration += 1
            mid = (low + high) // 2
            if mid == 0:
                break
            truncated_substr = content[:mid]
            if not truncated_substr:
                current_tokens = 0
            else:
                current_tokens = self._count_tokens(modelName, truncated_substr)
            if current_tokens is None:
                logger.error("Token counting failed during truncation search. Stopping search.")
                token_counting_failed_during_search = True
                break
            if current_tokens <= max_tokens:
                if mid > best_len:
                    best_len, best_token_count = mid, current_tokens
                low = mid + 1
            else:
                high = mid - 1
        if iteration >= max_iterations:
            logger.warning("Truncation search reached max iterations. Using best length found.")
        if token_counting_failed_during_search:
            if best_len > 0:
                omitted = len(content) - best_len
                logger.warning(f"Falling back to truncated content with length {best_len} (~{best_token_count} tokens) due to token counting error during search.")
                return content[:best_len], best_token_count, omitted
            else:
                logger.error("Could not find any valid truncation point before token counting failed during search.")
                return "", None, len(content)
        if best_len == 0 and initial_tokens > max_tokens:
            logger.error(f"Could not truncate content below the token limit of {max_tokens}. Returning empty string.")
            return "", None, len(content)
        omitted_chars = len(content) - best_len
        truncated_result = content[:best_len]
        if omitted_chars > 0:
            logger.warning(f"Truncated content to {best_len} characters (~{best_token_count} tokens) to meet limit of {max_tokens} tokens.")
        return truncated_result, best_token_count, omitted_chars

    def _load_safety_settings(self: 'LLMInterface') -> List[Dict[str, Union[HarmCategory, HarmBlockThreshold]]]:
        """ Loads safety settings from config, returning List[Dict] for API. """
        safety_settings: List[Dict[str, Union[HarmCategory, HarmBlockThreshold]]] = []
        config_keys = [
            'HarmCategoryHarassmentThreshold',
            'HarmCategoryHateSpeechThreshold',
            'HarmCategorySexuallyExplicitThreshold',
            'HarmCategoryDangerousContentThreshold'
        ]
        harm_category_name_map = {
            'HarmCategoryHarassmentThreshold': "HARM_CATEGORY_HARASSMENT",
            'HarmCategoryHateSpeechThreshold': "HARM_CATEGORY_HATE_SPEECH",
            'HarmCategorySexuallyExplicitThreshold': "HARM_CATEGORY_SEXUALLY_EXPLICIT",
            'HarmCategoryDangerousContentThreshold': "HARM_CATEGORY_DANGEROUS_CONTENT"
        }
        for config_key in config_keys:
            try:
                threshold_str = self._configManager.getConfigValue('LLM', config_key, required=False)
                if threshold_str is not None and threshold_str.strip():
                    harm_category_str = harm_category_name_map.get(config_key)
                    category_enum = HARM_CATEGORY_MAP.get(harm_category_str)
                    if category_enum is None:
                        logger.warning(f"Invalid harm category name '{harm_category_str}' derived from config key '{config_key}'. Skipping.")
                        continue
                    threshold_enum = HARM_THRESHOLD_MAP.get(threshold_str.strip().upper())
                    if threshold_enum is None:
                        logger.warning(f"Invalid safety threshold value '{threshold_str}' for '{config_key}'. Must be one of {list(HARM_THRESHOLD_MAP.keys())}. Skipping.")
                        continue
                    setting_dict: Dict[str, Union[HarmCategory, HarmBlockThreshold]] = {
                        "category": category_enum,
                        "threshold": threshold_enum
                    }
                    safety_settings.append(setting_dict)
                    logger.debug(f"Loaded safety setting: {harm_category_str} = {threshold_str}")
                else:
                    logger.debug(f"Safety setting '{config_key}' not found or empty in config. Using API default for this category.")
            except ConfigurationError as e:
                logger.warning(f"Error loading configuration for safety setting '{config_key}': {e}. Skipping.")
            except Exception as e:
                logger.error(f"Error processing safety setting dictionary for {config_key} with threshold '{threshold_str}': {e}", exc_info=True)
        if not safety_settings:
            logger.info("No valid safety settings found in configuration. Using Google Gemini API defaults.")
        else:
            logger.info(f"Loaded {len(safety_settings)} safety settings from configuration.")
        return safety_settings

    def buildPrompt(self: 'LLMInterface', instruction: str, fileContents: Dict[str, str]) -> str:
        """ Constructs the main prompt including instructions, context, format specs, and rules. """
        logger.debug(f"Building LLM prompt. Instruction length: {len(instruction)}, Files: {len(fileContents)}")
        truncation_applied = False
        overall_truncation_type = ""
        truncation_details = []
        token_counting_failed_overall = False
        try:
            # Configuration loading
            modelName = self._configManager.getConfigValue('General', 'DefaultLlmModel', fallback='gemini-1.5-flash-latest')
            if not isinstance(modelName, str) or not modelName.strip():
                modelName = 'gemini-1.5-flash-latest'
            max_tokens_per_file_config = self._configManager.getConfigValueInt('LLM', 'MaxTokensPerFileInPrompt', fallback=262144)
            max_chars_per_file_config = self._configManager.getConfigValueInt('LLM', 'MaxCharsPerFileInPrompt', fallback=262144)
            max_tokens_per_file = max_tokens_per_file_config if max_tokens_per_file_config is not None and max_tokens_per_file_config > 0 else 0
            max_chars_per_file = max_chars_per_file_config if max_chars_per_file_config is not None and max_chars_per_file_config > 0 else 0
            use_token_truncation = max_tokens_per_file > 0
            use_char_truncation = max_chars_per_file > 0
            if use_token_truncation:
                logger.debug(f"Token-based truncation enabled (MaxTokensPerFileInPrompt={max_tokens_per_file}). Checking API key...")
                self._get_model_instance(modelName, configure_api=True)
            elif use_char_truncation:
                logger.debug(f"Character-based truncation enabled (MaxCharsPerFileInPrompt={max_chars_per_file}). Token truncation disabled.")
            else:
                logger.debug("Both token and character truncation disabled.")
            output_format = self._configManager.getConfigValue('General', 'ExpectedOutputFormat', fallback='json')
            if not isinstance(output_format, str) or not output_format.strip():
                output_format = 'json'
            output_format_upper = output_format.upper()
        except (ConfigurationError, LLMError) as e:
            logger.error(f"Setup error preparing for prompt build: {e}")
            raise e
        except Exception as e:
            logger.error(f"Unexpected error reading configuration for prompt build: {e}", exc_info=True)
            raise ConfigurationError(f"Unexpected error reading configuration: {e}") from e

        promptLines: List[str] = []
        # User Instruction
        promptLines.append("## User Instruction:")
        promptLines.append(instruction)
        promptLines.append("\n")
        # File Context with Truncation
        promptLines.append("## Code Context:")
        if fileContents:
            promptLines.append("The user instruction applies to the following file(s):")
            for filePath, content in fileContents.items():
                promptLines.append(f"--- START FILE: {filePath} ---")
                final_content = content
                omitted_count = 0
                applied_trunc_type = ""
                final_tokens: Optional[int] = None
                token_count_info = ""
                file_token_counting_failed = False
                if use_token_truncation:
                    truncated_tuple = self._truncate_content_by_tokens(modelName, content, max_tokens_per_file)
                    final_content, final_tokens, omitted_chars = truncated_tuple
                    if final_tokens is None:
                        file_token_counting_failed = True
                        token_counting_failed_overall = True
                        token_count_info = " (Token count unavailable)"
                    else:
                        token_count_info = f" (~{final_tokens} tokens)"
                    if omitted_chars > 0:
                        truncation_applied = True
                        applied_trunc_type = "token"
                        omitted_count = omitted_chars
                        truncation_details.append((filePath, applied_trunc_type, omitted_count))
                    if not overall_truncation_type:
                        overall_truncation_type = "token"
                    elif overall_truncation_type == "character":
                        overall_truncation_type = "mixed"
                should_apply_char_trunc = (not use_token_truncation or file_token_counting_failed) and use_char_truncation and len(final_content) > max_chars_per_file
                if should_apply_char_trunc:
                    original_len_before_char_trunc = len(final_content)
                    final_content = final_content[:max_chars_per_file]
                    omitted_count = original_len_before_char_trunc - max_chars_per_file
                    applied_trunc_type = "character"
                    truncation_applied = True
                    logger.warning(f"Applied fallback character truncation to '{filePath}' (omitted {omitted_count} chars).")
                    token_count_info = ""
                    existing_detail_index = next((i for i, d in enumerate(truncation_details) if d[0] == filePath), -1)
                    if existing_detail_index != -1:
                        truncation_details[existing_detail_index] = (filePath, applied_trunc_type, omitted_count)
                    else:
                        truncation_details.append((filePath, applied_trunc_type, omitted_count))
                    if not overall_truncation_type:
                        overall_truncation_type = "character"
                    elif overall_truncation_type == "token":
                        overall_truncation_type = "mixed"
                promptLines.append(final_content)
                if applied_trunc_type:
                    unit = "characters"
                    promptLines.append(f"\n... [TRUNCATED by {applied_trunc_type} limit - {omitted_count} {unit} omitted] ...")
                promptLines.append(f"--- END FILE: {filePath} ---{token_count_info}")
                promptLines.append("")
        else:
            promptLines.append("No specific file context was provided.")
            promptLines.append("\n")

        # Output Format Specification (Strengthened rules)
        promptLines.append("## Required Output Format:")
        promptLines.append(f"Based *only* on the user instruction and the provided file contexts, generate the necessary code modifications.")
        promptLines.append(f"CRITICAL: Provide the **complete, updated content** for **all modified or newly created files** as a single, syntactically perfect {output_format_upper} object.")
        promptLines.append(f"CRITICAL: This {output_format_upper} object MUST be enclosed within a SINGLE markdown code block using the tag '```{output_format}'.")
        promptLines.append(f"The {output_format_upper} object MUST map the relative file path (as a string key) to the full updated file content (as a string value).")
        promptLines.append(f"\nExample {output_format_upper} structure:")
        promptLines.append(f"```{output_format}")
        promptLines.append("{")
        promptLines.append("  \"path/to/updated_file1.py\": \"# Updated Python code\\nprint('Hello')\",")
        promptLines.append("  \"path/to/new_file.txt\": \"This is a new file created by the LLM.\",")
        promptLines.append("  \"another/path/service.yaml\": \"apiVersion: v1\\nkind: Service\\nmetadata:\\n  name: updated-service\\n...\"")
        promptLines.append("}")
        promptLines.append("```")
        promptLines.append("\n**VERY Important Rules:**")
        promptLines.append(f"* **Self-Correction:** Before outputting, double-check that the generated {output_format_upper} object is 100% valid according to {output_format_upper} syntax rules (commas, quotes, brackets, braces).")
        promptLines.append("* Only include files that require modification or are newly created based *directly* on the instruction.")
        promptLines.append("* If a file needs changes, include its *entire* final content in the value, not just the changed lines.")
        promptLines.append(f"* **CRITICAL:** Ensure the {output_format_upper} is perfectly valid and enclosed in **one** markdown code block (```{output_format} ... ```).")
        promptLines.append(f"* If **no files** need modification or creation based on the instruction, return ONLY an empty {output_format_upper} object: `{{}}` within the code block.")
        promptLines.append(f"* **CRITICAL:** All string values within the {output_format_upper}, especially code content, MUST have special characters (like quotes `\"`, backslashes `\\\\`, newlines `\\n`, etc.) correctly escaped according to {output_format_upper} rules.")
        promptLines.append(f"* **CRITICAL:** The final output MUST contain ONLY the single markdown code block with the {output_format_upper} object. Absolutely NO text, explanations, apologies, or any other content before or after the code block.")

        # Truncation Note
        if truncation_applied:
            if overall_truncation_type == "token":
                limit_note = f"token limit (~{max_tokens_per_file} tokens)"
            elif overall_truncation_type == "character":
                limit_note = f"character limit ({max_chars_per_file} chars)"
            elif overall_truncation_type == "mixed":
                limit_note = f"token (~{max_tokens_per_file}) or character ({max_chars_per_file}) limit"
            else:
                limit_note = "configured limit"
            if token_counting_failed_overall and "token" in limit_note:
                limit_note += " (token counting may have failed for some files)"
            promptLines.append("\n* Note: Content for some files provided above may have been truncated due to the " + limit_note + ".")
            promptLines.append("  Files truncated:")
            for fname, ttype, omitted in truncation_details:
                unit = "chars"
                promptLines.append(f"    - {fname} (by {ttype}, {omitted} {unit} omitted)")

        fullPrompt: str = "\n".join(promptLines)
        logger.debug(f"Generated prompt length (characters): {len(fullPrompt)}")
        return fullPrompt

    def build_correction_prompt(
        self: 'LLMInterface',
        original_bad_output: str,
        original_instruction: str,
        expected_format: str
    ) -> str:
        """
        Constructs a prompt asking the LLM to correct its previous invalid output.

        Args:
            original_bad_output (str): The previous, invalid response from the LLM.
            original_instruction (str): The original user instruction (for context).
            expected_format (str): The required output format (e.g., 'json', 'yaml').

        Returns:
            str: The correction prompt.
        """
        logger.debug("Building correction prompt.")
        output_format_upper = expected_format.upper()
        promptLines: List[str] = []

        promptLines.append(f"Your previous response did not adhere to the required {output_format_upper} format or contained syntax errors.")
        promptLines.append("CRITICAL: Please analyse your previous output below, identify the errors, and provide a corrected response.")
        promptLines.append(f"The corrected response MUST be a single, syntactically perfect {output_format_upper} object, mapping file paths to their full content.")
        promptLines.append(f"This {output_format_upper} object MUST be enclosed within a SINGLE markdown code block (```{expected_format} ... ```).")
        promptLines.append("Ensure all rules regarding structure, escaping, and content from the original request are followed.")
        promptLines.append("Do NOT include any explanations or text outside the final code block.")

        promptLines.append("\n## Original User Instruction (for context):")
        promptLines.append(original_instruction)

        promptLines.append("\n## Previous Incorrect Output (analyse and fix this):")
        # Include the previous bad output verbatim, maybe within its own block for clarity?
        # Putting it raw might be better for the LLM to see exactly what it produced.
        promptLines.append(original_bad_output)

        promptLines.append(f"\n## Corrected Output (Provide ONLY the valid ```{expected_format} ... ``` block below):")

        fullPrompt: str = "\n".join(promptLines)
        logger.debug(f"Generated correction prompt length (characters): {len(fullPrompt)}")
        return fullPrompt

    def queryLlmApi(
        self: 'LLMInterface',
        prompt: str,
        modelName: Optional[str] = None,
        override_temperature: Optional[float] = None
    ) -> str:
        """
        Sends the prompt to the specified LLM API (Google Gemini) and returns the response.

        Args:
            prompt (str): The fully constructed prompt to send.
            modelName (Optional[str]): The specific LLM model to use (e.g., "gemini-pro").
                                   If None, the default from config is used.
            override_temperature (Optional[float]): If provided, uses this temperature instead
                                                of the value from config.

        Returns:
            str: The text response received from the LLM.

        Raises:
            ConfigurationError: If the API key is missing or other configuration is invalid.
            LLMError: If there are issues communicating with the API.
        """
        try:
            resolved_model_name = modelName or self._configManager.getConfigValue(
                'General',
                'DefaultLlmModel',
                fallback='gemini-1.5-flash-latest'
            )

            if not isinstance(resolved_model_name, str) or not resolved_model_name.strip():
                resolved_model_name = 'gemini-1.5-flash-latest'

            model = self._get_model_instance(resolved_model_name, configure_api=True)
            if not model:
                raise LLMError(f"Failed to get model instance for '{resolved_model_name}'")

            logger.debug(f"Using model instance: '{resolved_model_name}'")

            # Handle Temperature Override
            if override_temperature is not None:
                temperature = override_temperature
                logger.info(f"Using overridden temperature: {temperature}")
            else:
                temp_config = self._configManager.getConfigValueFloat(
                    'LLM',
                    'Temperature',
                    fallback=None
                )
                temperature = temp_config if temp_config is not None else 0.7

            max_tokens_config = self._configManager.getConfigValueInt('LLM', 'MaxOutputTokens', fallback=None)
            max_output_tokens = max_tokens_config if max_tokens_config is not None else 8192
            safety_settings: List[Dict[str, Union[HarmCategory, HarmBlockThreshold]]] = self._load_safety_settings()
            if not (0.0 <= temperature <= 1.0):
                temperature = max(0.0, min(1.0, temperature))
            if max_output_tokens is not None and max_output_tokens <= 0:
                max_output_tokens = None
        except (ConfigurationError, LLMError) as e:
            logger.error(f"Setup error preparing for LLM query: {e}")
            raise e
        except Exception as e:
            logger.error(f"Unexpected error reading configuration for LLM query: {e}", exc_info=True)
            raise ConfigurationError(f"Unexpected error reading configuration: {e}") from e

        logger.info(f"Querying LLM model '{resolved_model_name}'...")
        last_exception: Optional[Exception] = None

        for attempt in range(MAX_RETRIES + 1):
            try:
                gen_config_args = {'temperature': temperature}
                if max_output_tokens is not None:
                    gen_config_args['max_output_tokens'] = max_output_tokens
                generation_config = GenerationConfig(**gen_config_args)
                logger.debug(f"Sending prompt (length chars: {len(prompt)}) to model '{resolved_model_name}' (Attempt {attempt + 1}/{MAX_RETRIES + 1})...")
                logger.debug(f"Using GenerationConfig: {gen_config_args}")  # Log effective config
                logger.debug(f"Using SafetySettings: {safety_settings if safety_settings else 'API Defaults'}")
                response: GenerateContentResponse = model.generate_content(
                    prompt,
                    generation_config=generation_config,
                    safety_settings=safety_settings,
                    request_options={'timeout': 300}
                )
                llmOutput: str = response.text  # This raises exceptions if blocked/stopped
                if not llmOutput.strip():
                    # Check if response finished normally despite empty text
                    finish_reason = "UNKNOWN"
                    if response.candidates and response.candidates[0].finish_reason:
                        finish_reason = response.candidates[0].finish_reason.name
                    if finish_reason == 'STOP':
                        errMsg = "LLM returned an empty or whitespace-only response despite finishing normally (STOP)."
                        logger.error(errMsg)
                        # Decide whether to treat this as an error or return empty string
                        # Raising error seems more robust for this application's expected output
                        raise LLMError(errMsg)
                    else:
                         # If finish reason wasn't STOP, it's likely handled by StopCandidateException
                         # Log a warning here for unexpected state
                         logger.warning(f"LLM response text empty, finish reason: {finish_reason}. Exception expected.")
                         # Let StopCandidateException handle it if applicable, otherwise generic error
                         raise LLMError(f"LLM returned empty response with unexpected finish reason: {finish_reason}")

                logger.info(f"LLM query successful on attempt {attempt + 1}. Response length: {len(llmOutput)}")
                return llmOutput
            except ConfigurationError as e:
                raise e  # Propagate config errors immediately
            except BlockedPromptException as e:  # Handle prompt safety blocks (non-retryable)
                errMsg = f"LLM query blocked due to safety settings in the prompt."
                prompt_feedback_details = ""
                if hasattr(e, 'response') and hasattr(e.response, 'prompt_feedback'):
                    pf = e.response.prompt_feedback
                    if pf:
                        reason = getattr(pf, 'block_reason_message', '')
                        reason_enum = getattr(pf, 'block_reason', None)
                        if not reason and reason_enum:
                            reason = getattr(reason_enum, 'name', 'UNKNOWN')
                        prompt_feedback_details += f" Reason: {reason if reason else 'Not Specified'} (Rating:"
                        if pf.safety_ratings:
                            ratings_str = ", ".join([
                                f"{getattr(r.category, 'name', 'UNK')}="
                                f"{getattr(r.probability, 'name', 'UNK')}"
                                for r in pf.safety_ratings])
                            prompt_feedback_details += f" {ratings_str})".strip()
                        else:
                            prompt_feedback_details += " No ratings)"
                logger.error(errMsg + prompt_feedback_details)
                raise LLMError(errMsg + " Adjust safety settings or prompt content.") from e
            except StopCandidateException as e:  # Handle candidate blocks/stops (non-retryable)
                finish_reason_name = "UNKNOWN"
                candidate = None
                if hasattr(e, 'args') and e.args:
                    resp_or_candidate = e.args[0]
                    if isinstance(resp_or_candidate, GenerateContentResponse):
                        candidate = resp_or_candidate.candidates[0] if resp_or_candidate.candidates else None
                    elif hasattr(resp_or_candidate, 'finish_reason'):
                        candidate = resp_or_candidate
                if candidate and hasattr(candidate, 'finish_reason'):
                    try:
                        finish_reason_name = candidate.finish_reason.name
                    except AttributeError:
                        finish_reason_name = str(candidate.finish_reason)
                errMsg = f"LLM generation stopped unexpectedly. Reason: {finish_reason_name}."
                logger.error(errMsg)
                safety_details = ""
                if candidate and hasattr(candidate, 'safety_ratings') and candidate.safety_ratings:
                    safety_details += " Candidate Safety:"
                    for rating in candidate.safety_ratings:
                        cat_name = getattr(rating.category, 'name', 'UNKNOWN')
                        prob_name = getattr(rating.probability, 'name', 'UNKNOWN')
                        safety_details += f" {cat_name}={prob_name}"
                    logger.error(safety_details)
                finalErrMsg = errMsg
                if finish_reason_name == "SAFETY":
                    finalErrMsg += " Generation blocked due to safety settings." + safety_details + " Adjust safety settings or prompt content."
                elif finish_reason_name == "MAX_TOKENS":
                    finalErrMsg += " Maximum output tokens reached."
                elif finish_reason_name == "RECITATION":
                    finalErrMsg += " Response blocked due to recitation policy."
                elif finish_reason_name == "OTHER":
                    finalErrMsg += " Generation stopped for an unspecified reason by the API."
                raise LLMError(finalErrMsg) from e
            except google_exceptions.PermissionDenied as e:
                errMsg = f"LLM API key is likely invalid or lacks permissions: {e}"
                logger.error(errMsg, exc_info=False)
                raise LLMError(errMsg) from e  # Non-retryable
            except google_exceptions.InvalidArgument as e:  # Non-retryable
                if "API key not valid" in str(e):
                    errMsg = f"LLM API key not valid. Please pass a valid API key via GEMINI_API_KEY environment variable."
                    logger.error(errMsg)
                    raise ConfigurationError(errMsg) from e
                else:
                    errMsg = f"LLM API query failed (Invalid Argument - check model name/API parameters?): {e}"
                    logger.error(errMsg, exc_info=False)
                    raise LLMError(errMsg) from e
            except google_exceptions.GoogleAPIError as e:
                errorType = type(e).__name__
                logger.warning(f"LLM API query attempt {attempt + 1} failed ({errorType}): {e}", exc_info=False)
                last_exception = e  # Potentially retryable
            except Exception as e:
                errorType = type(e).__name__
                logger.warning(f"LLM API query attempt {attempt + 1} failed ({errorType}): {e}", exc_info=False)
                last_exception = e  # Potentially retryable

            if last_exception and attempt < MAX_RETRIES:
                logger.info(f"Retrying in {RETRY_DELAY_SECONDS} seconds...")
                time.sleep(RETRY_DELAY_SECONDS)
                last_exception = None
            elif last_exception:
                break  # Exit loop if last attempt failed

        if last_exception:
            errorType = type(last_exception).__name__
            finalErrMsg = f"LLM API query failed after {MAX_RETRIES + 1} attempts. Last error ({errorType}): {last_exception}"
            logger.error(finalErrMsg, exc_info=bool(last_exception))
        else:
            finalErrMsg = f"LLM API query failed after {MAX_RETRIES + 1} attempts for an unexpected reason (no final exception recorded)."
            logger.error(finalErrMsg)
        raise LLMError(finalErrMsg) from last_exception
