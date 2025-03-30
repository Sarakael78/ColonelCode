# Updated Codebase/core/github_handler.py
# --- START: core/github_handler.py ---
# core/github_handler.py
"""
Handles interactions with Git repositories, including cloning, pulling, listing files,
reading file content, staging, committing, and pushing changes.
Uses the GitPython library.

This module facilitates communication with local and remote Git repositories,
encapsulating operations like cloning, file access, and state modification.
Includes enhanced error handling and pre-checks for operations like pushing.
Adds progress reporting capability for clone operations.
"""
import git # Import the git library
import os
import logging
from typing import List, Optional, Tuple, Any, Dict # Use Tuple for branch status, Any for progress handler, ADDED Dict
from PySide6.QtCore import QObject, Signal

# Relative import from the 'core' package for custom exceptions
from .exceptions import GitHubError

# Logger instance specific to this module for targeted logging
logger: logging.Logger = logging.getLogger(__name__)


# --- Signal Emitter Helper Class (for Composition) ---
class _SignalEmitter(QObject):
	"""Internal QObject solely for emitting signals from the progress handler."""
	# Signal format: progressUpdate(percentage, message)
	# Percentage: 0-100, or -1 for indeterminate stages
	# Message: Text description of the current stage/progress
	progressUpdate = Signal(int, str)

	def __init__(self: '_SignalEmitter', parent: Optional[QObject] = None) -> None:
		"""Initialise the signal emitter."""
		super().__init__(parent)

# --- Progress Handler Class ---
class GitProgressHandler(git.remote.RemoteProgress):
	"""
	Custom progress handler for GitPython operations (like clone).
	Inherits from RemoteProgress for GitPython integration and uses composition
	with a QObject (_SignalEmitter) to emit Qt signals for updating the GUI,
	a voiding multiple C-extension inheritance conflicts.
	"""

	# Keep a reference to the signal emitter
	# Corrected type hint for _emitter
	_emitter: Optional[_SignalEmitter]

	_last_percentage: Optional[int] = None
	# Using Dict type hint requires importing it from typing
	_stage_map: Dict[int, str] = {
		git.remote.RemoteProgress.BEGIN: "Connecting",
		git.remote.RemoteProgress.CHECKING_OUT: "Checking out files",
		git.remote.RemoteProgress.COMPRESSING: "Compressing objects",
		git.remote.RemoteProgress.COUNTING: "Counting objects",
		git.remote.RemoteProgress.END: "Finalising",
		git.remote.RemoteProgress.FINDING_SOURCES: "Finding sources",
		git.remote.RemoteProgress.RECEIVING: "Receiving objects",
		git.remote.RemoteProgress.RESOLVING: "Resolving deltas",
		git.remote.RemoteProgress.WRITING: "Writing objects",
		# Add pull stages if known/different, otherwise reuse generic ones
		# git.FetchInfo.HEAD_UPTODATE: "Checking status", # Example, might not be exact stage
	}

	def __init__(self: 'GitProgressHandler', parent_qobject: Optional[QObject] = None) -> None:
		"""
		Initialise GitProgressHandler.

		Args:
			parent_qobject (Optional[QObject]): An optional parent QObject for the internal signal emitter.
		"""
		# Initialise the RemoteProgress base class
		super().__init__()
		# Create and store the internal signal emitter
		self._emitter = _SignalEmitter(parent=parent_qobject)
		self._last_percentage = None

	# Getter for the actual signal (needed for connections)
	@property
	def progressUpdateSignal(self: 'GitProgressHandler') -> Signal:
		"""Provides access to the progressUpdate signal of the internal emitter."""
		if self._emitter:
			return self._emitter.progressUpdate
		# Return a dummy signal or raise error if emitter not initialised (shouldn't happen)
		# For simplicity, assume emitter is always created in __init__
		# If robustness is needed, handle self._emitter being None.
		raise RuntimeError("GitProgressHandler internal signal emitter not initialised.")

	# This method is called by GitPython, NOT decorated with @Slot
	def update(self: 'GitProgressHandler', op_code: int, cur_count: Any, max_count: Any = None, message: str = '') -> None:
		"""
		Callback method called by GitPython during remote operations (clone, fetch, pull).
		Processes the progress information and emits a signal via the internal emitter.

		Args:
			op_code (int): Code indicating the current operation stage (e.g., BEGIN, COUNTING).
			cur_count (Any): Current progress count (often float or int).
			max_count (Any, optional): Maximum progress count (often float or int). Defaults to None.
			message (str, optional): Additional progress message. Defaults to ''.
		"""
		stage_mask = op_code & git.remote.RemoteProgress.STAGE_MASK
		# Use specific op_code name if stage is 0 (often for messages)
		stage: str = self._stage_map.get(op_code if stage_mask == 0 else stage_mask, "Processing")
		# op_name: str = self._stage_map.get(op_code, "") # Get specific operation if no stage mask

		percentage: int = -1 # Default to indeterminate

		# Try converting counts to numbers for percentage calculation
		try:
			current = float(cur_count) if cur_count is not None else 0
			maximum = float(max_count) if max_count is not None else 0
			if maximum > 0:
				percentage = int((current / maximum) * 100)
			elif op_code & git.remote.RemoteProgress.BEGIN:
				percentage = 0
			elif op_code & git.remote.RemoteProgress.END:
				percentage = 100
		except (ValueError, TypeError):
			# If conversion fails, keep percentage indeterminate
			percentage = -1

		# Ensure percentage is within bounds or indeterminate
		if not (0 <= percentage <= 100):
			percentage = -1

		# Construct a meaningful status message
		status_message = f"{stage}: {message}".strip()
		if not message: # If no specific message, just use stage name
				status_message = stage

		# Only emit signal if percentage or message actually changes significantly
		# to avoid flooding the GUI event loop. Emit always for BEGIN/END.
		# Also emit if percentage is different from last emitted percentage
		# Only emit END once
		if op_code & git.remote.RemoteProgress.END and self._last_percentage == 100:
			return # Avoid duplicate END signals
		if (op_code & (git.remote.RemoteProgress.BEGIN | git.remote.RemoteProgress.END)) or \
		   (percentage != self._last_percentage):
			# Ensure percentage is clamped 0-100 for END signal consistency
			if op_code & git.remote.RemoteProgress.END:
				percentage = 100

			# Emit signal using the internal emitter
			if self._emitter:
				self._emitter.progressUpdate.emit(percentage, status_message)
			else:
				# Fallback or logging if emitter somehow isn't there
				logger.error("GitProgressHandler cannot emit signal: internal emitter not found.")

			self._last_percentage = percentage if not (op_code & git.remote.RemoteProgress.END) else None # Reset last % after END
			logger.debug(f"Git Progress: {percentage}% - {status_message}") # Optional debug log

# --- GitHub Handler Class ---
class GitHubHandler:
	"""
	Provides methods to interact with Git repositories locally and remotely.

	Encapsulates Git operations using the GitPython library, offering a
	structured interface for cloning, pulling, file access, and repository updates.
	Includes enhanced error handling for common Git issues and pre-checks.
	"""
	# No specific __init__ needed currently
	# def __init__(self: 'GitHubHandler') -> None:
	#     """Initialises the GitHubHandler."""
	#     logger.debug("GitHubHandler initialised.")


	def cloneRepository(
		self: 'GitHubHandler',
		repoUrlOrPath: str,
		localPath: str,
		authToken: Optional[str] = None, # authToken is informational only
		progress_handler: Optional[GitProgressHandler] = None # Add progress handler arg
	) -> git.Repo:
		"""
		Clones a Git repository from a URL or initialises from a local path.

		If `localPath` already exists and is a valid Git repository, it loads the
		existing repository. If the path exists but is not a repository or is
		empty, it attempts to clone into it. Relies on Git's configured credential
		management (helpers, SSH keys) for authentication. Provides progress updates
		via the optional `progress_handler`.

		Args:
			repoUrlOrPath (str): The URL of the repository to clone (e.g.,
								 'https://github.com/user/repo.git') or the path
								 to an existing local repository.
			localPath (str): The target local directory path where the repository
							 should be cloned or where it already exists.
			authToken (Optional[str]): Informational only. If provided for an HTTPS URL,
								   a warning is logged suggesting use of a credential
								   manager instead of direct token handling.
			progress_handler (Optional[GitProgressHandler]): An instance of GitProgressHandler
															 to receive progress updates.

		Returns:
			git.Repo: The Repo object representing the cloned or loaded repository.

		Raises:
			GitHubError: If cloning or loading fails due to various reasons,
						 including invalid URL/path, authentication issues (with
						 enhanced messaging), network problems, Git command errors,
						 or file system permission errors.
		"""
		logger.info(f"Attempting to clone/load repo '{repoUrlOrPath}' into '{localPath}'")

		try:
			# Case 1: Check if localPath is already a valid Git repository
			if os.path.isdir(localPath) and os.path.exists(os.path.join(localPath, '.git')):
				logger.info(f"'{localPath}' exists and appears to be a Git repository. Loading existing repo.")
				# Use progress_handler.update directly if available, otherwise emit via signal
				if progress_handler and hasattr(progress_handler, '_emitter'):
					progress_handler._emitter.progressUpdate.emit(0, "Loading existing repository...")
				try:
					repo: git.Repo = git.Repo(localPath)
					logger.info(f"Successfully loaded existing repository from '{localPath}'.")
					if progress_handler and hasattr(progress_handler, '_emitter'):
						progress_handler._emitter.progressUpdate.emit(50, "Fetching remote updates...")
					# Perform a fetch after loading to update remote refs (useful for push pre-check)
					try:
						logger.debug(f"Fetching updates from remotes for '{localPath}'...")
						for remote in repo.remotes:
							# Pass progress handler to fetch if needed (more complex setup)
							# Fetch with prune=True to remove remote-tracking branches that no longer exist on remote
							remote.fetch(prune=True, progress=progress_handler) # Pass progress
						logger.debug("Fetch successful.")
					except git.GitCommandError as fetch_err:
						# Log warning but don't fail the load operation
						logger.warning(f"Could not fetch updates after loading repo: {getattr(fetch_err, 'stderr', fetch_err)}")
					except Exception as fetch_err_generic:
						# Log warning but don't fail the load operation
						logger.warning(f"Unexpected error during fetch after loading repo: {fetch_err_generic}")

					if progress_handler and hasattr(progress_handler, '_emitter'):
						progress_handler._emitter.progressUpdate.emit(100, "Repository loaded.")
					return repo
				except git.InvalidGitRepositoryError as e:
					errMsg: str = f"Directory '{localPath}' exists but is not a valid Git repository: {e}"
					logger.error(errMsg)
					raise GitHubError(errMsg) from e
				except Exception as e: # Catch other potential git.Repo errors
					errMsg: str = f"Error loading existing repository from '{localPath}': {e}"
					logger.error(errMsg, exc_info=True)
					raise GitHubError(errMsg) from e

			# Case 2: localPath does not exist or is an empty directory - proceed with cloning
			# Check if the input was actually a local path that turned out *not* to be a repo
			# We infer this if repoUrlOrPath and localPath are the same *and* the previous check failed
			if repoUrlOrPath == localPath:
				# If the input path was the target path, and we determined it's not a valid repo, raise an error.
				errMsg = f"The specified local path '{localPath}' exists but is not a valid Git repository. Please select a valid repository or clone from a URL."
				logger.error(errMsg)
				raise GitHubError(errMsg)
			
			logger.info(f"Path '{localPath}' is not an existing valid repository. Proceeding with clone.")
			if progress_handler and hasattr(progress_handler, '_emitter'):
				progress_handler._emitter.progressUpdate.emit(0, "Preparing to clone...")
			# Ensure the parent directory exists before attempting to clone
			parentDir: str = os.path.dirname(localPath)
			if parentDir and not os.path.exists(parentDir):
				try:
					logger.debug(f"Creating parent directory: {parentDir}")
					os.makedirs(parentDir, exist_ok=True) # exist_ok=True prevents error if dir exists
				except OSError as e:
					errMsg = f"Failed to create parent directory '{parentDir}' for clone target '{localPath}': {e}"
					logger.error(errMsg)
					raise GitHubError(errMsg) from e

			cloneUrl: str = repoUrlOrPath

			# --- Authentication Warning/Info ---
			if authToken and cloneUrl.startswith("https://"):
				logger.warning("An auth token was provided, but direct token injection into HTTPS URLs is insecure and disabled.")
				logger.warning("Cloning will rely on Git's credential manager (e.g., git-credential-manager, osxkeychain).")
				logger.warning("Ensure a credential helper is configured if authentication is required.")
			elif cloneUrl.startswith("git@"):
				logger.info("Cloning via SSH protocol. Ensure SSH key is configured and accessible (e.g., via ssh-agent).")
			else: # http or other protocols
				logger.info(f"Cloning via {cloneUrl.split(':')[0]} protocol. Ensure Git credentials/config are appropriate.")


			logger.info(f"Cloning '{repoUrlOrPath}'...") # Log original URL for clarity

			# --- Execute Clone with Progress ---
			repo: git.Repo = git.Repo.clone_from(
				url=cloneUrl,
				to_path=localPath,
				progress=progress_handler # Pass progress handler here
			)
			logger.info(f"Repository successfully cloned into '{localPath}'.")
			# Progress handler should emit 100% / END signal
			return repo

		except git.GitCommandError as e:
			# Provide more specific feedback based on stderr content
			stderrOutput: str = getattr(e, 'stderr', "No stderr output.").strip()
			# Enhanced check for authentication failure
			if "Authentication failed" in stderrOutput or "could not read Username" in stderrOutput or "Permission denied" in stderrOutput:
				errMsg: str = f"Authentication failed for '{repoUrlOrPath}'. "
				if repoUrlOrPath.startswith("https://"):
					errMsg += "Ensure the repository is public, or check Git's credential manager configuration (e.g., git-credential-manager) and ensure valid credentials (like a PAT) are stored."
				elif repoUrlOrPath.startswith("git@"):
					errMsg += "Check your SSH key setup (key exists, correct permissions, added to ssh-agent, registered with Git host)."
				else: # Other protocols
					errMsg += "Check relevant credentials or network configuration."
				logger.error(errMsg)
				raise GitHubError(errMsg) from e
			elif "repository not found" in stderrOutput or "does not exist" in stderrOutput:
				errMsg: str = f"Repository '{repoUrlOrPath}' not found or access denied. Verify the URL and your permissions."
				logger.error(errMsg)
				raise GitHubError(errMsg) from e
			elif "already exists and is not an empty directory" in stderrOutput:
				# This error might occur if Case 1 check failed unexpectedly or race condition
				errMsg: str = f"Target directory '{localPath}' already exists and is not empty or not a valid Git repository. Please check the path or clear the directory if appropriate."
				logger.error(errMsg)
				raise GitHubError(errMsg) from e
			else:
				# Generic Git command error
				errMsg: str = f"Git command failed during clone/load: {e.command} - Status: {e.status}\nStderr: {stderrOutput}"
				logger.error(errMsg, exc_info=False) # Log less detail for common git errors
				raise GitHubError(errMsg) from e
		except Exception as e:
			# Catch other potential errors (network issues, invalid paths etc.)
			errMsg: str = f"An unexpected error occurred during clone/load: {e}"
			logger.error(errMsg, exc_info=True) # Log full trace for unexpected
			raise GitHubError(errMsg) from e

	def pullRepository(
		self: 'GitHubHandler',
		repoPath: str,
		remoteName: str = 'origin',
		branchName: str = 'main',
		progress_handler: Optional[GitProgressHandler] = None
	) -> Tuple[str, bool]:
		"""
		Pulls changes from the specified remote and branch into the local repository.

		Args:
			repoPath (str): The path to the local Git repository.
			remoteName (str): The name of the remote to pull from. Defaults to 'origin'.
			branchName (str): The name of the branch to pull. Defaults to 'main'.
			progress_handler (Optional[GitProgressHandler]): Handler for progress updates.

		Returns:
			Tuple[str, bool]: (message, had_conflicts)
							  A status message indicating the outcome (e.g., "Already up to date", "Pulled new commits").
							  A boolean indicating if conflicts likely occurred (True if repo is dirty after pull).

		Raises:
			GitHubError: If the repository is invalid, the remote/branch doesn't exist,
						 pulling fails due to network issues, authentication, or other Git errors.
		"""
		logger.info(f"Attempting to pull '{remoteName}/{branchName}' into '{repoPath}'")
		try:
			repo: git.Repo = git.Repo(repoPath)

			# Ensure local branch matches the one we intend to pull into
			# Handle detached HEAD state
			try:
				active_branch_name = repo.active_branch.name
			except TypeError as e:
				if "HEAD is a detached symbolic reference" in str(e):
					errMsg = f"Repository at '{repoPath}' is in a detached HEAD state. Cannot pull automatically. Please checkout a branch first (e.g., 'git checkout {branchName}')."
					logger.error(errMsg)
					raise GitHubError(errMsg) from e
				else: # Other unexpected TypeError
					errMsg = f"Could not determine active branch in '{repoPath}': {e}"
					logger.error(errMsg, exc_info=True)
					raise GitHubError(errMsg) from e

			if active_branch_name != branchName:
				logger.warning(f"Current active branch '{active_branch_name}' differs from target pull branch '{branchName}'. Pulling into '{branchName}' anyway.")
				# Consider checking out branchName first? For now, proceed.

			# Check if repository is dirty *before* pulling
			if self.isDirty(repoPath):
				errMsg = f"Repository '{repoPath}' has uncommitted changes. Please commit or stash them before pulling."
				logger.error(errMsg)
				raise GitHubError(errMsg)

			# Get the remote
			try:
				remote: git.Remote = repo.remote(name=remoteName)
			except ValueError:
				errMsg = f"Remote '{remoteName}' does not exist in the repository at '{repoPath}'. Cannot pull."
				logger.error(errMsg)
				raise GitHubError(errMsg)

			# Execute pull
			logger.debug(f"Executing pull from {remoteName}/{branchName}...")
			fetch_info_list: List[git.FetchInfo] = remote.pull(refspec=branchName, progress=progress_handler)

			# Analyse FetchInfo results (pull is essentially fetch + merge)
			status_messages: List[str] = []
			new_commits_pulled = False
			errors_found = False
			for info in fetch_info_list:
				# Simplified status interpretation
				if info.flags & git.FetchInfo.ERROR:
					errors_found = True
					status_messages.append(f"Error pulling {info.name or 'ref'}: {info.note or 'Unknown error'}")
				elif info.flags & git.FetchInfo.REJECTED:
					errors_found = True # Treat rejection as an error state for pulling
					status_messages.append(f"Pull rejected {info.name or 'ref'}: {info.note or 'Unknown reason'}")
				elif info.flags & git.FetchInfo.HEAD_UPTODATE:
					status_messages.append(f"Branch '{info.name or branchName}' already up-to-date.")
				elif info.flags & (git.FetchInfo.NEW_TAG | git.FetchInfo.NEW_HEAD | git.FetchInfo.FORCED_UPDATE | git.FetchInfo.FAST_FORWARD):
					new_commits_pulled = True
					status_messages.append(f"Pulled changes for '{info.name or branchName}'.") # Use branchName if info.name is None
				# Add other flags if needed, e.g., DELETED
				# else: # General status if flags are unexpected or 0
				#     status_messages.append(f"Pull status for '{info.name or 'ref'}': Flags={info.flags}, Note: {info.note}")

			# Consolidate messages
			if not status_messages:
				# If list is empty, it might still be okay (e.g., fetching branch already present)
				# Check if repo state suggests success or if fetch_info_list was truly empty
				final_message = "Pull completed. Repository likely up-to-date." # Assume okay if no errors/updates reported
			else:
				final_message = " ".join(status_messages)

			if errors_found:
				logger.error(f"Pull operation encountered errors: {final_message}")
				# Raise error if significant issues detected
				raise GitHubError(f"Pull operation failed: {final_message}")

			logger.info(f"Pull operation finished. Status: {final_message}")

			# Check dirty status *after* pulling to detect potential merge conflicts
			repo_is_dirty_after_pull = self.isDirty(repoPath)
			if repo_is_dirty_after_pull:
				logger.warning("Repository is dirty after pulling. Merge conflicts likely occurred. Manual resolution required.")
				final_message += " WARNING: Conflicts likely occurred, manual resolution needed."

			if progress_handler and hasattr(progress_handler, '_emitter'):
				progress_handler._emitter.progressUpdate.emit(100, "Pull complete.")
			return final_message, repo_is_dirty_after_pull

		except git.InvalidGitRepositoryError:
			errMsg = f"'{repoPath}' is not a valid Git repository."
			logger.error(errMsg)
			raise GitHubError(errMsg) from None
		except git.GitCommandError as e:
			stderrOutput: str = getattr(e, 'stderr', "No stderr output.").strip()
			# Check for specific pull-related errors
			if "You have unstaged changes" in stderrOutput or "Your local changes would be overwritten by merge" in stderrOutput:
				errMsg = f"Pull aborted: Repository has uncommitted changes that would be overwritten. Please commit or stash them first."
			elif "Authentication failed" in stderrOutput or "Permission denied" in stderrOutput:
				errMsg = f"Authentication failed during pull from '{remoteName}'. Check credentials/SSH keys."
			elif "could not resolve host" in stderrOutput.lower():
				errMsg = f"Network error during pull: Could not resolve host '{remoteName}'."
			elif "Connection timed out" in stderrOutput:
				errMsg = f"Network error during pull: Connection timed out."
			elif "fatal: refusing to merge unrelated histories" in stderrOutput:
				errMsg = "Pull failed: Refusing to merge unrelated histories. Ensure branches have common ancestry or use '--allow-unrelated-histories' manually if intended."
			elif "couldn't find remote ref" in stderrOutput:
				errMsg = f"Pull failed: Remote branch '{branchName}' likely does not exist on remote '{remoteName}'."
			else:
				errMsg = f"Git command failed during pull: {e.command} - Status: {e.status}\nStderr: {stderrOutput}"
			logger.error(errMsg, exc_info=False)
			raise GitHubError(errMsg) from e
		except GitHubError as e: # Re-raise GitHubErrors (e.g., dirty repo before pull)
			raise e
		except Exception as e:
			errMsg = f"An unexpected error occurred during pull: {e}"
			logger.error(errMsg, exc_info=True)
			raise GitHubError(errMsg) from e

	def listFiles(self: 'GitHubHandler', repoPath: str, excludeGitDir: bool = True) -> List[str]:
		"""
		Lists all files tracked by Git within the local repository.

		Uses the `git ls-files` command for efficiency, returning paths relative
		to the repository root.

		Args:
			repoPath (str): The file system path to the root of the local Git repository.
			excludeGitDir (bool): Whether to explicitly filter out any paths starting
								  with '.git/'. Defaults to True.

		Returns:
			List[str]: A list of relative file paths tracked by Git.

		Raises:
			GitHubError: If the `repoPath` is not a valid Git repository or if the
						 `git ls-files` command fails.
		"""
		logger.debug(f"Listing files in repository: {repoPath}")
		try:
			# Ensure the path points to a valid repository
			repo: git.Repo = git.Repo(repoPath)
			gitCmd: git.Git = repo.git
			# Execute 'git ls-files' to get tracked files
			trackedFilesStr: str = gitCmd.ls_files()
			# Split the output into a list of file paths
			fileList: List[str] = trackedFilesStr.splitlines()

			# Filter out '.git/' directory contents if requested
			if excludeGitDir:
				# Although ls-files usually doesn't list .git contents, filter just in case
				# Normalise separators for consistent check
				git_dir_prefix_unix = ".git/"
				git_dir_prefix_win = ".git\\"
				fileList = [f for f in fileList if not (f.startswith(git_dir_prefix_unix) or f.startswith(git_dir_prefix_win))]

			logger.info(f"Found {len(fileList)} tracked files in '{repoPath}'.")
			return fileList
		except git.InvalidGitRepositoryError:
			errMsg: str = f"'{repoPath}' is not a valid Git repository."
			logger.error(errMsg)
			raise GitHubError(errMsg) from None
		except git.GitCommandError as e:
			stderrOutput: str = getattr(e, 'stderr', "No stderr output.").strip()
			errMsg: str = f"Git command 'ls-files' failed in '{repoPath}': {stderrOutput}"
			logger.error(errMsg, exc_info=False)
			raise GitHubError(errMsg) from e
		except Exception as e:
			errMsg: str = f"An unexpected error occurred listing files in '{repoPath}': {e}"
			logger.error(errMsg, exc_info=True)
			raise GitHubError(errMsg) from e

	def readFileContent(self: 'GitHubHandler', repoPath: str, filePath: str) -> str:
		"""
		Reads the content of a specific file within the local repository.

		Constructs the full path and reads the file, attempting UTF-8 decoding.
		Includes path validation to prevent access outside the repository root.

		Args:
			repoPath (str): The path to the local Git repository root.
			filePath (str): The relative path of the file within the repository
							(e.g., 'src/main.py').

		Returns:
			str: The decoded content of the file as a string.

		Raises:
			GitHubError: If the repository path is invalid, the file does not exist,
						 the path attempts traversal, there's an error reading the
						 file (e.g., permissions), or if the file cannot be decoded
						 using UTF-8 (indicating it might be binary or use a
						 different encoding).
		"""
		# Construct the absolute path to the file
		fullPath: str = os.path.normpath(os.path.join(repoPath, filePath))
		logger.debug(f"Reading file content from: {fullPath}")

		# --- Path Validation ---
		try:
			# Resolve symbolic links and normalize before checking common prefix
			resolvedRepoPath = os.path.realpath(repoPath)
			resolvedFullPath = os.path.realpath(fullPath)

			# Check if the resolved full path is within the resolved repository path
			common_prefix = os.path.commonpath([resolvedRepoPath, resolvedFullPath])
			# Enhanced check: ensure resolved path starts with repo path + separator (or is identical)
			# Handle case where repo path might not have trailing separator
			if common_prefix != resolvedRepoPath or not (resolvedFullPath == resolvedRepoPath or resolvedFullPath.startswith(resolvedRepoPath + os.sep)):
				errMsg = f"Invalid file path '{filePath}' attempts to access outside repository root '{repoPath}' after path resolution."
				logger.error(errMsg)
				raise GitHubError(errMsg)
		except OSError as e: # Catch potential errors during realpath resolution
			errMsg = f"Error resolving file path '{fullPath}' or repo path '{repoPath}': {e}"
			logger.error(errMsg)
			raise GitHubError(errMsg) from e
		except Exception as e: # Catch unexpected errors during path checks
			errMsg = f"Unexpected error validating path for '{filePath}': {e}"
			logger.error(errMsg, exc_info=True)
			raise GitHubError(errMsg) from e


		# Check for file existence and type before attempting to open
		if not os.path.exists(fullPath):
			errMsg: str = f"File not found at calculated path: '{fullPath}' (relative: '{filePath}')"
			logger.error(errMsg)
			raise GitHubError(errMsg)
		if not os.path.isfile(fullPath):
			errMsg: str = f"Path exists but is not a file: '{fullPath}' (relative: '{filePath}')"
			logger.error(errMsg)
			raise GitHubError(errMsg)

		try:
			# Read the file content, trying UTF-8 first
			with open(fullPath, 'r', encoding='utf-8', errors='strict') as fileHandle:
				content: str = fileHandle.read()
			logger.debug(f"Successfully read content from '{filePath}'. Length: {len(content)}")
			return content
		except UnicodeDecodeError as e:
			errMsg: str = f"Could not decode file '{filePath}' using UTF-8. It might be binary or use a different encoding. Error: {e}"
			logger.error(errMsg)
			# Raise error indicating likely non-text file
			raise GitHubError(errMsg) from e
		except FileNotFoundError:
			# Defensive check, should be caught by os.path.exists earlier
			errMsg: str = f"File unexpectedly not found during read: '{fullPath}'"
			logger.error(errMsg)
			raise GitHubError(errMsg)
		except IOError as e:
			# Handles permission errors, etc.
			errMsg: str = f"IO error reading file '{filePath}': {e}"
			logger.error(errMsg, exc_info=True)
			raise GitHubError(errMsg) from e
		except Exception as e:
			errMsg: str = f"An unexpected error occurred reading file '{filePath}': {e}"
			logger.error(errMsg, exc_info=True)
			raise GitHubError(errMsg) from e

	def isDirty(self: 'GitHubHandler', repoPath: str) -> bool:
		"""
		Checks if the repository working directory has any uncommitted changes
		(staged or unstaged) or untracked files.

		Uses `git status --porcelain` for a comprehensive check.

		Args:
			repoPath (str): The path to the local Git repository.

		Returns:
			bool: True if there are uncommitted changes or untracked files,
				  False otherwise.

		Raises:
			GitHubError: If the `repoPath` is not a valid Git repository or if the
						 `git status` command fails.
		"""
		logger.debug(f"Checking repository status (isDirty) for: {repoPath}")
		try:
			repo: git.Repo = git.Repo(repoPath)
			gitCmd: git.Git = repo.git
			# Execute 'git status --porcelain'
			# Empty output indicates a clean working directory and index
			statusOutput: str = gitCmd.status(porcelain=True)
			is_dirty = bool(statusOutput) # True if the string is not empty
			logger.info(f"Repository dirty status for '{repoPath}': {is_dirty}")
			if is_dirty:
				# Log first few lines of status for context if dirty
				status_lines = statusOutput.splitlines()
				logger.debug(f"Porcelain status output (first 5 lines):\n" + "\n".join(status_lines[:5]))
			return is_dirty
		except git.InvalidGitRepositoryError:
			errMsg = f"'{repoPath}' is not a valid Git repository."
			logger.error(errMsg)
			raise GitHubError(errMsg) from None
		except git.GitCommandError as e:
			stderrOutput: str = getattr(e, 'stderr', "No stderr output.").strip()
			errMsg = f"Git command 'status' failed in '{repoPath}': {stderrOutput}"
			logger.error(errMsg, exc_info=False)
			raise GitHubError(errMsg) from e
		except Exception as e:
			errMsg = f"An unexpected error occurred checking repository status in '{repoPath}': {e}"
			logger.error(errMsg, exc_info=True)
			raise GitHubError(errMsg) from e

	def _check_branch_status(self: 'GitHubHandler', repo: git.Repo, remoteName: str, branchName: str, progress_handler: Optional[GitProgressHandler] = None) -> Tuple[bool, str]:
		"""
		Internal helper to check if the local branch is behind or diverged from its remote tracking branch.
		Performs a 'git fetch' first.

		Args:
			repo (git.Repo): The repository object.
			remoteName (str): The name of the remote.
			branchName (str): The name of the local branch.
			progress_handler (Optional[GitProgressHandler]): Handler for progress updates.

		Returns:
			Tuple[bool, str]: (is_behind_or_diverged_or_error, message)
							  True if behind, diverged, or an error occurred checking.
							  False if up-to-date or ahead.
							  Message provides details.
		"""
		try:
			logger.info(f"Checking status of branch '{branchName}' against remote '{remoteName}'...")
			# Ensure local branch exists
			local_branch = next((b for b in repo.branches if b.name == branchName), None)
			if not local_branch:
				return True, f"Local branch '{branchName}' does not exist."

			# Ensure remote exists
			try:
				remote = repo.remote(name=remoteName)
			except ValueError:
				return True, f"Remote '{remoteName}' does not exist."

			# Fetch latest updates from the remote
			logger.debug(f"Fetching from remote '{remoteName}'...")
			try:
				remote.fetch(prune=True, progress=progress_handler)
			except git.GitCommandError as fetch_err:
				stderrOutput = getattr(fetch_err, 'stderr', 'N/A').strip()
				if "Authentication failed" in stderrOutput or "Permission denied" in stderrOutput:
					errMsg = f"Authentication failed fetching from remote '{remoteName}'. Cannot check branch status."
				elif "could not resolve host" in stderrOutput.lower():
					errMsg = f"Network error fetching from remote '{remoteName}'. Cannot check branch status."
				else:
					errMsg = f"Could not fetch from remote '{remoteName}'. Push aborted to prevent potential issues. Error: {stderrOutput}"
				logger.warning(errMsg)
				return True, errMsg
			except Exception as fetch_exc: # Catch other potential fetch errors
				errMsg = f"Unexpected error fetching from remote '{remoteName}': {fetch_exc}. Cannot check branch status."
				logger.warning(errMsg, exc_info=True)
				return True, errMsg


			# Find the remote tracking branch
			tracking_branch = local_branch.tracking_branch()
			if not tracking_branch:
				# Branch might be local only or tracking not set up correctly.
				# Allow push attempt, remote will reject if needed.
				logger.warning(f"Local branch '{branchName}' is not tracking a remote branch on '{remoteName}'. Push will be attempted.")
				return False, f"Branch '{branchName}' not tracking remote. Push will be attempted."
			if not tracking_branch.is_valid():
				# Tracking branch points to a ref that no longer exists (e.g., remote branch deleted)
				logger.warning(f"Remote tracking branch '{tracking_branch.path}' for local branch '{branchName}' is invalid (likely deleted). Push will be attempted.")
				return False, f"Remote tracking branch for '{branchName}' is invalid. Push will be attempted."


			# Compare commit hashes
			local_commit = local_branch.commit
			remote_commit = tracking_branch.commit

			if local_commit == remote_commit:
				logger.info(f"Branch '{branchName}' is up-to-date with '{tracking_branch.path}'.")
				return False, f"Branch '{branchName}' is up-to-date."
			elif repo.is_ancestor(local_commit, remote_commit):
				# Remote has commits not in local -> behind
				logger.warning(f"Local branch '{branchName}' is behind remote tracking branch '{tracking_branch.path}'.")
				return True, f"Local branch '{branchName}' is behind remote. Please pull changes before pushing."
			elif repo.is_ancestor(remote_commit, local_commit):
				# Local has commits not in remote -> ahead (safe to push)
				logger.info(f"Local branch '{branchName}' is ahead of remote tracking branch '{tracking_branch.path}'.")
				return False, f"Branch '{branchName}' is ahead of remote."
			else:
				# Histories have diverged
				logger.warning(f"Local branch '{branchName}' has diverged from remote tracking branch '{tracking_branch.path}'.")
				return True, f"Local branch '{branchName}' has diverged from remote. Please pull and resolve conflicts before pushing."

		except git.GitCommandError as e:
			stderr = getattr(e, 'stderr', 'N/A')
			logger.error(f"Git command error during branch status check: {stderr}")
			return True, f"Error checking branch status: {stderr}" # Assume problematic if check fails
		except Exception as e:
			logger.error(f"Unexpected error during branch status check: {e}", exc_info=True)
			return True, f"Unexpected error checking branch status: {e}" # Assume problematic


	def updateRepo(
		self: 'GitHubHandler',
		repoPath: str,
		commitMessage: str,
		push: bool = True,
		remoteName: str = 'origin',
		branchName: str = 'main',
		progress_handler: Optional[GitProgressHandler] = None # For push progress (if implemented)
	) -> str:
		"""
		Commits staged changes and optionally pushes to the remote
		after checking if the local branch is behind its remote counterpart.

		Checks for staged changes. If staged changes exist, commits them using the
		provided message. If `push` is True, it first fetches the remote and checks
		if the local branch (`branchName`) is behind or has diverged from its tracking
		branch on `remoteName`. If it is behind/diverged, it raises a GitHubError
		prompting the user to pull. Otherwise, it attempts the push, relying on Git's
		credential management.

		Args:
			repoPath (str): The path to the local Git repository.
			commitMessage (str): The message to use for the commit.
			push (bool): If True, attempts to check remote status and push the commit.
						 Defaults to True.
			remoteName (str): The name of the Git remote to check against and push to.
							  Defaults to 'origin'.
			branchName (str): The name of the local branch to commit to and push from.
							  Defaults to 'main'.
			progress_handler (Optional[GitProgressHandler]): Progress handler for push (Limited support in GitPython).

		Returns:
			str: A success message indicating the outcome (e.g., "No staged changes detected.",
				 "Changes committed locally.", "Changes committed and pushed...").

		Raises:
			GitHubError: If committing or pushing fails, or if the push pre-check
						 determines the local branch is behind/diverged. Provides specific
						 messages for common issues.
		"""
		logger.info(f"Starting update process for repository: {repoPath}")
		try:
			repo: git.Repo = git.Repo(repoPath)
			gitCmd: git.Git = repo.git

			# 1. Check for STAGED changes specifically
			staged_diff = repo.index.diff("HEAD") # Diff staged changes against the last commit
			# Also check against empty tree if there are no commits yet (initial commit)
			has_staged_changes = bool(staged_diff) or (not repo.head.is_valid() and bool(repo.index.diff(None)))

			if not has_staged_changes:
				logger.info("No staged changes detected in the repository. Nothing to commit or push.")
				return "No staged changes detected."

			# 2. Commit STAGED changes (Staging is removed - must be done manually before clicking button)
			logger.info(f"Committing staged changes with message: '{commitMessage}'")
			repo.index.commit(commitMessage)
			logger.info("Commit successful.")

			# 3. Push changes (optional, with pre-check)
			if push:
				# --- Pre-push Check ---
				if progress_handler and hasattr(progress_handler, '_emitter'):
					progress_handler._emitter.progressUpdate.emit(-1, f"Checking status vs {remoteName}...")
				check_failed_or_behind, status_message = self._check_branch_status(repo, remoteName, branchName, progress_handler)
				if check_failed_or_behind:
					# If branch is behind, diverged, or status check failed, raise error before push attempt
					logger.error(f"Pre-push check failed: {status_message}")
					# Reset index to before the commit if push is aborted by pre-check
					logger.warning("Resetting index to HEAD~1 due to failed pre-push check...")
					try:
						repo.index.reset("HEAD~1", head=True) # Reset index and HEAD
						logger.info("Successfully reset commit due to failed pre-push check.")
					except git.GitCommandError as reset_err:
						logger.error(f"Failed to automatically reset commit after failed pre-push check: {reset_err}")
						# Still raise the original error, but add a note about the failed reset
						raise GitHubError(f"Push aborted. {status_message} (Failed to auto-reset local commit)") from reset_err
					raise GitHubError(f"Push aborted. {status_message} (Local commit has been reset)")
				else:
					logger.info(f"Pre-push check passed: {status_message}")

				# --- Proceed with Push ---
				logger.info(f"Attempting to push branch '{branchName}' to remote '{remoteName}'...")
				if progress_handler and hasattr(progress_handler, '_emitter'):
					progress_handler._emitter.progressUpdate.emit(0, f"Pushing to {remoteName}...")
				try:
					remote: git.Remote = repo.remote(name=remoteName)
				except ValueError:
					errMsg = f"Remote '{remoteName}' does not exist in the repository at '{repoPath}'. Cannot push."
					logger.error(errMsg)
					raise GitHubError(errMsg)

				# Authentication Info/Warning
				if remote.url.startswith("https://"):
					logger.info("Pushing via HTTPS. Ensure Git credential helper is configured.")
				elif remote.url.startswith("git@"):
					logger.info("Pushing via SSH. Ensure SSH key is configured.")
				else:
					logger.info(f"Pushing via {remote.url.split(':')[0]} protocol. Ensure credentials configured.")

				# Specify the refspec: local_branch:remote_branch
				refspec: str = f'{branchName}:{branchName}'
				logger.debug(f"Executing push with refspec: {refspec}")
				# Note: GitPython's push progress is less granular than clone.
				# The progress_handler might only get limited updates here.
				# Catch GitCommandError here for detailed push failure analysis
				try:
					pushInfoList: List[git.PushInfo] = remote.push(refspec=refspec, progress=progress_handler)
				except git.GitCommandError as push_error:
					stderrOutput = getattr(push_error, 'stderr', "No stderr output.").strip()
					logger.error(f"Git command 'push' failed. Stderr: {stderrOutput}", exc_info=False)
					# Analyse stderr for common push failures
					if "Authentication failed" in stderrOutput or "Permission denied" in stderrOutput:
						errMsg = f"Authentication failed during push to '{remoteName}'. Check credentials/SSH keys."
					elif "Updates were rejected because the remote contains work that you do" in stderrOutput:
						errMsg = f"Push rejected. Remote branch '{remoteName}/{branchName}' has changes not present locally. Please pull changes before pushing."
					elif "src refspec" in stderrOutput and "does not match any" in stderrOutput:
						errMsg = f"Push failed: Local branch '{branchName}' or specified refspec does not exist or match."
					elif "repository not found" in stderrOutput:
						errMsg = f"Push failed: Remote repository '{remote.url}' not found or access denied."
					elif "Connection timed out" in stderrOutput or "Could not resolve host" in stderrOutput:
						errMsg = f"Network error during push: {stderrOutput}"
					else: # Generic push error
						errMsg = f"Push to remote '{remoteName}' failed. Git error: {stderrOutput}"
					raise GitHubError(errMsg) from push_error


				# Check push results for non-fatal errors reported by GitPython (less common than command errors)
				pushSucceeded = True
				errorMessages: List[str] = []
				pushSummary = ""
				for info in pushInfoList:
					# Build summary regardless of error for logging
					local_ref_name = info.local_ref.name if info.local_ref else 'N/A'
					remote_ref_str = info.remote_ref_string or 'N/A'
					summary_note = info.summary.strip() if info.summary else 'No summary'
					pushSummary += f"[{local_ref_name} -> {remote_ref_str}: {summary_note}] "

					# Check flags for various error conditions reported by PushInfo
					if info.flags & git.PushInfo.ERROR:
						pushSucceeded = False
						errMsg = f"Push error reported by GitPython for ref '{remote_ref_str}': {summary_note}"
						errorMessages.append(errMsg)
					elif info.flags & (git.PushInfo.REJECTED | git.PushInfo.REMOTE_REJECTED):
						# Should ideally be caught by command error or pre-check, but check flags just in case
						pushSucceeded = False
						reason = summary_note or "Likely requires pulling changes first"
						errMsg = f"Push rejected for ref '{remote_ref_str}'. Reason: {reason}"
						errorMessages.append(errMsg)

				if not pushSucceeded:
					# Combine error messages and raise
					fullErrorMsg = "Push operation failed after command execution.\nDetails:\n" + "\n".join(errorMessages)
					logger.error(fullErrorMsg)
					if progress_handler and hasattr(progress_handler, '_emitter'):
						progress_handler._emitter.progressUpdate.emit(100, "Push failed.")
					raise GitHubError(fullErrorMsg)

				logger.info(f"Changes successfully pushed to '{remoteName}/{branchName}'. Summary: {pushSummary.strip()}")
				if progress_handler and hasattr(progress_handler, '_emitter'):
					progress_handler._emitter.progressUpdate.emit(100, "Push complete.")
				successMsg = f"Changes committed and pushed to '{remoteName}/{branchName}'."
			else:
				logger.info("Skipping push step as requested.")
				successMsg = "Changes committed locally."

			return successMsg

		except git.InvalidGitRepositoryError:
			errMsg = f"'{repoPath}' is not a valid Git repository."
			logger.error(errMsg)
			raise GitHubError(errMsg) from None
		except git.GitCommandError as e:
			# Catch errors during staging/commit phase if not push error
			stderrOutput = getattr(e, 'stderr', "No stderr output.").strip()
			if "nothing to commit" in stderrOutput:
				# This should be caught by the staged changes check, but handle defensively
				logger.warning(f"Git command '{e.command}' reported 'nothing to commit' after staged check. Status: {e.status}. Stderr: {stderrOutput}")
				# Double check staged status
				repo_check = git.Repo(repoPath)
				staged_diff_check = repo_check.index.diff("HEAD")
				has_staged_check = bool(staged_diff_check) or (not repo_check.head.is_valid() and bool(repo_check.index.diff(None)))
				if not has_staged_check:
					return "No staged changes needed committing."
				else: # Should not happen
					errMsg = f"Git reported 'nothing to commit' but repository seems to have staged changes. Commit failed? Command: {e.command}. Stderr: {stderrOutput}"
			elif "Changes not staged for commit" in stderrOutput:
				errMsg = f"Commit failed: No changes were staged. Staging might have failed. Stderr: {stderrOutput}"
			else: # Generic error during add/commit
				errMsg = f"Git command failed during update: {e.command} - Status: {e.status}\nStderr: {stderrOutput}"
			logger.error(errMsg, exc_info=False)
			raise GitHubError(errMsg) from e
		except GitHubError as e: # Re-raise specific GitHubErrors from push flag checking or pre-check
			raise e
		except Exception as e:
			errMsg = f"An unexpected error occurred during repository update: {e}"
			logger.error(errMsg, exc_info=True)
			raise GitHubError(errMsg) from e

# --- END: core/github_handler.py ---
