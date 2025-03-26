
# --- START: core/github_handler.py ---
# core/github_handler.py
"""
Handles interactions with Git repositories, including cloning, listing files,
reading file content, staging, committing, and pushing changes.
Uses the GitPython library.
"""
import git # Import the git library
import os
import logging
from typing import List, Optional # Use List from typing

from .exceptions import GitHubError

logger: logging.Logger = logging.getLogger(__name__)

class GitHubHandler:
	"""
	Provides methods to interact with Git repositories locally and remotely.
	"""
	def init(self: 'GitHubHandler') -> None:
		"""Initialises the GitHubHandler."""
		# TODO: Potentially accept configuration options (e.g., default remote)
		logger.debug("GitHubHandler initialised.")

def cloneRepository(
	self: 'GitHubHandler',
	repoUrlOrPath: str,
	localPath: str,
	authToken: Optional[str] = None
) -> git.Repo:
	"""
	Clones a Git repository from a URL or initialises from a local path.

	If localPath already exists and is a valid Git repo, it returns the Repo object.
	If it exists but is not a repo or is empty, it attempts to clone into it.
	Handles authentication for HTTPS via token in the URL.

	Args:
		repoUrlOrPath (str): The URL of the repository to clone (e.g., [https://github.com/user/repo.git](https://github.com/user/repo.git))
		                     or the path to an existing local repository.
		localPath (str): The local directory path where the repository should be cloned or exists.
		authToken (Optional[str]): A GitHub Personal Access Token (PAT) for private repos (HTTPS).

	Returns:
		git.Repo: The Repo object representing the cloned or existing repository.

	Raises:
		GitHubError: If cloning fails due to invalid URL, authentication issues,
		             network problems, Git command errors, or if localPath is invalid.
	"""
	logger.info(f"Attempting to clone/load repo '{repoUrlOrPath}' into '{localPath}'")

	try:
		# Case 1: Check if localPath is already a valid Git repository
		if os.path.isdir(localPath) and os.path.exists(os.path.join(localPath, '.git')):
			logger.info(f"'{localPath}' already exists and appears to be a Git repository. Loading existing repo.")
			try:
					repo: git.Repo = git.Repo(localPath)
					# # TODO: Optionally perform a 'git pull' here? Requires careful handling of conflicts.
					# repo.remotes.origin.pull()
					logger.info(f"Successfully loaded existing repository from '{localPath}'.")
					return repo
			except git.InvalidGitRepositoryError as e:
					errMsg = f"Directory '{localPath}' exists but is not a valid Git repository: {e}"
					logger.error(errMsg)
					raise GitHubError(errMsg) from e
			except Exception as e: # Catch other potential git.Repo errors
					errMsg = f"Error loading existing repository from '{localPath}': {e}"
					logger.error(errMsg, exc_info=True)
					raise GitHubError(errMsg) from e

		# Case 2: localPath does not exist or is an empty directory - proceed with cloning
		# Ensure the parent directory exists
		parentDir = os.path.dirname(localPath)
		if parentDir and not os.path.exists(parentDir):
				os.makedirs(parentDir, exist_ok=True)
				logger.debug(f"Created parent directory: {parentDir}")

		cloneUrl = repoUrlOrPath
		# Modify URL for authentication if token is provided (HTTPS only)
		# Assumes URL format like [https://github.com/user/repo.git](https://github.com/user/repo.git)
		# TODO: Handle SSH URLs if necessary (might require key management)
		if authToken and cloneUrl.startswith("https://"):
				# Insert token: https://<token>@[github.com/user/repo.git](https://github.com/user/repo.git)
				parts = cloneUrl.split("://")
				if len(parts) == 2:
						cloneUrl = f"{parts[0]}://{authToken}@{parts[1]}"
						logger.debug("Using auth token for HTTPS clone.")
				else:
						logger.warning("Could not inject auth token into potentially malformed URL.")

		logger.info(f"Cloning '{repoUrlOrPath}'...") # Log original URL for clarity
		# TODO: Implement progress reporting using a custom Progress class for GitPython
		#       This requires subclassing git.remote.RemoteProgress.
		# progressIndicator = CloneProgress() # Your custom progress class instance
		repo = git.Repo.clone_from(
				url=cloneUrl,
				to_path=localPath,
				# progress=progressIndicator # Pass progress handler here
		)
		logger.info(f"Repository successfully cloned into '{localPath}'.")
		return repo

	except git.GitCommandError as e:
		stderrOutput = e.stderr.strip() if e.stderr else "No stderr output."
		# Check for common errors
		if "Authentication failed" in stderrOutput:
			errMsg = f"Authentication failed for '{repoUrlOrPath}'. Check your credentials/token or repository permissions."
			logger.error(errMsg)
			raise GitHubError(errMsg) from e
		elif "repository not found" in stderrOutput or "does not exist" in stderrOutput:
			errMsg = f"Repository '{repoUrlOrPath}' not found or access denied."
			logger.error(errMsg)
			raise GitHubError(errMsg) from e
		elif "already exists and is not an empty directory" in stderrOutput:
			errMsg = f"Target directory '{localPath}' already exists and is not empty or not a valid repo."
			logger.error(errMsg)
			raise GitHubError(errMsg) from e
		else:
			errMsg = f"Git command failed during clone: {e.command} - Status: {e.status}\nStderr: {stderrOutput}"
			logger.error(errMsg, exc_info=True) # Include stack trace for generic errors
			raise GitHubError(errMsg) from e
	except Exception as e:
		# Catch other potential errors (network issues, invalid paths etc.)
		errMsg = f"An unexpected error occurred during clone/load: {e}"
		logger.error(errMsg, exc_info=True)
		raise GitHubError(errMsg) from e

def listFiles(self: 'GitHubHandler', repoPath: str, excludeGitDir: bool = True) -> List[str]:
	"""
	Lists all files tracked by Git within the local repository, relative to the repo root.

	Args:
		repoPath (str): The path to the local Git repository.
		excludeGitDir (bool): Whether to explicitly exclude files within the .git directory.

	Returns:
		List[str]: A list of relative file paths.

	Raises:
		GitHubError: If the path is not a valid Git repository or listing fails.
	"""
	logger.debug(f"Listing files in repository: {repoPath}")
	try:
		repo: git.Repo = git.Repo(repoPath)
		gitCmd: git.Git = repo.git
		# Use 'git ls-files' which lists tracked files efficiently
		trackedFilesStr: str = gitCmd.ls_files()
		fileList: List[str] = trackedFilesStr.splitlines() # Use List

		if excludeGitDir:
			# Although ls-files usually doesn't list .git contents, filter just in case
			fileList = [f for f in fileList if not f.startswith('.git/')]

		logger.info(f"Found {len(fileList)} tracked files in '{repoPath}'.")
		# TODO: Add filtering options? (e.g., exclude binary files, specific extensions?)
		return fileList
	except git.InvalidGitRepositoryError:
		errMsg = f"'{repoPath}' is not a valid Git repository."
		logger.error(errMsg)
		raise GitHubError(errMsg)
	except git.GitCommandError as e:
		errMsg = f"Git command 'ls-files' failed in '{repoPath}': {e.stderr}"
		logger.error(errMsg, exc_info=True)
		raise GitHubError(errMsg) from e
	except Exception as e:
		errMsg = f"An unexpected error occurred listing files in '{repoPath}': {e}"
		logger.error(errMsg, exc_info=True)
		raise GitHubError(errMsg) from e

def readFileContent(self: 'GitHubHandler', repoPath: str, filePath: str) -> str:
	"""
	Reads the content of a specific file within the local repository.

	Args:
		repoPath (str): The path to the local Git repository.
		filePath (str): The relative path of the file within the repository.

	Returns:
		str: The content of the file.

	Raises:
		GitHubError: If the repository is invalid, the file does not exist,
		             or there's an error reading the file (e.g., encoding).
	"""
	logger.debug(f"Reading file content: {os.path.join(repoPath, filePath)}")
	fullPath: str = os.path.join(repoPath, filePath)

	# Basic check first to avoid unnecessary repo loading for simple non-existence
	if not os.path.exists(fullPath) or not os.path.isfile(fullPath):
		errMsg = f"File not found at path: '{fullPath}'"
		logger.error(errMsg)
		raise GitHubError(errMsg) # Or could raise FileNotFoundError? Stick to GitHubError for consistency.

	try:
		# Verify repo context (optional, but good practice)
		repo: git.Repo = git.Repo(repoPath) # Raises InvalidGitRepositoryError if repoPath invalid

		# Read the file content
		# TODO: Handle potential large files? Read in chunks? For LLM context, full read is often needed.
		with open(fullPath, 'r', encoding='utf-8', errors='ignore') as fileHandle:
			content: str = fileHandle.read()
		logger.debug(f"Successfully read content from '{filePath}'. Length: {len(content)}")
		return content
	except git.InvalidGitRepositoryError:
		errMsg = f"'{repoPath}' is not a valid Git repository while trying to read '{filePath}'."
		logger.error(errMsg)
		raise GitHubError(errMsg)
	except FileNotFoundError:
		# This shouldn't be reached due to the initial check, but handle defensively
		errMsg = f"File not found: '{fullPath}'"
		logger.error(errMsg)
		raise GitHubError(errMsg)
	except UnicodeDecodeError as e:
		errMsg = f"Could not decode file '{filePath}' using UTF-8. It might be binary or use a different encoding: {e}"
		logger.error(errMsg)
		# TODO: Decide how to handle binary files. Skip them? Return placeholder? Raise specific error?
		raise GitHubError(errMsg) from e
	except IOError as e:
		errMsg = f"IO error reading file '{filePath}': {e}"
		logger.error(errMsg, exc_info=True)
		raise GitHubError(errMsg) from e
	except Exception as e:
		errMsg = f"An unexpected error occurred reading file '{filePath}': {e}"
		logger.error(errMsg, exc_info=True)
		raise GitHubError(errMsg) from e

def updateRepo(
	self: 'GitHubHandler',
	repoPath: str,
	commitMessage: str,
	push: bool = True,
	remoteName: str = 'origin',
	branchName: str = 'main',
	authToken: Optional[str] = None # Needed for push via HTTPS
) -> str:
	"""
	Stages all changes, commits them, and optionally pushes to the remote repository.

	Args:
		repoPath (str): The path to the local Git repository.
		commitMessage (str): The commit message.
		push (bool): Whether to push the changes to the remote repository (default: True).
		remoteName (str): The name of the remote to push to (default: 'origin').
		branchName (str): The name of the branch to push (default: 'main').
		authToken (Optional[str]): GitHub PAT for authentication if pushing via HTTPS.

	Returns:
		str: A success message indicating completion.

	Raises:
		GitHubError: If staging, committing, or pushing fails.
	"""
	logger.info(f"Starting update process for repository: {repoPath}")
	try:
		repo: git.Repo = git.Repo(repoPath)
		gitCmd: git.Git = repo.git

		# 1. Check for changes
		if not repo.is_dirty(untracked_files=True):
			logger.info("No changes detected in the repository. Nothing to commit or push.")
			return "No changes detected."

		# 2. Stage all changes (including untracked files)
		logger.info("Staging changes...")
		gitCmd.add(A=True) # Stage all changes (-A flag)
		logger.debug("Changes staged successfully.")

		# 3. Commit changes
		logger.info(f"Committing changes with message: '{commitMessage}'")
		repo.index.commit(commitMessage)
		logger.info("Commit successful.")

		# 4. Push changes (optional)
		if push:
			logger.info(f"Attempting to push changes to remote '{remoteName}' branch '{branchName}'...")
			# TODO: Handle authentication more robustly if needed (e.g., credential helper)
			# For HTTPS push with token, GitPython often requires the token in the remote URL
			# Or relies on a configured credential helper. Let's assume helper or SSH for now,
			# but add URL modification as a fallback if needed.

			remote: git.Remote = repo.remote(name=remoteName)

			# --- Authentication Handling (Example - Needs Refinement) ---
			pushUrl = remote.url
			if authToken and pushUrl.startswith("https://"):
					parts = pushUrl.split("://")
					if len(parts) == 2 and '@' not in parts[1]: # Avoid double-adding token
							pushUrl = f"{parts[0]}://{authToken}@{parts[1]}"
							logger.debug("Using auth token for HTTPS push.")
							# Temporarily set the URL? Or rely on credential helper?
							# Setting URL might be complex if user switches remotes often.
							# For simplicity, we rely on external config (credential helper/SSH key)
							# Or let GitPython/Git handle it if the URL already contains the token.
							# If push fails with auth error, suggest setting up a helper or using SSH.
					else:
							logger.warning("Cannot inject auth token for push URL, relying on existing config.")

			# TODO: Implement progress reporting for push if possible (harder with GitPython)
			pushInfoList: List[git.PushInfo] = remote.push(refspec=f'{branchName}:{branchName}') # Use List

			# Check push results
			pushSucceeded = True
			errorMessages: List[str] = [] # Use List
			for pushInfo in pushInfoList:
					if pushInfo.flags & (git.PushInfo.ERROR | git.PushInfo.REJECTED | git.PushInfo.REMOTE_REJECTED):
							pushSucceeded = False
							errMsg = f"Push failed for remote '{remoteName}': Flags={pushInfo.flags}, Summary: {pushInfo.summary}"
							logger.error(errMsg)
							errorMessages.append(errMsg)
							# More detailed error checking based on flags
							if pushInfo.flags & git.PushInfo.REJECTED:
									errorMessages.append("  Reason: Push rejected (likely requires pulling first).")
							if pushInfo.flags & git.PushInfo.REMOTE_REJECTED:
									errorMessages.append("  Reason: Remote repository rejected the push (check permissions/hooks).")
							if pushInfo.flags & git.PushInfo.ERROR:
									errorMessages.append("  Reason: An unspecified error occurred during push.")

			if not pushSucceeded:
					raise GitHubError("Push operation failed. See details:\n" + "\n".join(errorMessages))

			logger.info(f"Changes successfully pushed to '{remoteName}/{branchName}'.")
			successMsg = f"Changes committed and pushed to '{remoteName}/{branchName}'."
		else:
			logger.info("Skipping push step as requested.")
			successMsg = "Changes committed locally."

		return successMsg

	except git.InvalidGitRepositoryError:
		errMsg = f"'{repoPath}' is not a valid Git repository."
		logger.error(errMsg)
		raise GitHubError(errMsg)
	except git.GitCommandError as e:
		stderrOutput = e.stderr.strip() if e.stderr else "No stderr output."
		# More specific error checking for commit/push
		if "nothing to commit" in stderrOutput and not repo.is_dirty(untracked_files=True):
			# This might occur if staging happened but commit failed, then retried
			logger.warning("Git reported 'nothing to commit', though changes were expected.")
			return "No changes needed committing." # Or raise error?
		elif "Authentication failed" in stderrOutput:
			errMsg = f"Authentication failed during push to remote '{remoteName}'. Check credentials/token."
			logger.error(errMsg)
			raise GitHubError(errMsg) from e
		# TODO: Add check for push rejection (needs pull first)
		elif "Updates were rejected because the remote contains work that you do" in stderrOutput:
			errMsg = f"Push rejected. Remote branch '{remoteName}/{branchName}' has changes not present locally. Please pull changes first."
			logger.error(errMsg)
			raise GitHubError(errMsg) from e
		else:
			errMsg = f"Git command failed during update: {e.command} - Status: {e.status}\nStderr: {stderrOutput}"
			logger.error(errMsg, exc_info=True)
			raise GitHubError(errMsg) from e
	except Exception as e:
		errMsg = f"An unexpected error occurred during repository update: {e}"
		logger.error(errMsg, exc_info=True)
		raise GitHubError(errMsg) from e

# TODO: Add methods for 'git status', 'git pull', 'git diff' if needed for UI feedback.
# TODO: Add method to check if a repo URL/path is valid before attempting clone?
#       (Requires different approach - maybe HEAD request for URLs?)
# --- END: core/github_handler.py ---