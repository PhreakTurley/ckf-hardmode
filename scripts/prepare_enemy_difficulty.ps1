param(
    [string]$SourceContent = (Join-Path $PSScriptRoot '..\ckf-enemy-difficulty\source_content'),
    [string]$OutputDirectory = (Join-Path $PSScriptRoot '..\ckf-enemy-difficulty\parser_prepared\_data'),
    [string]$ModkitDirectory = 'C:\Program Files (x86)\Steam\steamapps\common\Cyber Knights Mod Uploader'
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# Calls the same installed managed parser as Prepare Mod Data, without opening
# the uploader or submitting anything. Its output is staged under a fresh name.
$SourceContent = [IO.Path]::GetFullPath($SourceContent)
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
$taskManifest = Join-Path $SourceContent 'stories.manifest'
$taskSchema = Join-Path $ModkitDirectory 'CyberKnightsModkit_Data\StreamingAssets\config.json'
$taskDll = Join-Path $ModkitDirectory 'CyberKnightsModkit_Data\Managed\DataParserNETStandard.dll'
$taskSources = @($taskManifest, $taskSchema, $taskDll)
foreach ($taskLine in [IO.File]::ReadAllLines($taskManifest)) {
    if ($taskLine.Trim() -and -not $taskLine.Trim().StartsWith('#')) {
        $taskSources += Join-Path $SourceContent $taskLine.Trim()
    }
}
$taskInputs = @{}
foreach ($taskPath in $taskSources) {
    $taskInputs[$taskPath] = (Get-FileHash -LiteralPath $taskPath -Algorithm SHA256).Hash.ToLowerInvariant()
}
$taskExpected = @{}
foreach ($taskName in @('data.sql', 'en-US.json')) {
    $taskDest = Join-Path $OutputDirectory $taskName
    $taskExpected[$taskName] = if (Test-Path -LiteralPath $taskDest) {
        @((Get-Item -LiteralPath $taskDest).LastWriteTimeUtc.Ticks,
          (Get-FileHash -LiteralPath $taskDest -Algorithm SHA256).Hash)
    } else { @() }
}
$taskStage = $OutputDirectory + '.stage-' + [guid]::NewGuid().ToString('N')
[IO.Directory]::CreateDirectory($taskStage) | Out-Null
$taskAsm = [Reflection.Assembly]::LoadFrom($taskDll)
$taskType = $taskAsm.GetType('DataParser.Core.Parser', $true)
$taskParser = [Activator]::CreateInstance($taskType)
$taskParserArgs = [string[]]@($taskManifest, $taskSchema,
    (Join-Path $taskStage 'data.sql'), (Join-Path $taskStage 'en-US.json'))
$taskExit = $taskType.GetMethod('Process').Invoke($taskParser, [object[]]@($false, $taskParserArgs))
$taskLog = $taskType.GetMethod('GetLog').Invoke($taskParser, @())
if ($taskExit -ne 0) { throw "Installed parser exited ${taskExit}: $taskLog" }
foreach ($taskPath in $taskSources) {
    if ((Get-FileHash -LiteralPath $taskPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskInputs[$taskPath]) {
        throw "Parser input changed: $taskPath"
    }
}
[IO.Directory]::CreateDirectory($OutputDirectory) | Out-Null
$taskOutputs = @{}
foreach ($taskName in @('data.sql', 'en-US.json')) {
    $taskStaged = Join-Path $taskStage $taskName
    $taskDest = Join-Path $OutputDirectory $taskName
    $taskHash = (Get-FileHash -LiteralPath $taskStaged -Algorithm SHA256).Hash
    $taskCurrent = if (Test-Path -LiteralPath $taskDest) {
        @((Get-Item -LiteralPath $taskDest).LastWriteTimeUtc.Ticks,
          (Get-FileHash -LiteralPath $taskDest -Algorithm SHA256).Hash)
    } else { @() }
    if (($taskCurrent -join '|') -ne ($taskExpected[$taskName] -join '|')) {
        throw "Parser output changed before commit: $taskDest"
    }
    [IO.File]::Move($taskStaged, $taskDest, $true)
    if ((Get-FileHash -LiteralPath $taskDest -Algorithm SHA256).Hash -ne $taskHash) {
        throw "Parser output readback differs: $taskDest"
    }
    $taskOutputs[$taskDest] = $taskHash.ToLowerInvariant()
}
[IO.Directory]::Delete($taskStage) # Empty directory; never recursively delete.
@{status='PASS'; parserLog=$taskLog.Trim(); inputHashes=$taskInputs; outputHashes=$taskOutputs} | ConvertTo-Json -Depth 4
