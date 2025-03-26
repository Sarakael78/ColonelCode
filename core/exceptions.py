# --- START: core/exceptions.py ---
# core/exceptions.py
"""
Defines custom exception classes for specific error conditions within the application.
This allows for more granular error handling and reporting.
"""

# Adhering to user preference for explicit initialisation (though less common for classes)
# Using standard Exception inheritance which is Pythonic.

class BaseApplicationError(Exception):
	"""
	Base class for all custom application-specific exceptions.
	Provides a common ancestor for catching application-related errors.
	"""
	def __init__(self: 'BaseApplicationError', message: str = "An application error occurred.") -> None:
		"""
		Initialises the BaseApplicationError.

		Args:
			message (str): A descriptive message for the error.
		"""
		super().__init__(message)


class ConfigurationError(BaseApplicationError):
	"""
	Raised for errors encountered during loading, parsing, or accessing
	configuration settings (e.g., missing keys, invalid formats).
	"""
	def __init__(self: 'ConfigurationError', message: str = "Configuration error.") -> None:
		"""
		Initialises the ConfigurationError.

		Args:
			message (str): A descriptive message specific to the configuration issue.
		"""
		super().__init__(message)


class GitHubError(BaseApplicationError):
	"""
	Raised for errors related to interacting with Git repositories or the GitHub API.
	Examples include cloning failures, authentication issues, command execution errors,
	network problems during Git operations.
	"""
	def __init__(self: 'GitHubError', message: str = "GitHub interaction error.") -> None:
		"""
		Initialises the GitHubError.

		Args:
			message (str): A descriptive message specific to the Git/GitHub issue.
		"""
		super().__init__(message)


class LLMError(BaseApplicationError):
	"""
	Raised for errors encountered while interacting with the Large Language Model API.
	Examples include API key errors, network issues, rate limits, content safety blocks,
	or unexpected responses from the LLM service.
	"""
	def __init__(self: 'LLMError', message: str = "LLM interaction error.") -> None:
		"""
		Initialises the LLMError.

		Args:
			message (str): A descriptive message specific to the LLM API issue.
		"""
		super().__init__(message)


class ParsingError(BaseApplicationError):
	"""
	Raised for errors during the parsing of structured data, typically the LLM response.
	Examples include failing to find the expected code block, invalid JSON/YAML/XML format,
	or incorrect data structure within the parsed response.
	"""
	def __init__(self: 'ParsingError', message: str = "Parsing error.") -> None:
		"""
		Initialises the ParsingError.

		Args:
			message (str): A descriptive message specific to the parsing issue.
		"""
		super().__init__(message)


class FileProcessingError(BaseApplicationError):
	"""
	Raised for errors related to file system operations, such as reading from or
	writing to files during the processing stages.
	Examples include permission denied errors, disk full errors, file not found (when expected),
	or issues creating directories.
	"""
	def __init__(self: 'FileProcessingError', message: str = "File processing error.") -> None:
		"""
		Initialises the FileProcessingError.

		Args:
			message (str): A descriptive message specific to the file system operation issue.
		"""
		super().__init__(message)

# TODO: Consider adding more specific sub-exceptions if needed (e.g., GitHubAuthError, LLMApiKeyError).
# --- END: core/exceptions.py ---