import type { CapacitorConfig } from '@capacitor/cli';

// The app opens a small local launcher page (www/index.html) that asks for the VIDHI server address, remembers it
// and opens it in the app, so the server can be anywhere (a public https address, or a PC on Wi-Fi) and can change
// without rebuilding. scripts/build-apk.ps1 -ServerUrl <url> only pre-fills that address.
const config: CapacitorConfig = {
  appId: 'com.vidhi.app',
  appName: 'VIDHI',
  webDir: 'www',
  backgroundColor: '#0B0C0D',
  server: {
    cleartext: true, // lets a PC on the same Wi-Fi (http) work as well as https servers
    allowNavigation: ['*'], // the launcher opens the server address inside the app instead of the browser
  },
  plugins: {
    SystemBars: { style: 'DARK', hidePermanently: false },
  },
};

export default config;
