param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Tool,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ToolArgs
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
$runner = Join-Path $root "scripts\run_tool_with_timeout.py"
$invokeArgs = @()
$invokeArgs += $pythonPrefix
$invokeArgs += $runner
$invokeArgs += $Tool
if ($ToolArgs) {
    $invokeArgs += $ToolArgs
}

& $pythonExe @invokeArgs
exit $LASTEXITCODE
