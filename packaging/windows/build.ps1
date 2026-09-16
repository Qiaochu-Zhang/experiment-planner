$ErrorActionPreference = 'Stop'
if (-not $IsWindows -and $env:OS -ne 'Windows_NT') { throw '必须在 Windows 上构建 Windows 运行包。' }
python -m pip check
if ($LASTEXITCODE -ne 0) { throw '依赖检查失败' }
python -m pytest -q --junitxml=windows-tests.xml
if ($LASTEXITCODE -ne 0) { throw 'Windows 源码测试失败' }
python -m pip freeze | Out-File -Encoding utf8 requirements/windows-resolved.txt
python -m PyInstaller --noconfirm --clean packaging/windows/ExperimentPlanner.spec
if ($LASTEXITCODE -ne 0) { throw '打包失败' }
$plannerExe = Join-Path $PWD 'dist/ExperimentPlanner/ExperimentPlanner.exe'
$testDirectory = Join-Path $env:TEMP ('Planner 合成验证 ' + [guid]::NewGuid().ToString('N'))
$result = Start-Process -FilePath $plannerExe -ArgumentList @('--self-test', ('"' + $testDirectory + '"')) -PassThru -Wait
if ($result.ExitCode -ne 0 -or -not (Test-Path (Join-Path $testDirectory 'evidence.json'))) { throw '冻结程序模型/spawn/恢复验证失败' }
Copy-Item (Join-Path $testDirectory 'evidence.json') dist/frozen-evidence.json
$smoke = Start-Process -FilePath $plannerExe -ArgumentList '--smoke' -PassThru -Wait
if ($smoke.ExitCode -ne 0) { throw '冻结程序 Qt 启动失败' }
Compress-Archive -Path dist/ExperimentPlanner -DestinationPath dist/ExperimentPlanner-win-x64-prototype.zip
Get-FileHash dist/ExperimentPlanner-win-x64-prototype.zip -Algorithm SHA256 | Format-List | Out-File -Encoding utf8 dist/SHA256.txt
