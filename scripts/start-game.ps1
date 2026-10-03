param([string]$GameDir = 'D:\steam\steamapps\common\Hollow Knight')
$ErrorActionPreference = 'Stop'
if (-not (Get-Process hollow_knight -ErrorAction SilentlyContinue)) {
    Start-Process 'steam://rungameid/367520' -WindowStyle Hidden
}
