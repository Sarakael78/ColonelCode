
# --- START: gui/threads.py ---
# gui/threads.py
"""
Defines QThread workers for performing long-running tasks in the background,
preventing the GUI from freezing. Emits signals to update the GUI.
"""
import logging
from PySide6.QtCore import QThread, Signal, Slot
from typing import Optional, List, Dict, Any

# Import core handlers and exceptions
from core.github_handler import GitHubHandler
from core.llm_interface import LLMInterface
from core.file_processor import FileProcessor
from core.exceptions import BaseApplicationError

logger: logging.Logger = logging.getLogger(name)

# --- Base Worker ---
class BaseWorker(QThread):
    """Base class for worker threads providing common signals."""
    # Signal Arguments:
    # finished: Dict/List/str (result data), str/None (error message)
    finished = Signal(object, str) # More specific types in subclasses are better
    progress = Signal(int, int) # current value, total value (or 0,0 for indeterminate)
    statusUpdate = Signal(str) # Simple status message updates

    def __init__(self: 'BaseWorker', parent: Optional[Any] = None) -> None:
        super().__init__(parent)
        # You can add common initialization here if needed
    # TODO: Add generic error handling wrapper?

#--- GitHub Worker ---
class GitHubWorker(BaseWorker):
    """Worker thread for Git/GitHub operations."""
    # Define more specific finished signals for each task type
    cloneFinished = Signal(list, str)      # list of files, error message
    listFilesFinished = Signal(list, str) # list of files, error message
    readFileFinished = Signal(str, str)    # file content, error message
    commitPushFinished = Signal(str, str)  # success message, error message
    errorOccurred = Signal(str)            # General error signal

    _task: Optional[str] = None
    _args: list = [] # Use list
    _kwargs: dict = {} # Use dict

    def __init__(self: 'GitHubWorker', parent: Optional[Any] = None) -> None:
        super().__init__(parent)
        self._handler = GitHubHandler() # Instantiate the handler
        self._task = None
        self._args = []
        self._kwargs = {}

    # --- Task initiation methods ---
    @Slot(str, str, str)
    def startClone(self: 'GitHubWorker', repoUrlOrPath: str, localPath: str, authToken: Optional[str]) -> None:
        self._task = 'clone'
        self._args = [repoUrlOrPath, localPath]
        self._kwargs = {'authToken': authToken}
        self.start() # Starts the run() method

    @Slot(str)
    def startListFiles(self: 'GitHubWorker', repoPath: str) -> None:
        # TODO: Implement if needed separately from clone
        self._task = 'listFiles'
        self._args = [repoPath]
        self._kwargs = {}
        self.start()

    @Slot(str, str)
    def startReadFile(self: 'GitHubWorker', repoPath: str, filePath: str) -> None:
        # TODO: Implement if needed for prompt building in thread
        self._task = 'readFile'
        self._args = [repoPath, filePath]
        self._kwargs = {}
        self.start()

    @Slot(str, str, str, str, str)
    def startCommitPush(self: 'GitHubWorker', repoPath: str, commitMessage: str, remoteName: str, branchName: str, authToken: Optional[str]) -> None:
        self._task = 'commitPush'
        self._args = [repoPath, commitMessage]
        self._kwargs = {'push': True, 'remoteName': remoteName, 'branchName': branchName, 'authToken': authToken}
        self.start()

    # --- Main thread execution ---
    def run(self: 'GitHubWorker') -> None:
        """The main execution method for the thread."""
        if not self._task:
            logger.warning("GitHubWorker started without a task.")
            return

        try:
            if self._task == 'clone':
                self.statusUpdate.emit(f"Cloning/Loading {self._args[0]}...")
                # # TODO: Connect progress signals from GitHubHandler if implemented
                repo = self._handler.cloneRepository(*self._args, **self._kwargs)
                self.statusUpdate.emit(f"Listing files in {repo.working_dir}...")
                fileList = self._handler.listFiles(repo.working_dir)
                self.cloneFinished.emit(fileList, None) # Success

            elif self._task == 'listFiles':
                self.statusUpdate.emit(f"Listing files in {self._args[0]}...")
                fileList = self._handler.listFiles(*self._args, **self._kwargs)
                self.listFilesFinished.emit(fileList, None)

            elif self._task == 'readFile':
                self.statusUpdate.emit(f"Reading file {self._args[1]}...")
                content = self._handler.readFileContent(*self._args, **self._kwargs)
                self.readFileFinished.emit(content, None)

            elif self._task == 'commitPush':
                self.statusUpdate.emit("Staging, committing, and pushing...")
                message = self._handler.updateRepo(*self._args, **self._kwargs)
                self.commitPushFinished.emit(message, None) # Success

            else:
                errMsg = f"Unknown GitHubWorker task: {self._task}"
                logger.error(errMsg)
                self.errorOccurred.emit(errMsg) # Use general error signal

        except BaseApplicationError as e:
            logger.error(f"Error during GitHub task '{self._task}': {e}", exc_info=False) # Log concise error
            # Emit specific finished signal with error
            if self._task == 'clone': self.cloneFinished.emit(None, str(e))
            elif self._task == 'listFiles': self.listFilesFinished.emit(None, str(e))
            elif self._task == 'readFile': self.readFileFinished.emit(None, str(e))
            elif self._task == 'commitPush': self.commitPushFinished.emit(None, str(e))
            else: self.errorOccurred.emit(str(e)) # Fallback general error

        except Exception as e:
            # Catch unexpected errors
            logger.critical(f"Unexpected critical error in GitHubWorker task '{self._task}': {e}", exc_info=True)
            errMsg = f"An unexpected error occurred: {e}"
            if self._task == 'clone': self.cloneFinished.emit(None, errMsg)
            elif self._task == 'listFiles': self.listFilesFinished.emit(None, errMsg)
            elif self._task == 'readFile': self.readFileFinished.emit(None, errMsg)
            elif self._task == 'commitPush': self.commitPushFinished.emit(None, errMsg)
            else: self.errorOccurred.emit(errMsg)
        finally:
            self._task = None # Reset task after execution


#--- LLM Worker ---
class LLMWorker(BaseWorker):
    """Worker thread for LLM interactions."""
    llmQueryFinished = Signal(str, str) # LLM response string, error message
    errorOccurred = Signal(str)

    _task: Optional[str] = None
    _args: list = []
    _kwargs: dict = {}

    def __init__(self: 'LLMWorker', parent: Optional[Any] = None) -> None:
        super().__init__(parent)
        self._handler = LLMInterface()
        self._task = None
        self._args = []
        self._kwargs = {}

    @Slot(str, str, str, dict)
    def startQuery(self: 'LLMWorker', apiKey: str, modelName: str, instruction: str, fileContents: Dict[str, str]) -> None:
        self._task = 'query'
        # Build prompt happens synchronously before starting thread usually,
        # but could be done here too. Let's assume prompt is built outside for now.
        prompt = self._handler.buildPrompt(instruction, fileContents)
        self._args = [apiKey, prompt]
        self._kwargs = {'modelName': modelName}
        self.start()

    def run(self: 'LLMWorker') -> None:
        if not self._task: return
        try:
            if self._task == 'query':
                self.statusUpdate.emit(f"Querying LLM model {self._kwargs.get('modelName')}...")
                response = self._handler.queryLlmApi(*self._args, **self._kwargs)
                self.llmQueryFinished.emit(response, None) # Success
            else:
                errMsg = f"Unknown LLMWorker task: {self._task}"
                logger.error(errMsg)
                self.errorOccurred.emit(errMsg)

        except BaseApplicationError as e:
            logger.error(f"Error during LLM task '{self._task}': {e}", exc_info=False)
            if self._task == 'query': self.llmQueryFinished.emit(None, str(e))
            else: self.errorOccurred.emit(str(e))
        except Exception as e:
            logger.critical(f"Unexpected critical error in LLMWorker task '{self._task}': {e}", exc_info=True)
            errMsg = f"An unexpected error occurred: {e}"
            if self._task == 'query': self.llmQueryFinished.emit(None, errMsg)
            else: self.errorOccurred.emit(errMsg)
        finally:
            self._task = None
		
#--- File Processing Worker ---
class FileWorker(BaseWorker):
    """Worker thread for parsing responses and saving files."""
    parsingFinished = Signal(dict, str) # Parsed data dict, error message
    savingFinished = Signal(list, str)  # List of saved files, error message
    errorOccurred = Signal(str)

    _task: Optional[str] = None
    _args: list = []
    _kwargs: dict = {}

    def __init__(self: 'FileWorker', parent: Optional[Any] = None) -> None:
        super().__init__(parent)
        self._handler = FileProcessor()
        self._task = None
        self._args = []
        self._kwargs = {}

    @Slot(str, str)
    def startParsing(self: 'FileWorker', llmResponse: str, expectedFormat: str = 'json') -> None:
        self._task = 'parse'
        # Extract code block happens synchronously before starting thread usually,
        # but could be done here. Assume extracted block is passed.
        codeBlock = self._handler.extractCodeBlock(llmResponse, expectedFormat)
        if codeBlock is None:
            # Handle error immediately if block extraction fails? Or let run() handle?
            # Let run handle it for consistency.
            self._args = [None] # Pass None to indicate extraction failed
        else:
            self._args = [codeBlock]
        self._kwargs = {'format': expectedFormat}
        self.start()

    @Slot(str, dict)
    def startSaving(self: 'FileWorker', outputDir: str, fileData: Dict[str, str]) -> None:
        self._task = 'save'
        self._args = [outputDir, fileData]
        self._kwargs = {}
        self.start()

    def run(self: 'FileWorker') -> None:
        if not self._task: return
        try:
            if self._task == 'parse':
                codeBlockContent = self._args[0]
                if codeBlockContent is None:
                    raise ParsingError("Could not find or extract code block from LLM response.")

                self.statusUpdate.emit(f"Parsing {self._kwargs.get('format')} data...")
                parsedData = self._handler.parseStructuredOutput(codeBlockContent, **self._kwargs)
                self.parsingFinished.emit(parsedData, None) # Success

            elif self._task == 'save':
                self.statusUpdate.emit(f"Saving files to {self._args[0]}...")
                savedFiles = self._handler.saveFilesToDisk(*self._args, **self._kwargs)
                self.savingFinished.emit(savedFiles, None) # Success
            else:
                errMsg = f"Unknown FileWorker task: {self._task}"
                logger.error(errMsg)
                self.errorOccurred.emit(errMsg)

        except BaseApplicationError as e:
            logger.error(f"Error during File task '{self._task}': {e}", exc_info=False)
            if self._task == 'parse': self.parsingFinished.emit(None, str(e))
            elif self._task == 'save': self.savingFinished.emit(None, str(e))
            else: self.errorOccurred.emit(str(e))
        except Exception as e:
            logger.critical(f"Unexpected critical error in FileWorker task '{self._task}': {e}", exc_info=True)
            errMsg = f"An unexpected error occurred: {e}"
            if self._task == 'parse': self.parsingFinished.emit(None, errMsg)
            elif self._task == 'save': self.savingFinished.emit(None, errMsg)
            else: self.errorOccurred.emit(errMsg)
        finally:
            self._task = None
            
    # TODO: Add init.py files to gui/ and core/ directories if not already present.
    # --- END: gui/threads.py ---

