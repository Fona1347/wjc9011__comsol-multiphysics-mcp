$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

$runId = "{0}-{1}" -f (Get-Date -Format "yyyyMMddHHmmssfff"), $PID
$baseTemp = Join-Path ".comsol_runtime" ("pytest-run-{0}" -f $runId)

.\.venv\python.exe -m pytest --basetemp=$baseTemp -p no:cacheprovider
