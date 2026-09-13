[CmdletBinding()]
param(
  [string]$InputPath,
  [switch]$Cleanup,
  [switch]$CleanupOnly,
  [string]$CacheBase
)

$ErrorActionPreference = 'Stop'
$cacheName = 'quick-try-v0.1.0a4-sha256-ps1'
$markerText = 'nsfw-guard-trial-v1'
$wheel = 'nsfw-guard[cpu] @ https://github.com/IamAngusU/nsfw-guard/releases/download/v0.1.0a4/nsfw_guard-0.1.0a4-py3-none-any.whl#sha256=754889cf0bd646f8f861c27fe4b1b25cd701c91f3813ac7a2bbb01200368c124'

function Assert-PlainPath([string]$Path) {
  $cursor = [IO.Path]::GetFullPath($Path)
  while ($cursor) {
    if (Test-Path -LiteralPath $cursor) {
      $item = Get-Item -LiteralPath $cursor -Force
      if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Refusing a linked cache path: $cursor"
      }
    }
    $parent = [IO.Directory]::GetParent($cursor)
    $cursor = if ($parent) { $parent.FullName } else { $null }
  }
}

function Remove-TrialCache([string]$Base, [string]$Root) {
  $expected = [IO.Path]::GetFullPath((Join-Path $Base (Join-Path 'nsfw-guard' $cacheName)))
  if ($Root -ne $expected) { throw 'Unsafe cleanup path.' }
  if (-not (Test-Path -LiteralPath $Root)) {
    Write-Host "Trial cache already absent / Test-Cache bereits entfernt: $Root"
    return
  }
  Assert-PlainPath $Root
  if ((Get-Content -LiteralPath (Join-Path $Root '.owner') -Raw).Trim() -ne $markerText) {
    throw 'Ownership marker missing or changed.'
  }
  Remove-Item -LiteralPath $Root -Recurse -Force
  Write-Host "Removed trial cache / Test-Cache entfernt: $Root"
}

$userHome = [IO.Path]::GetFullPath([Environment]::GetFolderPath('UserProfile'))
if ($CleanupOnly) {
  $base = if ($CacheBase) { [IO.Path]::GetFullPath($CacheBase) } else { Join-Path $userHome '.cache' }
  $root = [IO.Path]::GetFullPath((Join-Path $base (Join-Path 'nsfw-guard' $cacheName)))
  Remove-TrialCache $base $root
  return
}

if (-not $InputPath) { $InputPath = Read-Host 'Image or folder path / Bild- oder Ordnerpfad' }
$InputPath = $InputPath.Trim().Trim('"')
try {
  $inputItem = Get-Item -LiteralPath $InputPath -ErrorAction Stop
  if ($inputItem.PSProvider.Name -ne 'FileSystem') { throw 'Only local filesystem paths are supported.' }
  if ($inputItem.PSIsContainer) {
    $entries = [IO.Directory]::EnumerateFileSystemEntries($inputItem.FullName).GetEnumerator()
    try { [void]$entries.MoveNext() } finally { $entries.Dispose() }
  } else {
    $stream = [IO.File]::Open($inputItem.FullName, 'Open', 'Read', 'ReadWrite')
    $stream.Dispose()
  }
} catch {
  throw "Cannot read '$InputPath'. Check the path and your permissions. $($_.Exception.Message)"
}

$pythonCommand = $null
$launcherFlags = @()
foreach ($candidate in @('py', 'python')) {
  if (-not (Get-Command $candidate -ErrorAction SilentlyContinue)) { continue }
  $candidateFlags = @()
  if ($candidate -eq 'py') { $candidateFlags = @('-3') }
  try {
    & $candidate @candidateFlags -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'
    if ($LASTEXITCODE -eq 0) {
      $pythonCommand = $candidate
      $launcherFlags = $candidateFlags
      break
    }
  } catch { continue }
}
if (-not $pythonCommand) {
  throw 'Python 3.10+ is needed. Tried py -3 and python; install one for your user account and retry.'
}

if ($CacheBase) {
  $bases = @($CacheBase)
} else {
  # Documents may be redirected to OneDrive or another synced location.
  $bases = @((Join-Path $userHome '.cache'))
}

$root = $null
$base = $null
$problems = @()
foreach ($candidate in $bases) {
  $created = $false
  try {
    $base = [IO.Path]::GetFullPath($candidate)
    $root = [IO.Path]::GetFullPath((Join-Path $base (Join-Path 'nsfw-guard' $cacheName)))
    if (-not $root.StartsWith($base.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
      throw 'Unsafe cache path.'
    }
    Assert-PlainPath $root
    if (Test-Path -LiteralPath $root) {
      $item = Get-Item -LiteralPath $root -Force
      if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Cache is a link.' }
      if ((Get-Content -LiteralPath (Join-Path $root '.owner') -Raw -ErrorAction Stop).Trim() -ne $markerText) {
        throw 'Cache folder is not owned by this trial.'
      }
    } else {
      [void][IO.Directory]::CreateDirectory($root)
      $created = $true
      [IO.File]::WriteAllText((Join-Path $root '.owner'), $markerText)
    }
    $probe = Join-Path $root '.write-probe'
    [IO.File]::WriteAllText($probe, 'ok')
    Remove-Item -LiteralPath $probe -Force
    break
  } catch {
    $problems += "$candidate ($($_.Exception.Message))"
    if ($created -and $root -and (Test-Path -LiteralPath $root)) {
      Remove-Item -LiteralPath (Join-Path $root '.write-probe') -Force -ErrorAction SilentlyContinue
      Remove-Item -LiteralPath (Join-Path $root '.owner') -Force -ErrorAction SilentlyContinue
      Remove-Item -LiteralPath $root -Force -ErrorAction SilentlyContinue
    }
    $root = $null
    $base = $null
  }
}
if (-not $root) {
  throw "No writable private cache location. Try -CacheBase 'D:\some-writable-folder'. Checked: $($problems -join '; ')"
}

$venv = Join-Path $root 'venv'
$python = Join-Path $venv 'Scripts\python.exe'
$guard = Join-Path $venv 'Scripts\nsfw-guard.exe'
$model = Join-Path $root 'model.onnx'
try {
  if (-not (Test-Path -LiteralPath $python)) {
    & $pythonCommand @launcherFlags -m venv $venv
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $python)) {
      throw "Could not create the private environment at '$venv'. Try -CacheBase with another writable folder."
    }
  }
  if (-not (Test-Path -LiteralPath $guard)) {
    & $python -m pip install --no-cache-dir --disable-pip-version-check $wheel
    if ($LASTEXITCODE -ne 0) { throw 'Package installation failed; check the pip output, network and free space.' }
    if (-not (Test-Path -LiteralPath $guard)) { throw 'Package installation did not create the CLI.' }
  }
  Assert-PlainPath $root
  if ($inputItem.PSIsContainer) {
    & $guard folder $inputItem.FullName --provider cpu --model-path $model --max-files 32 --output-dir (Join-Path $root 'results') --links
  } else {
    & $guard scan $inputItem.FullName --provider cpu --model-path $model
  }
  $scanExit = $LASTEXITCODE
} finally {
  if ($Cleanup) {
    try {
      Remove-TrialCache $base $root
    } catch {
      throw "Cleanup did not finish at '$root'. Nothing else was removed. $($_.Exception.Message)"
    }
  }
}
if ($scanExit -notin @(0, 10, 20)) { throw "Scan failed (exit code $scanExit); check the output above." }
