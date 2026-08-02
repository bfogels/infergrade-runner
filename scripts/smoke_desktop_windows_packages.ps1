param(
    [Parameter(Mandatory = $true)][string]$MsiPath,
    [Parameter(Mandatory = $true)][string]$NsisPath,
    [Parameter(Mandatory = $true)][string]$ExpectedVersion
)

$ErrorActionPreference = "Stop"
$MsiPath = (Resolve-Path $MsiPath).Path
$NsisPath = (Resolve-Path $NsisPath).Path
$WorkDir = Join-Path $env:RUNNER_TEMP "infergrade-windows-package-smoke"
$MsiInstallDir = Join-Path $WorkDir "msi-install"
$NsisInstallDir = Join-Path $WorkDir "nsis-install"

function Get-MsiProperty([string]$Path, [string]$Property) {
    $installer = New-Object -ComObject WindowsInstaller.Installer
    $database = $installer.GetType().InvokeMember(
        "OpenDatabase", "InvokeMethod", $null, $installer, @($Path, 0)
    )
    $query = "SELECT ``Value`` FROM ``Property`` WHERE ``Property``='$Property'"
    $view = $database.GetType().InvokeMember("OpenView", "InvokeMethod", $null, $database, @($query))
    $view.GetType().InvokeMember("Execute", "InvokeMethod", $null, $view, $null) | Out-Null
    $record = $view.GetType().InvokeMember("Fetch", "InvokeMethod", $null, $view, $null)
    if ($null -eq $record) { throw "MSI property $Property is missing." }
    return $record.GetType().InvokeMember("StringData", "GetProperty", $null, $record, 1)
}

function Assert-DesktopLaunch([string]$Executable, [string]$Label) {
    $process = Start-Process -FilePath $Executable -PassThru
    Start-Sleep -Seconds 8
    if ($process.HasExited) {
        throw "$Label exited during launch smoke with code $($process.ExitCode)."
    }
    Stop-Process -Id $process.Id -Force
    $process.WaitForExit()
}

function Assert-PackagedSidecar([string]$Root, [string]$Label) {
    $sidecar = @(
        Get-ChildItem -Path $Root -File -Filter "infergrade-sidecar*.exe" -ErrorAction SilentlyContinue
        Get-ChildItem -Path (Join-Path $Root "binaries") -File -Filter "infergrade-sidecar*.exe" -ErrorAction SilentlyContinue
    ) | Select-Object -First 1
    if ($null -eq $sidecar) { throw "$Label is missing the packaged sidecar." }

    $diagnosticStem = $Label.ToLowerInvariant().Replace(" ", "-")
    $stdoutPath = Join-Path $WorkDir "$diagnosticStem-sidecar-self-test.stdout"
    $stderrPath = Join-Path $WorkDir "$diagnosticStem-sidecar-self-test.stderr"
    $process = Start-Process `
        -FilePath $sidecar.FullName `
        -ArgumentList "desktop-self-test" `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath `
        -Wait `
        -PassThru
    if ($process.ExitCode -ne 0) {
        $stderr = if (Test-Path $stderrPath) { (Get-Content $stderrPath -Raw).Trim() } else { "" }
        throw "$Label sidecar self-test failed with code $($process.ExitCode): $stderr"
    }
    $output = Get-Content $stdoutPath -Raw
    $payload = $output | ConvertFrom-Json
    if ($payload.invocation -ne "ok") { throw "$Label sidecar did not report invocation=ok." }
    if ($payload.python_runtime.source -ne "bundled" -or -not $payload.python_runtime.self_contained) {
        throw "$Label sidecar did not use the self-contained Python runtime."
    }
}

function Use-PythonFreePath([scriptblock]$Action) {
    $originalPath = $env:PATH
    $env:PATH = @(
        (Join-Path $env:SystemRoot "System32"),
        $env:SystemRoot,
        (Join-Path $env:SystemRoot "System32\Wbem"),
        (Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0")
    ) -join ";"
    try {
        if (Get-Command python -ErrorAction SilentlyContinue) { throw "Python unexpectedly remains on the clean-runtime PATH." }
        if (Get-Command python3 -ErrorAction SilentlyContinue) { throw "Python 3 unexpectedly remains on the clean-runtime PATH." }
        & $Action
    } finally {
        $env:PATH = $originalPath
    }
}

Remove-Item -Recurse -Force $WorkDir -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null

$productVersion = Get-MsiProperty $MsiPath "ProductVersion"
$productCode = Get-MsiProperty $MsiPath "ProductCode"
if ($productVersion -ne $ExpectedVersion) {
    throw "MSI version $productVersion does not match $ExpectedVersion."
}

$msiArgs = "/i `"$MsiPath`" INSTALLDIR=`"$MsiInstallDir`" /qn /norestart"
$msi = Start-Process msiexec.exe -ArgumentList $msiArgs -Wait -PassThru
if ($msi.ExitCode -notin @(0, 3010)) { throw "MSI install failed with code $($msi.ExitCode)." }
try {
    if (-not (Test-Path $MsiInstallDir)) { throw "MSI did not honor its requested install directory." }
    $msiExecutable = Get-ChildItem -Path $MsiInstallDir -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -in @("InferGrade Runner.exe", "infergrade_desktop_runner.exe") } |
        Select-Object -First 1
    if ($null -eq $msiExecutable) { throw "MSI install is missing the desktop executable." }
    Use-PythonFreePath {
        Assert-PackagedSidecar $msiExecutable.Directory.FullName "MSI"
        Assert-DesktopLaunch $msiExecutable.FullName "MSI desktop app"
    }
} finally {
    $uninstallArgs = "/x $productCode /qn /norestart"
    $msiUninstall = Start-Process msiexec.exe -ArgumentList $uninstallArgs -Wait -PassThru
    if ($msiUninstall.ExitCode -notin @(0, 1605, 3010)) {
        throw "MSI uninstall failed with code $($msiUninstall.ExitCode)."
    }
}

$nsis = Start-Process -FilePath $NsisPath -ArgumentList "/S", "/D=$NsisInstallDir" -Wait -PassThru
if ($nsis.ExitCode -ne 0) { throw "NSIS install failed with code $($nsis.ExitCode)." }
$nsisExecutable = Get-ChildItem -Path $NsisInstallDir -Recurse -File |
    Where-Object { $_.Name -in @("InferGrade Runner.exe", "infergrade_desktop_runner.exe") } |
    Select-Object -First 1
if ($null -eq $nsisExecutable) { throw "NSIS install is missing the desktop executable." }
Use-PythonFreePath {
    Assert-PackagedSidecar $NsisInstallDir "NSIS"
    Assert-DesktopLaunch $nsisExecutable.FullName "NSIS desktop app"
}

$uninstaller = Get-ChildItem -Path $NsisInstallDir -File -Filter "uninstall*.exe" | Select-Object -First 1
if ($null -ne $uninstaller) {
    $uninstall = Start-Process -FilePath $uninstaller.FullName -ArgumentList "/S" -Wait -PassThru
    if ($uninstall.ExitCode -ne 0) { throw "NSIS uninstall failed with code $($uninstall.ExitCode)." }
}

$msiSignature = (Get-AuthenticodeSignature $MsiPath).Status
$nsisSignature = (Get-AuthenticodeSignature $NsisPath).Status
Write-Output "desktop_windows_package_smoke=pass"
Write-Output "desktop_windows_package_version=$productVersion"
Write-Output "desktop_windows_product_code=$productCode"
Write-Output "desktop_windows_msi_signature=$msiSignature"
Write-Output "desktop_windows_nsis_signature=$nsisSignature"
Write-Output "desktop_windows_python_runtime=bundled_self_contained"
Write-Output "desktop_windows_gpu_execution=not_tested"
