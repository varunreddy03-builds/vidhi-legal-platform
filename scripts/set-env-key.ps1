# Puts one key into backend/.env without it ever being shown or pasted in a chat.
#   powershell -ExecutionPolicy Bypass -File scripts\set-env-key.ps1 GEMINI_API_KEY
# Allowed names: GEMINI_API_KEY, ANTHROPIC_API_KEY (Claude), OPENROUTER_API_KEY, GROQ_API_KEY, NVIDIA_API_KEY, MISTRAL_API_KEY, ZAI_API_KEY, and for money and mail: RESEND_API_KEY, EMAIL_FROM,
# RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET, RAZORPAY_WEBHOOK_SECRET, STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET. Add -Restart to restart the dev backend afterwards. You type the key hidden; the file is git-ignored; the key is never printed.
param([Parameter(Mandatory = $true)][ValidateSet("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "GROQ_API_KEY", "NVIDIA_API_KEY", "MISTRAL_API_KEY", "ZAI_API_KEY", "RESEND_API_KEY", "EMAIL_FROM", "RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET", "RAZORPAY_WEBHOOK_SECRET", "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET")][string]$Name, [switch]$Restart)

$envFile = Join-Path (Split-Path -Parent $PSScriptRoot) "backend\.env"
if (-not (Test-Path $envFile)) { Write-Error "backend\.env not found"; exit 1 }

$secure = Read-Host -Prompt "Paste the new $Name (typing is hidden)" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try { $key = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
if ([string]::IsNullOrWhiteSpace($key)) { Write-Error "Nothing entered. The file was not changed."; exit 1 }

$lines = [System.Collections.Generic.List[string]](Get-Content -Path $envFile -Encoding UTF8)
$found = $false
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match "^\s*$Name\s*=") { $lines[$i] = "$Name=$($key.Trim())"; $found = $true; break }
}
if (-not $found) { $lines.Add("$Name=$($key.Trim())") }
Set-Content -Path $envFile -Value $lines -Encoding UTF8
$key = $null
Write-Host "$Name saved in backend\.env (value not shown)."
if ($Restart) {
    $repo = Split-Path -Parent $PSScriptRoot
    Get-NetTCPConnection -State Listen -LocalPort 8001 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
    Start-Sleep 3
    Start-Process powershell -ArgumentList '-ExecutionPolicy', 'Bypass', '-File', "`"$repo\scripts\dev-backend.ps1`"" -WindowStyle Hidden -RedirectStandardOutput "$env:TEMP\dev-be.out" -RedirectStandardError "$env:TEMP\dev-be.err"
    Write-Host "Restarting the backend: it can take a few minutes to answer; then open http://localhost:3000"
} else {
    Write-Host "Restart the backend to use it (add -Restart next time)."
}
