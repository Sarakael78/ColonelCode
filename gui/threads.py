# Updated Codebase/gui/threads.py
# --- START: gui/threads.py ---
# gui/threads.py
"""
Defines QThread workers for performing long-running tasks in the background,
preventing the GUI from freezing. Emits signals to update the GUI.
"""
import logging
import time # For potential delays or progress simulation if needed
from PySide6.QtCore import QThread, Signal, Slot
from typing import Optional, List, Dict, Any, Tuple # Added Tuple

# Import core handlers and exceptions
# Ensure these imports work based on your project structure (running from root)
from core.github_handler import GitHubHandler, GitProgressHandler # Import progress handler
from core.llm_interface import LLMInterface
from core.file_processor import FileProcessor
from core.exceptions import BaseApplicationError, GitHubError, ParsingError, LLMError, ConfigurationError, FileProcessingError
from core.config_manager import ConfigManager # Needed for LLMWorker config

# Use __name__ for logger specific to this module
logger: logging.Logger = logging.getLogger(__name__)

# --- Base Worker ---
class BaseWorker(QThread):
	"""Base class for worker threads providing common signals."""
	# Signal Arguments: Updated for clarity
	# progress = Signal(int) # (percentage 0-100, or -1 for indeterminate) - REPLACED BY progressUpdate
	progressUpdate = Signal(int, str) # (percentage, message) - Use this for all progress
	statusUpdate = Signal(str) # (Simple status message updates)
	errorOccurred = Signal(str) # (General error message for unexpected issues)

	def __init__(self: 'BaseWorker', parent: Optional[Any] = None) -> None:
		"""
		Initialiser for the BaseWorker.

		Args:
			parent (Optional[Any]): Parent QObject, if any.
		"""
		super().__init__(parent)
		self._task: Optional[str] = None
		self._args: list = []
		self._kwargs: dict = {}
		self._isRunning = False # Flag to track execution state

	def setTask(self: 'BaseWorker', taskName: str, args: list, kwargs: dict) -> None:
		"""
		Sets the task details before starting the thread.

		Args:
			taskName (str): The name of the task to execute.
			args (list): Positional arguments for the task function.
			kwargs (dict): Keyword arguments for the task function.
		"""
		self._task = taskName
		self._args = args
		self._kwargs = kwargs

	# Override start to set running flag
	def start(self, priority=QThread.Priority.InheritPriority) -> None:
		"""Starts the thread execution and sets the running flag."""
		self._isRunning = True
		super().start(priority)

	# Override run to wrap execution with finally block
	# Subclasses should implement _executeTask instead of run
	def run(self: 'BaseWorker') -> None:
		"""Main execution wrapper; calls _executeTask and handles final state."""
		if not self._task:
			logger.warning(f"{self.__class__.__name__} started without a task.")
			self.errorOccurred.emit(f"{self.__class__.__name__} started without task.")
			self._isRunning = False
			return

		try:
			self._executeTask() # Call the subclass implementation
		except Exception as e: # Catch truly unexpected errors within _executeTask
			logger.critical(f"Unhandled exception in {self.__class__.__name__} task '{self._task}': {e}", exc_info=True)
			self.errorOccurred.emit(f"Critical internal error in {self.__class__.__name__}: {e}")
		finally:
			self._task = None # Reset task
			self._isRunning = False
			self.progressUpdate.emit(0, "Task finished.") # Reset progress bar appearance
			self.statusUpdate.emit("Idle.") # Reset status bar

	def _executeTask(self: 'BaseWorker') -> None:
		"""Subclasses must implement their task logic here."""
		raise NotImplementedError("Subclasses must implement _executeTask.")


#--- GitHub Worker ---
class GitHubWorker(BaseWorker):
	"""Worker thread for Git/GitHub operations."""
	# Specific signals for distinct outcomes
	cloneFinished = Signal(str, list)  # repoPath, fileList
	pullFinished = Signal(str, bool)   # message, had_conflicts
	listFilesFinished = Signal(list) # fileList
	readFileFinished = Signal(str)   # fileContent
	commitPushFinished = Signal(str) # successMessage
	isDirtyFinished = Signal(bool)   # Result of isDirty check
	# Signal for specific, handled errors
	gitHubError = Signal(str)        # Error message specific to Git/GitHub
	# Removed generic progress, uses progressUpdate from BaseWorker

	def __init__(self: 'GitHubWorker', parent: Optional[Any] = None) -> None:
		"""
		Initialiser for the GitHubWorker.

		Args:
			parent (Optional[Any]): Parent QObject, if any.
		"""
		super().__init__(parent)
		self._handler: GitHubHandler = GitHubHandler()
		# Instantiate progress handler (can be reused or created per task)
		self._progress_handler_instance = GitProgressHandler(parent=self)
		# Connect internal progress handler signal to the worker's progressUpdate signal
		self._progress_handler_instance.progressUpdate.connect(self.progressUpdate)

	# --- Task Initiation Methods ---
	@Slot(str, str, str)
	def startClone(self: 'GitHubWorker', repoUrlOrPath: str, localPath: str, authToken: Optional[str]) -> None:
		"""Configures and starts the clone/load task."""
		if self._isRunning: return # Prevent starting if already running
		# Pass the internal progress handler instance
		self.setTask('clone', [repoUrlOrPath, localPath], {'authToken': authToken, 'progress_handler': self._progress_handler_instance})
		self.start() # Starts the run() method -> _executeTask()

	@Slot(str, str, str)
	def startPull(self: 'GitHubWorker', repoPath: str, remoteName: str, branchName: str) -> None:
		"""Configures and starts the pull task."""
		if self._isRunning: return
		self.setTask('pull', [repoPath], {'remoteName': remoteName, 'branchName': branchName, 'progress_handler': self._progress_handler_instance})
		self.start()

	@Slot(str)
	def startListFiles(self: 'GitHubWorker', repoPath: str) -> None:
		"""Configures and starts the list files task."""
		if self._isRunning: return
		self.setTask('listFiles', [repoPath], {})
		self.start()

	@Slot(str, str)
	def startReadFile(self: 'GitHubWorker', repoPath: str, filePath: str) -> None:
		"""Configures and starts the read file task."""
		if self._isRunning: return
		self.setTask('readFile', [repoPath, filePath], {})
		self.start()

	@Slot(str)
	def startIsDirty(self: 'GitHubWorker', repoPath: str) -> None:
		"""Configures and starts the isDirty check task."""
		if self._isRunning: return
		self.setTask('isDirty', [repoPath], {})
		self.start()

	@Slot(str, str, str, str) # Removed authToken
	def startCommitPush(self: 'GitHubWorker', repoPath: str, commitMessage: str, remoteName: str, branchName: str) -> None:
		"""Configures and starts the commit and push task."""
		if self._isRunning: return
		# Pass progress handler for push as well (limited effect currently)
		self.setTask('commitPush', [repoPath, commitMessage], {'push': True, 'remoteName': remoteName, 'branchName': branchName, 'progress_handler': self._progress_handler_instance})
		self.start()

	# --- Main thread execution logic ---
	def _executeTask(self: 'GitHubWorker') -> None:
		"""Executes the assigned GitHub task."""
		try:
			if self._task == 'clone':
				# Status update is now handled by the progress handler signals
				repo = self._handler.cloneRepository(*self._args, **self._kwargs)
				repoPath: str = repo.working_dir # Get the actual path
				# List files after clone/load
				fileList: List[str] = self._handler.listFiles(repoPath)
				self.cloneFinished.emit(repoPath, fileList) # Success -> emit path and file list

			elif self._task == 'pull':
				# Status update handled by progress handler
				message, had_conflicts = self._handler.pullRepository(*self._args, **self._kwargs)
				self.pullFinished.emit(message, had_conflicts) # Success

			elif self._task == 'listFiles':
				self.statusUpdate.emit(f"Listing files in '{self._args[0]}'...")
				self.progressUpdate.emit(-1, "Listing files...") # Indeterminate progress
				fileList = self._handler.listFiles(*self._args, **self._kwargs)
				self.listFilesFinished.emit(fileList) # Success

			elif self._task == 'readFile':
				self.statusUpdate.emit(f"Reading file '{self._args[1]}'...")
				self.progressUpdate.emit(-1, f"Reading {self._args[1]}...")
				content = self._handler.readFileContent(*self._args, **self._kwargs)
				self.readFileFinished.emit(content) # Success

			elif self._task == 'isDirty':
				self.statusUpdate.emit(f"Checking repository status '{self._args[0]}'...")
				self.progressUpdate.emit(-1, "Checking status...")
				is_dirty = self._handler.isDirty(*self._args, **self._kwargs)
				self.isDirtyFinished.emit(is_dirty) # Success

			elif self._task == 'commitPush':
				# Status update handled by progress handler for push stage
				message = self._handler.updateRepo(*self._args, **self._kwargs)
				self.commitPushFinished.emit(message) # Success

			else:
				errMsg: str = f"Unknown GitHubWorker task: {self._task}"
				logger.error(errMsg)
				self.errorOccurred.emit(errMsg) # Use general error signal

		except GitHubError as e: # Catch specific, handled errors
			logger.error(f"GitHub task '{self._task}' failed: {e}", exc_info=False) # Log concise error
			self.gitHubError.emit(str(e)) # Emit specific error signal

		# Let base class run() handle unexpected errors and finally block


#--- LLM Worker ---
class LLMWorker(BaseWorker):
	"""Worker thread for LLM interactions."""
	llmQueryFinished = Signal(str) # LLM response string
	llmError = Signal(str)         # Specific LLM/Config error message

	def __init__(self: 'LLMWorker', parent: Optional[Any] = None, configManager: Optional[ConfigManager] = None) -> None:
		"""
		Initialiser for the LLMWorker.

		Args:
			parent (Optional[Any]): Parent QObject, if any.
			configManager (Optional[ConfigManager]): Config manager instance.
		"""
		super().__init__(parent)
		# Instantiate handler here, passing config manager if available
		self._handler: LLMInterface = LLMInterface(configManager=configManager)

	# Updated startQuery signature
	@Slot(str, str, str)
	def startQuery(self: 'LLMWorker', apiKey: str, modelName: str, prompt: str) -> None:
		"""Configures and starts the LLM query task."""
		if self._isRunning: return
		# Prompt is now built before calling this
		# Pass apiKey for now, although LLMInterface might already have configured it
		self.setTask('query', [apiKey, prompt], {'modelName': modelName})
		self.start()

	def _executeTask(self: 'LLMWorker') -> None:
		"""Executes the assigned LLM task."""
		try:
			if self._task == 'query':
				model_name_disp = self._kwargs.get('modelName', 'default model')
				self.statusUpdate.emit(f"Querying LLM model {model_name_disp}...")
				self.progressUpdate.emit(-1, f"Querying {model_name_disp}...") # Indeterminate
				response: str = self._handler.queryLlmApi(*self._args, **self._kwargs)
				self.llmQueryFinished.emit(response) # Success
			else:
				errMsg: str = f"Unknown LLMWorker task: {self._task}"
				logger.error(errMsg)
				self.errorOccurred.emit(errMsg)

		except (LLMError, ConfigurationError) as e: # Catch specific LLM/Config errors
			logger.error(f"LLM task '{self._task}' failed: {e}", exc_info=False)
			self.llmError.emit(str(e))

		# Let base class run() handle unexpected errors and finally block


#--- File Processing Worker ---
class FileWorker(BaseWorker):
	"""Worker thread for parsing responses, reading files, and saving files."""
	parsingFinished = Signal(dict) # Parsed data dict
	savingFinished = Signal(list)  # List of saved files
	fileContentsRead = Signal(dict, str) # Dict[filePath, content], userInstruction
	fileProcessingError = Signal(str) # Specific file/parsing/reading error

	def __init__(self: 'FileWorker', parent: Optional[Any] = None) -> None:
		"""
		Initialiser for the FileWorker.

		Args:
			parent (Optional[Any]): Parent QObject, if any.
		"""
		super().__init__(parent)
		self._handler: FileProcessor = FileProcessor()
		# GitHub handler needed for reading file content
		self._github_handler: GitHubHandler = GitHubHandler()

	@Slot(str, str)
	def startParsing(self: 'FileWorker', llmResponse: str, expectedFormat: str = 'json') -> None:
		"""Configures and starts the response parsing task."""
		if self._isRunning: return
		# Extracting code block is fast, do it before starting thread.
		try:
			codeBlock: Optional[str] = self._handler.extractCodeBlock(llmResponse, expectedFormat)
			if codeBlock is None:
				# If extraction fails, emit error immediately, don't start thread
				self.fileProcessingError.emit("Could not find or extract code block from LLM response.")
				return
			self.setTask('parse', [codeBlock], {'format': expectedFormat})
			self.start()
		except Exception as e:
			logger.error(f"Failed during code block extraction: {e}", exc_info=True)
			self.fileProcessingError.emit(f"Failed to extract code block: {e}")

	@Slot(str, list, str) # repoPath, filePaths, userInstruction
	def startReadFileContents(self: 'FileWorker', repoPath: str, filePaths: List[str], userInstruction: str) -> None:
		"""Configures and starts the task to read multiple file contents."""
		if self._isRunning: return
		# Pass instruction through kwargs to keep args simple
		self.setTask('readFileContents', [repoPath, filePaths], {'instruction': userInstruction})
		self.start()

	@Slot(str, dict)
	def startSaving(self: 'FileWorker', outputDir: str, fileData: Dict[str, str]) -> None:
		"""Configures and starts the file saving task."""
		if self._isRunning: return
		self.setTask('save', [outputDir, fileData], {})
		self.start()


	def _executeTask(self: 'FileWorker') -> None:
		"""Executes the assigned file processing task."""
		try:
			if self._task == 'parse':
				fmt = self._kwargs.get('format', 'data')
				self.statusUpdate.emit(f"Parsing {fmt}...")
				self.progressUpdate.emit(-1, f"Parsing {fmt}...")
				parsedData: Dict[str, str] = self._handler.parseStructuredOutput(*self._args, **self._kwargs)
				self.parsingFinished.emit(parsedData) # Success

			elif self._task == 'readFileContents':
				repoPath, filePaths = self._args
				userInstruction = self._kwargs.get('instruction', '')
				numFiles = len(filePaths)
				self.statusUpdate.emit(f"Reading {numFiles} files...")
				# Start with indeterminate progress
				self.progressUpdate.emit(-1, f"Reading {numFiles} files...")
				fileContents: Dict[str, str] = {}
				errors_occurred = False
				for i, filePath in enumerate(filePaths):
						try:
								# Use GitHubHandler's read method for consistency and path validation
								content = self._github_handler.readFileContent(repoPath, filePath)
								fileContents[filePath] = content
								# Emit determinate progress update
								percentage = int(((i + 1) / numFiles) * 100)
								self.progressUpdate.emit(percentage, f"Reading {filePath} ({i+1}/{numFiles})")
						except GitHubError as e: # Catch specific read errors
								logger.error(f"Failed to read file '{filePath}' for LLM context: {e}")
								self.fileProcessingError.emit(f"Error reading file '{filePath}': {e}")
								errors_occurred = True
								# Decide whether to stop or continue reading other files
								# Continue reading for now, GUI gets notified of failures
						except Exception as e: # Catch unexpected read errors
								logger.error(f"Unexpected error reading file '{filePath}': {e}", exc_info=True)
								self.fileProcessingError.emit(f"Unexpected error reading '{filePath}': {e}")
								errors_occurred = True

				# Only emit success signal if no errors occurred during reading?
				# Or always emit with potentially partial data?
				# Emit success even with errors, MainWindow checks logs/handles partial data.
				self.fileContentsRead.emit(fileContents, userInstruction) # Emit read contents

			elif self._task == 'save':
				outputDir = self._args[0]
				numFiles = len(self._args[1])
				self.statusUpdate.emit(f"Saving {numFiles} files to '{outputDir}'...")
				self.progressUpdate.emit(-1, f"Saving {numFiles} files...")
				# TODO: Could potentially emit progress per file saved inside saveFilesToDisk
				savedFiles: List[str] = self._handler.saveFilesToDisk(*self._args, **self._kwargs)
				self.savingFinished.emit(savedFiles) # Success
			else:
				errMsg: str = f"Unknown FileWorker task: {self._task}"
				logger.error(errMsg)
				self.errorOccurred.emit(errMsg)

		except (ParsingError, FileProcessingError, GitHubError) as e: # Catch specific file/parsing/read errors
			logger.error(f"File processing task '{self._task}' failed: {e}", exc_info=False)
			self.fileProcessingError.emit(str(e))

		# Let base class run() handle unexpected errors and finally block

# --- END: gui/threads.py ---