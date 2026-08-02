param(
    [Parameter(Mandatory = $true)][string]$MsiPath,
    [Parameter(Mandatory = $true)][string]$NsisPath,
    [Parameter(Mandatory = $true)][string]$ExpectedVersion
)

$ErrorActionPreference = "Stop"
$MsiPath = (Resolve-Path $MsiPath).Path
$NsisPath = (Resolve-Path $NsisPath).Path
$WorkDir = Join-Path $env:RUNNER_TEMP "infergrade-windows-package-smoke"
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
    $sidecar = Get-ChildItem -Path $Root -Recurse -File -Filter "infergrade-sidecar*.exe" |
        Select-Object -First 1
    if ($null -eq $sidecar) { throw "$Label is missing the packaged sidecar." }
    $output = & $sidecar.FullName desktop-self-test
    if ($LASTEXITCODE -ne 0) { throw "$Label sidecar self-test failed." }
    $payload = $output | ConvertFrom-Json
    if ($payload.invocation -ne "ok") { throw "$Label sidecar did not report invocation=ok." }
}

Remove-Item -Recurse -Force $WorkDir -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null

$productVersion = Get-MsiProperty $MsiPath "ProductVersion"
$productCode = Get-MsiProperty $MsiPath "ProductCode"
if ($productVersion -ne $ExpectedVersion) {
    throw "MSI version $productVersion does not match $ExpectedVersion."
}

$msiArgs = "/i `"$MsiPath`" /qn /norestart"
$msi = Start-Process msiexec.exe -ArgumentList $msiArgs -Wait -PassThru
if ($msi.ExitCode -notin @(0, 3010)) { throw "MSI install failed with code $($msi.ExitCode)." }
try {
    $msiRoots = @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:LOCALAPPDATA) |
        Where-Object { $_ -and (Test-Path $_) }
    $msiExecutable = Get-ChildItem -Path $msiRoots -Recurse -File -Filter "InferGrade Runner.exe" `
        -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $msiExecutable) { throw "MSI install is missing InferGrade Runner.exe." }
    Assert-PackagedSidecar $msiExecutable.Directory.FullName "MSI"
    Assert-DesktopLaunch $msiExecutable.FullName "MSI desktop app"
} finally {
    $uninstallArgs = "/x $productCode /qn /norestart"
    $msiUninstall = Start-Process msiexec.exe -ArgumentList $uninstallArgs -Wait -PassThru
    if ($msiUninstall.ExitCode -notin @(0, 1605, 3010)) {
        throw "MSI uninstall failed with code $($msiUninstall.ExitCode)."
    }
}

$nsis = Start-Process -FilePath $NsisPath -ArgumentList "/S", "/D=$NsisInstallDir" -Wait -PassThru
if ($nsis.ExitCode -ne 0) { throw "NSIS install failed with code $($nsis.ExitCode)." }
$nsisExecutable = Get-ChildItem -Path $NsisInstallDir -Recurse -File -Filter "InferGrade Runner.exe" |
    Select-Object -First 1
if ($null -eq $nsisExecutable) { throw "NSIS install is missing InferGrade Runner.exe." }
Assert-PackagedSidecar $NsisInstallDir "NSIS"
Assert-DesktopLaunch $nsisExecutable.FullName "NSIS desktop app"

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
Write-Output "desktop_windows_gpu_execution=not_tested"
