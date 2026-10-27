param([Parameter(ValueFromRemainingArguments = $true)][string[]]$ScriptArgs)
$ErrorActionPreference = 'Stop'
if (Get-Command python -ErrorAction SilentlyContinue) {
    & python (Join-Path $PSScriptRoot 'jb.py') @ScriptArgs
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 (Join-Path $PSScriptRoot 'jb.py') @ScriptArgs
} else {
    throw 'Python 3.9+ is required. Install Python, then run this script again.'
}
exit $LASTEXITCODE
