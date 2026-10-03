param([string]$GameDir = 'D:\steam\steamapps\common\Hollow Knight', [switch]$NoInstall)
$ErrorActionPreference = 'Stop'
$managed = Join-Path $GameDir 'hollow_knight_Data\Managed'
$core = Join-Path $GameDir 'BepInEx\core'
$output = Join-Path $PSScriptRoot '..\artifacts\build'
New-Item -ItemType Directory -Force $output | Out-Null
$references = @('Assembly-CSharp.dll','Assembly-CSharp-firstpass.dll','UnityEngine.dll','UnityEngine.CoreModule.dll','UnityEngine.Physics2DModule.dll','netstandard.dll') | ForEach-Object { '/reference:' + (Join-Path $managed $_) }
$references += @('BepInEx.dll','0Harmony.dll') | ForEach-Object { '/reference:' + (Join-Path $core $_) }
& 'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe' /nologo /target:library ('/out:' + (Join-Path $output 'PantheonTraining.dll')) $references (Join-Path $PSScriptRoot '..\mod\TrainingBridge.cs')
if ($LASTEXITCODE -ne 0) { throw 'Plugin compilation failed' }
if ($NoInstall) { return }
New-Item -ItemType Directory -Force (Join-Path $GameDir 'BepInEx\plugins') | Out-Null
Copy-Item (Join-Path $output 'PantheonTraining.dll') (Join-Path $GameDir 'BepInEx\plugins\PantheonTraining.dll') -Force
