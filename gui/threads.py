"""
Threading module for background task execution in the GUI application.
Provides worker classes for handling long-running operations without freezing the UI.

Features:
- Base worker thread with common signal handling
- GitHub operations worker for repository interactions
- LLM worker for AI model interactions
- File processing worker with validation capabilities

Each worker emits signals to update the GUI about progress and completion status.
"""

# Standard library imports
import logging
import os
import io
import json
from typing import Optional, List, Dict, Any

# Qt imports
from PySide6.QtCore import QThread, Signal, Slot

# Initialize logging
logger: logging.Logger = logging.getLogger(__name__)

# Third-party validation imports (with fallback handling)
try:
    import pyflakes.api
    import pyflakes.reporter
    PYFLAKES_AVAILABLE = True
except ImportError:
    PYFLAKES_AVAILABLE = False
    logger.warning(
        "pyflakes library not found. Python validation disabled. "
        "Install with 'pip install pyflakes'."
    )

try:
    import yaml
    PYYAML_AVAILABLE = True
except ImportError:
    PYYAML_AVAILABLE = False
    yaml = None
    logger.warning("PyYAML library not found. YAML validation may be limited.")

# Local imports
from core.github_handler import GitHubHandler, GitProgressHandler
from core.llm_interface import LLMInterface
from core.file_processor import FileProcessor
from core.exceptions import (
    GitHubError,
    ParsingError,
    LLMError,
    ConfigurationError,
    FileProcessingError
)
from core.config_manager import ConfigManager


class BaseWorker(QThread):
    """
    Base class for worker threads providing common functionality and signals.
    
    This abstract class defines the basic structure and common signals used
    by all worker threads in the application.
    
    Signals:
        progressUpdate (int, str): Emitted to update progress percentage and message
        statusUpdate (str): Emitted to update status message
        errorOccurred (str): Emitted when an error occurs
    
    Attributes:
        _task (Optional[str]): Current task name
        _args (list): Task arguments
        _kwargs (dict): Task keyword arguments
        _isRunning (bool): Thread running state
    """
    
    progressUpdate = Signal(int, str)
    statusUpdate = Signal(str)
    errorOccurred = Signal(str)
    
    def __init__(self: 'BaseWorker', parent: Optional[Any] = None) -> None:
        """
        Initialize the base worker thread.
        
        Args:
            parent: Optional parent QObject
        """
        super().__init__(parent)
        self._task: Optional[str] = None
        self._args: list = []
        self._kwargs: dict = {}
        self._isRunning = False

    def setTask(self: 'BaseWorker', taskName: str, args: list, kwargs: dict) -> None:
        self._task = taskName
        self._args = args
        self._kwargs = kwargs

    def start(self, priority=QThread.Priority.InheritPriority) -> None:
        if self._isRunning:
            logger.warning(f"{self.__class__.__name__} already running. Ignoring start request.")
            return
        self._isRunning = True
        super().start(priority)

    def run(self: 'BaseWorker') -> None:
        if not self._task:
            logger.warning(f"{self.__class__.__name__} started without a task.")
            self.errorOccurred.emit(f"{self.__class__.__name__} started without task.")
            self._isRunning = False
            return
        try:
            self._executeTask()
        except Exception as e:
            logger.critical(f"Unhandled exception in {self.__class__.__name__} task '{self._task}': {e}", exc_info=True)
            self.errorOccurred.emit(f"Critical internal error in {self.__class__.__name__}: {e}")
        finally:
            self._task = None
            self._isRunning = False
            try:
                self.progressUpdate.emit(0, "Task finished.")
                self.statusUpdate.emit("Idle.")
            except RuntimeError as e:
                logger.error(f"Error emitting final signals in {self.__class__.__name__}: {e}")

    def _executeTask(self: 'BaseWorker') -> None:
        raise NotImplementedError("Subclasses must implement _executeTask.")


class GitHubWorker(BaseWorker):
    """
    Worker thread for handling Git/GitHub operations asynchronously.
    
    Signals:
        cloneFinished (str, list): Repository path and file list after clone
        pullFinished (str, bool): Pull message and conflict status
        listFilesFinished (list): List of files in repository
        readFileFinished (str): File content
        commitPushFinished (str): Commit/push result message
        isDirtyFinished (bool): Repository dirty status
        gitHubError (str): GitHub-specific error message
    """
    
    cloneFinished = Signal(str, list)
    pullFinished = Signal(str, bool)
    listFilesFinished = Signal(list)
    readFileFinished = Signal(str)
    commitPushFinished = Signal(str)
    isDirtyFinished = Signal(bool)
    gitHubError = Signal(str)
    
    def __init__(self: 'GitHubWorker', parent: Optional[Any] = None) -> None:
        """Initialize the GitHub worker with progress handling."""
        super().__init__(parent)
        self._handler: GitHubHandler = GitHubHandler()
        self._progress_handler_instance = GitProgressHandler(parent_qobject=self)
        
        if hasattr(self._progress_handler_instance, 'progressUpdateSignal'):
            self._progress_handler_instance.progressUpdateSignal.connect(self.progressUpdate)
        else:
            logger.warning("Could not connect progress handler signal in GitHubWorker.")

    @Slot(str, str, str)
    def startClone(self: 'GitHubWorker', repoUrlOrPath: str, localPath: str, authToken: Optional[str]) -> None:
        if self._isRunning:
            return
        self.setTask('clone', [repoUrlOrPath, localPath], {'authToken': authToken, 'progress_handler': self._progress_handler_instance})
        self.start()

    @Slot(str, str, str)
    def startPull(self: 'GitHubWorker', repoPath: str, remoteName: str, branchName: str) -> None:
        if self._isRunning:
            return
        self.setTask('pull', [repoPath], {'remoteName': remoteName, 'branchName': branchName, 'progress_handler': self._progress_handler_instance})
        self.start()

    @Slot(str)
    def startListFiles(self: 'GitHubWorker', repoPath: str) -> None:
        if self._isRunning:
            return
        self.setTask('listFiles', [repoPath], {})
        self.start()

    @Slot(str, str)
    def startReadFile(self: 'GitHubWorker', repoPath: str, filePath: str) -> None:
        if self._isRunning:
            return
        self.setTask('readFile', [repoPath, filePath], {})
        self.start()

    @Slot(str)
    def startIsDirty(self: 'GitHubWorker', repoPath: str) -> None:
        if self._isRunning:
            return
        self.setTask('isDirty', [repoPath], {})
        self.start()

    @Slot(str, str, str, str)
    def startCommitPush(self: 'GitHubWorker', repoPath: str, commitMessage: str, remoteName: str, branchName: str) -> None:
        if self._isRunning:
            return
        self.setTask('commitPush', [repoPath, commitMessage], {'push': True, 'remoteName': remoteName, 'branchName': branchName, 'progress_handler': self._progress_handler_instance})
        self.start()

    def _executeTask(self: 'GitHubWorker') -> None:
        try:
            if self._task == 'clone':
                repo = self._handler.cloneRepository(*self._args, **self._kwargs)
                repoPath: str = repo.working_dir
                fileList: List[str] = self._handler.listFiles(repoPath)
                self.cloneFinished.emit(repoPath, fileList)
            elif self._task == 'pull':
                message, had_conflicts = self._handler.pullRepository(*self._args, **self._kwargs)
                self.pullFinished.emit(message, had_conflicts)
            elif self._task == 'listFiles':
                self.statusUpdate.emit(f"Listing files in '{self._args[0]}'...")
                self.progressUpdate.emit(-1, "Listing files...")
                fileList = self._handler.listFiles(*self._args, **self._kwargs)
                self.listFilesFinished.emit(fileList)
            elif self._task == 'readFile':
                self.statusUpdate.emit(f"Reading file '{self._args[1]}'...")
                self.progressUpdate.emit(-1, f"Reading {self._args[1]}...")
                content = self._handler.readFileContent(*self._args, **self._kwargs)
                self.readFileFinished.emit(content)
            elif self._task == 'isDirty':
                self.statusUpdate.emit(f"Checking repository status '{self._args[0]}'...")
                self.progressUpdate.emit(-1, "Checking status...")
                is_dirty = self._handler.isDirty(*self._args, **self._kwargs)
                self.isDirtyFinished.emit(is_dirty)
            elif self._task == 'commitPush':
                message = self._handler.updateRepo(*self._args, **self._kwargs)
                self.commitPushFinished.emit(message)
            else:
                errMsg: str = f"Unknown GitHubWorker task: {self._task}"
                logger.error(errMsg)
                self.errorOccurred.emit(errMsg)
        except GitHubError as e:
            logger.error(f"GitHub task '{self._task}' failed: {e}", exc_info=False)
            self.gitHubError.emit(str(e))
        except Exception as e:
            logger.critical(f"Unexpected error during GitHub task '{self._task}': {e}", exc_info=True)
            self.errorOccurred.emit(f"Unexpected internal error during {self._task}: {e}")


class LLMWorker(BaseWorker):
    """
    Worker thread for handling LLM API interactions asynchronously.
    
    Handles communication with the LLM model, including standard queries
    and correction queries with temperature override.
    
    Signals:
        llmQueryFinished (str): Emitted with LLM response text
        llmError (str): Emitted with LLM-specific error message
    
    Attributes:
        _handler (LLMInterface): Interface for LLM operations
    """
    
    llmQueryFinished = Signal(str)
    llmError = Signal(str)
    
    def __init__(
        self: 'LLMWorker',
        parent: Optional[Any] = None,
        configManager: Optional[ConfigManager] = None
    ) -> None:
        """
        Initialize the LLM worker.
        
        Args:
            parent: Optional parent QObject
            configManager: Optional configuration manager instance
        """
        super().__init__(parent)
        self._handler: LLMInterface = LLMInterface(configManager=configManager)

    @Slot(str, str)
    def startQuery(self: 'LLMWorker', modelName: str, prompt: str) -> None:
        """
        Start a standard LLM query task.
        
        Args:
            modelName: Name of the LLM model to use
            prompt: The prompt text to send to the model
        """
        if self._isRunning:
            return
        self.setTask('query', [prompt], {'modelName': modelName})
        self.start()

    @Slot(str, str, float)
    def startCorrectionQuery(self: 'LLMWorker', modelName: str, correction_prompt: str, override_temperature: float) -> None:
        """Configures and starts the LLM correction query task."""
        if self._isRunning:
            return
        self.setTask('queryCorrection', [correction_prompt], {'modelName': modelName, 'override_temperature': override_temperature})
        self.start()

    def _executeTask(self: 'LLMWorker') -> None:
        """Executes the assigned LLM task."""
        try:
            if self._task == 'query' or self._task == 'queryCorrection':
                model_name_disp = self._kwargs.get('modelName', 'default model')
                override_temp = self._kwargs.get('override_temperature', None)
                status_msg = f"Querying LLM model {model_name_disp}"
                if self._task == 'queryCorrection':
                    status_msg = f"Requesting correction from LLM {model_name_disp} (Temp: {override_temp:.1f})..."
                self.statusUpdate.emit(status_msg)
                self.progressUpdate.emit(-1, status_msg)
                logger.debug(f"Calling queryLlmApi for task '{self._task}' with kwargs: {self._kwargs}")
                response: str = self._handler.queryLlmApi(*self._args, modelName=self._kwargs.get('modelName'), override_temperature=override_temp)
                self.llmQueryFinished.emit(response)
            else:
                errMsg: str = f"Unknown LLMWorker task: {self._task}"
                logger.error(errMsg)
                self.errorOccurred.emit(errMsg)
        except (LLMError, ConfigurationError) as e:
            logger.error(f"LLM task '{self._task}' failed: {e}", exc_info=False)
            self.llmError.emit(str(e))
        except TypeError as e:
            logger.critical(f"TypeError calling API in LLMWorker task '{self._task}': {e}", exc_info=True)
            self.errorOccurred.emit(f"Internal TypeError calling API: {e}")
        except Exception as e:
            logger.critical(f"Unexpected error during LLM task '{self._task}': {e}", exc_info=True)
            self.errorOccurred.emit(f"Unexpected internal error during {self._task}: {e}")


class FileWorker(BaseWorker):
    """
    Worker thread for file operations including parsing, validation, and saving.
    
    Signals:
        parsingFinished (dict, dict): Parsed data and validation results
        savingFinished (list): List of saved file paths
        fileContentsRead (dict, str): File contents and user instruction
        fileProcessingError (str): File processing error message
    """
    
    parsingFinished = Signal(dict, dict)
    savingFinished = Signal(list)
    fileContentsRead = Signal(dict, str)
    fileProcessingError = Signal(str)
    
    def __init__(self: 'FileWorker', parent: Optional[Any] = None) -> None:
        """Initialize the file worker."""
        super().__init__(parent)
        self._handler: FileProcessor = FileProcessor()
        self._github_handler: GitHubHandler = GitHubHandler()

    @Slot(str, str)
    def startParsing(self: 'FileWorker', llmResponse: str, expectedFormat: str = 'json') -> None:
        """Configures and starts the response parsing and validation task."""
        if self._isRunning:
            return
        try:
            codeBlock: Optional[str] = self._handler.extractCodeBlock(llmResponse, expectedFormat)
            if codeBlock is None:
                self.fileProcessingError.emit("Could not find or extract code block from LLM response.")
                return
            self.setTask('parseAndValidate', [codeBlock], {'format': expectedFormat})
            self.start()
        except Exception as e:
            logger.error(f"Error during code block extraction: {e}", exc_info=True)
            self.fileProcessingError.emit(f"Failed to extract code block: {e}")

    @Slot(str, list, str)
    def startReadFileContents(self: 'FileWorker', repoPath: str, filePaths: List[str], userInstruction: str) -> None:
        if self._isRunning:
            return
        self.setTask('readFileContents', [repoPath, filePaths], {'instruction': userInstruction})
        self.start()

    @Slot(str, dict)
    def startSaving(self: 'FileWorker', outputDir: str, fileData: Dict[str, str]) -> None:
        if self._isRunning:
            return
        self.setTask('save', [outputDir, fileData], {})
        self.start()

    def _validate_code_content(self, file_path: str, content: str) -> List[str]:
        """
        Validates code syntax based on file extension.
        
        Args:
            file_path: Path to the file (for determining type)
            content: Code content to validate
            
        Returns:
            List of validation error messages (empty if valid)
        """
        errors: List[str] = []
        _, extension = os.path.splitext(file_path.lower())
        
        try:
            if extension == '.py':
                if PYFLAKES_AVAILABLE and pyflakes:
                    error_stream = io.StringIO()
                    reporter = pyflakes.reporter.Reporter(io.StringIO(), error_stream)
                    try:
                        pyflakes.api.check(content, file_path, reporter=reporter)
                        error_output = error_stream.getvalue().strip()
                        if error_output:
                            errors.extend(error_output.splitlines())
                    except Exception as pyflakes_err:
                        errors.append(f"Pyflakes runtime error: {pyflakes_err}")
                    finally:
                        error_stream.close()
                else:
                    logger.debug("Skipped Python validation (pyflakes unavailable).")
            
            elif extension == '.json':
                try:
                    json.loads(content)
                except json.JSONDecodeError as json_err:
                    errors.append(
                        f"JSON Error: {json_err.msg} "
                        f"(line {json_err.lineno}, col {json_err.colno})"
                    )
            
            elif extension in ['.yaml', '.yml']:
                if PYYAML_AVAILABLE and yaml is not None:
                    try:
                        list(yaml.safe_load_all(content))
                    except yaml.YAMLError as yaml_err:
                        mark_info = (
                            f" (line {yaml_err.problem_mark.line + 1})"
                            if hasattr(yaml_err, 'problem_mark') and yaml_err.problem_mark
                            else ""
                        )
                        errors.append(f"YAML Error: {yaml_err.problem}{mark_info}")
                else:
                    logger.debug("Skipped YAML validation (PyYAML unavailable).")
                    
        except Exception as e:
            logger.error(
                f"Unexpected validation error for '{file_path}': {e}",
                exc_info=True
            )
            errors.append(f"Internal validation error: {e}")
            
        return errors

    def _executeTask(self: 'FileWorker') -> None:
        """Executes the assigned file processing task."""
        try:
            if self._task == 'parseAndValidate':
                fmt = self._kwargs.get('format', 'data')
                self.statusUpdate.emit(f"Parsing {fmt}...")
                self.progressUpdate.emit(-1, f"Parsing {fmt}...")
                codeBlockContent = self._args[0]
                parsedData: Dict[str, str] = self._handler.parseStructuredOutput(codeBlockContent, fmt)

                # --- Log proposed file updates ---
                if parsedData:
                    logger.info("LLM proposes updates for the following files:")
                    for file_path in sorted(parsedData.keys()): # Log in sorted order for consistency
                        logger.info(f"  - {file_path}")
                else:
                    logger.info("LLM response parsed, but contained no file updates.")
                # --- End log proposed file updates ---

                self.statusUpdate.emit(f"Validating {len(parsedData)} file(s)...")
                self.progressUpdate.emit(-1, f"Validating {len(parsedData)} files...")
                validationResults: Dict[str, List[str]] = {}
                total_files = len(parsedData)
                files_validated = 0
                for file_path, content in parsedData.items():
                    file_errors = self._validate_code_content(file_path, content)
                    if file_errors:
                        validationResults[file_path] = file_errors
                        logger.warning(f"Validation failed for '{file_path}': {len(file_errors)} error(s).")
                    files_validated += 1
                    percentage = int((files_validated / total_files) * 100) if total_files > 0 else 100
                    self.progressUpdate.emit(percentage, f"Validated {files_validated}/{total_files} files")
                if validationResults:
                    self.statusUpdate.emit(f"Parsing complete. Validation FAILED for {len(validationResults)} file(s).")
                else:
                    self.statusUpdate.emit("Parsing and validation complete. No errors found.")
                self.parsingFinished.emit(parsedData, validationResults)
            elif self._task == 'readFileContents':
                repoPath, filePaths = self._args
                userInstruction = self._kwargs.get('instruction', '')
                numFiles = len(filePaths)
                self.statusUpdate.emit(f"Reading {numFiles} files...")
                self.progressUpdate.emit(-1, f"Reading {numFiles} files...")
                fileContents: Dict[str, str] = {}
                for i, filePath in enumerate(filePaths):
                    try:
                        content = self._github_handler.readFileContent(repoPath, filePath)
                        fileContents[filePath] = content
                        percentage = int(((i + 1) / numFiles) * 100)
                        self.progressUpdate.emit(percentage, f"Reading {filePath} ({i+1}/{numFiles})")
                    except GitHubError as e:
                        logger.error(f"Failed to read file '{filePath}' for context: {e}")
                        self.fileProcessingError.emit(f"Error reading file '{filePath}': {e}")
                    except Exception as e:
                        logger.error(f"Unexpected error reading file '{filePath}': {e}", exc_info=True)
                        self.fileProcessingError.emit(f"Unexpected error reading '{filePath}': {e}")
                self.fileContentsRead.emit(fileContents, userInstruction)
            elif self._task == 'save':
                outputDir = self._args[0]
                numFiles = len(self._args[1])
                self.statusUpdate.emit(f"Saving {numFiles} files to '{outputDir}'...")
                self.progressUpdate.emit(-1, f"Saving {numFiles} files...")
                savedFiles: List[str] = self._handler.saveFilesToDisk(*self._args, **self._kwargs)
                self.savingFinished.emit(savedFiles)
            else:
                errMsg: str = f"Unknown FileWorker task: {self._task}"
                logger.error(errMsg)
                self.errorOccurred.emit(errMsg)
        except ParsingError as e:
            logger.error(f"File processing task '{self._task}' failed: {e}", exc_info=False)
            self.fileProcessingError.emit(f"ParsingError: {str(e)}")
        except (FileProcessingError, GitHubError) as e:
            logger.error(f"File processing task '{self._task}' failed: {e}", exc_info=False)
            self.fileProcessingError.emit(str(e))
        except Exception as e:
            logger.critical(f"Unexpected error during FileWorker task '{self._task}': {e}", exc_info=True)
            self.errorOccurred.emit(f"Unexpected internal error during {self._task}: {e}")
