param(
    [Parameter(Mandatory = $true)][string]$Path,
    [string]$ExpectedPublisher = $env:AZURE_SIGNING_PUBLISHER
)
$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($ExpectedPublisher)) { throw "Expected signing publisher is required." }
$resolved = (Resolve-Path -LiteralPath $Path).Path
$signature = Get-AuthenticodeSignature -LiteralPath $resolved
if ($signature.Status -ne 'Valid') { throw "Authenticode verification failed: $resolved ($($signature.Status))" }
$publisher = $signature.SignerCertificate.GetNameInfo([System.Security.Cryptography.X509Certificates.X509NameType]::SimpleName, $false)
if ($publisher -cne $ExpectedPublisher) { throw "Authenticode publisher mismatch: $resolved ($publisher)" }
if ($null -eq $signature.TimeStamperCertificate) { throw "Authenticode timestamp missing: $resolved" }
Write-Output "authenticode_verified=$resolved publisher=$publisher timestamp=present"
