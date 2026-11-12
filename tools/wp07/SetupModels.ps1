param(
    [ValidateSet('easyocr','trocr','rfdetr','all')][string]$Engine='easyocr',
    [string]$ModelRoot = "$env:LOCALAPPDATA\PIDReader\models",
    [string]$Python = 'python'
)
$ErrorActionPreference = 'Stop'
$Repository = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$RuntimeRoot = Join-Path $ModelRoot 'runtime'
if (-not (Test-Path (Join-Path $RuntimeRoot 'Scripts\python.exe'))) {
    & $Python -m venv $RuntimeRoot
    if ($LASTEXITCODE -ne 0) { throw 'Cannot create the model runtime.' }
}
$ModelPython = Join-Path $RuntimeRoot 'Scripts\python.exe'
& $ModelPython -m pip install --index-url https://download.pytorch.org/whl/cpu 'torch==2.8.0+cpu' 'torchvision==0.23.0+cpu'
if ($LASTEXITCODE -ne 0) { throw 'CPU PyTorch installation failed.' }
& $ModelPython -m pip install -r (Join-Path $PSScriptRoot 'requirements-runtime.txt')
if ($LASTEXITCODE -ne 0) { throw 'Model dependencies did not install.' }
$PreviousPythonPath = $env:PYTHONPATH
try {
    $SourceRoot = Join-Path $Repository 'src'
    $WorkerArchive = Join-Path $Repository 'model_lab\model_lab_worker.zip'
    $env:PYTHONPATH = if (Test-Path $SourceRoot) { $SourceRoot } elseif (Test-Path $WorkerArchive) { $WorkerArchive } else { throw 'Reader source or worker archive not found.' }
    $Engines = if ($Engine -eq 'all') { @('easyocr','trocr','rfdetr') } else { @($Engine) }
    foreach ($Item in $Engines) {
        & $ModelPython -m pid_reader.engineering.model_lab.provision $Item $ModelRoot
        if ($LASTEXITCODE -ne 0) { throw "Model staging failed for $Item" }
    }
    & $ModelPython -m pip freeze | Out-File -Encoding utf8 (Join-Path $ModelRoot 'installed-runtime-WINDOWS.txt')
} finally { $env:PYTHONPATH = $PreviousPythonPath }
Write-Output 'Models staged. Open Model comparison, choose a manifest and enable comparison for this session.'
