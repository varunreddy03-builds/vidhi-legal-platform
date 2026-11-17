<#
 Builds the signed VIDHI release APK. The web screens are bundled INSIDE the app; it talks to a VIDHI server (the backend, for
 example through a Cloudflare tunnel) whose address is typed in the app on first start.
 Usage:  powershell -ExecutionPolicy Bypass -File scripts\build-apk.ps1 [-ServerUrl https://your-tunnel.trycloudflare.com]   (only pre-fills the address)
 Output: repo\VIDHI.apk (git-ignored). No keys or secrets are used or embedded.
#>
param(
  [string]$ServerUrl = ""
)
$ErrorActionPreference = 'Stop'

# Any failure ends here with plain words: what stopped, what to do, and the fact that no APK was produced.
function Fail([string]$what, [string]$todo) {
  Write-Host ''
  Write-Host 'The APK was NOT built.' -ForegroundColor Red
  Write-Host "What went wrong: $what" -ForegroundColor Red
  Write-Host "What to do: $todo"
  exit 1
}
trap {
  $msg = $_.Exception.Message
  $todo = 'Read the lines above this message for the first error, fix that, and run the same command again.'
  if ($msg -match 'frontend build') { $todo = 'The web app does not build. In the frontend folder run: yarn typecheck   and fix what it reports.' }
  elseif ($msg -match 'gradle') { $todo = 'Gradle (the Android builder) failed. On some Windows set-ups it cannot open a local network connection and fails every time: build on another computer, or ask for help. Read the Gradle lines above for the exact reason.' }
  elseif ($msg -match 'cap sync|npm install') { $todo = 'Check the internet connection (the build downloads packages), then run the command again. If the folder is inside OneDrive, wait until OneDrive has finished syncing.' }
  Fail $msg $todo
}

$repo   = Split-Path -Parent $PSScriptRoot
$mobile = Join-Path $repo 'mobile'

$nodeDir = 'C:\vidhi-tools\node\node-v22.11.0-win-x64'
$jdk     = 'C:\vidhi-tools\android\jdk21\jdk-21.0.12.1+1'   # Capacitor 8 needs JDK 21
$sdk     = 'C:\vidhi-tools\android\sdk'

# Preflight: the tools this script uses must be where it expects them.
if (-not (Test-Path (Join-Path $nodeDir 'node.exe'))) { Fail "Node.js was not found at $nodeDir." 'Install Node.js 22 there, or change $nodeDir at the top of this script.' }
if (-not (Test-Path (Join-Path $jdk 'bin\java.exe'))) { Fail "Java (JDK 21) was not found at $jdk." 'Install JDK 21 there, or change $jdk at the top of this script. Android builds with Capacitor 8 need JDK 21.' }
if (-not (Test-Path $sdk)) { Fail "The Android SDK was not found at $sdk." 'Install the Android SDK there (platform 35 and build-tools), or change $sdk at the top of this script.' }
if (-not (Test-Path (Join-Path $mobile 'package.json'))) { Fail "The mobile folder is missing or incomplete ($mobile)." 'Run this script from a full copy of the project, not a partial one.' }

if (-not $ServerUrl) {
  # The app asks for the server address on first start, so this is only a pre-filled suggestion. Default: this PC's Wi-Fi address, API port.
  $ip = $null
  try {
    $ip = (Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias 'Wi-Fi*' -ErrorAction Stop |
           Where-Object { $_.IPAddress -notlike '169.254.*' } | Select-Object -First 1).IPAddress
  } catch {}
  if ($ip) { $ServerUrl = "http://${ip}:8001" }
}
Write-Host "Server address pre-filled in the APK: $ServerUrl (can be changed inside the app)"

$env:JAVA_HOME    = $jdk
$env:ANDROID_HOME = $sdk
$env:ANDROID_SDK_ROOT = $sdk
$env:PATH = "$nodeDir;$jdk\bin;$sdk\platform-tools;$env:PATH"

# 1. Build the web app that goes INSIDE the APK (the screens live in the app; only the data comes from the server)
$frontend = Join-Path $repo 'frontend'
$env:VITE_DEFAULT_SERVER_URL = $ServerUrl
Push-Location $frontend
try {
  yarn build
  if ($LASTEXITCODE) { throw 'frontend build failed' }
} finally { Pop-Location }
if (-not (Test-Path (Join-Path $frontend 'dist\index.html'))) { throw 'frontend\dist\index.html is missing' }

# 2. Build in a copy outside OneDrive (OneDrive locks folders and breaks cap sync / gradle)
$work = 'C:\vidhi-tools\apk-build\mobile'
New-Item -ItemType Directory -Force $work | Out-Null
$null = robocopy $mobile $work /MIR /XD node_modules build .gradle .idea /XF local.properties /NFL /NDL /NJH /NJS /NP
if ($LASTEXITCODE -ge 8) { throw "Copy to $work failed (robocopy code $LASTEXITCODE)" }
$global:LASTEXITCODE = 0
# OneDrive marks copied folders read-only, which makes `cap sync` fail with EPERM when it clears its asset folders: clear the flag in the work copy
& attrib -R "$work\*" /S /D | Out-Null
# The built web app becomes the app's own screens
$null = robocopy (Join-Path $frontend 'dist') (Join-Path $work 'www') /MIR /NFL /NDL /NJH /NJS /NP
if ($LASTEXITCODE -ge 8) { throw "Copy of the web build failed (robocopy code $LASTEXITCODE)" }
$global:LASTEXITCODE = 0
& attrib -R "$work\www\*" /S /D | Out-Null

Push-Location $work
try {
  npm install --no-audit --no-fund
  if ($LASTEXITCODE) { throw 'npm install failed' }
  $sdkEsc = $sdk.Replace([string][char]92, '/')
  Set-Content -Path 'android\local.properties' -Value "sdk.dir=$sdkEsc" -Encoding ascii

  npx cap sync android
  $assets = 'android\app\src\main\assets\public\index.html'
  if ($LASTEXITCODE -or -not (Test-Path $assets)) {
    throw "cap sync failed (exit $LASTEXITCODE, or $assets missing). Nothing was built."
  }

  Push-Location 'android'
  try {
    $env:JAVA_TOOL_OPTIONS = '-Djava.net.preferIPv4Stack=true'   # Gradle talks to its worker over loopback; some Windows setups only allow IPv4 there
    # Signed release build. The key is created once, outside the repo and OneDrive; never commit it.
    $ksDir = 'C:\vidhi-tools\keys'; $ks = Join-Path $ksDir 'vidhi-release.jks'; $pw = Join-Path $ksDir 'vidhi-release.pass'
    if (-not (Test-Path $ks)) {
      New-Item -ItemType Directory -Force $ksDir | Out-Null
      $newPass = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 24 | ForEach-Object { [char]$_ })
      Set-Content -Path $pw -Value $newPass -Encoding ascii -NoNewline
      & "$jdk\bin\keytool.exe" -genkeypair -keystore $ks -alias vidhi -keyalg RSA -keysize 2048 -validity 10000 -storepass $newPass -keypass $newPass -dname 'CN=VIDHI, O=VIDHI, C=IN'
      if ($LASTEXITCODE) { throw 'keytool failed' }
    }
    $env:VIDHI_KS_FILE = $ks; $env:VIDHI_KS_PASS = (Get-Content $pw -Raw).Trim()
    .\gradlew.bat assembleRelease --no-daemon
    if ($LASTEXITCODE) { throw 'gradle assembleRelease failed' }
  } finally { Pop-Location }
} finally { Pop-Location }

$apk = Join-Path $work 'android\app\build\outputs\apk\release\app-release.apk'
if (-not (Test-Path $apk)) { throw "APK not found at $apk" }
Copy-Item $apk (Join-Path $repo 'VIDHI.apk') -Force
$size = [math]::Round((Get-Item (Join-Path $repo 'VIDHI.apk')).Length / 1MB, 2)
Write-Host "Done: $repo\VIDHI.apk ($size MB), server URL $ServerUrl"
