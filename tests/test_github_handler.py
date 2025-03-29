# Updated Codebase/tests/test_github_handler.py
# --- START: tests/test_github_handler.py ---
import unittest
import os
import git # Import git module itself for exception types and constants
from unittest.mock import patch, MagicMock, PropertyMock, call
# FIX: Import Any from typing
from typing import List, Any # For type hints

# Ensure imports work correctly assuming tests are run from the project root
# Adjust path if necessary based on your test runner setup
import sys
if '.' not in sys.path:
    sys.path.append('.') # Add project root if needed

from core.github_handler import GitHubHandler
from core.exceptions import GitHubError

# Dummy Progress class for mocking
class MockProgress:
    """ Mock progress reporter """
    # Use imported Any type hint
    def update(self, op_code: int, cur_count: Any, max_count: Any = None, message: str = '') -> None: # type: ignore
        """ Mock update method """
        pass # No-op for tests unless progress reporting needs verification

# Test Suite for GitHubHandler
class TestGitHubHandler(unittest.TestCase):
    """
    Unit tests for the GitHubHandler class.
    Mocks file system operations and the 'git' library extensively.
    """

    def setUp(self: 'TestGitHubHandler') -> None:
        """Set up test fixtures."""
        self.handler = GitHubHandler()
        self.repoUrl = "https://github.com/user/repo.git" # Corrected format
        self.sshRepoUrl = "git@github.com:user/repo.git"
        self.localPath = "/fake/local/repo"
        self.authToken = "dummy_pat_token" # Example Personal Access Token

        # Create a reusable mock repo instance for many tests
        self.mock_repo = MagicMock(spec=git.Repo)
        self.mock_repo.working_dir = self.localPath
        self.mock_git_cmd = MagicMock(spec=git.Git)
        self.mock_index = MagicMock(spec=git.IndexFile)
        self.mock_remote = MagicMock(spec=git.Remote)

        # Connect mocks using PropertyMock for attribute access
        type(self.mock_repo).git = PropertyMock(return_value=self.mock_git_cmd)
        type(self.mock_repo).index = PropertyMock(return_value=self.mock_index)
        # Simulate repo.remote('name') call returning our mock remote
        self.mock_repo.remote.return_value = self.mock_remote
        # Mock the URL attribute of the mock remote
        type(self.mock_remote).url = PropertyMock(return_value=self.repoUrl) # Default to HTTPS

        # Patch logger to suppress output during tests
        self.patcher = patch('core.github_handler.logger', MagicMock())
        self.mock_logger = self.patcher.start()

    def tearDown(self: 'TestGitHubHandler') -> None:
        """Stop logger patching."""
        self.patcher.stop()

    # --- Test cloneRepository ---

    @patch('os.path.isdir', return_value=False) # Target path does not exist
    @patch('os.path.dirname', return_value='/fake/local')
    @patch('os.path.exists') # Mock exists for parent dir check too
    @patch('os.makedirs')
    @patch('git.Repo.clone_from')
    def test_cloneRepo_success_newClone_https_noAuth(
        self: 'TestGitHubHandler', mock_clone_from: MagicMock, mock_makedirs: MagicMock,
        mock_exists: MagicMock, mock_dirname: MagicMock, mock_isdir: MagicMock
    ) -> None:
        """Test successful HTTPS cloning without providing auth token."""
        # Simulate parent dir exists
        mock_exists.side_effect = lambda p: p == '/fake/local'
        mock_clone_from.return_value = self.mock_repo # clone_from returns a repo object

        # Create a mock progress handler instance
        mock_progress = MockProgress()

        repo = self.handler.cloneRepository(self.repoUrl, self.localPath, None, progress_handler=mock_progress) # No auth token, pass mock progress

        self.assertEqual(repo, self.mock_repo)
        mock_isdir.assert_called_once_with(self.localPath)
        mock_dirname.assert_called_once_with(self.localPath)
        mock_exists.assert_called_once_with('/fake/local')
        mock_makedirs.assert_not_called() # Parent exists, no need to create

        # Check clone_from called with original URL (no token injection) and progress handler
        mock_clone_from.assert_called_once_with(url=self.repoUrl, to_path=self.localPath, progress=mock_progress)
        self.mock_logger.warning.assert_not_called() # No warning if token not provided

    @patch('os.path.isdir', return_value=False)
    @patch('git.Repo.clone_from')
    def test_cloneRepo_https_withAuth_warning(
        self: 'TestGitHubHandler', mock_clone_from: MagicMock, mock_isdir: MagicMock
    ) -> None:
        """Test that providing an auth token for HTTPS clone logs a warning."""
        with patch('os.path.exists'), patch('os.makedirs'): # Mock FS checks
            mock_clone_from.return_value = self.mock_repo
            # Create a mock progress handler instance
            mock_progress = MockProgress()

            repo = self.handler.cloneRepository(self.repoUrl, self.localPath, self.authToken, progress_handler=mock_progress)

            self.assertEqual(repo, self.mock_repo)
            # Verify the warning was logged
            self.mock_logger.warning.assert_any_call("An auth token was provided, but direct token injection into HTTPS URLs is insecure and disabled.")
            self.mock_logger.warning.assert_any_call("Cloning will rely on Git's credential manager (e.g., git-credential-manager).") # Updated message
            # Ensure clone was still called with the original URL and progress
            mock_clone_from.assert_called_once_with(url=self.repoUrl, to_path=self.localPath, progress=mock_progress)


    @patch('os.path.isdir', return_value=False)
    @patch('git.Repo.clone_from')
    def test_cloneRepo_ssh_noAuth_infoLog(
        self: 'TestGitHubHandler', mock_clone_from: MagicMock, mock_isdir: MagicMock
    ) -> None:
        """Test that cloning via SSH logs an informational message."""
        with patch('os.path.exists'), patch('os.makedirs'): # Mock FS checks
            mock_clone_from.return_value = self.mock_repo
            # Create a mock progress handler instance
            mock_progress = MockProgress()
            repo = self.handler.cloneRepository(self.sshRepoUrl, self.localPath, None, progress_handler=mock_progress) # No auth token

            self.assertEqual(repo, self.mock_repo)
            # Verify the info message was logged
            self.mock_logger.info.assert_any_call("Cloning via SSH protocol. Ensure SSH key is configured and accessible (e.g., via ssh-agent).")
            # Ensure clone was called with the SSH URL and progress
            mock_clone_from.assert_called_once_with(url=self.sshRepoUrl, to_path=self.localPath, progress=mock_progress)


    @patch('os.path.isdir', return_value=False)
    @patch('os.path.dirname', return_value='/fake/local')
    @patch('os.path.exists', return_value=False) # Parent does NOT exist initially
    @patch('os.makedirs')
    @patch('git.Repo.clone_from')
    def test_cloneRepo_success_newClone_parentDirCreated(
        self: 'TestGitHubHandler', mock_clone_from: MagicMock, mock_makedirs: MagicMock,
        mock_exists: MagicMock, mock_dirname: MagicMock, mock_isdir: MagicMock
    ) -> None:
        """Test successful cloning when parent directory needs creation."""
        mock_clone_from.return_value = self.mock_repo
        # Create a mock progress handler instance
        mock_progress = MockProgress()
        repo = self.handler.cloneRepository(self.repoUrl, self.localPath, None, progress_handler=mock_progress) # No auth token

        self.assertEqual(repo, self.mock_repo)
        mock_makedirs.assert_called_once_with('/fake/local', exist_ok=True)
        # Check clone_from called without auth token in URL but with progress
        mock_clone_from.assert_called_once_with(url=self.repoUrl, to_path=self.localPath, progress=mock_progress)

    @patch('os.path.isdir', return_value=True) # Path is a directory
    @patch('os.path.exists', return_value=True) # .git dir exists
    @patch('git.Repo') # Mock the Repo constructor
    def test_cloneRepo_success_existingValidRepo(
        self: 'TestGitHubHandler', mock_Repo_constructor: MagicMock, mock_exists: MagicMock, mock_isdir: MagicMock
    ) -> None:
        """Test loading an existing valid repository."""
        mock_Repo_constructor.return_value = self.mock_repo
        # Simulate successful fetch during load
        self.mock_remote.fetch.return_value = []

        # Create a mock progress handler instance
        mock_progress = MockProgress()

        repo = self.handler.cloneRepository("any_url_ignored", self.localPath, None, progress_handler=mock_progress)

        self.assertEqual(repo, self.mock_repo)
        mock_isdir.assert_called_once_with(self.localPath)
        mock_exists.assert_called_once_with(os.path.join(self.localPath, '.git'))
        mock_Repo_constructor.assert_called_once_with(self.localPath) # Verify Repo was initialized with path
        # Verify fetch was called (can check remote mock)
        self.mock_remote.fetch.assert_called_with(prune=True, progress=mock_progress)


    @patch('os.path.isdir', return_value=True) # Path is a directory
    @patch('os.path.exists', return_value=False) # .git dir does NOT exist
    @patch('git.Repo') # Mock Repo constructor
    @patch('git.Repo.clone_from') # Mock clone_from as well
    def test_cloneRepo_existingDir_notRepo_shouldClone(
        self: 'TestGitHubHandler', mock_clone_from: MagicMock, mock_Repo_constructor: MagicMock,
        mock_exists: MagicMock, mock_isdir: MagicMock
    ) -> None:
        """Test cloning into an existing empty/non-git directory."""
        # Repo constructor shouldn't be called if .git doesn't exist
        mock_clone_from.return_value = self.mock_repo
        # Create a mock progress handler instance
        mock_progress = MockProgress()

        repo = self.handler.cloneRepository(self.repoUrl, self.localPath, None, progress_handler=mock_progress)

        self.assertEqual(repo, self.mock_repo)
        mock_isdir.assert_called_once_with(self.localPath)
        mock_exists.assert_called_once_with(os.path.join(self.localPath, '.git'))
        mock_Repo_constructor.assert_not_called() # Should not try to load as existing repo
        mock_clone_from.assert_called_once_with(url=self.repoUrl, to_path=self.localPath, progress=mock_progress)

    @patch('os.path.isdir', return_value=False) # Not a directory
    @patch('git.Repo.clone_from', side_effect=git.GitCommandError('clone', 128, stderr='fatal: Authentication failed for \'https://github.com/\'...'))
    def test_cloneRepo_authFailure_https(
        self: 'TestGitHubHandler', mock_clone_from: MagicMock, mock_isdir: MagicMock
    ) -> None:
        """Test handling of authentication failure during HTTPS clone."""
        with patch('os.path.exists'), patch('os.makedirs'): # Mock FS checks
            with self.assertRaisesRegex(GitHubError, "Authentication failed .* Ensure the repository is public, or check Git's credential manager configuration"):
                self.handler.cloneRepository(self.repoUrl, self.localPath, None) # No token passed

    @patch('os.path.isdir', return_value=False) # Not a directory
    @patch('git.Repo.clone_from', side_effect=git.GitCommandError('clone', 128, stderr='git@github.com: Permission denied (publickey).'))
    def test_cloneRepo_authFailure_ssh(
        self: 'TestGitHubHandler', mock_clone_from: MagicMock, mock_isdir: MagicMock
    ) -> None:
        """Test handling of authentication failure during SSH clone."""
        with patch('os.path.exists'), patch('os.makedirs'): # Mock FS checks
            with self.assertRaisesRegex(GitHubError, "Authentication failed .* Check your SSH key setup"):
                self.handler.cloneRepository(self.sshRepoUrl, self.localPath, None)

    @patch('os.path.isdir', return_value=True) # Path exists
    @patch('os.path.exists', return_value=True) # .git exists
    @patch('git.Repo', side_effect=git.InvalidGitRepositoryError("Not a repo")) # Mock constructor raising error
    def test_cloneRepo_loadExisting_InvalidGitRepoError(
        self: 'TestGitHubHandler', mock_Repo_constructor: MagicMock, mock_exists: MagicMock, mock_isdir: MagicMock
    ) -> None:
        """Test loading an existing directory that is not a valid repo (InvalidGitRepositoryError)."""
        with self.assertRaisesRegex(GitHubError, "exists but is not a valid Git repository"):
            self.handler.cloneRepository("any_url", self.localPath, None)

    @patch('os.path.isdir', return_value=False) # Not a directory
    @patch('git.Repo.clone_from', side_effect=git.GitCommandError('clone', 128, stderr='fatal: repository \'https://github.com/user/repo.git/\' not found'))
    def test_cloneRepo_repoNotFound(
        self: 'TestGitHubHandler', mock_clone_from: MagicMock, mock_isdir: MagicMock
    ) -> None:
        """Test handling of repository not found error during clone."""
        with patch('os.path.exists'), patch('os.makedirs'): # Mock FS checks
            with self.assertRaisesRegex(GitHubError, "Repository .* not found or access denied"):
                self.handler.cloneRepository(self.repoUrl, self.localPath, None)

    @patch('os.path.isdir', return_value=False)
    @patch('git.Repo.clone_from', side_effect=git.GitCommandError('clone', 1, stderr='Could not resolve host: github.com'))
    def test_cloneRepo_networkError(self: 'TestGitHubHandler', mock_clone_from: MagicMock, mock_isdir: MagicMock) -> None:
        """Test handling network errors during clone."""
        with patch('os.path.exists'), patch('os.makedirs'): # Mock fs operations
            with self.assertRaisesRegex(GitHubError, "Git command failed.*Could not resolve host"):
                self.handler.cloneRepository(self.repoUrl, self.localPath, None)

    # --- Test listFiles ---

    @patch('git.Repo')
    def test_listFiles_success_excludeGitDir(self: 'TestGitHubHandler', mock_Repo_constructor: MagicMock) -> None:
        """Test successfully listing files, excluding .git dir contents."""
        mock_Repo_constructor.return_value = self.mock_repo
        # Simulate ls-files output - it usually doesn't include .git anyway, but test filter
        self.mock_git_cmd.ls_files.return_value = "file1.py\nsrc/main.py\n.git/config\nREADME.md"
        expectedFiles: List[str] = ["file1.py", "src/main.py", "README.md"] # Excludes .git/

        files = self.handler.listFiles(self.localPath, excludeGitDir=True)

        self.assertEqual(sorted(files), sorted(expectedFiles))
        mock_Repo_constructor.assert_called_once_with(self.localPath)
        self.mock_git_cmd.ls_files.assert_called_once()

    @patch('git.Repo')
    def test_listFiles_success_includeGitDir(self: 'TestGitHubHandler', mock_Repo_constructor: MagicMock) -> None:
        """Test successfully listing files including .git dir contents."""
        mock_Repo_constructor.return_value = self.mock_repo
        self.mock_git_cmd.ls_files.return_value = "file1.py\nsrc/main.py\n.git/config"
        expectedFiles: List[str] = ["file1.py", "src/main.py", ".git/config"]

        files = self.handler.listFiles(self.localPath, excludeGitDir=False)

        self.assertEqual(sorted(files), sorted(expectedFiles))
        mock_Repo_constructor.assert_called_once_with(self.localPath)
        self.mock_git_cmd.ls_files.assert_called_once()

    @patch('git.Repo')
    def test_listFiles_emptyRepo(self: 'TestGitHubHandler', mock_Repo_constructor: MagicMock) -> None:
        """Test listing files in an empty repository (or repo with no tracked files)."""
        mock_Repo_constructor.return_value = self.mock_repo
        self.mock_git_cmd.ls_files.return_value = "" # No files tracked
        expectedFiles: List[str] = []

        files = self.handler.listFiles(self.localPath)

        self.assertEqual(files, expectedFiles)
        mock_Repo_constructor.assert_called_once_with(self.localPath)
        self.mock_git_cmd.ls_files.assert_called_once()

    @patch('git.Repo', side_effect=git.InvalidGitRepositoryError)
    def test_listFiles_invalidRepo(self: 'TestGitHubHandler', mock_Repo_constructor: MagicMock) -> None:
        """Test listing files in an invalid repository path."""
        with self.assertRaisesRegex(GitHubError, "not a valid Git repository"):
            self.handler.listFiles(self.localPath)

    @patch('git.Repo')
    def test_listFiles_gitCommandError(self: 'TestGitHubHandler', mock_Repo_constructor: MagicMock) -> None:
        """Test handling GitCommandError during ls-files."""
        mock_Repo_constructor.return_value = self.mock_repo
        self.mock_git_cmd.ls_files.side_effect = git.GitCommandError('ls-files', 1, stderr='Some git error')

        with self.assertRaisesRegex(GitHubError, "Git command 'ls-files' failed"):
            self.handler.listFiles(self.localPath)

    # --- Test readFileContent ---

    # Mock open globally for file reading tests
    @patch('builtins.open', new_callable=MagicMock)
    @patch('os.path.isfile', return_value=True)
    @patch('os.path.exists', return_value=True)
    @patch('os.path.realpath') # Mock realpath for security check
    def test_readFileContent_success(
        self: 'TestGitHubHandler', mock_realpath: MagicMock, mock_exists: MagicMock,
        mock_isfile: MagicMock, mock_open: MagicMock
    ) -> None:
        """Test successfully reading a file."""
        # Setup mock file handle and content
        mock_handle = MagicMock()
        mock_handle.read.return_value = "file content"
        # Configure the context manager part of the mock
        mock_open.return_value.__enter__.return_value = mock_handle

        # Simulate realpath returning paths that are inside the repo
        resolvedRepoPath = "/fake/local/repo" # Assume resolved repo path
        filePath = "src/main.py"
        fullPath = os.path.normpath(os.path.join(self.localPath, filePath))
        resolvedFullPath = os.path.normpath(os.path.join(resolvedRepoPath, filePath)) # Simulate resolved file path within repo

        def realpath_side_effect(p):
             norm_p = os.path.normpath(p)
             if norm_p == self.localPath: return resolvedRepoPath
             if norm_p == fullPath: return resolvedFullPath
             return os.path.abspath(p) # Fallback
        mock_realpath.side_effect = realpath_side_effect

        content = self.handler.readFileContent(self.localPath, filePath)

        self.assertEqual(content, "file content")
        # Check security path validation calls
        mock_realpath.assert_any_call(self.localPath)
        mock_realpath.assert_any_call(fullPath)
        # Check existence and type checks
        mock_exists.assert_called_once_with(fullPath)
        mock_isfile.assert_called_once_with(fullPath)
        # Check file open call
        mock_open.assert_called_once_with(fullPath, 'r', encoding='utf-8', errors='strict')

    @patch('os.path.realpath')
    @patch('os.path.exists', return_value=False) # Simulate file not existing
    def test_readFileContent_fileNotFound(
        self: 'TestGitHubHandler', mock_exists: MagicMock, mock_realpath: MagicMock
    ) -> None:
        """Test reading a file that does not exist."""
        mock_realpath.side_effect = lambda p: os.path.abspath(p) # Simulate realpath returning abs path
        filePath = "nonexistent.txt"
        fullPath = os.path.normpath(os.path.join(self.localPath, filePath))

        with self.assertRaisesRegex(GitHubError, "File not found at calculated path"):
            self.handler.readFileContent(self.localPath, filePath)
        mock_exists.assert_called_once_with(fullPath)

    @patch('os.path.realpath')
    @patch('os.path.exists', return_value=True)
    @patch('os.path.isfile', return_value=False) # Simulate path is not a file
    def test_readFileContent_pathIsNotFile(
        self: 'TestGitHubHandler', mock_isfile: MagicMock, mock_exists: MagicMock, mock_realpath: MagicMock
    ) -> None:
        """Test reading a path that exists but is not a file."""
        mock_realpath.side_effect = lambda p: os.path.abspath(p)
        filePath = "src" # A directory
        fullPath = os.path.normpath(os.path.join(self.localPath, filePath))

        with self.assertRaisesRegex(GitHubError, "Path exists but is not a file"):
            self.handler.readFileContent(self.localPath, filePath)
        mock_exists.assert_called_once_with(fullPath)
        mock_isfile.assert_called_once_with(fullPath)

    @patch('os.path.realpath')
    def test_readFileContent_pathTraversalAttempt_realpath(
        self: 'TestGitHubHandler', mock_realpath: MagicMock
    ) -> None:
        """Test reading a file fails if realpath resolves outside repo root."""
        filePath = "../outside/secret.txt"
        fullPath = os.path.normpath(os.path.join(self.localPath, filePath))
        resolvedRepoPath = os.path.abspath(self.localPath) # Assume this is resolved repo path
        # Mock realpath to simulate resolving outside the base directory
        resolvedOutsidePath = os.path.abspath('/fake/outside/secret.txt')
        mock_realpath.side_effect = lambda p: resolvedOutsidePath if os.path.normpath(p) == fullPath else resolvedRepoPath

        with self.assertRaisesRegex(GitHubError, "Invalid file path .* attempts to access outside repository root"):
            self.handler.readFileContent(self.localPath, filePath)
        # Ensure realpath was called for the check
        mock_realpath.assert_any_call(fullPath)
        mock_realpath.assert_any_call(self.localPath)

    @patch('builtins.open', new_callable=MagicMock)
    @patch('os.path.isfile', return_value=True)
    @patch('os.path.exists', return_value=True)
    @patch('os.path.realpath')
    def test_readFileContent_decodeError(
        self: 'TestGitHubHandler', mock_realpath: MagicMock, mock_exists: MagicMock,
        mock_isfile: MagicMock, mock_open: MagicMock
    ) -> None:
        """Test reading a file with undecodable content (using default UTF-8 strict)."""
        resolvedRepoPath = os.path.abspath(self.localPath)
        filePath = "binary.dat"
        fullPath = os.path.normpath(os.path.join(self.localPath, filePath))
        resolvedFullPath = os.path.abspath(fullPath)
        mock_realpath.side_effect = lambda p: resolvedFullPath if os.path.normpath(p) == fullPath else resolvedRepoPath

        # Make mock file handle raise UnicodeDecodeError when read() is called
        mock_handle = MagicMock()
        mock_handle.read.side_effect = UnicodeDecodeError('utf-8', b'\x80', 0, 1, 'invalid start byte')
        mock_open.return_value.__enter__.return_value = mock_handle

        with self.assertRaisesRegex(GitHubError, "Could not decode file .* using UTF-8"):
            self.handler.readFileContent(self.localPath, filePath)
        mock_open.assert_called_once_with(fullPath, 'r', encoding='utf-8', errors='strict')

    # --- Test isDirty ---

    @patch('git.Repo')
    def test_isDirty_cleanRepo(self: 'TestGitHubHandler', mock_Repo_constructor: MagicMock) -> None:
        """Test isDirty on a clean repository."""
        mock_Repo_constructor.return_value = self.mock_repo
        self.mock_git_cmd.status.return_value = "" # Empty porcelain status means clean

        is_dirty = self.handler.isDirty(self.localPath)

        self.assertFalse(is_dirty)
        mock_Repo_constructor.assert_called_once_with(self.localPath)
        self.mock_git_cmd.status.assert_called_once_with(porcelain=True)

    @patch('git.Repo')
    def test_isDirty_modifiedFile(self: 'TestGitHubHandler', mock_Repo_constructor: MagicMock) -> None:
        """Test isDirty with a modified file."""
        mock_Repo_constructor.return_value = self.mock_repo
        self.mock_git_cmd.status.return_value = " M modified_file.py" # Non-empty status

        is_dirty = self.handler.isDirty(self.localPath)

        self.assertTrue(is_dirty)
        self.mock_git_cmd.status.assert_called_once_with(porcelain=True)

    @patch('git.Repo')
    def test_isDirty_untrackedFile(self: 'TestGitHubHandler', mock_Repo_constructor: MagicMock) -> None:
        """Test isDirty with an untracked file."""
        mock_Repo_constructor.return_value = self.mock_repo
        self.mock_git_cmd.status.return_value = "?? untracked_file.txt" # Non-empty status

        is_dirty = self.handler.isDirty(self.localPath)

        self.assertTrue(is_dirty)
        self.mock_git_cmd.status.assert_called_once_with(porcelain=True)

    @patch('git.Repo')
    def test_isDirty_stagedFile(self: 'TestGitHubHandler', mock_Repo_constructor: MagicMock) -> None:
        """Test isDirty with a staged file."""
        mock_Repo_constructor.return_value = self.mock_repo
        self.mock_git_cmd.status.return_value = "A  newly_staged_file.py" # Non-empty status

        is_dirty = self.handler.isDirty(self.localPath)

        self.assertTrue(is_dirty)
        self.mock_git_cmd.status.assert_called_once_with(porcelain=True)

    @patch('git.Repo', side_effect=git.InvalidGitRepositoryError)
    def test_isDirty_invalidRepo(self: 'TestGitHubHandler', mock_Repo_constructor: MagicMock) -> None:
        """Test isDirty on an invalid repository path."""
        with self.assertRaisesRegex(GitHubError, "not a valid Git repository"):
            self.handler.isDirty(self.localPath)

    @patch('git.Repo')
    def test_isDirty_gitCommandError(self: 'TestGitHubHandler', mock_Repo_constructor: MagicMock) -> None:
        """Test handling GitCommandError during status check."""
        mock_Repo_constructor.return_value = self.mock_repo
        self.mock_git_cmd.status.side_effect = git.GitCommandError('status', 1, stderr='Some git status error')

        with self.assertRaisesRegex(GitHubError, "Git command 'status' failed"):
            self.handler.isDirty(self.localPath)

    # --- Test updateRepo ---

    @patch.object(GitHubHandler, 'isDirty', return_value=False)
    @patch('git.Repo')
    def test_updateRepo_noChanges_viaIsDirty(
        self: 'TestGitHubHandler', mock_Repo_constructor: MagicMock, mock_isDirty: MagicMock
    ) -> None:
        """Test updateRepo returns 'No changes' when isDirty returns False."""
        mock_Repo_constructor.return_value = self.mock_repo

        result = self.handler.updateRepo(self.localPath, "Commit msg", push=False)

        self.assertEqual(result, "No changes detected.")
        mock_isDirty.assert_called_once_with(self.localPath)
        # Ensure add/commit were not called
        self.mock_git_cmd.add.assert_not_called()
        self.mock_index.commit.assert_not_called()

    @patch.object(GitHubHandler, 'isDirty', return_value=True) # Simulate changes exist
    @patch('git.Repo')
    def test_updateRepo_commitOnly_success(
        self: 'TestGitHubHandler', mock_Repo_constructor: MagicMock, mock_isDirty: MagicMock
    ) -> None:
        """Test successful local commit without push."""
        mock_Repo_constructor.return_value = self.mock_repo

        result = self.handler.updateRepo(self.localPath, "Test commit", push=False)

        self.assertEqual(result, "Changes committed locally.")
        mock_isDirty.assert_called_once_with(self.localPath)
        self.mock_git_cmd.add.assert_called_once_with(A=True)
        self.mock_index.commit.assert_called_once_with("Test commit")
        # Ensure push was not called
        self.mock_remote.push.assert_not_called()

    @patch.object(GitHubHandler, '_check_branch_status', return_value=(False, "Branch up-to-date")) # Simulate pre-check success
    @patch.object(GitHubHandler, 'isDirty', return_value=True) # Simulate changes exist
    @patch('git.Repo')
    def test_updateRepo_commitAndPush_success(
        self: 'TestGitHubHandler', mock_Repo_constructor: MagicMock, mock_isDirty: MagicMock, mock_check_status: MagicMock
    ) -> None:
        """Test successful commit and push using PushInfo flags."""
        mock_Repo_constructor.return_value = self.mock_repo
        # Simulate successful push flags (e.g., FAST_FORWARD or NEW_TAG/HEAD)
        mock_push_info = MagicMock(spec=git.PushInfo, flags=git.PushInfo.NEW_HEAD)
        # Provide attributes needed for summary generation if that logic is complex in updateRepo
        mock_push_info.local_ref = MagicMock(); type(mock_push_info.local_ref).name = PropertyMock(return_value='main')
        mock_push_info.remote_ref_string = 'refs/heads/main'
        mock_push_info.summary = "[new branch]      main -> main" # Simple summary example

        self.mock_remote.push.return_value = [mock_push_info]
        # Create mock progress handler
        mock_progress = MockProgress()

        result = self.handler.updateRepo(self.localPath, "Test push", push=True, remoteName='origin', branchName='main', progress_handler=mock_progress)

        self.assertTrue(result.startswith("Changes committed and pushed"))
        mock_isDirty.assert_called_once_with(self.localPath)
        self.mock_git_cmd.add.assert_called_once_with(A=True)
        self.mock_index.commit.assert_called_once_with("Test push")
        mock_check_status.assert_called_once_with(self.mock_repo, 'origin', 'main') # Verify pre-check call
        self.mock_repo.remote.assert_called_once_with(name='origin')
        self.mock_remote.push.assert_called_once_with(refspec='main:main', progress=mock_progress)


    @patch.object(GitHubHandler, '_check_branch_status', return_value=(False, "Branch up-to-date")) # Simulate pre-check success
    @patch.object(GitHubHandler, 'isDirty', return_value=True)
    @patch('git.Repo')
    def test_updateRepo_push_rejected_viaPushInfoFlag(
        self: 'TestGitHubHandler', mock_Repo_constructor: MagicMock, mock_isDirty: MagicMock, mock_check_status: MagicMock
    ) -> None:
        """Test handling push rejection via PushInfo.REJECTED flag."""
        mock_Repo_constructor.return_value = self.mock_repo
        # Simulate rejection flag
        mock_push_info = MagicMock(spec=git.PushInfo, flags=git.PushInfo.REJECTED)
        mock_push_info.summary = "! [rejected]        main -> main (non-fast-forward)"
        self.mock_remote.push.return_value = [mock_push_info]

        with self.assertRaisesRegex(GitHubError, "Push operation failed after command execution.*Push rejected.*non-fast-forward"):
            self.handler.updateRepo(self.localPath, "Test push rejected", push=True)
        self.mock_index.commit.assert_called_once() # Ensure commit happened before push failed
        mock_check_status.assert_called_once()
        self.mock_remote.push.assert_called_once()

    @patch.object(GitHubHandler, '_check_branch_status', return_value=(False, "Branch up-to-date")) # Simulate pre-check success
    @patch.object(GitHubHandler, 'isDirty', return_value=True)
    @patch('git.Repo')
    def test_updateRepo_push_error_viaPushInfoFlag(
        self: 'TestGitHubHandler', mock_Repo_constructor: MagicMock, mock_isDirty: MagicMock, mock_check_status: MagicMock
    ) -> None:
        """Test handling push error via PushInfo.ERROR flag."""
        mock_Repo_constructor.return_value = self.mock_repo
        # Simulate error flag
        mock_push_info = MagicMock(spec=git.PushInfo, flags=git.PushInfo.ERROR)
        mock_push_info.summary = "error: src refspec main does not match any" # Example summary
        self.mock_remote.push.return_value = [mock_push_info]

        with self.assertRaisesRegex(GitHubError, "Push operation failed after command execution.*src refspec main does not match any"):
            self.handler.updateRepo(self.localPath, "Test push error", push=True)
        self.mock_index.commit.assert_called_once()
        mock_check_status.assert_called_once()
        self.mock_remote.push.assert_called_once()

    @patch.object(GitHubHandler, '_check_branch_status', return_value=(False, "Branch up-to-date")) # Simulate pre-check success
    @patch.object(GitHubHandler, 'isDirty', return_value=True)
    @patch('git.Repo')
    def test_updateRepo_push_authError_viaGitCommandError_https(
        self: 'TestGitHubHandler', mock_Repo_constructor: MagicMock, mock_isDirty: MagicMock, mock_check_status: MagicMock
    ) -> None:
        """Test handling push authentication error via GitCommandError (HTTPS)."""
        mock_Repo_constructor.return_value = self.mock_repo
        # Simulate push raising GitCommandError with auth failure stderr
        self.mock_remote.push.side_effect = git.GitCommandError('push', 128, stderr='remote: Support for password authentication was removed.*')
        # Mock remote URL for error message check
        type(self.mock_remote).url = PropertyMock(return_value=self.repoUrl) # HTTPS URL

        with self.assertRaisesRegex(GitHubError, "Authentication failed during push.*Check credentials/SSH keys."): # Adjusted message check
            self.handler.updateRepo(self.localPath, "Test push auth fail", push=True)
        self.mock_index.commit.assert_called_once() # Ensure commit happened before push failed
        mock_check_status.assert_called_once()
        self.mock_remote.push.assert_called_once()

    @patch.object(GitHubHandler, '_check_branch_status', return_value=(False, "Branch up-to-date")) # Simulate pre-check success
    @patch.object(GitHubHandler, 'isDirty', return_value=True)
    @patch('git.Repo')
    def test_updateRepo_push_authError_viaGitCommandError_ssh(
        self: 'TestGitHubHandler', mock_Repo_constructor: MagicMock, mock_isDirty: MagicMock, mock_check_status: MagicMock
    ) -> None:
        """Test handling push authentication error via GitCommandError (SSH)."""
        mock_Repo_constructor.return_value = self.mock_repo
        self.mock_remote.push.side_effect = git.GitCommandError('push', 128, stderr='git@github.com: Permission denied (publickey).')
        # Mock remote URL for error message check
        type(self.mock_remote).url = PropertyMock(return_value=self.sshRepoUrl) # SSH URL

        with self.assertRaisesRegex(GitHubError, "Authentication failed during push.*Check credentials/SSH keys."): # Adjusted message check
            self.handler.updateRepo(self.localPath, "Test push auth fail", push=True)
        self.mock_index.commit.assert_called_once()
        mock_check_status.assert_called_once()
        self.mock_remote.push.assert_called_once()

    @patch.object(GitHubHandler, '_check_branch_status', return_value=(False, "Branch up-to-date")) # Simulate pre-check success
    @patch.object(GitHubHandler, 'isDirty', return_value=True)
    @patch('git.Repo')
    def test_updateRepo_push_rejected_viaGitCommandError(
        self: 'TestGitHubHandler', mock_Repo_constructor: MagicMock, mock_isDirty: MagicMock, mock_check_status: MagicMock
    ) -> None:
        """Test handling push rejection via GitCommandError (stderr check)."""
        mock_Repo_constructor.return_value = self.mock_repo
        self.mock_remote.push.side_effect = git.GitCommandError(
            'push', 1, stderr='error: failed to push some refs to \'...\'\n...'
                               'Updates were rejected because the remote contains work that you do')

        with self.assertRaisesRegex(GitHubError, "Push rejected.*Remote branch .* has changes not present locally"):
            self.handler.updateRepo(self.localPath, "Test push rejected", push=True)
        self.mock_index.commit.assert_called_once()
        mock_check_status.assert_called_once()
        self.mock_remote.push.assert_called_once()

    @patch.object(GitHubHandler, 'isDirty', return_value=True)
    @patch('git.Repo')
    def test_updateRepo_remoteNotFound(self: 'TestGitHubHandler', mock_Repo_constructor: MagicMock, mock_isDirty: MagicMock) -> None:
        """Test handling push failure when the specified remote doesn't exist."""
        mock_Repo_constructor.return_value = self.mock_repo
        # Simulate repo.remote('name') raising ValueError BEFORE _check_branch_status is called
        self.mock_repo.remote.side_effect = ValueError("Remote 'bad_remote' not found")

        # Mock _check_branch_status; it shouldn't be reached if remote lookup fails first in updateRepo
        with patch.object(self.handler, '_check_branch_status') as mock_check_status:
            with self.assertRaisesRegex(GitHubError, "Remote 'bad_remote' does not exist"):
                self.handler.updateRepo(self.localPath, "Test push bad remote", push=True, remoteName='bad_remote')

            # Ensure commit still happened before remote lookup failure
            self.mock_index.commit.assert_called_once()
            # Ensure remote lookup was attempted
            self.mock_repo.remote.assert_any_call(name='bad_remote')
            # Ensure pre-check and push were not attempted
            mock_check_status.assert_not_called()
            self.mock_remote.push.assert_not_called()


    @patch.object(GitHubHandler, '_check_branch_status', return_value=(True, "Local branch 'main' is behind remote. Please pull changes before pushing.")) # Simulate pre-check failure (behind)
    @patch.object(GitHubHandler, 'isDirty', return_value=True)
    @patch('git.Repo')
    def test_updateRepo_push_aborted_due_to_behind(
        self: 'TestGitHubHandler', mock_Repo_constructor: MagicMock, mock_isDirty: MagicMock, mock_check_status: MagicMock
    ) -> None:
        """Test that push is aborted and commit is reset if pre-check shows branch is behind."""
        mock_Repo_constructor.return_value = self.mock_repo
        # Mock repo.index.reset to verify it's called
        mock_reset = MagicMock()
        self.mock_index.reset = mock_reset # Attach mock reset method to mock index

        with self.assertRaisesRegex(GitHubError, "Push aborted.*Local branch 'main' is behind remote.*Local commit has been reset"):
            self.handler.updateRepo(self.localPath, "Test push behind", push=True)

        mock_isDirty.assert_called_once()
        self.mock_git_cmd.add.assert_called_once()
        self.mock_index.commit.assert_called_once() # Commit happened
        mock_check_status.assert_called_once()      # Pre-check happened
        self.mock_remote.push.assert_not_called()  # Push did NOT happen
        # Verify commit reset was called
        mock_reset.assert_called_once_with(head=True) # Check reset call args (reset --hard HEAD) - Needs verification based on actual code



if __name__ == '__main__':
    unittest.main()
# --- END: tests/test_github_handler.py ---