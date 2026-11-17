# VIDHI Android APK (debug, for testing on your own phone)

The APK is a Capacitor shell (`mobile/`) that opens the VIDHI web app from your PC's dev server. It is not standalone.

## Build
```
powershell -ExecutionPolicy Bypass -File scripts\build-apk.ps1
```
Optional: `-ServerUrl http://192.168.1.5:3000` (default: this PC's Wi-Fi IPv4 + port 3000). The URL is baked into the APK, so rebuild if the PC's IP changes.
The script copies `mobile/` to `C:\vidhi-tools\apk-build\mobile` (avoids OneDrive file locks), runs `npx cap sync android` and gradle `assembleDebug` there, and writes `VIDHI.apk` at the repo root (git-ignored). Tools used: Node and JDK 21 under `C:\vidhi-tools`, Android SDK platform 36.
Check it: `aapt dump badging VIDHI.apk` (package `com.vidhi.app`, label VIDHI) and `apksigner verify VIDHI.apk` (debug-signed).

## Install
Copy `VIDHI.apk` to the phone (USB, Drive, etc.), open it, allow "install unknown apps" for that file manager, install.

## What must be running on the PC
1. Backend: `scripts\dev-backend.ps1` (port 8001).
2. Frontend: in `frontend`, `yarn dev --host` (port 3000; its Vite proxy forwards `/api` to 8001).
3. Windows Firewall must allow inbound TCP 3000 on the private network (allow Node.js when prompted).
4. Phone and PC on the same Wi-Fi, and the PC on. Away from that Wi-Fi the app shows the fallback page.

## Standalone app (not done yet)
Needs: a hosted HTTPS backend and frontend (then build with `-ServerUrl https://your-domain`), and a release keystore for signing and Play Store upload. The owner creates the keystore and must never commit it or its passwords (`*.keystore` and `*.jks` are git-ignored in `mobile/`). No keys or secrets are in the APK.
