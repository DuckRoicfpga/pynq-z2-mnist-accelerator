param(
    [ValidateSet('software','remote')][string]$Backend = 'software',
    [string]$BoardUrl = '',
    [string]$Python = 'python'
)
$ErrorActionPreference = 'Stop'
$arguments = @('-X','utf8','-B',(Join-Path $PSScriptRoot 'app.py'),'--backend',$Backend,'--self-test')
if ($Backend -eq 'remote') {
    if (-not $BoardUrl) { throw 'Remote mode needs -BoardUrl http://BOARD_IP:8766' }
    $arguments += @('--board-url',$BoardUrl)
}
& $Python @arguments
exit $LASTEXITCODE
