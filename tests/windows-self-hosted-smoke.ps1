$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $PSScriptRoot
$artifactRoot = Join-Path $repoRoot 'test-results\windows-gui-smoke'
New-Item -ItemType Directory -Path $artifactRoot -Force | Out-Null
$logPath = Join-Path $artifactRoot 'self-hosted-smoke.log'
$startedAt = (Get-Date).ToUniversalTime()

function Write-Log {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Message)
    $Message | Tee-Object -FilePath $logPath -Append
}

function Invoke-LoggedCommand {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    Write-Log "=== $Name ==="
    Write-Log "command: $FilePath $($Arguments -join ' ')"
    $stdoutPath = [IO.Path]::GetTempFileName()
    $stderrPath = [IO.Path]::GetTempFileName()
    $commandPath = [IO.Path]::ChangeExtension([IO.Path]::GetTempFileName(), '.cmd')
    $cmd = (Get-Command cmd.exe -ErrorAction Stop).Source
    $quotedCommand = @((('"' + $FilePath + '"'))) + @($Arguments | ForEach-Object { '"' + $_.Replace('"', '""') + '"' })
    $commandText = @(
        '@echo off',
        ('cd /d "' + $repoRoot + '"'),
        (($quotedCommand -join ' ') + ' > "' + $stdoutPath + '" 2> "' + $stderrPath + '"'),
        'exit /b %ERRORLEVEL%'
    ) -join "`r`n"
    [IO.File]::WriteAllText($commandPath, $commandText, [Text.Encoding]::ASCII)

    try {
        $process = Start-Process `
            -FilePath $cmd `
            -ArgumentList @('/d', '/s', '/c', ('"' + $commandPath + '"')) `
            -WorkingDirectory $repoRoot `
            -NoNewWindow `
            -Wait `
            -PassThru

        foreach ($streamPath in @($stdoutPath, $stderrPath)) {
            if (Test-Path -LiteralPath $streamPath) {
                foreach ($line in (Get-Content -LiteralPath $streamPath)) {
                    Write-Log $line
                }
            }
        }

        if ($process.ExitCode -ne 0) {
            throw "$Name failed with exit code $($process.ExitCode)"
        }
    }
    finally {
        Remove-Item -LiteralPath $stdoutPath, $stderrPath, $commandPath -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-WindowsEdgeSmoke {
    param(
        [Parameter(Mandatory = $true)][string]$PlaywrightPath,
        [Parameter(Mandatory = $true)][string]$NodeRoot
    )

    Write-Log '=== Windows Edge browser smoke ==='
    Write-Log "command: $PlaywrightPath test tests/self-hosted-browser-smoke.spec.js --config=playwright.selfhosted.config.js"
    $cmd = (Get-Command cmd.exe -ErrorAction Stop).Source
    $commandPath = [IO.Path]::ChangeExtension([IO.Path]::GetTempFileName(), '.cmd')
    $commandText = @(
        '@echo off',
        ('set "PATH=' + $NodeRoot + ';%PATH%"'),
        'set "PATHEXT=.COM;.EXE;.BAT;.CMD"',
        ('cd /d "' + $repoRoot + '"'),
        ('call "' + $PlaywrightPath + '" test tests/self-hosted-browser-smoke.spec.js --config=playwright.selfhosted.config.js'),
        'exit /b %ERRORLEVEL%'
    ) -join "`r`n"
    [IO.File]::WriteAllText($commandPath, $commandText, [Text.Encoding]::ASCII)

    try {
        $process = Start-Process `
            -FilePath $cmd `
            -ArgumentList @('/d', '/s', '/c', ('"' + $commandPath + '"')) `
            -WorkingDirectory $repoRoot `
            -NoNewWindow `
            -Wait `
            -PassThru
        if ($process.ExitCode -ne 0) {
            throw "Windows Edge browser smoke failed with exit code $($process.ExitCode)"
        }
        Write-Log 'PASS Windows Edge browser smoke'
    }
    finally {
        Remove-Item -LiteralPath $commandPath -Force -ErrorAction SilentlyContinue
    }
}

function Test-PrivacyRetention {
    Write-Log '=== Privacy retention test ==='
    $updateScript = Get-Content -LiteralPath (Join-Path $repoRoot 'scripts\update_vods.py') -Raw
    foreach ($forbidden in @(
        'CHAT_ARCHIVE_ROOT',
        'archive_chat_for_video',
        'write_chat_archive_jsonl',
        'build_chat_archive_records',
        '.chat.jsonl'
    )) {
        if ($updateScript.Contains($forbidden)) {
            throw "Raw chat persistence marker remains in update script: $forbidden"
        }
    }

    $workflow = Get-Content -LiteralPath (Join-Path $repoRoot '.github\workflows\update-vods.yml') -Raw
    if ($workflow.Contains('data/chat-archive') -or $workflow.Contains('*.chat.jsonl')) {
        throw 'Daily workflow still references raw chat storage.'
    }

    $rawChatFiles = @(
        Get-ChildItem -LiteralPath (Join-Path $repoRoot 'data') -File -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -eq 'chat.json' -or $_.Name -like '*.chat.jsonl' -or $_.FullName -match '[\\/]chat-archive[\\/]' }
    )
    if ($rawChatFiles.Count -gt 0) {
        throw "Raw chat files found: $($rawChatFiles.FullName -join ', ')"
    }
    Write-Log 'PASS no raw Twitch chat retention'
}

Push-Location $repoRoot
try {
    $node = (Get-Command node.exe -ErrorAction Stop).Source
    $nodeRoot = Split-Path -Parent $node
    $npmCli = Join-Path $nodeRoot 'node_modules\npm\bin\npm-cli.js'
    if (-not (Test-Path -LiteralPath $npmCli -PathType Leaf)) {
        throw "Required npm CLI is missing: $npmCli"
    }

    Test-PrivacyRetention
    Invoke-LoggedCommand -Name 'Install dependencies' -FilePath $node -Arguments @($npmCli, 'ci')
    $playwright = Join-Path $repoRoot 'node_modules\.bin\playwright.cmd'
    if (-not (Test-Path -LiteralPath $playwright -PathType Leaf)) {
        throw "Required Playwright launcher is missing after npm ci: $playwright"
    }
    Invoke-LoggedCommand -Name 'Frontend unit tests' -FilePath $node -Arguments @(
        '--test',
        'tests/formatters.test.mjs',
        'tests/site-shell.test.mjs',
        'tests/vod-list-view.test.mjs',
        'tests/vod-normalizer.test.mjs'
    )
    Invoke-WindowsEdgeSmoke -PlaywrightPath $playwright -NodeRoot $nodeRoot

    $versionOutputPath = [IO.Path]::GetTempFileName()
    $versionErrorPath = [IO.Path]::GetTempFileName()
    try {
        $versionProcess = Start-Process `
            -FilePath $node `
            -ArgumentList @('--version') `
            -NoNewWindow `
            -Wait `
            -PassThru `
            -RedirectStandardOutput $versionOutputPath `
            -RedirectStandardError $versionErrorPath
        if ($versionProcess.ExitCode -ne 0) {
            throw "Node.js version check failed with exit code $($versionProcess.ExitCode)"
        }
        $nodeVersion = (Get-Content -LiteralPath $versionOutputPath -Raw).Trim()
        if ([string]::IsNullOrWhiteSpace($nodeVersion)) {
            throw 'Node.js version check returned no output.'
        }
    }
    finally {
        Remove-Item -LiteralPath $versionOutputPath, $versionErrorPath -Force -ErrorAction SilentlyContinue
    }

    [pscustomobject]@{
        status = 'passed'
        startedAt = $startedAt.ToString('o')
        completedAt = (Get-Date).ToUniversalTime().ToString('o')
        machine = $env:COMPUTERNAME
        sessionId = [System.Diagnostics.Process]::GetCurrentProcess().SessionId
        node = $nodeVersion
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $artifactRoot 'result.json') -Encoding UTF8
}
catch {
    [pscustomobject]@{
        status = 'failed'
        startedAt = $startedAt.ToString('o')
        completedAt = (Get-Date).ToUniversalTime().ToString('o')
        error = $_.Exception.Message
        machine = $env:COMPUTERNAME
        sessionId = [System.Diagnostics.Process]::GetCurrentProcess().SessionId
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $artifactRoot 'result.json') -Encoding UTF8
    throw
}
finally {
    Pop-Location
}
