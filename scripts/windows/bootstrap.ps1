param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$InstallerArgs
)

$ErrorActionPreference = "Stop"

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$pythonExe = $null
$pythonPrefix = @()
if (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonExe = "py"
    $pythonPrefix = @("-3")
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonExe = "python"
} else {
    throw "Python interpreter not found. Install Python 3.9+ first."
}

$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$installer = Join-Path $root "scripts\install_prerequisites.py"
$invokeArgs = @()
$invokeArgs += $pythonPrefix
$invokeArgs += $installer
if ($InstallerArgs) {
    $invokeArgs += $InstallerArgs
}

& $pythonExe @invokeArgs
exit $LASTEXITCODE
