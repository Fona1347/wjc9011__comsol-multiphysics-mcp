# Dependency and Test Status

Checked at: 2026-05-25

## Repository

- Path: `E:\hycodespace\Forks\COMSOL_Multiphysics_MCP`
- Project file: `pyproject.toml`
- Python requirement declared by project: `>=3.10`
- Existing environment: `.venv`
- `.venv` type: conda-style prefix
- `.venv` Python path: `.\.venv\python.exe`
- `.venv` Python version: `Python 3.12.13`

## Declared Dependencies

Runtime dependencies declared in `pyproject.toml`:

```toml
dependencies = [
    "mcp>=1.0.0",
    "mph>=1.3.0",
    "pydantic>=2.0.0",
    "pymupdf>=1.24.0",
    "chromadb>=0.4.0",
    "sentence-transformers>=2.2.0",
]
```

Development dependencies declared in `pyproject.toml`:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "pytest-asyncio>=0.21.0",
]
```

## Installation Command Used

The current fork was installed in editable mode with development dependencies:

```powershell
cd E:\hycodespace\Forks\COMSOL_Multiphysics_MCP
.\.venv\python.exe -m pip install -e ".[dev]"
```

Installation completed successfully.

Important installed packages after installation:

```text
comsol-mcp      0.1.0  E:\hycodespace\Forks\COMSOL_Multiphysics_MCP
pytest          9.0.3
pytest-asyncio  1.3.0
```

The editable `comsol-mcp` install now points to the current fork:

```text
E:\hycodespace\Forks\COMSOL_Multiphysics_MCP
```

Before reinstalling, the environment had pointed at another checkout:

```text
E:\hycodespace\Clone\wjc9011__COMSOL_Multiphysics_MCP
```

## PATH Warning

During installation, pip reported:

```text
pytest.exe is installed in '.\.venv\Scripts' which is not on PATH
```

This is not a blocker when tests are run through the interpreter:

```powershell
.\.venv\python.exe -m pytest
```

Using `python -m pytest` is recommended for this repository because it guarantees pytest runs inside the intended `.venv`.

## Test Command

Current Windows environment recommended test command:

```powershell
cd E:\hycodespace\Forks\COMSOL_Multiphysics_MCP
.\scripts\test.ps1
```

This command is recommended because the default pytest temporary directory and cache path currently hit Windows permission issues:

```text
C:\Users\Huayun\AppData\Local\Temp\pytest-of-Huayun
E:\hycodespace\Forks\COMSOL_Multiphysics_MCP\.pytest_cache
```

The wrapper script keeps pytest temporary files inside a unique per-run directory under `.comsol_runtime`, and passes `-p no:cacheprovider` to avoid writing `.pytest_cache`.

The script runs the equivalent of:

```powershell
.\.venv\python.exe -m pytest --basetemp=.comsol_runtime\pytest-run-<timestamp>-<pid> -p no:cacheprovider
```

If PowerShell blocks `.ps1` execution with an execution policy error, run the same script with a process-local bypass:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\test.ps1
```

Plain pytest command, kept for reference but not recommended in the current Windows environment:

```powershell
cd E:\hycodespace\Forks\COMSOL_Multiphysics_MCP
.\.venv\python.exe -m pytest
```

## Test Result

Current result:

```text
21 passed
```

Previous failure note: `tests/test_basic.py::TestVersioning::test_generate_version_path` had an outdated path expectation. The implementation and documentation use structured model paths:

```text
./comsol_models/{model_name}/{model_name}_{timestamp}.mph
```
The test has been updated to validate that structured path behavior.

## Pytest Cache Warnings

Plain pytest may report cache warnings:

```text
PytestCacheWarning: could not create cache path
E:\hycodespace\Forks\COMSOL_Multiphysics_MCP\.pytest_cache\v\cache
[WinError 5] access denied
```

These warnings do not prevent test execution, but the current recommended command disables pytest cache to keep output clean.

## Recommended Workflow

For this repository, use the project-local environment explicitly:

```powershell
cd E:\hycodespace\Forks\COMSOL_Multiphysics_MCP
.\.venv\python.exe -m pip install -e ".[dev]"
.\scripts\test.ps1
```

Avoid relying on global `pytest` or the system Python for this project.
