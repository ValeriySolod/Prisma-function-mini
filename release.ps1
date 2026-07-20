[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root

$VersionMatch = Select-String -LiteralPath (Join-Path $Root "version.py") -Pattern '^__version__\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+)"$'
if (-not $VersionMatch) { throw "Could not read the release version from version.py." }
$Version = $VersionMatch.Matches[0].Groups[1].Value
$BuildDirectory = Join-Path $Root "dist\PrismaFunctionMini"
$Executable = Join-Path $BuildDirectory "PrismaFunctionMini.exe"
$ReleaseDirectory = Join-Path $Root "release"
$ArchiveName = "PrismaFunctionMini-v$Version-windows-x64.zip"
$ArchivePath = Join-Path $ReleaseDirectory $ArchiveName
$ChecksumPath = "$ArchivePath.sha256"

if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
    throw "Missing build output: $Executable. Run build.bat first."
}

$ExcludedDirectoryNames = @("__pycache__", ".pytest_cache", ".venv", "logs", "output")
$ExcludedExtensions = @(".csv", ".log", ".pyc", ".pyo", ".tmp")
$Files = @(Get-ChildItem -LiteralPath $BuildDirectory -File -Recurse | Where-Object {
    $relative = $_.FullName.Substring($BuildDirectory.Length + 1)
    $parts = $relative -split '[\\/]'
    -not ($parts | Where-Object { $ExcludedDirectoryNames -contains $_ }) -and
    -not ($ExcludedExtensions -contains $_.Extension.ToLowerInvariant())
} | Sort-Object { $_.FullName.Substring($BuildDirectory.Length + 1) })

if ($Files.Count -eq 0) { throw "The build output contains no releasable files." }
New-Item -ItemType Directory -Force -Path $ReleaseDirectory | Out-Null
Remove-Item -LiteralPath $ArchivePath -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $ChecksumPath -Force -ErrorAction SilentlyContinue

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$Stream = [System.IO.File]::Open($ArchivePath, [System.IO.FileMode]::CreateNew)
try {
    $Zip = [System.IO.Compression.ZipArchive]::new($Stream, [System.IO.Compression.ZipArchiveMode]::Create, $false)
    try {
        foreach ($File in $Files) {
            $Relative = $File.FullName.Substring($BuildDirectory.Length + 1).Replace("\", "/")
            $Entry = $Zip.CreateEntry("PrismaFunctionMini/$Relative", [System.IO.Compression.CompressionLevel]::Optimal)
            $Entry.LastWriteTime = [DateTimeOffset]::new(2000, 1, 1, 0, 0, 0, [TimeSpan]::Zero)
            $Input = [System.IO.File]::OpenRead($File.FullName)
            try { $Output = $Entry.Open(); try { $Input.CopyTo($Output) } finally { $Output.Dispose() } }
            finally { $Input.Dispose() }
        }
    } finally { $Zip.Dispose() }
} catch {
    $Stream.Dispose()
    Remove-Item -LiteralPath $ArchivePath -Force -ErrorAction SilentlyContinue
    throw "Release archive generation failed: $($_.Exception.Message)"
} finally {
    $Stream.Dispose()
}

$Hash = (Get-FileHash -LiteralPath $ArchivePath -Algorithm SHA256).Hash.ToLowerInvariant()
[System.IO.File]::WriteAllText($ChecksumPath, "$Hash *$ArchiveName`n", [System.Text.UTF8Encoding]::new($false))
Write-Host "Release archive: $ArchivePath"
Write-Host "SHA-256 checksum: $ChecksumPath"
