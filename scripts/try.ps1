[CmdletBinding()]
param(
  [string]$InputPath,
  [switch]$Cleanup,
  [switch]$CleanupOnly,
  [string]$CacheBase,
  [switch]$AcceptDownloads,
  [switch]$PlanOnly,
  [switch]$PortablePython
)

$ErrorActionPreference = 'Stop'
$cacheName = 'quick-try-v0.1.0a4-sha256-ps1'
$markerText = 'nsfw-guard-trial-v1'
$wheelUrl = 'https://github.com/IamAngusU/nsfw-guard/releases/download/v0.1.0a4/nsfw_guard-0.1.0a4-py3-none-any.whl'
$wheelSha256 = '754889cf0bd646f8f861c27fe4b1b25cd701c91f3813ac7a2bbb01200368c124'
$wheel = "nsfw-guard[cpu] @ $wheelUrl#sha256=$wheelSha256"
$modelUrl = 'https://huggingface.co/KanariKanaru/nsfw-image-detection-384-onnx/resolve/8edc47eedf74b30fd379673bc202fe3b754b1538/model.onnx?download=true'
$modelSha256 = 'E9350E576608AFE4B57A089FFEB0EBAFA1389CDCEA4882DD61DF28C45F1C24D2'
$uvVersion = '0.12.13'
$pythonBuildSource = 'https://github.com/astral-sh/python-build-standalone/releases/download'

function Find-SupportedPython {
  $candidates = @(
    @{ Name = 'py'; Flags = @('-3.12') },
    @{ Name = 'py'; Flags = @('-3.11') },
    @{ Name = 'py'; Flags = @('-3.10') },
    @{ Name = 'python'; Flags = @() },
    @{ Name = 'python3'; Flags = @() }
  )
  foreach ($candidate in $candidates) {
    $command = $candidate.Name
    $resolved = Get-Command $command -ErrorAction SilentlyContinue
    if (-not $resolved) { continue }
    if ($resolved.Source -like '*\Microsoft\WindowsApps\python*.exe') {
      try {
        if (-not (Get-AppxPackage -Name 'PythonSoftwareFoundation.Python.*' -ErrorAction Stop)) { continue }
      } catch { continue }
    }
    $flags = @($candidate.Flags)
    try {
      & $command @flags -c 'import sys, venv, ensurepip; sys.exit(0 if (3, 10) <= sys.version_info[:2] < (3, 13) else 1)'
      if ($LASTEXITCODE -eq 0) { return $candidate }
    } catch { continue }
  }
  return $null
}

function Get-UvRelease {
  $architecture = [Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
  switch ($architecture) {
    'X64' { $platform = 'x86_64'; $hash = 'A86C9DC7BAD9B03F388583B7187C05FE9951C2E0D392217E8FD43D97787F6EC2' }
    'Arm64' { $platform = 'aarch64'; $hash = '1EFB2654B06E7063D4AC1FC9D49A9BDA9A6704D82F035B589A2751A592F14151' }
    default { throw "Portable Python requires Windows x64 or ARM64; found $architecture." }
  }
  $name = "uv-$platform-pc-windows-msvc.zip"
  return @{ Url = "https://github.com/astral-sh/uv/releases/download/$uvVersion/$name"; Sha256 = $hash; Name = $name }
}

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

if ($CacheBase) {
  $bases = @($CacheBase)
} else {
  # Documents may be redirected to OneDrive or another synced location.
  $bases = @((Join-Path $userHome '.cache'))
}

$root = $null
$base = $null
$rootWasCreated = $false
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
    $rootWasCreated = $created
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
$uv = Join-Path $root 'tools\uv.exe'
$managedPython = Join-Path $root 'python'
$uvCache = Join-Path $root 'uv-cache'
Assert-PlainPath $venv
Assert-PlainPath $model
Assert-PlainPath $uv

$needsEnvironment = -not (Test-Path -LiteralPath $python)
$systemPython = if ($needsEnvironment -and -not $PortablePython) { Find-SupportedPython } else { $null }
$usePortable = $needsEnvironment -and -not $systemPython
$uvRelease = if ($usePortable) { Get-UvRelease } else { $null }
$needsGuard = $needsEnvironment -or -not (Test-Path -LiteralPath $guard)
$needsModel = -not (Test-Path -LiteralPath $model)
if (-not $needsModel) {
  $needsModel = ((Get-FileHash -LiteralPath $model -Algorithm SHA256).Hash -ne $modelSha256)
}
$needsDownloads = $usePortable -or $needsGuard -or $needsModel

Write-Host "`nDownload plan / Download-Plan:"
if ($usePortable) {
  if (-not (Test-Path -LiteralPath $uv)) {
    Write-Host "- uv $uvVersion ($($uvRelease.Name), about 18 MB): $($uvRelease.Url)"
    Write-Host "  SHA-256: $($uvRelease.Sha256)"
  }
  Write-Host "- CPython 3.12 (about 20-30 MB if not cached): $pythonBuildSource"
}
if ($needsGuard) {
  Write-Host "- NSFW Guard 0.1.0a4 wheel (71 KB): $wheelUrl"
  Write-Host "  SHA-256: $wheelSha256"
  Write-Host '- CPU dependencies (platform-dependent, about 35 MB): https://pypi.org/simple/'
}
if ($needsModel) {
  Write-Host "- ONNX model (22.5 MB): $modelUrl"
  Write-Host "  SHA-256: $modelSha256 (checked by NSFW Guard)"
}
if (-not $needsDownloads) { Write-Host '- None / Keine; private cache is ready.' }
Write-Host "Private storage / Privater Speicherort: $root"
Write-Host 'No admin rights, global Python install, or PATH change. -Cleanup removes this private trial cache.'
if ($PlanOnly) {
  if ($rootWasCreated) { Remove-TrialCache $base $root }
  return
}
if ($needsDownloads -and -not $AcceptDownloads) {
  $answer = [string](Read-Host 'Allow all listed downloads? [y/yes/j/ja] / Alle Downloads erlauben? (default: no)')
  if ($answer.Trim().ToLowerInvariant() -notin @('y', 'yes', 'j', 'ja')) {
    if ($rootWasCreated) { Remove-TrialCache $base $root }
    throw 'Downloads declined; no download started / Downloads abgelehnt; nichts geladen.'
  }
}

try {
  if ($needsEnvironment) {
    if ($usePortable) {
      if (-not (Test-Path -LiteralPath $uv)) {
        $archive = Join-Path $root $uvRelease.Name
        Assert-PlainPath $archive
        try {
          Invoke-WebRequest -Uri $uvRelease.Url -OutFile $archive -UseBasicParsing
          if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $uvRelease.Sha256) {
            throw 'Portable uv archive failed SHA-256 verification; refusing to run it.'
          }
          Expand-Archive -LiteralPath $archive -DestinationPath (Join-Path $root 'tools') -Force
        } finally {
          Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
        }
      }
      if (-not (Test-Path -LiteralPath $uv)) { throw 'Verified uv archive did not contain uv.exe.' }
      $savedUvEnv = @{}
      foreach ($key in @('UV_PYTHON_INSTALL_DIR', 'UV_CACHE_DIR', 'UV_PYTHON_DOWNLOADS', 'UV_INDEX', 'UV_INDEX_URL', 'UV_EXTRA_INDEX_URL', 'UV_FIND_LINKS')) {
        $savedUvEnv[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
      }
      try {
        $env:UV_PYTHON_INSTALL_DIR = $managedPython
        $env:UV_CACHE_DIR = $uvCache
        $env:UV_PYTHON_DOWNLOADS = 'manual'
        $env:UV_INDEX = $null
        $env:UV_INDEX_URL = $null
        $env:UV_EXTRA_INDEX_URL = $null
        $env:UV_FIND_LINKS = $null
        & $uv --no-config --cache-dir $uvCache python install 3.12 --install-dir $managedPython --no-bin --no-registry --mirror $pythonBuildSource
        if ($LASTEXITCODE -ne 0) { throw 'Private Python installation failed.' }
        & $uv --no-config --cache-dir $uvCache venv --python 3.12 --managed-python --no-python-downloads $venv
        if ($LASTEXITCODE -ne 0) { throw 'Private Python environment creation failed.' }
        if (-not (Test-Path -LiteralPath $python)) { throw 'Private Python executable is missing.' }
        & $uv --no-config --cache-dir $uvCache pip install --python $python --default-index 'https://pypi.org/simple' --only-binary ':all:' $wheel
        if ($LASTEXITCODE -ne 0) { throw 'Package installation failed; check the uv output and network.' }
      } finally {
        foreach ($key in $savedUvEnv.Keys) {
          [Environment]::SetEnvironmentVariable($key, $savedUvEnv[$key], 'Process')
        }
      }
    } else {
      $pythonCommand = $systemPython.Name
      $launcherFlags = @($systemPython.Flags)
      & $pythonCommand @launcherFlags -m venv $venv
      if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $python)) {
        throw "Could not create the private environment at '$venv'. Try -CacheBase with another writable folder."
      }
    }
  }
  if ($needsGuard -and -not $usePortable) {
    & $python -m pip --isolated install --no-cache-dir --disable-pip-version-check --index-url 'https://pypi.org/simple' --only-binary ':all:' $wheel
    if ($LASTEXITCODE -ne 0) { throw 'Package installation failed; check the pip output, network and free space.' }
  }
  if (-not (Test-Path -LiteralPath $guard)) { throw 'Package installation did not create the CLI.' }
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
