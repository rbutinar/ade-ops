<#
.SYNOPSIS
  Soft reset of an onboarding-canary seat to zero user-data state.

.DESCRIPTION
  Wipes the seat's user-data partition (sessions, identity manifest,
  per-project settings, pulled state, credentials) and aligns the
  framework to the upstream HEAD via git reset --hard. The .git
  history, filesystem metadata, and (by default) the Claude Code
  user-scope memory all SURVIVE.

  Use this script before each onboarding test cycle on a seat
  configured with role: onboarding-canary in its .seat.yaml.

  For a complete teardown (fresh-clone), use fresh-install.ps1 instead.

.PARAMETER WipeClaudeMemory
  If set, also deletes the Claude Code user-scope memory directory at
  ~/.claude/projects/<slug>/. Default: false (memory survives).

.PARAMETER Confirm
  Prompts before each destructive operation. Default: true.
  Pass -Confirm:$false for non-interactive runs (CI / scripted).

.EXAMPLE
  ./factory-reset.ps1
  # Interactive soft reset, memory preserved

.EXAMPLE
  ./factory-reset.ps1 -WipeClaudeMemory -Confirm:$false
  # Full canary cycle preparation, no prompts

.NOTES
  Must be run from the seat repo root (the directory containing
  the .git folder of this seat).

  The script intentionally does NOT touch:
  - .git/ (history preserved; use fresh-install for that)
  - Sibling seats on the same machine
  - User-scope env vars (use setx VAR "" manually if needed)
#>

[CmdletBinding(SupportsShouldProcess)]
param(
    [switch]$WipeClaudeMemory,
    [switch]$NonInteractive
)

$ErrorActionPreference = 'Stop'

function Write-Step {
    param([string]$Message)
    Write-Host "→ $Message" -ForegroundColor Cyan
}

function Remove-IfExists {
    param([string]$Path, [string]$Description)
    if (Test-Path $Path) {
        Write-Step "Removing $Description ($Path)"
        if (-not $NonInteractive) {
            $confirm = Read-Host "  Proceed? (y/N)"
            if ($confirm -ne 'y') {
                Write-Host "  Skipped." -ForegroundColor Yellow
                return
            }
        }
        Remove-Item -Path $Path -Recurse -Force
        Write-Host "  removed." -ForegroundColor Green
    } else {
        Write-Host "  (not present, skip) $Description" -ForegroundColor DarkGray
    }
}

# --- Locate seat root ---

$seatRoot = git rev-parse --show-toplevel 2>$null
if (-not $seatRoot) {
    Write-Error "Not inside a git repo. cd into the seat root first."
    exit 1
}
$seatRoot = $seatRoot.Trim()
Set-Location $seatRoot
Write-Step "Seat root: $seatRoot"

# --- Confirm the seat is actually a canary (best-effort guardrail) ---

$seatManifest = Get-ChildItem -Path "distributions" -Recurse -Filter ".seat.yaml" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($seatManifest) {
    $manifestText = Get-Content $seatManifest.FullName -Raw
    if ($manifestText -notmatch "onboarding-canary") {
        Write-Warning "This seat does NOT declare role onboarding-canary in .seat.yaml."
        Write-Warning "factory-reset is intended for canary seats. Running it on an operator"
        Write-Warning "seat will wipe your live session logs and pulled state."
        if (-not $NonInteractive) {
            $confirm = Read-Host "Continue anyway? (y/N)"
            if ($confirm -ne 'y') {
                Write-Host "Aborted." -ForegroundColor Yellow
                exit 0
            }
        }
    }
}

# --- 1. Wipe user-data partition ---

Write-Step "Wiping user-data partition..."

Remove-IfExists ".claude/settings.local.json"                        "per-seat Claude settings"
Get-ChildItem "distributions" -Recurse -Filter ".seat.yaml"          -ErrorAction SilentlyContinue | ForEach-Object {
    Remove-IfExists $_.FullName                                       "seat manifest ($($_.FullName))"
}
Get-ChildItem "distributions" -Recurse -Filter ".seat-sessions"      -Directory -ErrorAction SilentlyContinue | ForEach-Object {
    Remove-IfExists $_.FullName                                       "session logs ($($_.FullName))"
}
Get-ChildItem "distributions" -Recurse -Filter ".ade-ops-onboarding-done" -ErrorAction SilentlyContinue | ForEach-Object {
    Remove-IfExists $_.FullName                                       "onboarding sentinel"
}
Get-ChildItem "distributions" -Recurse -Filter "state" -Directory    -ErrorAction SilentlyContinue | ForEach-Object {
    Remove-IfExists $_.FullName                                       "pulled remote state ($($_.FullName))"
}
Get-ChildItem "distributions" -Recurse -Filter "credentials.yaml"    -ErrorAction SilentlyContinue | ForEach-Object {
    Remove-IfExists $_.FullName                                       "credentials file ($($_.FullName))"
}
Get-ChildItem "distributions" -Recurse -Filter "ops.log"             -ErrorAction SilentlyContinue | ForEach-Object {
    Remove-IfExists $_.FullName                                       "per-project ops.log ($($_.FullName))"
}

# --- 2. Optional: wipe user-scope Claude memory ---

if ($WipeClaudeMemory) {
    Write-Step "Wiping Claude Code user-scope memory..."
    $seatBasename = Split-Path $seatRoot -Leaf
    $slug = "C--codebase-$seatBasename"
    $memoryDir = Join-Path $env:USERPROFILE ".claude/projects/$slug"
    Remove-IfExists $memoryDir "Claude memory directory ($slug)"
} else {
    Write-Host "  (skipping Claude memory wipe — use -WipeClaudeMemory to include)" -ForegroundColor DarkGray
}

# --- 3. Align framework to upstream ---

Write-Step "Fetching upstream..."
git fetch origin

Write-Step "Aligning framework to origin/main via reset --hard"
if (-not $NonInteractive) {
    $confirm = Read-Host "  This will discard any local commits ahead of origin/main. Proceed? (y/N)"
    if ($confirm -ne 'y') {
        Write-Host "  Skipped reset. Framework left at current HEAD." -ForegroundColor Yellow
        exit 0
    }
}
git reset --hard origin/main

# --- 4. Confirm new state ---

Write-Step "Reset complete. New HEAD:"
git log -1 --oneline

Write-Host "`nThis seat is now in zero user-data state aligned to upstream." -ForegroundColor Green
Write-Host "Open Claude Code in this seat and exercise /ade-ops-onboarding as if it were the first run.`n" -ForegroundColor Green
