# --- START: core/llm_interface.py ---
# core/llm_interface.py
"""
Handles interaction with the Large Language Model (LLM) API.
Includes building prompts and querying the API (e.g., Google Gemini).
"""
import logging
import google.generativeai as genai # Use google-generativeai library
from typing import Dict # Use Dict from typing

from .exceptions import LLMError, ConfigurationError

logger: logging.Logger = logging.getLogger(name)

class LLMInterface:
	"""
	Provides methods to build prompts and interact with an LLM API.
	"""
	def init(self: 'LLMInterface') -> None:
		"""Initialises the LLMInterface."""
		# TODO: Potentially accept configuration (e.g., default model, safety settings)
		logger.debug("LLMInterface initialised.")

	def buildPrompt(self: 'LLMInterface', instruction: str, fileContents: Dict[str, str]) -> str:
		"""
		Constructs a detailed prompt for the LLM, including user instructions
		and the content of selected files, specifying the desired output format.

		Args:
			instruction (str): The user's specific instruction for code modification.
			fileContents (Dict[str, str]): A dictionary mapping relative file paths
										to their string content.

		Returns:
			str: The fully constructed prompt string ready to be sent to the LLM.

		# TODO: Make the requested output format (JSON/YAML/XML) configurable.
		# TODO: Add options to truncate very long file contents to manage token limits.
		# TODO: Consider adding line numbers to file content snippets in the prompt.
		"""
		logger.debug(f"Building LLM prompt. Instruction length: {len(instruction)}, Files: {len(fileContents)}")

		promptLines: list[str] = [] # Use list type hint via import? Not necessary for local var

		# --- User Instruction ---
		promptLines.append("## User Instruction:")
		promptLines.append(instruction)
		promptLines.append("\n") # Add spacing

		# --- File Context ---
		if fileContents:
			promptLines.append("## Code Context:")
			promptLines.append("The user instruction applies to the following file(s):")
			for filePath, content in fileContents.items():
				promptLines.append(f"--- START FILE: {filePath} ---")
				# TODO: Implement token counting/truncation if content is excessively long
				promptLines.append(content)
				promptLines.append(f"--- END FILE: {filePath} ---")
				promptLines.append("") # Add spacing between files
		else:
			promptLines.append("## Code Context:")
			promptLines.append("No specific file context was provided.")
			promptLines.append("\n")

		# --- Output Format Specification ---
		# CRITICAL: Clearly define the expected output format for the LLM.
		promptLines.append("## Required Output Format:")
		promptLines.append("Based *only* on the user instruction and the provided file contexts, generate the necessary code modifications.")
		promptLines.append("Provide the **complete, updated content** for **all modified or newly created files** as a single JSON object within a single markdown code block.")
		promptLines.append("The JSON object MUST map the relative file path (as a string key) to the full updated file content (as a string value).")
		promptLines.append("\nExample JSON structure:")
		promptLines.append("```json")
		promptLines.append("{")
		promptLines.append("  \"path/to/updated_file1.py\": \"# Updated Python code\\nprint('Hello')\",")
		promptLines.append("  \"path/to/new_file.txt\": \"This is a new file created by the LLM.\",")
		promptLines.append("  \"another/path/service.yaml\": \"apiVersion: v1\\nkind: Service\\nmetadata:\\n  name: updated-service\\n...\"")
		promptLines.append("}")
		promptLines.append("```")
		promptLines.append("\n**Important Rules:**")
		promptLines.append("* Only include files that require modification or are newly created based *directly* on the instruction.")
		promptLines.append("* If a file needs changes, include its *entire* final content in the JSON value, not just the changed lines.")
		promptLines.append("* Ensure the JSON is perfectly valid and enclosed in **one** markdown code block (```json ... ```).")
		promptLines.append("* If **no files** need modification or creation based on the instruction, return an empty JSON object: `{}` within the code block.")
		promptLines.append("* Do NOT include explanations, apologies, or any other text outside the single JSON code block.")

		fullPrompt: str = "\n".join(promptLines)
		logger.debug(f"Generated prompt length: {len(fullPrompt)}")
		# logger.debug(f"Generated Prompt:\n{fullPrompt[:500]}...") # Log beginning of prompt
		return fullPrompt


	def queryLlmApi(
		self: 'LLMInterface',
		apiKey: str,
		prompt: str,
		modelName: str = "gemini-pro" # Or fetch from config
	) -> str:
		"""
		Sends the prompt to the specified LLM API (Google Gemini) and returns the response.

		Args:
			apiKey (str): The API key for the LLM service.
			prompt (str): The fully constructed prompt to send.
			modelName (str): The specific LLM model to use (e.g., "gemini-pro", "gemini-1.5-flash").

		Returns:
			str: The text response received from the LLM.

		Raises:
			ConfigurationError: If the API key is invalid or not configured.
			LLMError: If there are issues communicating with the API (network, rate limits,
					content safety blocks, API errors, empty response).

		# TODO: Add configuration for safety settings, generation config (temperature, max_output_tokens).
		# TODO: Implement more robust retry logic for transient network errors or rate limits.
		# TODO: Handle potential multipart responses if the model generates very large content.
		"""
		logger.info(f"Querying LLM model '{modelName}'...")
		if not apiKey:
			errMsg = "LLM API key is missing. Cannot query API."
			logger.error(errMsg)
			# Raise ConfigurationError as it's a setup issue
			raise ConfigurationError(errMsg)

		try:
			# Configure the Generative AI client
			genai.configure(api_key=apiKey)

			# TODO: Add GenerationConfig and SafetySettings based on ConfigManager values
			generation_config = {
				# "temperature": 0.7, # Example
				# "max_output_tokens": 8192, # Example
			}
			safety_settings = [
				# Examples - Adjust based on needs and Gemini documentation
				# {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
				# {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
				# {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
				# {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
			]

			# Select the model
			# TODO: Add error handling if the modelName is invalid/unavailable
			model = genai.GenerativeModel(
					model_name=modelName,
					# generation_config=generation_config,
					# safety_settings=safety_settings
			)

			logger.debug(f"Sending prompt (length: {len(prompt)}) to model '{modelName}'...")
			# Send the prompt
			response = model.generate_content(prompt)

			# --- Response Handling ---
			# Check for safety blocks or other reasons for no content
			if not response.parts:
				# Check prompt feedback for safety issues
				if response.prompt_feedback and response.prompt_feedback.block_reason:
					blockReason = response.prompt_feedback.block_reason.name
					errMsg = f"LLM query blocked due to safety settings. Reason: {blockReason}"
					logger.error(errMsg)
					# Check safety ratings for details
					for rating in response.prompt_feedback.safety_ratings:
						logger.error(f"  - Category: {rating.category.name}, Probability: {rating.probability.name}")
					raise LLMError(errMsg + ". Adjust safety settings or prompt content if appropriate.")
				else:
					# No parts and no explicit block reason - might be an API issue or empty generation
					errMsg = "LLM response was empty or incomplete. No content parts received and no block reason given."
					logger.error(errMsg)
					# Log candidate details if available
					if response.candidates:
						logger.error(f"Candidate Finish Reason: {response.candidates[0].finish_reason.name if response.candidates[0].finish_reason else 'N/A'}")
						# Log safety ratings per candidate if available
						for rating in response.candidates[0].safety_ratings:
								logger.error(f"  - Candidate Safety: {rating.category.name}, Probability: {rating.probability.name}")
					raise LLMError(errMsg)

			# Extract the text content
			# Assuming simple text response for now. Handle multipart/function calls later if needed.
			llmOutput: str = response.text # response.parts[0].text should also work

			if not llmOutput.strip():
				# Handle cases where the response contains parts but the text is empty/whitespace
				errMsg = "LLM returned an empty response."
				logger.error(errMsg)
				raise LLMError(errMsg)

			logger.info(f"LLM query successful. Response length: {len(llmOutput)}")
			# logger.debug(f"LLM Response Snippet:\n{llmOutput[:500]}...")
			return llmOutput

		except ConfigurationError as e: # Re-raise config errors
			raise e
		except LLMError as e: # Re-raise our specific LLM errors
			raise e
		except Exception as e:
			# Catch potential API errors from the google-generativeai library or network issues
			errorType = type(e).__name__
			errMsg = f"An unexpected error occurred during LLM API query ({errorType}): {e}"
			logger.error(errMsg, exc_info=True)
			# Check for common API error types if possible (e.g., AuthenticationError, RateLimitError)
			# The specific exception types might vary based on the library version.
			# Example check (adapt based on actual exceptions raised by the library):
			# if "API key not valid" in str(e):
			#     raise ConfigurationError(f"Invalid Gemini API Key: {e}") from e
			# if "rate limit" in str(e).lower():
			#     raise LLMError(f"LLM API rate limit exceeded: {e}") from e

			raise LLMError(errMsg) from e
	
# --- END: core/llm_interface.py ---