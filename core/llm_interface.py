# Updated Codebase/core/llm_interface.py
# --- START: core/llm_interface.py ---
# core/llm_interface.py
"""
Handles interaction with the Large Language Model (LLM) API.
Includes building prompts with token-based truncation (preferred) or
character-based truncation (fallback) and querying the API
(e.g., Google Gemini) with configurable safety settings and retry logic.
"""
import logging
import time # For retry delay
import google.generativeai as genai # Use google-generativeai library
# Import specific types for clarity and type checking
# FIX: Correct import based on google-generativeai v0.7.1 library structure if needed
# Assuming SafetySetting is directly under types for this version. If not, adjust.
# Add BlockedPromptException, StopCandidateException
from google.generativeai.types import (
    GenerationConfig, SafetySetting, HarmCategory, HarmBlockThreshold,
    ContentDict, PartDict, GenerateContentResponse, BlockedPromptException,
    StopCandidateException
)
# Verify the import path for SafetySetting based on your installed google-generativeai version.
# If it causes ImportError, find its correct location (e.g., google.generativeai.types.safety_types ?)

from google.api_core import exceptions as google_exceptions # For specific API errors

from typing import Dict, Optional, Any, List, Tuple

from .exceptions import LLMError, ConfigurationError
from .config_manager import ConfigManager # Assuming ConfigManager is accessible or passed

logger: logging.Logger = logging.getLogger(__name__)

# Constants for retry logic
MAX_RETRIES = 1 # Number of retries (1 means try original + 1 retry = 2 attempts total)
RETRY_DELAY_SECONDS = 2 # Delay between retries

# Mapping from config string to HarmCategory enum
HARM_CATEGORY_MAP = {
    "HARM_CATEGORY_HARASSMENT": HarmCategory.HARM_CATEGORY_HARASSMENT,
    "HARM_CATEGORY_HATE_SPEECH": HarmCategory.HARM_CATEGORY_HATE_SPEECH,
    "HARM_CATEGORY_SEXUALLY_EXPLICIT": HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
    "HARM_CATEGORY_DANGEROUS_CONTENT": HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
}

# Mapping from config string to HarmBlockThreshold enum
HARM_THRESHOLD_MAP = {
    "BLOCK_NONE": HarmBlockThreshold.BLOCK_NONE,
    "BLOCK_LOW_AND_ABOVE": HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
    "BLOCK_MEDIUM_AND_ABOVE": HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    "BLOCK_ONLY_HIGH": HarmBlockThreshold.BLOCK_ONLY_HIGH,
    # Add aliases if needed, e.g., "MEDIUM": HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE
}


class LLMInterface:
    """
    Provides methods to build prompts and interact with an LLM API.
    Includes configuration for generation parameters, safety settings,
    token/character prompt truncation, and retry logic.
    """
    _configManager: ConfigManager # Type hint for clarity
    _model_instance_cache: Dict[str, genai.GenerativeModel] = {} # Cache models per name
    _api_configured: bool = False # Track if API key has been configured in this instance

    def __init__(self: 'LLMInterface', configManager: Optional[ConfigManager] = None) -> None:
        """
        Initialises the LLMInterface.

        Args:
            configManager (Optional[ConfigManager]): The application's configuration manager instance.
                                                     Used to fetch LLM settings. If None, a default
                                                     ConfigManager will be instantiated and used.
        """
        # Ensure configManager is always assigned
        self._configManager = configManager if configManager is not None else ConfigManager()
        self._model_instance_cache = {} # Clear cache on init
        self._api_configured = False # Reset flag on init
        logger.debug("LLMInterface initialised.")

    def _configure_api_key(self: 'LLMInterface') -> None:
        """Configures the genai API key if not already done."""
        if self._api_configured:
            return
        try:
            # Use ConfigManager to get the key, ensures consistency
            apiKey = self._configManager.getEnvVar('GEMINI_API_KEY', required=True)
            # The required=True in getEnvVar should raise ConfigurationError if missing
            # No need to check for emptiness here if getEnvVar works as expected.
            genai.configure(api_key=apiKey)
            self._api_configured = True # Mark as configured
            logger.debug(f"Configured google-generativeai API key.")
        except ConfigurationError as e:
            logger.error(f"API Key configuration failed: {e}")
            raise e # Re-raise config errors

    def _get_model_instance(self: 'LLMInterface', modelName: str, configure_api: bool = True) -> Optional[genai.GenerativeModel]:
        """
        Instantiates or retrieves a cached GenerativeModel instance.
        Handles API key configuration if requested.

        Args:
            modelName (str): The name of the model to get/create.
            configure_api (bool): Whether to ensure genai.configure(api_key=...) is called. Defaults to True.

        Returns:
            Optional[genai.GenerativeModel]: The model instance, or None if API key is missing/invalid.

        Raises:
            ConfigurationError: If API key is missing and configure_api is True.
            LLMError: If model instantiation fails for other reasons.
        """
        try:
            # Ensure API key is configured if requested
            if configure_api:
                self._configure_api_key() # Will raise ConfigurationError if key missing

            # Return cached model if available
            if modelName in self._model_instance_cache:
                return self._model_instance_cache[modelName]

            # Instantiate the model if not cached
            model = genai.GenerativeModel(modelName)
            self._model_instance_cache[modelName] = model
            logger.info(f"Instantiated GenerativeModel: '{modelName}'")
            return model

        except ConfigurationError as e: # Re-raise config errors
            raise e
        except Exception as e:
            # Catch potential model instantiation errors (e.g., invalid model name)
            errMsg = f"Failed to instantiate GenerativeModel '{modelName}': {e}"
            logger.error(errMsg, exc_info=True)
            # Wrap other exceptions in LLMError
            raise LLMError(errMsg) from e


    def _count_tokens(self: 'LLMInterface', modelName: str, content: str | List[str | PartDict]) -> Optional[int]:
        """
        Counts tokens for the given content using the specified model.
        Handles potential API errors during token counting.

        Args:
            modelName (str): The model name to use for counting (must match generation model).
            content (str | List[str | PartDict]): The content to count tokens for.

        Returns:
            Optional[int]: The total token count, or None if counting fails.
        """
        try:
            # Ensure API key is configured before attempting to count tokens
            # Call _get_model_instance which handles configuration via _configure_api_key
            model = self._get_model_instance(modelName, configure_api=True)
            # If model is None here, _get_model_instance would have raised ConfigurationError
            if not model: # Defensive check
                 logger.error(f"Model instance '{modelName}' unavailable for token counting.")
                 return None

            # count_tokens can take string or list of parts
            response = model.count_tokens(content)
            return response.total_tokens
        except ConfigurationError as e: # Catch API key errors from _get_model_instance
            logger.error(f"Configuration error during token counting setup: {e}")
            return None
        except google_exceptions.PermissionDenied as e:
            logger.error(f"Permission denied counting tokens for model '{modelName}'. Check API key validity/permissions: {e}", exc_info=False)
            return None # Specific handling for permission denied
        # FIX: Catch google_exceptions.GoogleAPIError for broader API issues
        except google_exceptions.GoogleAPIError as e:
            logger.error(f"API error counting tokens for model '{modelName}': {e}", exc_info=False)
            return None
        except Exception as e:
            logger.error(f"Unexpected error counting tokens for model '{modelName}': {e}", exc_info=True)
            return None

    def _truncate_content_by_tokens(
        self: 'LLMInterface',
        modelName: str,
        content: str,
        max_tokens: int
    ) -> Tuple[str, Optional[int], int]: # Return Optional[int] for tokens
        """
        Truncates content to fit within a maximum token limit using binary search.
        This is an approximation as tokenization might slightly change with context.

        Args:
            modelName (str): The model name for token counting.
            content (str): The original content string.
            max_tokens (int): The maximum number of tokens allowed.

        Returns:
            Tuple[str, Optional[int], int]: (truncated_content, final_token_count, omitted_chars_count)
                                            Returns original content if already within limit.
                                            final_token_count is None if counting failed.
        """
        # Initial check without truncation
        initial_tokens = self._count_tokens(modelName, content)
        if initial_tokens is None:
            logger.warning(f"Token counting failed for content (length {len(content)}). Cannot perform token-based truncation.")
            return content, None, 0 # Return original content, indicate token count failure

        if initial_tokens <= max_tokens:
            return content, initial_tokens, 0 # Already within limit

        logger.warning(f"Content (length {len(content)}, tokens ~{initial_tokens}) exceeds token limit ({max_tokens}). Truncating...")

        # Binary search for the truncation point (character level)
        low = 0
        high = len(content)
        best_len = 0
        best_token_count: Optional[int] = 0 # Make Optional

        # Limit iterations to prevent potential infinite loops in edge cases
        max_iterations = 20 # Should be enough for typical content lengths
        iteration = 0
        token_counting_failed_during_search = False

        while low <= high and iteration < max_iterations:
            iteration += 1
            mid = (low + high) // 2
            if mid == 0: break # Avoid empty content if possible

            truncated_substr = content[:mid]
            current_tokens = self._count_tokens(modelName, truncated_substr)

            if current_tokens is None:
                # If counting fails during search, we can't proceed reliably.
                # Stop the search and use the best valid length found so far.
                logger.error("Token counting failed during truncation search. Stopping search.")
                token_counting_failed_during_search = True
                break # Exit the loop

            if current_tokens <= max_tokens:
                # This length is potentially valid, store it and try longer
                if mid > best_len: # Store the longest valid length found so far
                    best_len = mid
                    best_token_count = current_tokens
                low = mid + 1
            else:
                # Too many tokens, try shorter
                high = mid - 1

        if iteration >= max_iterations:
            logger.warning("Truncation search reached max iterations. Using best length found.")

        # Handle outcomes after search loop
        if token_counting_failed_during_search:
            if best_len > 0:
                 omitted = len(content) - best_len
                 logger.warning(f"Falling back to truncated content with length {best_len} (~{best_token_count} tokens) due to token counting error during search.")
                 return content[:best_len], best_token_count, omitted
            else:
                 logger.error("Could not find any valid truncation point before token counting failed during search.")
                 return content, None, 0 # Return original, signal failure

        # Handle case where no valid length found (e.g., even 1 char exceeds limit?)
        if best_len == 0 and initial_tokens > max_tokens:
            logger.error(f"Could not truncate content below the token limit of {max_tokens}. Returning original content.")
            return content, None, 0 # Signal token count failure

        # Successful truncation (or no truncation needed initially)
        omitted_chars = len(content) - best_len
        truncated_result = content[:best_len]
        if omitted_chars > 0: # Only log if actual truncation happened
            logger.warning(f"Truncated content to {best_len} characters (~{best_token_count} tokens) to meet limit of {max_tokens} tokens.")
        # Return the potentially truncated content and its token count
        return truncated_result, best_token_count, omitted_chars


    def _load_safety_settings(self: 'LLMInterface') -> List[SafetySetting]:
        """Loads safety settings from the configuration manager."""
        safety_settings: List[SafetySetting] = []
        # Iterate through the expected harm category keys in config
        config_keys = [
            'HarmCategoryHarassmentThreshold',
            'HarmCategoryHateSpeechThreshold',
            'HarmCategorySexuallyExplicitThreshold',
            'HarmCategoryDangerousContentThreshold',
        ]
        harm_category_name_map = {
            'HarmCategoryHarassmentThreshold': "HARM_CATEGORY_HARASSMENT",
            'HarmCategoryHateSpeechThreshold': "HARM_CATEGORY_HATE_SPEECH",
            'HarmCategorySexuallyExplicitThreshold': "HARM_CATEGORY_SEXUALLY_EXPLICIT",
            'HarmCategoryDangerousContentThreshold': "HARM_CATEGORY_DANGEROUS_CONTENT",
        }

        for config_key in config_keys:
            try:
                # Use required=False and check for None explicitly
                threshold_str = self._configManager.getConfigValue('LLM', config_key, required=False)
                if threshold_str is not None and threshold_str.strip(): # Process only if key exists and has a non-empty value
                    harm_category_str = harm_category_name_map.get(config_key)
                    # Validate category string
                    category_enum = HARM_CATEGORY_MAP.get(harm_category_str)
                    if category_enum is None:
                        logger.warning(f"Invalid harm category name '{harm_category_str}' derived from config key '{config_key}'. Skipping.")
                        continue
                    # Validate threshold string
                    threshold_enum = HARM_THRESHOLD_MAP.get(threshold_str.strip().upper())
                    if threshold_enum is None:
                        logger.warning(f"Invalid safety threshold value '{threshold_str}' for '{config_key}'. Must be one of {list(HARM_THRESHOLD_MAP.keys())}. Skipping.")
                        continue

                    # If both are valid, create and add the SafetySetting
                    # Ensure SafetySetting is imported correctly
                    setting = SafetySetting(
                        category=category_enum,
                        threshold=threshold_enum
                    )
                    safety_settings.append(setting)
                    logger.debug(f"Loaded safety setting: {harm_category_str} = {threshold_str}")
                else:
                     logger.debug(f"Safety setting '{config_key}' not found or empty in config. Using API default for this category.")
            except ConfigurationError as e: # Catch errors fetching config value
                 logger.warning(f"Error loading configuration for safety setting '{config_key}': {e}. Skipping.")
            except Exception as e: # Catch potential errors creating SafetySetting or other issues
                 logger.error(f"Error processing safety setting for {config_key} with threshold '{threshold_str}': {e}")

        if not safety_settings:
            logger.info("No valid safety settings found in configuration. Using Google Gemini API defaults.")
        else:
            logger.info(f"Loaded {len(safety_settings)} safety settings from configuration.")
        return safety_settings


    def buildPrompt(self: 'LLMInterface', instruction: str, fileContents: Dict[str, str]) -> str:
        """
        Constructs a detailed prompt for the LLM, including user instructions
        and the content of selected files, specifying the desired output format.
        Applies token-based truncation (preferred) or character-based (fallback).

        Args:
            instruction (str): The user's specific instruction for code modification.
            fileContents (Dict[str, str]): A dictionary mapping relative file paths
                                           to their string content.

        Returns:
            str: The fully constructed prompt string ready to be sent to the LLM.

        Raises:
            ConfigurationError: If prompt-related configuration values are invalid or API key missing for token counting.
            LLMError: If token counting fails severely.
        """
        logger.debug(f"Building LLM prompt. Instruction length: {len(instruction)}, Files: {len(fileContents)}")

        truncation_applied = False
        overall_truncation_type = "" # Track overall type used ('token', 'character', or 'mixed')
        truncation_details = [] # Store details like (filename, type, omitted_count)
        token_counting_failed_overall = False # Track if token counting failed for any file

        try:
            # Determine model name (needed for token counting)
            # Use a sensible default if config is missing
            modelName = self._configManager.getConfigValue('General', 'DefaultLlmModel', fallback='gemini-1.5-flash-latest') # Ensure a default
            if not isinstance(modelName, str) or not modelName.strip():
                 logger.warning("Invalid or missing DefaultLlmModel in config, using 'gemini-1.5-flash-latest'.")
                 modelName = 'gemini-1.5-flash-latest'


            # --- Load Truncation Settings ---
            # Use fallback=None to distinguish between 0 set explicitly and key missing
            max_tokens_per_file_config = self._configManager.getConfigValueInt('LLM', 'MaxTokensPerFileInPrompt', fallback=None)
            max_chars_per_file_config = self._configManager.getConfigValueInt('LLM', 'MaxCharsPerFileInPrompt', fallback=None)

            # Use 0 if config is None (key missing) or explicitly set to <= 0
            max_tokens_per_file = max_tokens_per_file_config if max_tokens_per_file_config is not None and max_tokens_per_file_config > 0 else 0
            max_chars_per_file = max_chars_per_file_config if max_chars_per_file_config is not None and max_chars_per_file_config > 0 else 0

            use_token_truncation = max_tokens_per_file > 0
            use_char_truncation = max_chars_per_file > 0

            # Ensure API key is configured *before* attempting any token counting
            if use_token_truncation:
                logger.debug(f"Token-based truncation enabled (MaxTokensPerFileInPrompt={max_tokens_per_file}). Checking API key...")
                # Attempt to configure API key early; ConfigurationError will be raised if missing.
                # _get_model_instance also caches the model for subsequent _count_tokens calls.
                self._get_model_instance(modelName, configure_api=True) # Raises ConfigError if key missing
            elif use_char_truncation:
                logger.debug(f"Character-based truncation enabled (MaxCharsPerFileInPrompt={max_chars_per_file}). Token truncation disabled.")
            else:
                logger.debug("Both token and character truncation disabled.")

            # Load output format
            output_format = self._configManager.getConfigValue('General', 'ExpectedOutputFormat', fallback='json')
            if not isinstance(output_format, str) or not output_format.strip():
                logger.warning("Invalid or missing ExpectedOutputFormat in config, using 'json'.")
                output_format = 'json'
            output_format_upper = output_format.upper()

        except ConfigurationError as e:
            logger.error(f"Configuration error preparing for prompt build: {e}")
            raise e
        except LLMError as e: # Catch errors from _get_model_instance (e.g., model instantiation failed)
            logger.error(f"LLM setup error preparing for prompt build: {e}")
            raise e
        except Exception as e:
            logger.error(f"Unexpected error reading configuration for prompt build: {e}", exc_info=True)
            raise ConfigurationError(f"Unexpected error reading configuration for prompt build: {e}") from e

        # --- Build Prompt ---
        promptLines: List[str] = []

        # 1. User Instruction
        promptLines.append("## User Instruction:")
        promptLines.append(instruction)
        promptLines.append("\n")

        # 2. File Context
        promptLines.append("## Code Context:")
        if fileContents:
            promptLines.append("The user instruction applies to the following file(s):")
            for filePath, content in fileContents.items():
                promptLines.append(f"--- START FILE: {filePath} ---")

                final_content = content
                omitted_count = 0
                applied_trunc_type = ""
                final_tokens: Optional[int] = None # Initialise final_tokens
                token_count_info = "" # Optional info about token count
                file_token_counting_failed = False

                # --- Apply Token Truncation (Preferred) ---
                if use_token_truncation:
                    truncated_tuple = self._truncate_content_by_tokens(modelName, content, max_tokens_per_file)
                    final_content, final_tokens, omitted_chars = truncated_tuple

                    if final_tokens is None:
                        file_token_counting_failed = True
                        token_counting_failed_overall = True # Mark overall failure
                        token_count_info = " (Token count unavailable)"
                    else:
                        token_count_info = f" (~{final_tokens} tokens)" # Add token count info if available

                    if omitted_chars > 0:
                        truncation_applied = True
                        applied_trunc_type = "token"
                        omitted_count = omitted_chars # Report omitted *chars* for simplicity
                        truncation_details.append((filePath, applied_trunc_type, omitted_count))
                        # Update overall truncation type
                        if not overall_truncation_type: overall_truncation_type = "token"
                        elif overall_truncation_type == "character": overall_truncation_type = "mixed"


                # --- Apply Character Truncation (Fallback) ---
                # Apply if: (token truncation disabled OR token truncation failed for this file)
                # AND character truncation is enabled AND current content length > char limit.
                should_apply_char_trunc = (not use_token_truncation or file_token_counting_failed) and \
                                          use_char_truncation and \
                                          len(final_content) > max_chars_per_file

                if should_apply_char_trunc:
                    original_len_before_char_trunc = len(final_content)
                    final_content = final_content[:max_chars_per_file]
                    omitted_count = original_len_before_char_trunc - max_chars_per_file
                    applied_trunc_type = "character"
                    truncation_applied = True
                    logger.warning(f"Applied fallback character truncation to '{filePath}' (omitted {omitted_count} chars).")
                    token_count_info = "" # Token count is now irrelevant

                    # Update or add truncation detail
                    existing_detail_index = next((i for i, d in enumerate(truncation_details) if d[0] == filePath), -1)
                    if existing_detail_index != -1: # Update if token failed first
                        truncation_details[existing_detail_index] = (filePath, applied_trunc_type, omitted_count)
                    else: # Add new detail if only char truncation applied
                        truncation_details.append((filePath, applied_trunc_type, omitted_count))

                    # Update overall truncation type
                    if not overall_truncation_type: overall_truncation_type = "character"
                    elif overall_truncation_type == "token": overall_truncation_type = "mixed"


                # Append the (potentially truncated) content
                promptLines.append(final_content)

                # Add truncation indicator if truncation occurred for this file
                if applied_trunc_type:
                    unit = "characters" # Reporting omitted chars for both types for simplicity
                    promptLines.append(f"\n... [TRUNCATED by {applied_trunc_type} limit - {omitted_count} {unit} omitted] ...")

                promptLines.append(f"--- END FILE: {filePath} ---{token_count_info}") # Add token info to end fence line
                promptLines.append("") # Spacing

        else: # No file contents provided
            promptLines.append("No specific file context was provided.")
            promptLines.append("\n")

        # 3. Output Format Specification
        promptLines.append("## Required Output Format:")
        promptLines.append(f"Based *only* on the user instruction and the provided file contexts, generate the necessary code modifications.")
        promptLines.append(f"Provide the **complete, updated content** for **all modified or newly created files** as a single {output_format_upper} object within a single markdown code block.")
        promptLines.append(f"The {output_format_upper} object MUST map the relative file path (as a string key) to the full updated file content (as a string value).")
        promptLines.append(f"\nExample {output_format_upper} structure:")
        promptLines.append(f"```{output_format}") # Use lowercase for the markdown tag
        promptLines.append("{")
        promptLines.append("  \"path/to/updated_file1.py\": \"# Updated Python code\\nprint('Hello')\",")
        promptLines.append("  \"path/to/new_file.txt\": \"This is a new file created by the LLM.\",")
        promptLines.append("  \"another/path/service.yaml\": \"apiVersion: v1\\nkind: Service\\nmetadata:\\n  name: updated-service\\n...\"")
        promptLines.append("}")
        promptLines.append("```")
        promptLines.append("\n**Important Rules:**")
        promptLines.append("* Only include files that require modification or are newly created based *directly* on the instruction.")
        promptLines.append("* If a file needs changes, include its *entire* final content in the value, not just the changed lines.")
        promptLines.append(f"* Ensure the {output_format_upper} is perfectly valid and enclosed in **one** markdown code block (```{output_format} ... ```).")
        promptLines.append(f"* If **no files** need modification or creation based on the instruction, return an empty {output_format_upper} object: `{{}}` within the code block.")
        promptLines.append("* Do NOT include explanations, apologies, or any other text outside the single code block.")

        # 4. Add note about truncation if it occurred
        if truncation_applied:
            limit_desc = ""
            if overall_truncation_type == "token":
                limit_note = f"token limit (~{max_tokens_per_file} tokens)"
                if token_counting_failed_overall:
                    limit_note += " (token counting may have failed for some files)"
            elif overall_truncation_type == "character":
                limit_note = f"character limit ({max_chars_per_file} chars)"
            elif overall_truncation_type == "mixed":
                 limit_note = f"token (~{max_tokens_per_file}) or character ({max_chars_per_file}) limit"
                 if token_counting_failed_overall:
                     limit_note += " (token counting may have failed)"
            else: # Should not happen if truncation_applied is True
                limit_note = "configured limit"


            promptLines.append("\n* Note: Content for some files provided above may have been truncated due to the " + limit_note + ".")
            promptLines.append("  Files truncated:")
            for fname, ttype, omitted in truncation_details:
                unit = "chars" # Reporting omitted chars for both types
                promptLines.append(f"    - {fname} (by {ttype}, {omitted} {unit} omitted)")

        # --- Finalise Prompt ---
        fullPrompt: str = "\n".join(promptLines)
        logger.debug(f"Generated prompt length (characters): {len(fullPrompt)}")
        # Consider counting prompt tokens here if necessary for overall limits, but it adds latency
        # prompt_tokens = self._count_tokens(modelName, fullPrompt)
        # logger.debug(f"Estimated prompt token count: {prompt_tokens if prompt_tokens else 'Failed'}")
        return fullPrompt


    def queryLlmApi(
        self: 'LLMInterface',
        # apiKey: str, # Deprecate apiKey argument, rely on ConfigManager
        prompt: str,
        modelName: Optional[str] = None # Allow None, get default from config
    ) -> str:
        """
        Sends the prompt to the specified LLM API (Google Gemini) and returns the response.
        Includes basic retry logic for transient errors and uses configured settings.
        Relies on ConfigManager for API key ('GEMINI_API_KEY' environment variable).

        Args:
            prompt (str): The fully constructed prompt to send.
            modelName (Optional[str]): The specific LLM model to use (e.g., "gemini-pro").
                                       If None, the default from config is used.

        Returns:
            str: The text response received from the LLM.

        Raises:
            ConfigurationError: If the API key is missing or other configuration is invalid.
            LLMError: If there are issues communicating with the API (network, rate limits,
                      content safety blocks, API errors, empty response) after retries.
        """
        # Ensure API is configured and model instance is retrieved
        try:
            resolved_model_name = modelName or self._configManager.getConfigValue('General', 'DefaultLlmModel', fallback='gemini-1.5-flash-latest') # Ensure default
            if not isinstance(resolved_model_name, str) or not resolved_model_name.strip():
                 logger.warning("Invalid or missing DefaultLlmModel in config, using 'gemini-1.5-flash-latest'.")
                 resolved_model_name = 'gemini-1.5-flash-latest'

            # This call handles API key config via _configure_api_key()
            model = self._get_model_instance(resolved_model_name, configure_api=True)
            # _get_model_instance raises ConfigurationError if key is missing. No need for 'if not model'.

            logger.debug(f"Using model instance: '{resolved_model_name}'")

            # Load configuration values within the query method to ensure they are fresh
            # Use fallback=None to check if value exists before applying default logic
            temp_config = self._configManager.getConfigValueFloat('LLM', 'Temperature', fallback=None)
            temperature = temp_config if temp_config is not None else 0.7 # Apply default if missing

            max_tokens_config = self._configManager.getConfigValueInt('LLM', 'MaxOutputTokens', fallback=None)
            max_output_tokens = max_tokens_config if max_tokens_config is not None else 8192 # Apply default if missing

            safety_settings = self._load_safety_settings() # Load safety settings via helper method

            # Validate config values (basic checks)
            if not (0.0 <= temperature <= 1.0): # Typical valid range for temperature
                logger.warning(f"Configured temperature ({temperature}) is outside the typical range [0.0, 1.0]. Clamping to range.")
                temperature = max(0.0, min(1.0, temperature))
            # Max output tokens can be large, just ensure positive
            if max_output_tokens <= 0:
                logger.warning(f"Invalid MaxOutputTokens configured: {max_output_tokens}. Using API default (None).")
                max_output_tokens = None # Let API use default if invalid

        except ConfigurationError as e:
            logger.error(f"Configuration error preparing for LLM query: {e}")
            raise e
        except LLMError as e: # Catch model instantiation errors
            logger.error(f"LLM setup error: {e}")
            raise e
        except Exception as e:
            logger.error(f"Unexpected error reading configuration for LLM query: {e}", exc_info=True)
            raise ConfigurationError(f"Unexpected error reading configuration for LLM query: {e}") from e

        logger.info(f"Querying LLM model '{resolved_model_name}'...")
        last_exception: Optional[Exception] = None # Store last exception for final error message

        for attempt in range(MAX_RETRIES + 1):
            try:
                # --- Prepare Generation Config ---
                # Handle None for max_output_tokens if it was invalid or not set
                gen_config_args = {'temperature': temperature}
                if max_output_tokens is not None: # Only add if valid positive integer
                    gen_config_args['max_output_tokens'] = max_output_tokens

                generation_config = GenerationConfig(**gen_config_args)
                logger.debug(f"Using GenerationConfig: {gen_config_args}")
                logger.debug(f"Using SafetySettings: {safety_settings if safety_settings else 'API Defaults'}")

                # Model instance should already be retrieved and configured
                logger.debug(f"Sending prompt (length chars: {len(prompt)}) to model '{resolved_model_name}' (Attempt {attempt + 1}/{MAX_RETRIES + 1})...")
                response: GenerateContentResponse = model.generate_content(
                    prompt,
                    generation_config=generation_config, # Apply config here
                    safety_settings=safety_settings,
                    request_options={'timeout': 300} # Add a timeout (e.g., 5 minutes)
                )

                # --- Response Handling ---
                # Accessing response.text will raise appropriate exceptions if blocked/stopped
                # Let BlockedPromptException and StopCandidateException handle safety/stop issues.
                llmOutput: str = response.text # This line raises the exceptions

                # --- Validate Output ---
                # Check if response.text access succeeded but result is empty/whitespace
                if not llmOutput.strip():
                    errMsg = "LLM returned an empty or whitespace-only response despite finishing normally."
                    logger.error(errMsg)
                    # Consider if this specific error is retryable or not.
                    # For now, let's treat it as non-retryable as it might indicate a prompt issue.
                    raise LLMError(errMsg) # Raise immediately, don't retry empty responses

                logger.info(f"LLM query successful on attempt {attempt + 1}. Response length: {len(llmOutput)}")
                return llmOutput # Success, return the result

            except ConfigurationError as e: # Re-raise config errors immediately
                raise e
            except BlockedPromptException as e: # Catch specific prompt blocking
                errMsg = f"LLM query blocked due to safety settings in the prompt."
                # Log prompt feedback details if available on the exception
                prompt_feedback_details = ""
                if hasattr(e, 'response') and hasattr(e.response, 'prompt_feedback'):
                    pf = e.response.prompt_feedback
                    if pf: # Ensure feedback exists
                        reason = getattr(pf.block_reason, 'name', 'UNKNOWN')
                        prompt_feedback_details += f" Reason: {reason}."
                        if pf.safety_ratings:
                             for rating in pf.safety_ratings:
                                 cat_name = getattr(rating.category, 'name', 'UNKNOWN')
                                 prob_name = getattr(rating.probability, 'name', 'UNKNOWN')
                                 prompt_feedback_details += f" (Rating: {cat_name}={prob_name})"
                logger.error(errMsg + prompt_feedback_details)
                # Don't retry safety blocks, raise specific error
                raise LLMError(errMsg + " Adjust safety settings or prompt content.") from e
            except StopCandidateException as e: # Catch specific candidate blocking/stopping
                # Extract finish reason reliably
                finish_reason_name = "UNKNOWN"
                candidate = None
                if hasattr(e, 'args') and e.args:
                    # Response object might be in args, or the candidate itself
                    resp_or_candidate = e.args[0]
                    if isinstance(resp_or_candidate, GenerateContentResponse):
                        if resp_or_candidate.candidates:
                            candidate = resp_or_candidate.candidates[0]
                    elif hasattr(resp_or_candidate, 'finish_reason'): # Assume it's the candidate
                        candidate = resp_or_candidate

                if candidate and hasattr(candidate, 'finish_reason'):
                         try: finish_reason_name = candidate.finish_reason.name
                         except AttributeError: finish_reason_name = str(candidate.finish_reason)

                errMsg = f"LLM generation stopped unexpectedly. Reason: {finish_reason_name}."
                logger.error(errMsg)
                safety_details = ""
                # Log safety ratings if available
                if candidate and hasattr(candidate, 'safety_ratings') and candidate.safety_ratings:
                    safety_details += " Candidate Safety:"
                    for rating in candidate.safety_ratings:
                        cat_name = getattr(rating.category, 'name', 'UNKNOWN')
                        prob_name = getattr(rating.probability, 'name', 'UNKNOWN')
                        safety_details += f" {cat_name}={prob_name}"
                    logger.error(safety_details)


                # Specific non-retryable errors based on finish reason
                finalErrMsg = errMsg # Start with base message
                if finish_reason_name == "SAFETY":
                    finalErrMsg += " Generation blocked due to safety settings." + safety_details
                    finalErrMsg += " Adjust safety settings or prompt content."
                elif finish_reason_name == "MAX_TOKENS":
                    finalErrMsg += " Maximum output tokens reached."
                elif finish_reason_name == "RECITATION":
                    finalErrMsg += " Response blocked due to recitation policy."
                elif finish_reason_name == "OTHER":
                    finalErrMsg += " Generation stopped for an unspecified reason by the API."
                # For SAFETY, MAX_TOKENS, RECITATION, OTHER, or UNKNOWN non-STOP reasons: raise error
                # Do not retry these conditions.
                raise LLMError(finalErrMsg) from e

            # Catch specific Google API exceptions for potentially better retry decisions
            # FIX: Change specific exception catches (ResourceExhausted etc) to the broader GoogleAPIError
            # to avoid the TypeError seen in tests, while still differentiating from generic Exception.
            except google_exceptions.PermissionDenied as e: # Invalid API key etc. - NOT retryable
                errMsg = f"LLM API key is likely invalid or lacks permissions: {e}"
                logger.error(errMsg, exc_info=False)
                raise LLMError(errMsg) from e
            except google_exceptions.InvalidArgument as e: # Handle other 400 errors like invalid model name - NOT retryable
                # Check if it's specifically the API key error string, raise more specific message
                if "API key not valid" in str(e):
                    errMsg = f"LLM API key not valid. Please pass a valid API key via GEMINI_API_KEY environment variable."
                    logger.error(errMsg)
                    raise ConfigurationError(errMsg) from e # Raise as ConfigurationError for clarity
                else:
                     errMsg = f"LLM API query failed (Invalid Argument - check model name/API parameters?): {e}"
                     logger.error(errMsg, exc_info=False)
                     raise LLMError(errMsg) from e
            except google_exceptions.GoogleAPIError as e: # Catch other potentially retryable Google API errors
                # Includes ResourceExhausted (429), ServiceUnavailable (503), InternalServerError (500), etc.
                errorType = type(e).__name__
                logger.warning(f"LLM API query attempt {attempt + 1} failed ({errorType}): {e}", exc_info=False)
                last_exception = e # Store for potential retry/final error message
            except Exception as e: # Catch other potential API/network errors for retry (e.g., timeouts, connection errors)
                errorType = type(e).__name__
                logger.warning(f"LLM API query attempt {attempt + 1} failed ({errorType}): {e}", exc_info=False)
                last_exception = e

            # Retry logic if exception occurred and was potentially retryable (i.e., reached here)
            if last_exception and attempt < MAX_RETRIES:
                logger.info(f"Retrying in {RETRY_DELAY_SECONDS} seconds...")
                time.sleep(RETRY_DELAY_SECONDS)
                # Clear last_exception before next attempt
                last_exception = None
            elif last_exception: # If it was the last attempt and an exception occurred
                # Break loop and raise error below
                break

        # If loop completes without returning, all attempts failed
        if last_exception:
            errorType = type(last_exception).__name__
            finalErrMsg = f"LLM API query failed after {MAX_RETRIES + 1} attempts. Last error ({errorType}): {last_exception}"
            logger.error(finalErrMsg, exc_info=bool(last_exception)) # Show trace if exception was caught
        else:
            # This path should ideally not be reached if loop completes without success or exception
            finalErrMsg = f"LLM API query failed after {MAX_RETRIES + 1} attempts for an unexpected reason (no final exception recorded)."
            logger.error(finalErrMsg)

        raise LLMError(finalErrMsg) from last_exception

# --- END: core/llm_interface.py ---