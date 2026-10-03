param([string]$GameDir = 'D:\steam\steamapps\common\Hollow Knight')
$ErrorActionPreference = 'Stop'
if (Get-Process hollow_knight -ErrorAction SilentlyContinue) { throw 'Close the game first.' }
$plugin = Join-Path $GameDir 'BepInEx\plugins\PantheonTraining.dll'
if (Test-Path -LiteralPath $plugin) {
    Move-Item -LiteralPath $plugin -Destination ($plugin + '.disabled') -Force
}
Write-Output 'Training plugin disabled; normal save behavior will resume on next launch.'
