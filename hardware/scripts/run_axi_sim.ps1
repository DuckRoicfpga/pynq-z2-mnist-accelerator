param([string]$VivadoBin = 'C:\Xilinx\Vivado\2022.2\bin')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$testDir = Join-Path $projectRoot 'output\stage3\axi_sim'
$referenceDir = Join-Path $projectRoot 'output\validation\regression'
New-Item -ItemType Directory -Path $testDir -Force | Out-Null
Copy-Item -LiteralPath (Get-ChildItem -LiteralPath $referenceDir -Filter '*.mem' -File).FullName -Destination $testDir
Copy-Item -LiteralPath (Join-Path $referenceDir 'case_count.vh') -Destination $testDir
Push-Location $testDir
try {
    & (Join-Path $VivadoBin 'xvlog.bat') -sv -i (Join-Path $projectRoot 'rtl') -i $testDir `
        (Join-Path $projectRoot 'rtl\mlp_accelerator.v') (Join-Path $projectRoot 'rtl\mlp_axi_lite.v') `
        (Join-Path $projectRoot 'sim\tb_mlp_axi.sv') -log xvlog_axi.log
    if ($LASTEXITCODE -ne 0) { throw 'AXI test compile failed' }
    & (Join-Path $VivadoBin 'xelab.bat') -debug typical work.tb_mlp_axi -s axi_snapshot -log xelab_axi.log
    if ($LASTEXITCODE -ne 0) { throw 'AXI test elaboration failed' }
    & (Join-Path $VivadoBin 'xsim.bat') axi_snapshot -runall -log xsim_axi.log
    if ($LASTEXITCODE -ne 0) { throw 'AXI simulation failed' }
    $simLog = Get-Content -LiteralPath 'xsim_axi.log' -Raw
    if ($simLog -notmatch 'AXI REGRESSION PASS: 120/120 cases') { throw 'AXI regression did not pass all cases' }
} finally {
    Pop-Location
}
