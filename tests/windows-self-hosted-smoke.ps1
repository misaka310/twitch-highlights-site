$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $PSScriptRoot
$artifactRoot = Join-Path $repoRoot 'test-results\windows-gui-smoke'
New-Item -ItemType Directory -Path $artifactRoot -Force | Out-Null
$logPath = Join-Path $artifactRoot 'self-hosted-smoke.log'
$startedAt = (Get-Date).ToUniversalTime()

function Write-Log {
    param([Parameter(Mandatory = $true)][string]$Message)
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
    & $FilePath @Arguments 2>&1 | Tee-Object -FilePath $logPath -Append
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE"
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
    $npm = (Get-Command npm.cmd -ErrorAction Stop).Source
    $node = (Get-Command node.exe -ErrorAction Stop).Source
    $npx = (Get-Command npx.cmd -ErrorAction Stop).Source

    Test-PrivacyRetention
    Invoke-LoggedCommand -Name 'Install dependencies' -FilePath $npm -Arguments @('ci')
    Invoke-LoggedCommand -Name 'Frontend unit tests' -FilePath $node -Arguments @(
        '--test',
        'tests/formatters.test.mjs',
        'tests/site-shell.test.mjs',
        'tests/vod-list-view.test.mjs',
        'tests/vod-normalizer.test.mjs'
    )
    Invoke-LoggedCommand -Name 'Windows Edge browser smoke' -FilePath $npx -Arguments @(
        'playwright',
        'test',
        'tests/self-hosted-browser-smoke.spec.js',
        '--config=playwright.selfhosted.config.js'
    )

    [pscustomobject]@{
        status = 'passed'
        startedAt = $startedAt.ToString('o')
        completedAt = (Get-Date).ToUniversalTime().ToString('o')
        machine = $env:COMPUTERNAME
        sessionId = [System.Diagnostics.Process]::GetCurrentProcess().SessionId
        node = (& $node --version).Trim()
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
