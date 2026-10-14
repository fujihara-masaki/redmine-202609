#requires -Version 5.1
[CmdletBinding()]
param(
    [string] $Command,
    [string] $ProxyMode = 'Inherit',
    [string] $ConfigPath,
    [string] $Project,
    [string] $OutputDir,
    [string] $Fields = 'basic',
    [switch] $IncludeSubprojects,
    [switch] $IncludeJstColumns,
    [string] $Status = '*',
    [string] $Tracker
)

# Binding validation is deliberately inside the safe error boundary below.
$code = 3
try {
    Import-Module (Join-Path $PSScriptRoot 'RedmineReadonly.Launcher.psm1') -Force -ErrorAction Stop
    $root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
    $code = Invoke-ReadonlyLauncher -Root $root -Options $PSBoundParameters
} catch {
    [Console]::Error.WriteLine('ERROR: launcher setup failed')
}
# Exiting a script invoked with & returns to its caller, and sets LASTEXITCODE.
# Dot-sourcing is deliberately unsupported.
exit $code
