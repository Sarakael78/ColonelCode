# Colonol Code - LLM Code Updater - Scope and Roadmap

This file contains the initial project scope and roadmap for the LLM Code Updater application.

**TODO**: instructions within code files mark areas (but not limiting thereto) requiring further development.

## Technologies and Strategies

* **GUI:** `PyQt6` or `PySide6` for a modern look and feel (using `PySide6` for LGPL license flexibility).
* **GitHub Interaction:** `gitpython` library for programmatic Git operations. `requests` might be needed for direct API calls if `gitpython` isn't sufficient for certain tasks (like checking repo existence without cloning).
* **LLM Interaction:** `google-generativeai` for Gemini.
* **Structured Data:** `json` (built-in), `PyYAML`, `xml.etree.ElementTree`. `json` is often the simplest for API <-> LLM interaction.
* **Configuration:** `python-dotenv` or `configparser`.
* **Logging:** `logging` (built-in).
* **Architectural Design:** A modular structure separating concerns: GUI, core logic (GitHub, LLM, file processing), utilities (logging, configuration), and potentially tests.
* **Core Logic Implementation Strategy:**
  * **GitHub:** Clone, list files, read selected files, stage/commit/push. Handle authentication (`token`).
  * **LLM Prompting:** Combine user instructions and selected file contents into a structured prompt, explicitly requesting `JSON`/`YAML`/`XML` output in a single code block.
  * **LLM Interaction:** Send prompt via API, handle responses and API errors. Allow manual paste input.
  * **Response Parsing:** Extract the code block, parse the structured data (`json` chosen as primary example), validate structure.
  * **File Writing:** Recreate the file structure locally based on parsed data.
* **GUI Design Strategy:**
  * User-friendly layout for input (Repo URL, prompt, API keys).
  * Mechanism for file selection within the cloned repo (e.g., `QListWidget` with checkboxes or `QTreeView`).
  * Display area for logs/status updates (`QTextEdit`).
  * Area for LLM response input/display (`QTextEdit`).
  * Buttons for actions (Clone, Select Files, Generate Prompt, Send to LLM, Parse Response, Save Files, Push to GitHub).
  * Use threading (`QThread`) for long-running tasks (network, file I/O) to keep the GUI responsive.
  * Provide clear feedback via status bar, log area, and message boxes.
* **Error Handling Strategy:** Implement granular `try...except` blocks, define custom exceptions for different error types (GitHub, LLM, Parsing, Configuration), log errors thoroughly, and present user-friendly error messages via the GUI.
* **Documentation & Best Practices:** Adhere to PEP 8 (with noted user preference overrides), use type hinting, write comprehensive docstrings (Google style), include inline comments, use a virtual environment, manage dependencies (`requirements.txt`), implement logging, handle secrets securely (config/env files, `.gitignore`). Address user's specific Python style preferences (`camelCase`, tabs, `[]` init).
* **Output Generation:** Structure the explanation, provide code structure, detail each module, include example snippets, and list requirements.

## Proposed Application Structure

This structure promotes modularity and separation of concerns.

```txt
llm_code_updater/
├── main.py                     # Application entry point
├── gui/                        # PyQt6/PySide6 GUI components
│   ├── __init__.py
│   ├── main_window.py          # Main application window class
│   ├── widgets/                # Custom reusable GUI widgets (e.g., file selector)
│   │   └── __init__.py
│   │   └── file_selector.py
│   ├── threads.py              # QThread workers for background tasks
│   └── gui_utils.py            # GUI-specific helper functions/signals
├── core/                       # Core application logic (backend)
│   ├── __init__.py
│   ├── github_handler.py       # Handles cloning, file access, pushing
│   ├── llm_interface.py        # Handles prompt creation and LLM interaction
│   ├── file_processor.py       # Handles parsing LLM output and writing files
│   ├── config_manager.py       # Manages configuration and API keys
│   └── exceptions.py           # Custom exception classes
├── utils/                      # Shared utility functions
│   ├── __init__.py
│   └── logger_setup.py         # Centralised logging configuration
├── tests/                      # Unit and integration tests (Essential Best Practice)
│   ├── __init__.py
│   ├── test_github_handler.py
│   └── ...                     # Tests for other core modules
├── resources/                  # Static resources like icons (optional)
│   └── app_icon.png
├── docs/                       # Extensive documentation (e.g., Sphinx generated)
│   └── ...
├── .env.example                # Example environment file for secrets
├── .gitignore                  # To exclude venv, __pycache__, .env, etc.
├── config.ini                  # Optional configuration file
├── requirements.txt            # Project dependencies
└── README.md                   # Project overview, setup, usage instructions
```

## Key Components and Functionality

### 1. `main.py` (Entry Point)

### 2. `gui/` (Graphical User Interface Folder)

* `main_window.py`: Defines the main application window layout, widgets (input fields, buttons, lists, text areas), connects signals (button clicks) to slots (methods that trigger actions). It orchestrates the user interaction flow. It will instantiate worker threads from `threads.py` for background tasks.
* `widgets/`: Subfolder containing custom, reusable widgets. For example, `file_selector.py` could implement a `QTreeView` or `QListWidget` tailored for displaying and selecting files from the cloned repository.
* `threads.py`: Defines `QThread` subclasses for long-running operations (Git clone, push, LLM API call, file processing) to prevent the GUI from freezing. These threads emit signals to update the GUI with progress, results, or errors.
* `gui_utils.py`: May contain utility functions specific to the GUI, like custom signal definitions or helper functions for updating GUI elements safely from threads. It could also contain a custom logging handler that emits signals to update a `QTextEdit` log widget.

### 3. `core/` (Folder Containing Core Logic)

* `github_handler.py`:
  * Uses `gitpython`.
  * `cloneRepository(repoUrl: str, localPath: str, authToken: str | None = None) -> git.Repo`: Clones the repository. Handles authentication (HTTPS token or SSH key). Raises `GitHubError` for issues (invalid URL, auth failure, network error, Git command failure). Provides granular output via logging.
  * `listFiles(repoPath: str) -> list[str]`: Returns a list of relative file paths within the repository, potentially filtering out `.git` directory, binary files, etc.
  * `readFileContent(repoPath: str, filePath: str) -> str`: Reads the content of a specific file. Handles `FileNotFoundError`, `UnicodeDecodeError`, raising `GitHubError`.
  * `updateRepo(repoPath: str, commitMessage: str, push: bool = True, remoteName: str = 'origin', branchName: str = 'main', authToken: str | None = None)`: Stages all changes, commits them with the provided message, and optionally pushes to the remote. Handles Git command errors, push conflicts, and authentication, raising `GitHubError`. Logs steps taken.
* `llm_interface.py`:
  * `buildPrompt(instruction: str, fileContents: dict[str, str]) -> str`: Constructs the prompt. Includes the user's instruction and the content of selected files. Critically, it must instruct the LLM on the desired output format.
  * Example Prompt Snippet:

    ```txt
    User Instruction: {instruction}

    Context from codebase:
    --- FILE: path/to/file1.py ---
    {content of file1.py}
    --- END FILE: path/to/file1.py ---
    --- FILE: path/to/another/file2.js ---
    {content of file2.js}
    --- END FILE: path/to/another/file2.js ---

    Based on the user instruction and the provided file contexts, update the code.
    Provide the *complete, updated content* for *all modified files* as a single JSON object within a single markdown code block.
    The JSON object should map the relative file path (as a string key) to the full updated file content (as a string value).
    Example JSON structure:
    {{
      "path/to/updated_file1.py": "...",
      "path/to/new_file.txt": "...",
      "path/to/another/file2.js": "..."
    }}
    Ensure the JSON is valid and contains the full file contents. Only include files that were modified or newly created in the response JSON. If no files need modification based on the instruction, return an empty JSON object: {{}}.
    ```

  * `queryLlmApi(apiKey: str, prompt: str, modelName: str = "gemini-pro") -> str`: Sends the prompt to the specified LLM API (e.g., Gemini). Uses the `google-generativeai` library. Handles API key errors, network errors, rate limits, content safety blocks, raising `LLMError`. Logs interaction steps.
* `file_processor.py`:
  * `extractCodeBlock(llmResponse: str, language: str = 'json') -> str | None`: Uses regex or string manipulation to find and extract the content within the first code block (e.g., ````json ...````). Raises `ParsingError` if no block is found.
  * `parseStructuredOutput(structuredDataString: str, format: str = 'json') -> dict[str, str]`: Parses the extracted string using the appropriate library (`json.loads`, `yaml.safe_load`). Validates that the result is a dictionary with string keys (filenames) and string values (content). Raises `ParsingError` for invalid format or structure. Logs parsing steps.
  * `saveFilesToDisk(outputDir: str, fileData: dict[str, str]) -> list[str]`
  : Iterates through the parsed dictionary. Creates necessary subdirectories within `outputDir`. Writes the content to each file, overwriting existing ones. Handles file system errors (permissions, disk space), raising `FileProcessingError`. Returns a list of saved file paths. Logs files being written.
* `config_manager.py`:
  * Uses `configparser` for `config.ini` and `dotenv` for `.env`.
  * Loads API keys (Gemini, potentially GitHub token) securely from environment variables or a `.env` file (which must be in `.gitignore`).
  * Loads non-sensitive settings (default paths, model preferences) from `config.ini`.
  * Provides methods to get configuration values, raising `ConfigurationError` if a required value is missing.
* `exceptions.py`:
  * Defines custom exception classes for granular error handling.

### 4. utils/ (Utilities)

* `logger_setup.py`
  * Configures the root logger. Sets formatters, handlers (console, file, custom GUI handler). Allows adjusting log levels.

### 5. tests/ (Testing)

* Crucial for reliability and maintainability (Best Practice).
* Uses `unittest` or `pytest`.
* Mocks external dependencies (Git commands, API calls) during unit testing.
* Includes integration tests where feasible.

### 6. requirements.txt

```txt
# requirements.txt
PySide6>=6.6.0,<7.0.0       # Or PyQt6
GitPython>=3.1.30,<4.0.0
google-generativeai>=0.4.0,<1.0.0
python-dotenv>=1.0.0,<2.0.0
PyYAML>=6.0,<7.0.0           # If YAML support is desired
# Add other dependencies like 'requests' if needed
```

### 7. .env.example & .gitignore

* `.env.example`:

  ```.env
  # DO NOT COMMIT ACTUAL KEYS TO GIT. COPY THIS TO .env AND FILL IN YOUR KEYS.
  GEMINI_API_KEY="YOUR_GEMINI_API_KEY"
  GITHUB_TOKEN="YOUR_GITHUB_PERSONAL_ACCESS_TOKEN" # Optional, for private repos/pushing
  ```

* `.gitignore`
  * Crucially includes `.env`, `__pycache__/`, `*.pyc`, virtual environment directories (`venv/`, `.venv/`), configuration files potentially containing secrets if not using `.env`, build artifacts, test reports, log files.

## Error Handling and User Feedback

* **Granular Exceptions:** Use the custom exceptions (`GitHubError`, `LLMError`, etc.) to catch specific problems.
* **Try/Except Blocks:** Wrap all operations prone to failure (I/O, network, parsing, Git commands) in `try...except` blocks.
* **Logging:** Log extensively at different levels (INFO for steps, WARNING for recoverable issues, ERROR for failures, DEBUG for detailed tracing). Include timestamps and module names.
* **GUI Feedback:**
  * **Status Bar:** Display brief status updates (e.g., "Cloning repository...", "Querying LLM...", "Idle").
  * **Log Area:** Pipe log messages (INFO and above) to a `QTextEdit` widget in the GUI for detailed tracking. Use the custom logging handler mentioned earlier.
  * **Message Boxes:** Use `QMessageBox.information`, `QMessageBox.warning`, or `QMessageBox.critical` to notify the user of success, non-critical issues, or critical errors that halt a process.
  * **Progress Indicators:** For long tasks running in threads, use `QProgressBar` updated via signals from the worker thread.
  * **Widget Disabling:** Disable buttons/inputs that are not applicable in the current state (e.g., disable "Push to GitHub" until changes are generated and saved).

## Best Industry Practices Employed

* **Modularity:** Code divided into logical, reusable components.
* **Separation of Concerns:** GUI logic is separate from core business logic.
* **Dependency Management:** `requirements.txt` used. Virtual environments strongly recommended.
* **Version Control:** Use Git for the application's own codebase.
* **Configuration Management:** Secrets handled via `.env` (and `.gitignore`), other settings via `config.ini`. No hardcoded secrets or paths.
* **Robust Error Handling:** Custom exceptions, comprehensive `try...except`.
* **Extensive Logging:** Centralised logging configuration.
* **Code Style & Linting:** Adherence to PEP 8 (with noted deviations for user preference like `camelCase` and tabs) enforced potentially using tools like `flake8` or `black` (though black enforces spaces over tabs).
* **Type Hinting:** Improves code clarity and allows static analysis (`mypy`).
* **Documentation:** Docstrings for public APIs, README.md, potentially external `docs/`. Inline comments for complex parts.
* **Testing:** Inclusion of a `tests/` directory structure (implementation required).
* **GUI Responsiveness:** Use of threading for long-running tasks.
* **Security:** Handling API keys securely, avoiding storing them in version control.

## Adherence to User Preferences

* **Python Style:** Using `camelCase` for variables/functions, `[]` for list initialisation, tabs for indentation (note: this conflicts with PEP 8's preference for 4 spaces; ensure consistency), extensive documentation/comments, type hints, descriptive names.
* **Output Format:** The prompt explicitly requests the structured format (JSON example provided) in a single code block. The parsing logic expects this.
* **Granular Output:** Achieved through detailed logging piped to the GUI and status bar updates.
* **Error Handling:** Addressed via custom exceptions and GUI feedback.
* **Modularity:** Core design principle followed.

## Summary of Necessary Coding Steps

Based on the foundational code and placeholders provided above, here is a detailed breakdown of the subsequent development steps:

1. **GUI Implementation (`gui/main_window.py`):**
   * Refine `_setupUI`: Store references to interactive widgets (buttons, inputs, lists, text areas) as class members (e.g., `self._cloneButton = QPushButton(...)`). Set `objectName` for widgets if needed for styling or later lookup (less common with member references).
   * Implement `_connectSignals`: Connect signals from the member widgets (e.g., `self._cloneButton.clicked.connect(...)`) to the corresponding `_handle...` slots.
   * Implement `_updateWidgetStates`: Create a method to enable/disable widgets based on the application's state (e.g., disable "Send to LLM" until repo is loaded and files are selected; disable all actions while a worker thread is busy). Call this method at the end of `_setupUI` and in `_resetTaskState` and before starting tasks.
   * **GUI Log Handler:** Implement a custom `logging.Handler` (likely in `gui/gui_utils.py`) that emits a Qt signal (`Signal(str)`). Connect this signal in `MainWindow` to the `_appendLogMessage` slot. Modify `utils/logger_setup.py` to optionally accept and add this handler.
   * **File List Population:** In the `_onCloneFinished` slot, populate the `self._fileListWidget` with the received file list. Consider using a `QTreeView` for better directory structure representation (requires more complex data model).
   * **Worker Thread Instantiation:** In `MainWindow.__init__`, instantiate the worker threads (`GitHubWorker`, `LLMWorker`, `FileWorker`).
   * **Worker Signal Connections:** In `_connectSignals`, connect the various signals from each worker thread instance (`cloneFinished`, `llmQueryFinished`, `parsingFinished`, `savingFinished`, `commitPushFinished`, `statusUpdate`, `progress`, `errorOccurred`) to the appropriate handler slots in `MainWindow` (e.g., `_onCloneFinished`, `_onLlmFinished`, `_updateStatusBar`, `_updateProgressBar`, `_handleWorkerError`).
   * **Implement Placeholders in Handlers:** Fill in the **TODO** sections within the `_handle...` methods to correctly gather necessary data (URLs, paths, tokens, messages) and call the appropriate `start...` method on the corresponding worker thread instance (e.g., `self._githubWorker.startClone(...)`).
2. **Core Logic Implementation (`core/` modules):**
   * `GitHubHandler`:
     * Implement progress reporting for `clone_from` by subclassing `git.remote.RemoteProgress` and emitting signals (requires passing the progress instance to `clone_from`). Connect these signals through the `GitHubWorker`.
     * Add methods for `git status` or `is_dirty` checks if needed for GUI feedback before commit/push.
     * Refine authentication handling for push (consider credential helpers vs. token injection).
     * Add filtering options to `listFiles` (e.g., by extension, ignore patterns).
   * `LLMInterface`:
     * Implement configuration loading for safety settings and generation parameters (temperature, max tokens).
     * Add robust token counting and content truncation logic in `buildPrompt`.
     * Implement retry logic for transient API errors in `queryLlmApi`.
     * Handle potential multipart responses or function calling if supported/needed by the chosen model or use case.
     * Add error handling for invalid model names.
   * `FileProcessor`:
     * Make `extractCodeBlock` more robust to variations in markdown (e.g., optional language identifier, different spacing).
     * Implement YAML parsing fully (ensure PyYAML is installed). Add support for other formats (XML) if required.
     * Add validation for file path safety (preventing writing outside `outputDir`) in `saveFilesToDisk`.
     * Consider adding a method `readFilesFromDisk` to complement `saveFilesToDisk`, potentially useful for gathering context before calling the LLM.
3. **Threading Implementation (`gui/threads.py`):**
   * Refine the signals in `BaseWorker` and specific workers for clarity if needed.
   * Implement progress reporting propagation from handlers (like `GitHubHandler`) through the worker threads using the `progress` signal.
   * Ensure robust error capturing within the `run` methods and emit appropriate error signals.
4. **Testing (`tests/`):**
   * Implement unit tests for `ConfigManager`, `LLMInterface` (mocking `genai`), `FileProcessor`.
   * Implement unit tests for `GitHubHandler` by mocking `git.Repo` and `git.Git` calls extensively (using `unittest.mock`). This is crucial as Git operations are external dependencies.
   * Implement integration tests where feasible (e.g., testing the flow from `main.py` through config loading). GUI testing is complex but could use frameworks like `pytest-qt`.
5. **Documentation (`docs/`, `README.md`, Docstrings):**
   * Expand `README.md` with detailed setup, usage instructions, and troubleshooting tips.
   * Generate formal documentation using Sphinx in the `docs/` directory, pulling from docstrings.
   * Review and enhance all docstrings and inline comments for clarity and completeness.
6. **Refinement and Packaging (Optional):**
   * Refine the GUI layout and user experience based on testing.
   * Add features like theme selection, persistent window geometry, etc.
   * Consider packaging the application using tools like PyInstaller or cx\_Freeze for easier distribution.
