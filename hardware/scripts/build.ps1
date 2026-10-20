param([string]$VivadoBin = 'C:\Xilinx\Vivado\2022.2\bin', [string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$pythonExe = $Python
Push-Location $projectRoot
try {
    & (Join-Path $projectRoot 'validation\run_checks.ps1') -VivadoBin $VivadoBin -Python $Python
    & (Join-Path $PSScriptRoot 'run_axi_sim.ps1') -VivadoBin $VivadoBin
    & $pythonExe -B (Join-Path $projectRoot 'sim\test_pynq_driver.py')
    if ($LASTEXITCODE -ne 0) { throw 'Host driver tests failed' }
    New-Item -ItemType Directory -Path (Join-Path $projectRoot 'hardware\build') -Force | Out-Null
    Set-Location (Join-Path $projectRoot 'hardware\build')
    & (Join-Path $VivadoBin 'vivado.bat') -mode batch -source (Join-Path $PSScriptRoot 'build_overlay.tcl') `
        -log stage3_build.log -journal stage3_build.jou
    if ($LASTEXITCODE -ne 0) { throw 'Vivado build failed' }
    Set-Location $projectRoot
    & $pythonExe -B (Join-Path $PSScriptRoot 'finalize_bundle.py')
    if ($LASTEXITCODE -ne 0) { throw 'Artifact verification/bundling failed' }
} finally {
    Pop-Location
}
