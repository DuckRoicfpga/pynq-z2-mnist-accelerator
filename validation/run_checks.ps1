param(
    [string]$VivadoBin = 'C:\Xilinx\Vivado\2022.2\bin',
    [switch]$Synthesis,
    [string]$Python = 'python'
)
$ErrorActionPreference = 'Stop'
$sourceDir = $PSScriptRoot
$projectRoot = Split-Path $sourceDir -Parent
$validationDir = Join-Path $projectRoot 'output\validation'
New-Item -ItemType Directory -Path $validationDir -Force | Out-Null

$originalDir = Join-Path $validationDir 'original'
$regressionDir = Join-Path $validationDir 'regression'
$rtlDir = Join-Path $projectRoot 'rtl'
$pythonExe = $Python

function Invoke-Checked {
    param([string]$Tool, [string[]]$ToolArguments)
    & (Join-Path $VivadoBin $Tool) @ToolArguments
    if ($LASTEXITCODE -ne 0) { throw "$Tool failed with exit code $LASTEXITCODE" }
}

Push-Location $projectRoot
try {
    & $pythonExe -B -u (Join-Path $sourceDir 'verify_stage1.py') 2>&1 |
        Tee-Object -FilePath (Join-Path $validationDir 'stage1.log')
    if ($LASTEXITCODE -ne 0) { throw 'Python model/export verification failed' }
    New-Item -ItemType Directory -Path $originalDir -Force | Out-Null
    Copy-Item -LiteralPath (Get-ChildItem -LiteralPath (Join-Path $projectRoot 'sim') -Filter '*.mem' -File).FullName -Destination $originalDir
    Set-Location $originalDir
    Invoke-Checked -Tool 'xvlog.bat' -ToolArguments @('-sv', '-i', $rtlDir,
        (Join-Path $rtlDir 'mlp_accelerator.v'), (Join-Path $projectRoot 'sim\tb_mlp_accelerator.v'),
        '-log', 'xvlog_original.log')
    Invoke-Checked -Tool 'xelab.bat' -ToolArguments @('-debug', 'typical', 'work.tb_mlp_accelerator',
        '-s', 'original_snapshot', '-log', 'xelab_original.log')
    Invoke-Checked -Tool 'xsim.bat' -ToolArguments @('original_snapshot', '-runall', '-log', 'xsim_original.log')
    $originalLog = Get-Content -LiteralPath 'xsim_original.log' -Raw
    if ($originalLog -notmatch 'PASS:\s*10 / 10' -or $originalLog -notmatch 'FAIL:\s*0 / 10' -or $originalLog -match '\[ERROR\]') {
        throw 'Original testbench did not pass all 10 tests'
    }
    Set-Location $regressionDir
    Invoke-Checked -Tool 'xvlog.bat' -ToolArguments @('-sv', '-i', $rtlDir, '-i', $regressionDir,
        (Join-Path $rtlDir 'mlp_accelerator.v'), (Join-Path $projectRoot 'sim\tb_mlp_regression.sv'),
        '-log', 'xvlog_regression.log')
    Invoke-Checked -Tool 'xelab.bat' -ToolArguments @('-debug', 'typical', 'work.tb_mlp_regression',
        '-s', 'regression_snapshot', '-log', 'xelab_regression.log')
    Invoke-Checked -Tool 'xsim.bat' -ToolArguments @('regression_snapshot', '-runall', '-log', 'xsim_regression.log')
    $regressionLog = Get-Content -LiteralPath 'xsim_regression.log' -Raw
    if ($regressionLog -notmatch 'REGRESSION PASS: 120/120 cases') { throw 'RTL regression failed' }
    if ($Synthesis) {
        $synthesisDir = Join-Path $validationDir 'synthesis'
        New-Item -ItemType Directory -Path $synthesisDir -Force | Out-Null
        Set-Location $synthesisDir
        Invoke-Checked -Tool 'vivado.bat' -ToolArguments @('-mode', 'batch', '-source',
            (Join-Path $sourceDir 'synth_check.tcl'), '-log', 'vivado_synthesis.log', '-journal', 'vivado_synthesis.jou')
        $synthesisLog = Get-Content -LiteralPath 'vivado_synthesis.log' -Raw
        if ($synthesisLog -notmatch 'SYNTHESIS_CHECK_COMPLETE') { throw 'Synthesis did not complete' }
        Write-Host 'Synthesis completed. Read synthesis\timing_summary.rpt and drc.rpt; completion does not mean timing or board DRC passed.'
    }
    Write-Host 'PASS: stage 1 and stage 2 validation complete.'
} finally {
    Pop-Location
}
