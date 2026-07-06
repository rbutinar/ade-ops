<#
.SYNOPSIS
  Hard reset of a seat — full deletion + fresh clone from upstream.

.DESCRIPTION
  Completely removes the seat directory and re-clones it from the
  configured upstream remote. Equivalent to "opening a brand new device"
  in the consumer-electronics analogy — no .git/ history, no filesystem
  metadata residue, no orphan files.

  Use this when you need stronger guarantees than the soft reset
  provided by factory-reset.ps1:
  - Sanitization audit / leak verification (no carry-over .git/objects)
  - Pre-release checks where you want the EXACT experience of a fresh
    adopter cloning for the first time
  - Recovery from filesystem corruption or accumulated junk

.PARAMETER SeatPath
  Absolute path to the seat directory to wipe and re-clone.
  REQUIRED. The script refuses to run if SeatPath equals the script's
  own working directory (you cannot delete the directory you are
  running from).

.PARAMETER RemoteUrl
  Git remote URL to clone from. If omitted, the script reads
  the origin URL from the existing seat (BEFORE wiping it) to preserve
  the configuration.

.PARAMETER Branch
  Branch to check out after clone. Default: main.

.PARAMETER WipeClaudeMemory
  If set, also deletes the Claude Code user-scope memory directory at
  ~/.claude/projects/<slug>/ before re-cloning. Default: true (a fresh
  install means fresh memory).

.PARAMETER NonInteractive
  Skip confirmation prompts. For CI use.

.EXAMPLE
  ./fresh-install.ps1 -SeatPath <dev-root>\ade-ops-1
  # Interactive hard reset of ade-ops-1 seat, prompts before each step

.EXAMPLE
  ./fresh-install.ps1 -SeatPath <dev-root>\ade-ops-1 -NonInteractive
  # Hard reset, no prompts (CI / scripted)

.NOTES
  This script MUST be invoked from outside the seat being reset. If you
  run it from inside the seat directory, the script will detect that
  and abort.

  Workflow:
  1. cd to the parent directory of all seats (the dev-root)
  2. Copy fresh-install.ps1 here OR run it from a different location
  3. .\fresh-install.ps1 -SeatPath <dev-root>\ade-ops-1
#>

[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)]
    [string]$SeatPath,
    [string]$RemoteUrl = $null,
    [string]$Branch = 'main',
    [switch]$WipeClaudeMemory = $true,
    [switch]$NonInteractive
)

$ErrorActionPreference = 'Stop'

function Write-Step {
    param([string]$Message)
    Write-Host "→ $Message" -ForegroundColor Cyan
}

function Confirm-Or-Abort {
    param([string]$Prompt)
    if ($NonInteractive) { return }
    $reply = Read-Host "$Prompt (y/N)"
    if ($reply -ne 'y') {
        Write-Host "Aborted by user." -ForegroundColor Yellow
        exit 0
    }
}

# --- Sanity: refuse to run from inside the target ---

$SeatPath = [System.IO.Path]::GetFullPath($SeatPath)
$cwd = [System.IO.Path]::GetFullPath((Get-Location).Path)

if ($cwd.StartsWith($SeatPath, [System.StringComparison]::OrdinalIgnoreCase)) {
    Write-Error @"
You are running fresh-install.ps1 from inside the target seat ($SeatPath).
The script cannot delete the directory it is running from.

Solution:
  1. cd to the parent directory: cd $(Split-Path $SeatPath -Parent)
  2. Copy this script there or invoke with full path
  3. Re-run: .\fresh-install.ps1 -SeatPath '$SeatPath'
"@
    exit 1
}

# --- Discover remote URL from existing seat (if not provided) ---

if (-not $RemoteUrl) {
    if (-not (Test-Path $SeatPath)) {
        Write-Error "SeatPath $SeatPath does not exist and -RemoteUrl was not provided. Cannot determine clone source."
        exit 1
    }
    Write-Step "Reading current origin URL from $SeatPath"
    Push-Location $SeatPath
    try {
        $RemoteUrl = git remote get-url origin 2>$null
        if (-not $RemoteUrl) {
            Write-Error "Cannot read origin URL from $SeatPath. Pass -RemoteUrl explicitly."
            exit 1
        }
        Write-Host "  origin: $RemoteUrl" -ForegroundColor Green
    } finally {
        Pop-Location
    }
}

# --- Show plan + final confirmation ---

Write-Host ""
Write-Host "Fresh install plan:" -ForegroundColor Yellow
Write-Host "  Seat path  : $SeatPath"
Write-Host "  Remote URL : $RemoteUrl"
Write-Host "  Branch     : $Branch"
Write-Host "  Wipe Claude memory: $WipeClaudeMemory"
Write-Host ""
Write-Warning "This will DELETE the entire directory $SeatPath and re-clone from $RemoteUrl."
Write-Warning "Any uncommitted work, session logs, settings.local.json, credentials, etc. will be LOST."

Confirm-Or-Abort "Proceed?"

# --- 1. Delete the seat dir ---

if (Test-Path $SeatPath) {
    Write-Step "Removing $SeatPath..."
    # Walk children to clear ReadOnly attributes (.git/objects often have these)
    Get-ChildItem -Path $SeatPath -Recurse -Force -ErrorAction SilentlyContinue |
        ForEach-Object { try { $_.Attributes = 'Normal' } catch {} }
    Remove-Item -Path $SeatPath -Recurse -Force
    Write-Host "  removed." -ForegroundColor Green
}

# --- 2. Wipe Claude memory ---

if ($WipeClaudeMemory) {
    $seatBasename = Split-Path $SeatPath -Leaf
    $slug = "C--codebase-$seatBasename"
    $memoryDir = Join-Path $env:USERPROFILE ".claude/projects/$slug"
    if (Test-Path $memoryDir) {
        Write-Step "Wiping Claude memory at $memoryDir"
        Get-ChildItem -Path $memoryDir -Recurse -Force -ErrorAction SilentlyContinue |
            ForEach-Object { try { $_.Attributes = 'Normal' } catch {} }
        Remove-Item -Path $memoryDir -Recurse -Force
        Write-Host "  removed." -ForegroundColor Green
    } else {
        Write-Host "  (Claude memory dir not present, skipping)" -ForegroundColor DarkGray
    }
}

# --- 3. Fresh clone ---

Write-Step "Cloning $RemoteUrl into $SeatPath..."
git clone --branch $Branch $RemoteUrl $SeatPath
if ($LASTEXITCODE -ne 0) {
    Write-Error "git clone failed (exit code $LASTEXITCODE)."
    exit 1
}

# --- 4. Smoke verification ---

Write-Step "Verification:"
Push-Location $SeatPath
try {
    Write-Host "  HEAD: $(git log -1 --oneline)"
    Write-Host "  Branch: $(git rev-parse --abbrev-ref HEAD)"
    $commitCount = git rev-list --count HEAD
    Write-Host "  Commits in branch: $commitCount  (expected ~1 for orphan-release template repos)"
} finally {
    Pop-Location
}

Write-Host "`nFresh install complete. The seat at $SeatPath is now in a pristine state — identical to a brand-new clone." -ForegroundColor Green
Write-Host "Open Claude Code in this seat and exercise the onboarding flow as if you were the first adopter.`n" -ForegroundColor Green
