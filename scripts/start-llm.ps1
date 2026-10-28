param(
    [ValidateSet('simulator', 'cpu-model')][string]$Backend = 'cpu-model',
    [int]$Port = 8800,
    [ValidateRange(1, 16)][int]$Workers = 2,
    [ValidateRange(1, 16)][int]$Threads = 2
)
$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectDirectory
$pythonExecutable = Join-Path $projectDirectory '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create virtual environment' }
}
if ($Backend -eq 'cpu-model') {
    & $pythonExecutable -c "import torch, transformers"
    if ($LASTEXITCODE -ne 0) {
        & $pythonExecutable -m pip install -r requirements-llm.txt
        if ($LASTEXITCODE -ne 0) { throw 'Failed to install CPU inference dependencies' }
    }
    if (-not (Test-Path -LiteralPath '.runtime\qwen25-05b\tokenflow-model.json')) {
        & $pythonExecutable -m llm_lab download-model
        if ($LASTEXITCODE -ne 0) { throw 'Failed to download model' }
    }
}
& $pythonExecutable -m llm_lab serve --backend $Backend --port $Port --workers $Workers --threads $Threads
