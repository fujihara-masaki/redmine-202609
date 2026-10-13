Set-StrictMode -Version 2.0

function Invoke-ReadonlyHelper {
    param([string] $Python, [hashtable] $Message)
    $start = New-Object Diagnostics.ProcessStartInfo
    $start.FileName = $Python
    $start.Arguments = '-I -m redmine_readonly.windows_launcher'
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardInput = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $start
    try {
        if (-not $process.Start()) { throw 'helper' }
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        $json = $Message | ConvertTo-Json -Compress
        # ASCII JSON keeps Windows .NET Framework pipe encoding independent
        # of the console code page, including Japanese configuration paths.
        $json = [regex]::Replace($json, '[^\x00-\x7f]', { param($m) '\u{0:x4}' -f [int][char]$m.Value })
        $process.StandardInput.Write($json)
        $process.StandardInput.Close()
        $process.WaitForExit()
        if ($process.ExitCode -ne 0) { throw 'helper' }
        # Never forward helper stderr, including parse errors or tracebacks.
        $null = $stderr.Result
        return ($stdout.Result | ConvertFrom-Json -ErrorAction Stop)
    } finally {
        $process.Dispose()
    }
}

function Get-ReadonlySystemProxy {
    param([Uri] $Target)
    $system = [Net.WebRequest]::GetSystemWebProxy()
    if ($null -eq $system) { throw 'system' }
    $selected = $system.GetProxy($Target)
    if ($null -eq $selected) { throw 'system' }
    return $selected
}

function Get-ReadonlyDecision {
    param([Uri] $Target, $Selected)
    if ($null -eq $Selected -or -not ($Selected -is [Uri]) -or -not $Selected.IsAbsoluteUri) {
        throw 'system'
    }
    if ($Selected.Equals($Target)) {
        return @{ Kind = 'DIRECT'; Proxy = $null }
    }
    if ($Selected.Scheme -notin @('http', 'https') -or
        [Uri]::CheckHostName($Selected.DnsSafeHost) -eq [UriHostNameType]::Unknown -or
        $Selected.Port -lt 1 -or $Selected.Port -gt 65535 -or
        $Selected.UserInfo -ne '' -or $Selected.OriginalString.Contains('@') -or
        $Selected.OriginalString -match '[\x00-\x20\x7f\\?#]' -or
        $Selected.AbsolutePath -ne '/' -or
        $Selected.OriginalString -notmatch '\Ahttps?://[^/]+/?\z') { throw 'system' }
    return @{ Kind = 'PROXY'; Proxy = $Selected.OriginalString }
}

function Get-ReadonlyEnvironment {
    $variables = [Environment]::GetEnvironmentVariables('Process')
    # Windows environment names are case insensitive; the returned dictionary
    # must not be assumed to have the same comparer.
    foreach ($name in $variables.Keys) {
        if ([string]::Equals($name, 'HTTPS_PROXY', [StringComparison]::OrdinalIgnoreCase)) {
            return @{ Exists = $true; Value = $variables[$name] }
        }
    }
    return @{ Exists = $false; Value = $null }
}

function Set-ReadonlyEnvironment {
    param([AllowNull()][string] $Value)
    [Environment]::SetEnvironmentVariable('HTTPS_PROXY', $Value, 'Process')
}

function Restore-ReadonlyEnvironment {
    param([hashtable] $Snapshot)
    $value = $null
    if ($Snapshot.Exists) { $value = $Snapshot.Value }
    Set-ReadonlyEnvironment -Value $value
    $actual = Get-ReadonlyEnvironment
    if ($actual.Exists -ne $Snapshot.Exists -or $actual.Value -cne $Snapshot.Value) {
        throw 'cleanup'
    }
}

function Invoke-ReadonlyCli {
    param([string] $Python, [string[]] $Arguments)
    # .NET Framework has no ArgumentList. Quote each fixed CLI argument using
    # Windows CRT rules; this is passed to python.exe, never to a command shell.
    $quoted = foreach ($argument in $Arguments) {
        '"' + ([regex]::Replace(
            ([regex]::Replace($argument, '(\\*)"', '$1$1\"')), '(\\+)$', '$1$1')) + '"'
    }
    $start = New-Object Diagnostics.ProcessStartInfo
    $start.FileName = $Python
    $start.Arguments = $quoted -join ' '
    $start.UseShellExecute = $false
    # Inherit all three console handles: no helper pipe touches CLI/getpass.
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $start
    try {
        if (-not $process.Start()) { throw 'launch' }
        $process.WaitForExit()
        $nativeCode = $process.ExitCode
        return [int] $nativeCode
    } finally {
        $process.Dispose()
    }
}

function Resolve-ReadonlyPath {
    param([string] $Value, [string] $RelativeTo)
    if ([string]::IsNullOrWhiteSpace($Value) -or $Value -match '[\x00-\x1f\x7f"*?]') {
        throw 'input'
    }
    if (-not [IO.Path]::IsPathRooted($Value)) { $Value = Join-Path $RelativeTo $Value }
    $path = [IO.Path]::GetFullPath($Value)
    # Remove trailing separators from non-root paths: PS 5.1 native argument
    # quoting otherwise makes a trailing backslash escape the closing quote.
    if ($path -ne [IO.Path]::GetPathRoot($path)) { $path = $path.TrimEnd('\', '/') }
    return $path
}

function Test-ReadonlyContainedOutput {
    param([string] $Root, [string] $Output)
    # Inputs have already been normalized. Trim only comparison strings so
    # filesystem roots get exactly one boundary separator. Never change the
    # actual C:\ root to the drive-relative C:, or the UNC leading separators.
    $rootComparison = $Root.TrimEnd('\', '/')
    $outputComparison = $Output.TrimEnd('\', '/')
    $boundary = $rootComparison + '\'
    return ($outputComparison.Equals($rootComparison, [StringComparison]::OrdinalIgnoreCase) -or
        $outputComparison.StartsWith($boundary, [StringComparison]::OrdinalIgnoreCase))
}

function Invoke-ReadonlyLauncher {
    param([string] $Root, [hashtable] $Options)
    $code = 3
    $cliCompleted = $false
    $changed = $false
    $snapshot = $null
    $classification = 'input'
    try {
        $o = @{ ProxyMode = 'Inherit'; Fields = 'basic'; Status = '*' }
        foreach ($key in $Options.Keys) {
            if ($key -notin @('Command', 'ProxyMode', 'ConfigPath', 'Project', 'OutputDir',
                'Fields', 'IncludeSubprojects', 'IncludeJstColumns', 'Status', 'Tracker')) { throw 'input' }
            $o[$key] = $Options[$key]
        }
        if (-not $o.ContainsKey('Command') -or
            $o.Command -cnotin @('check', 'resolve-project', 'export') -or
            $o.ProxyMode -cnotin @('Inherit', 'System') -or
            $o.Fields -cnotin @('basic', 'extended')) { throw 'input' }
        $exportOnly = @('OutputDir', 'Fields', 'IncludeSubprojects', 'IncludeJstColumns', 'Status', 'Tracker')
        if ($o.Command -ne 'export') {
            foreach ($key in $exportOnly) { if ($Options.ContainsKey($key)) { throw 'input' } }
        }
        if ($o.Command -eq 'check') {
            if ($Options.ContainsKey('Project')) { throw 'input' }
            $o.Project = ''
        } elseif (-not $o.ContainsKey('Project') -or
            $o.Project -cnotmatch '\A(?:[1-9][0-9]*|[a-z0-9][a-z0-9_-]*)\z') { throw 'input' }
        $Root = Resolve-ReadonlyPath $Root $Root
        $config = Join-Path $Root 'config.toml'
        if ($o.ContainsKey('ConfigPath')) { $config = Resolve-ReadonlyPath $o.ConfigPath $Root }
        $cliArgs = @('-I', '-m', 'redmine_readonly.cli', '--config', $config, $o.Command)
        if ($o.Command -ne 'check') { $cliArgs += @('--project', $o.Project) }
        if ($o.Command -eq 'export') {
            if (-not $o.ContainsKey('OutputDir') -or [string]::IsNullOrWhiteSpace($o.OutputDir) -or
                $o.OutputDir -notmatch '\A(?:[A-Za-z]:[\\/]|\\\\[^\\]+\\[^\\]+)') { throw 'input' }
            $output = Resolve-ReadonlyPath $o.OutputDir $Root
            if (Test-ReadonlyContainedOutput $Root $output) { throw 'input' }
            if ([string]::IsNullOrWhiteSpace($o.Status) -or $o.Status -match '[\x00-\x1f\x7f"]') { throw 'input' }
            $cliArgs += @('--output-dir', $output, '--fields', $o.Fields, ('--status=' + $o.Status))
            if ($o.ContainsKey('Tracker')) {
                $trackerId = 0
                if ($o.Tracker -notmatch '\A[1-9][0-9]*\z' -or
                    -not [int]::TryParse([string] $o.Tracker, [ref] $trackerId)) { throw 'input' }
                $cliArgs += @('--tracker', [string] $o.Tracker)
            }
            if ($o.ContainsKey('IncludeSubprojects') -and $o.IncludeSubprojects) { $cliArgs += '--include-subprojects' }
            if ($o.ContainsKey('IncludeJstColumns') -and $o.IncludeJstColumns) { $cliArgs += '--include-jst-columns' }
        }
        $classification = 'setup'
        $python = Join-Path $Root '.venv\Scripts\python.exe'
        foreach ($file in @($python, $config, (Join-Path $Root 'src\redmine_readonly\windows_launcher.py'))) {
            if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw 'setup' }
        }
        $message = @{ stage = 'target'; root = $Root; config = $config; command = $o.Command; project = $o.Project }
        $classification = 'preflight'
        $target = Invoke-ReadonlyHelper $python $message
        if ($o.ProxyMode -eq 'System') {
            $classification = 'system-selection'
            $uri = [Uri] $target.url
            if (-not $uri.IsAbsoluteUri -or $uri.Scheme -ne 'https') { throw 'system' }
            $decision = Get-ReadonlyDecision $uri (Get-ReadonlySystemProxy $uri)
            if ($decision.Kind -eq 'PROXY') {
                $snapshot = Get-ReadonlyEnvironment
                $changed = $true
                Set-ReadonlyEnvironment $decision.Proxy
            }
            $message.stage = 'verify'
            $message.decision = $decision.Kind
            $message.proxy = $decision.Proxy
            $classification = 'proxy-conflict-or-preflight'
            $verified = Invoke-ReadonlyHelper $python $message
            if ($verified.ok -ne $true) { throw 'preflight' }
            Write-Host ('ProxyMode=System; ' + $decision.Kind)
        } else {
            Write-Host 'ProxyMode=Inherit'
        }
        $classification = 'launch'
        $code = Invoke-ReadonlyCli $python $cliArgs
        $cliCompleted = $true
    } catch {
        [Console]::Error.WriteLine('ERROR: launcher ' + $classification + ' failed')
        $code = 3
    } finally {
        if ($changed) {
            try { Restore-ReadonlyEnvironment $snapshot } catch {
                [Console]::Error.WriteLine('WARNING: launcher environment cleanup failed')
                if ($code -eq 0 -or -not $cliCompleted) { $code = 4 }
            }
        }
    }
    return $code
}

Export-ModuleMember -Function Invoke-ReadonlyLauncher
