#requires -Version 5.1
# Dependency-free harness. All PAC/native CLI boundaries are replaced in unit
# cases; integration uses a copied repository with a fake CLI, never Redmine.
param([switch] $AllowPowerShell7)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
if (-not $AllowPowerShell7 -and
    ($PSVersionTable.PSEdition -ne 'Desktop' -or $PSVersionTable.PSVersion.Major -ne 5 -or
     $PSVersionTable.PSVersion.Minor -ne 1)) { throw 'Windows PowerShell 5.1 required' }
Write-Host ('PowerShell under test: ' + $PSVersionTable.PSVersion + '; ' + $PSVersionTable.PSEdition)
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
Import-Module (Join-Path $repo 'scripts\RedmineReadonly.Launcher.psm1') -Force
$module = Get-Module RedmineReadonly.Launcher
$temporary = Join-Path ([IO.Path]::GetTempPath()) ('launcher-' + [Guid]::NewGuid().ToString('N'))
$fixture = Join-Path $temporary 'fixture'
$null = New-Item -ItemType Directory -Path (Join-Path $fixture '.venv\Scripts') -Force
$null = New-Item -ItemType Directory -Path (Join-Path $fixture 'src\redmine_readonly') -Force
Set-Content -LiteralPath (Join-Path $fixture '.venv\Scripts\python.exe') -Value 'placeholder'
Set-Content -LiteralPath (Join-Path $fixture 'src\redmine_readonly\windows_launcher.py') -Value 'placeholder'
Set-Content -LiteralPath (Join-Path $fixture 'config.toml') -Value 'placeholder'
$originals = & $module {
    $saved = @{}
    foreach ($name in @('Invoke-ReadonlyHelper', 'Get-ReadonlySystemProxy', 'Invoke-ReadonlyCli',
        'Get-ReadonlyEnvironment', 'Set-ReadonlyEnvironment', 'Restore-ReadonlyEnvironment')) {
        $saved[$name] = (Get-Item ('Function:' + $name)).ScriptBlock
    }
    return $saved
}
$script:count = 0
function Assert-True {
    param($Condition, [string] $Description = 'assertion')
    if (-not $Condition) { throw ('FAILED: ' + $Description) }
}
function Test-Case {
    param([string] $Name, [scriptblock] $Body)
    & $module {
        param($Saved)
        foreach ($name in $Saved.Keys) { Set-Item ('Function:script:' + $name) $Saved[$name] }
        $script:state = @{ pac = 0; cli = 0; helper = 0; code = 0; failCli = $false;
            failHelper = $false; failRestore = $false; failPac = $false; nullPac = $false;
            snapshot = @{ Exists = $true; Value = 'http://original.example.invalid:8080' };
            environment = 'http://original.example.invalid:8080'; selected = 'http://chosen.example.invalid:8080';
            target = 'https://redmine.example.invalid/redmine/users/current.json';
            requestsConflict = $false; restore = 0; args = @(); python = ''; message = $null }
        function script:Invoke-ReadonlyHelper {
            param($Python, $Message)
            $script:state.helper++
            $script:state.message = $Message.Clone()
            if ($Message.stage -eq 'target') { return @{ url = $script:state.target } }
            if ($script:state.failHelper -or $script:state.requestsConflict) { throw 'FAKE-SECRET internal-url' }
            return @{ ok = $true }
        }
        function script:Get-ReadonlySystemProxy {
            param($Target)
            $script:state.pac++
            $script:state.pacTarget = $Target.AbsoluteUri
            if ($script:state.failPac) { throw 'FAKE-SECRET internal-url' }
            if ($script:state.nullPac) { return $null }
            return [Uri] $script:state.selected
        }
        function script:Invoke-ReadonlyCli {
            param($Python, $Arguments)
            $script:state.cli++
            $script:state.python = $Python
            $script:state.args = $Arguments
            $script:state.cliEnvironment = $script:state.environment
            if ($script:state.failCli) { throw 'FAKE-SECRET simulated interruption' }
            return $script:state.code
        }
        function script:Get-ReadonlyEnvironment { return $script:state.snapshot.Clone() }
        function script:Set-ReadonlyEnvironment { param($Value) $script:state.environment = $Value }
        function script:Restore-ReadonlyEnvironment {
            param($Snapshot)
            $script:state.restore++
            if ($script:state.failRestore) { throw 'FAKE-SECRET cleanup' }
            if ($Snapshot.Exists) { $script:state.environment = $Snapshot.Value }
            else { $script:state.environment = $null }
        }
    } $originals
    & $Body
    $script:count++
    Write-Host ('PASS: ' + $Name)
}
function State { return (& $module { return $script:state }) }
function Launch { param([hashtable] $Options) return (Invoke-ReadonlyLauncher $fixture $Options) }
try {
    Test-Case 'Inherit defaults preserve settings without PAC' {
        Assert-True ((Launch @{ Command = 'check' }) -eq 0)
        $s = State
        Assert-True ($s.pac -eq 0 -and $s.restore -eq 0 -and $s.cli -eq 1)
        Assert-True ($s.environment -eq $s.snapshot.Value)
        Assert-True ($s.python -eq (Join-Path $fixture '.venv\Scripts\python.exe'))
        Assert-True ($s.args[4] -eq (Join-Path $fixture 'config.toml'))
    }
    Test-Case 'different cwd and explicit relative config use repository' {
        $before = Get-Location
        try {
            Set-Location -LiteralPath $temporary
            Assert-True ((Launch @{ Command = 'check'; ConfigPath = 'config.toml' }) -eq 0)
            Assert-True ((Get-Location).Path -eq $temporary)
            Assert-True ((State).args[4] -eq (Join-Path $fixture 'config.toml'))
        } finally { Set-Location -LiteralPath $before.Path }
    }
    foreach ($kind in @('check', 'export', 'resolve-project')) {
        Test-Case ('System PROXY uses target for ' + $kind) {
            $s = State
            $endpoint = '/users/current.json'
            $o = @{ Command = $kind; ProxyMode = 'System' }
            if ($kind -ne 'check') { $o.Project = 'sample-project' }
            if ($kind -eq 'export') { $o.OutputDir = 'C:\Exports'; $endpoint = '/issues.json' }
            if ($kind -eq 'resolve-project') { $endpoint = '/projects/sample-project.json' }
            $s.target = 'https://redmine.example.invalid/redmine' + $endpoint
            Assert-True ((Launch $o) -eq 0)
            Assert-True ($s.pacTarget -eq $s.target -and $s.pac -eq 1 -and $s.cli -eq 1)
            Assert-True ($s.cliEnvironment -eq $s.selected -and $s.environment -eq $s.snapshot.Value)
            Assert-True ($s.message.command -eq $kind -and $s.message.decision -eq 'PROXY')
        }
    }
    Test-Case 'DIRECT verifies Requests and does not change environment' {
        $s = State; $s.selected = $s.target
        Assert-True ((Launch @{ Command = 'check'; ProxyMode = 'System' }) -eq 0)
        Assert-True ($s.message.decision -eq 'DIRECT' -and $s.restore -eq 0 -and $s.cli -eq 1)
    }
    Test-Case 'target helper failure stops before PAC and environment change' {
        & $module { function script:Invoke-ReadonlyHelper { throw 'FAKE-SECRET internal-url' } }
        Assert-True ((Launch @{Command='check'; ProxyMode='System'}) -eq 3)
        Assert-True ((State).cli -eq 0 -and (State).pac -eq 0 -and (State).restore -eq 0)
    }
    Test-Case 'opaque system result is rejected' {
        & $module { function script:Get-ReadonlySystemProxy { return 'not a URI' } }
        Assert-True ((Launch @{Command='check'; ProxyMode='System'}) -eq 3)
        Assert-True ((State).cli -eq 0)
    }
    Test-Case 'temporary setting failure still attempts restoration' {
        & $module { function script:Set-ReadonlyEnvironment { throw 'FAKE-SECRET setter' } }
        Assert-True ((Launch @{Command='check'; ProxyMode='System'}) -eq 3)
        Assert-True ((State).restore -eq 1 -and (State).cli -eq 0)
    }
    Test-Case 'simulated cancellation restores environment' {
        & $module { function script:Invoke-ReadonlyCli { throw (New-Object OperationCanceledException('FAKE-SECRET')) } }
        Assert-True ((Launch @{Command='check'; ProxyMode='System'}) -eq 3)
        Assert-True ((State).restore -eq 1 -and (State).environment -eq (State).snapshot.Value)
    }
    Test-Case 'exception details and internal URL are never forwarded' {
        $writer = New-Object IO.StringWriter
        $previous = [Console]::Error
        try {
            [Console]::SetError($writer)
            (State).failHelper = $true
            Assert-True ((Launch @{Command='check'; ProxyMode='System'}) -eq 3)
        } finally { [Console]::SetError($previous) }
        Assert-True ($writer.ToString() -eq ('ERROR: launcher proxy-conflict-or-preflight failed' + [Environment]::NewLine))
    }
    foreach ($mode in @('PROXY', 'DIRECT')) {
        Test-Case ($mode + ' Requests conflict stops before CLI') {
            $s = State; $s.requestsConflict = $true
            if ($mode -eq 'DIRECT') { $s.selected = $s.target }
            Assert-True ((Launch @{ Command = 'check'; ProxyMode = 'System' }) -eq 3)
            Assert-True ($s.cli -eq 0 -and $s.pac -eq 1 -and $s.environment -eq $s.snapshot.Value)
        }
    }
    foreach ($bad in @(@{Command='unknown'}, @{Command='export'; Fields='unknown'},
        @{Command='check'; ProxyMode='unknown'}, @{Command='check'; Project='42'},
        @{Command='check'; Fields='basic'}, @{Command='resolve-project'; Project='../users'},
        @{Command='resolve-project'; Project='x; command'}, @{Command='resolve-project'; Project='x?y'},
        @{Command='export'; Project='42'}, @{Command='export'; Project='42'; OutputDir='relative'},
        @{Command='export'; Project='42'; OutputDir='C:\Exports'; Tracker=0},
        @{Command='export'; Project='42'; OutputDir='C:\Exports'; Status=''},
        @{Command='export'; Project='42'; OutputDir='C:\Exports'; Status='x"y'},
        @{Command='check'; Url='https://arbitrary.example.invalid'})) {
        Test-Case 'invalid fixed input stops before helper/PAC/CLI' {
            Assert-True ((Launch $bad) -eq 3)
            $s = State; Assert-True ($s.helper -eq 0 -and $s.cli -eq 0 -and $s.pac -eq 0)
        }
    }
    Test-Case 'repository output is refused' {
        Assert-True ((Launch @{Command='export'; Project='42'; OutputDir=$fixture}) -eq 3)
        Assert-True ((State).cli -eq 0)
    }
    foreach ($file in @('config.toml', '.venv\Scripts\python.exe', 'src\redmine_readonly\windows_launcher.py')) {
        Test-Case ('missing ' + $file) {
            $path = Join-Path $fixture $file
            Move-Item -LiteralPath $path -Destination ($path + '.saved')
            try {
                Assert-True ((Launch @{Command='check'}) -eq 3)
                Assert-True ((State).cli -eq 0)
            } finally { Move-Item -LiteralPath ($path + '.saved') -Destination $path }
        }
    }
    foreach ($bad in @('socks5://proxy.example.invalid:8080', 'http://user:FAKE-SECRET@proxy.example.invalid',
        'http://proxy.example.invalid/path', 'http://proxy.example.invalid?query',
        'http://proxy.example.invalid#fragment', 'http://proxy.example.invalid:0',
        'http://proxy.example.invalid:65536', 'http://proxy.example.invalid/a/..',
        "http://proxy.example.invalid`n", 'relative')) {
        Test-Case 'invalid system proxy stops without fallback' {
            (State).selected = $bad
            Assert-True ((Launch @{Command='check'; ProxyMode='System'}) -eq 3)
            Assert-True ((State).cli -eq 0 -and (State).pac -eq 1)
        }
    }
    foreach ($failure in @('nullPac', 'failPac')) {
        Test-Case ($failure + ' does not become DIRECT') {
            (State)[$failure] = $true
            Assert-True ((Launch @{Command='check'; ProxyMode='System'}) -eq 3)
            Assert-True ((State).cli -eq 0 -and (State).helper -eq 1)
        }
    }
    foreach ($exists in @($false, $true)) {
        foreach ($failure in @('success', 'cli-error', 'failCli', 'failHelper')) {
            Test-Case ('restore existence=' + $exists + ' after ' + $failure) {
                $s = State; $s.snapshot.Exists = $exists
                if (-not $exists) { $s.snapshot.Value = $null; $s.environment = $null }
                $expected = 0
                if ($failure -eq 'cli-error') { $s.code = 17; $expected = 17 }
                elseif ($failure -ne 'success') { $s[$failure] = $true; $expected = 3 }
                Assert-True ((Launch @{Command='check'; ProxyMode='System'}) -eq $expected)
                Assert-True ($s.restore -eq 1 -and $s.environment -eq $s.snapshot.Value)
            }
        }
    }
    foreach ($cliCode in @(0, 17)) {
        Test-Case ('cleanup failure retains nonzero state, CLI=' + $cliCode) {
            $s = State; $s.failRestore = $true; $s.code = $cliCode
            $expected = 4; if ($cliCode -ne 0) { $expected = $cliCode }
            Assert-True ((Launch @{Command='check'; ProxyMode='System'}) -eq $expected)
        }
    }
    Test-Case 'export argument contract and trailing separator' {
        $o = @{Command='export'; Project='42'; OutputDir='C:\架空 (exports)\';
            Fields='extended'; Status='*'; Tracker=2; IncludeSubprojects=$true; IncludeJstColumns=$true}
        Assert-True ((Launch $o) -eq 0)
        $actual = (State).args
        $expected = @('-I','-m','redmine_readonly.cli','--config',(Join-Path $fixture 'config.toml'),
            'export','--project','42','--output-dir','C:\架空 (exports)','--fields','extended',
            '--status=*','--tracker','2','--include-subprojects','--include-jst-columns')
        Assert-True (($actual | ConvertTo-Json -Compress) -eq ($expected | ConvertTo-Json -Compress))
    }
    # Restore actual boundaries for child-process integration.
    & $module { param($Saved) foreach ($name in $Saved.Keys) { Set-Item ('Function:script:' + $name) $Saved[$name] } } $originals
    if (-not $AllowPowerShell7) {
        $integration = Join-Path $temporary '架空 repository (integration)'
        $null = New-Item -ItemType Directory -Path $integration
        Copy-Item -LiteralPath (Join-Path $repo 'scripts') -Destination $integration -Recurse
        Copy-Item -LiteralPath (Join-Path $repo 'src') -Destination $integration -Recurse
        Copy-Item -LiteralPath (Join-Path $repo 'pyproject.toml'), (Join-Path $repo 'README.md') -Destination $integration
        $python = Join-Path $repo '.venv\Scripts\python.exe'
        & $python -m venv --system-site-packages (Join-Path $integration '.venv')
        if ($LASTEXITCODE -ne 0) { throw 'integration venv setup failed' }
        $childPython = Join-Path $integration '.venv\Scripts\python.exe'
        # The dedicated fixture shadows only the source modules. Reuse installed
        # Requests without downloading/building any packages during the test.
        # An ASCII .pth line also works on 5.1/3.11 with non-ASCII root paths.
        $source = (Join-Path $integration 'src') | ConvertTo-Json -Compress
        $source = [regex]::Replace($source, '[^\x00-\x7f]', { param($m) '\u{0:x4}' -f [int][char]$m.Value })
        $pth = Join-Path $integration '.venv\Lib\site-packages\launcher-fixture.pth'
        [IO.File]::WriteAllText($pth, ('import sys; sys.path.insert(0, ' + $source + ')' + [Environment]::NewLine), [Text.Encoding]::ASCII)
        $config = Join-Path $integration '設定 (sample).toml'
        Set-Content -LiteralPath $config -Value 'base_url="https://redmine.example.invalid/redmine"' -Encoding UTF8
        # Windows PS UTF8 writes BOM; TOML fixture must be UTF8 without BOM.
        [IO.File]::WriteAllText($config, 'base_url="https://redmine.example.invalid/redmine"', (New-Object Text.UTF8Encoding($false)))
        $cli = @'
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
assert args[0] == '--config'
assert Path(args[1]).name == '設定 (sample).toml'
assert args[2:] == ['export', '--project', '42', '--output-dir', os.environ['TEST_OUTPUT'], '--fields', 'extended', '--status=*', '--tracker', '2', '--include-subprojects', '--include-jst-columns']
assert os.environ.get('HTTPS_PROXY') == 'http://chosen.example.invalid:8080'
assert os.environ.get('NO_PROXY') == 'localhost'
assert os.environ.get('REQUESTS_CA_BUNDLE') == 'fictional-ca.pem'
assert not any('proxy.example.invalid' in a for a in args)
print('FAKE-CLI-STDOUT')
print('FAKE-CLI-STDERR', file=sys.stderr)
raise SystemExit(17)
'@
        [IO.File]::WriteAllText((Join-Path $integration 'src\redmine_readonly\cli.py'), $cli, (New-Object Text.UTF8Encoding($false)))
        # Only the fixture's PAC boundary is replaced; real helper and real
        # native invocation run in a dedicated child PowerShell process.
        $mPath = Join-Path $integration 'scripts\RedmineReadonly.Launcher.psm1'
        Add-Content -LiteralPath $mPath -Value @'
function Get-ReadonlySystemProxy { param($Target) return [Uri] 'http://chosen.example.invalid:8080' }
'@
        $caller = Join-Path $temporary 'caller.ps1'
        $callerText = @'
param($Repo, $Output)
$ErrorActionPreference = 'Stop'
$env:HTTPS_PROXY = 'http://original.example.invalid:8080'
if ($env:TEST_SNAPSHOT -eq 'absent') { Remove-Item Env:HTTPS_PROXY -ErrorAction SilentlyContinue }
if ($env:TEST_SNAPSHOT -eq 'lowercase') {
    Remove-Item Env:HTTPS_PROXY -ErrorAction SilentlyContinue
    $env:https_proxy = 'http://original.example.invalid:8080'
}
$env:HTTP_PROXY = 'http://other.example.invalid:8080'
$env:ALL_PROXY = 'http://other.example.invalid:8080'
$env:NO_PROXY = 'localhost'
$env:REQUESTS_CA_BUNDLE = 'fictional-ca.pem'
$env:TEST_OUTPUT = $Output.TrimEnd('\')
$env:REDMINE_API_KEY = 'FAKE-SECRET-KEY'
$initialLocation = (Get-Location).Path
$options = @{ Command='export'; ProxyMode='System'; ConfigPath='設定 (sample).toml'; Project='42'; OutputDir=$Output; Fields='extended'; Status='*'; Tracker=2; IncludeSubprojects=$true; IncludeJstColumns=$true }
& (Join-Path $Repo 'scripts\Invoke-RedmineReadonly.ps1') @options
$code = $LASTEXITCODE
if ($env:TEST_SNAPSHOT -eq 'absent') {
    if (Test-Path Env:HTTPS_PROXY) { throw 'absence restore failed' }
} elseif ($env:HTTPS_PROXY -ne 'http://original.example.invalid:8080') { throw 'restore failed' }
if ((Get-Location).Path -ne $initialLocation) { throw 'cwd changed' }
Write-Output 'CALLER-SURVIVED'
exit $code
'@
        [IO.File]::WriteAllText($caller, $callerText, (New-Object Text.UTF8Encoding($true)))
        $out = Join-Path $temporary '架空 output (exports)'
        function Invoke-TestChild {
            param([string] $Snapshot = 'value')
            $start = New-Object Diagnostics.ProcessStartInfo
            $start.FileName = Join-Path $PSHOME 'powershell.exe'
            $start.Arguments = '-NoProfile -File "' + $caller + '" "' + $integration + '" "' + $out + '\\"'
            $start.UseShellExecute = $false
            $start.EnvironmentVariables['TEST_SNAPSHOT'] = $Snapshot
            $start.RedirectStandardOutput = $true
            $start.RedirectStandardError = $true
            $process = New-Object Diagnostics.Process
            $process.StartInfo = $start
            try {
                $null = $process.Start()
                $stdout = $process.StandardOutput.ReadToEndAsync()
                $stderr = $process.StandardError.ReadToEndAsync()
                $process.WaitForExit()
                return @{ Code = $process.ExitCode; Text = ($stdout.Result + $stderr.Result) }
            } finally { $process.Dispose() }
        }
        $result = Invoke-TestChild
        $code = $result.Code
        if ($code -ne 17) {
            # Only fixed launcher classifications, never exception values.
            $result.Text -split '\r?\n' | Where-Object { $_ -match '^(ERROR|WARNING): launcher [a-z-]+ failed$' } | Write-Host
        }
        Assert-True ($code -eq 17) ('child-process exit: ' + $code)
        $combined = $result.Text
        Assert-True ($combined.Contains('FAKE-CLI-STDOUT') -and $combined.Contains('FAKE-CLI-STDERR') -and $combined.Contains('CALLER-SURVIVED'))
        Assert-True (-not $combined.Contains('FAKE-SECRET') -and -not $combined.Contains('proxy.example.invalid'))
        Assert-True (-not (Test-Path -LiteralPath $out)) 'launcher must not create output runs'
        $script:count++
        Write-Host 'PASS: real child environment, UTF8 helper, native arguments, stdout/stderr, exit and caller survival'
        foreach ($snapshot in @('absent', 'lowercase')) {
            $result = Invoke-TestChild -Snapshot $snapshot
            Assert-True ($result.Code -eq 17 -and $result.Text.Contains('CALLER-SURVIVED'))
            $script:count++
            Write-Host ('PASS: real Process environment restoration with snapshot=' + $snapshot)
        }
        # Real successful CLI exit, including stderr, must remain success.
        [IO.File]::WriteAllText((Join-Path $integration 'src\redmine_readonly\cli.py'), $cli.Replace('SystemExit(17)', 'SystemExit(0)'), (New-Object Text.UTF8Encoding($false)))
        $result = Invoke-TestChild
        Assert-True ($result.Code -eq 0 -and $result.Text.Contains('FAKE-CLI-STDERR') -and $result.Text.Contains('CALLER-SURVIVED'))
        $script:count++
        Write-Host 'PASS: real CLI success preserves zero exit even with stderr'
        [IO.File]::WriteAllText((Join-Path $integration 'src\redmine_readonly\cli.py'), $cli, (New-Object Text.UTF8Encoding($false)))
        # Real Requests NO_PROXY disagreement: no CLI and no API fallback.
        [IO.File]::WriteAllText($caller, $callerText.Replace("'localhost'", "'*'"), (New-Object Text.UTF8Encoding($true)))
        $result = Invoke-TestChild
        Assert-True ($result.Code -eq 3 -and -not $result.Text.Contains('FAKE-CLI'))
        Assert-True (-not $result.Text.Contains('FAKE-SECRET') -and -not $result.Text.Contains('proxy.example.invalid'))
        $script:count++
        Write-Host 'PASS: real Requests NO_PROXY conflict stops before CLI and restores environment'
        [IO.File]::WriteAllText($caller, $callerText, (New-Object Text.UTF8Encoding($true)))
        # Helper failure must be opaque before fake CLI execution.
        [IO.File]::WriteAllText($config, 'base_url="http://FAKE-SECRET.example.invalid"')
        $result = Invoke-TestChild
        $code = $result.Code
        $combined = $result.Text
        Assert-True ($code -eq 3 -and -not $combined.Contains('FAKE-CLI') -and -not $combined.Contains('FAKE-SECRET'))
        $script:count++
        Write-Host 'PASS: real helper failure is safe and prevents CLI'
    }
    if ($script:count -lt 50) { throw 'too few tests; refusing empty/skip success' }
    Write-Host ('Windows launcher tests: ' + $script:count + ' passed; 0 skipped')
} finally {
    Remove-Module RedmineReadonly.Launcher -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $temporary -Recurse -Force -ErrorAction Stop
}
