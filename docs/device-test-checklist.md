# Device test checklist

Tick each line on a real device. Write the device, browser/OS version and date at the top. If a line fails, note what you saw. Use a throwaway account; one account should work on all three devices (that checks "same account, same data").

Device: ____________   OS/browser: ____________   Date: ________

## 0. How to get VIDHI on each device
- **Laptop:** open the VIDHI address in Chrome, Edge, Safari or Firefox.
- **iPhone (PWA):** open the address in **Safari**, tap Share, then **Add to Home Screen**, then open it from the Home Screen icon.
- **Android (APK):** build with `powershell -ExecutionPolicy Bypass -File scripts\build-apk.ps1`, copy `VIDHI.apk` to the phone, install it, type the server address on first start. If the build fails, the script prints what went wrong and what to do.

## 1. Every device
1. Sign in with the same account on all three devices. [ ] A matter created on one appears on the others after a refresh.
2. **Matter description:** create a matter with a description in Telugu (for example `ఇది ఒక వివరణ`) plus symbols (`& "quotes" Rs 5,00,000`).
   - [ ] The full description shows on the matter's Overview.
   - [ ] It shows (two lines) in the Matters list.
   - [ ] Tap **Edit details**, change the description, save: the change shows after a reload.
   - [ ] Clear it: it shows "No description recorded."
3. **Telugu and other scripts:** [ ] Telugu, Hindi and Tamil text show as letters (no empty boxes) in the title, description and a draft.
4. **"Ask questions" is gone:** [ ] there is no Ask entry in the menus; opening `/ask` lands on the Start screen.
5. **Toolkit:**
   - [ ] Toolkit is in the main navigation.
   - [ ] Authority Check is a card (live, or "Not switched on yet" if the switch is off).
   - [ ] The other three cards say "Coming next" and have no working buttons.
6. **Recovery:** [ ] Legal Recovery is under **More** (phone) / **Settings, then More** (laptop) and opens; the bottom bar stays the same afterwards.
7. **Upload:**
   - [ ] In a matter's Documents tab, the upload box opens the file picker.
   - [ ] A small .txt file uploads, shows progress, then appears in the list.
   - [ ] A wrong file type shows a plain message.
8. **Weak network:** start an upload of a larger PDF, switch to airplane mode for a few seconds, then back. [ ] It says the connection is weak and tries again, or shows **Try again**; tapping it finishes the upload.
9. **Authority Check** (needs the switch on): paste or upload a draft.
   - [ ] The report lists every case and section.
   - [ ] A case shows "Could not check" if the source is unreachable, never "not found".
   - [ ] Fix / Accept as is / Mark reviewed save and survive a reload.
   - [ ] Word and PDF download or open.

## 2. Laptop only
1. [ ] The Authority Check report shows the draft's references on the left and what the source shows on the right at the same time.
2. [ ] Press Tab on any screen: the first stop is **Skip to content**; Enter jumps to the main area.
3. [ ] Every button can be reached and used with the keyboard (Tab, Shift+Tab, Enter, Space); focus is always visible.
4. [ ] Drag a file from your computer onto the upload box: it uploads.
5. [ ] Resize the window from wide to narrow: nothing scrolls sideways.
6. [ ] With a screen reader (NVDA, VoiceOver): the upload box announces as a button; progress is announced; the report's two panes are labelled "Your draft" and "What the source shows".

## 3. iPhone (PWA) only
1. [ ] Add to Home Screen works; it opens full-screen with the VIDHI icon.
2. [ ] The Dates screen shows the "To install VIDHI on an iPhone" hint **before** it is installed, and not after.
3. [ ] The top of the app is clear of the camera cut-out; the bottom bar is clear of the home indicator.
4. [ ] The upload box opens **Files / Photo Library / Take Photo**.
5. [ ] Authority Check on a phone shows one pane at a time: the list, then a reference with an **All references** back button.
6. [ ] Turn on airplane mode and open the app: the screens open, but no matters, reports or documents are shown (they are never kept offline). Turn it off: everything returns.
7. [ ] (iOS 16.4 or later) Notifications can be turned on from the Dates screen after installing.

## 4. Android (APK) only
1. [ ] First start asks for the server address; after typing it, sign-in works.
2. [ ] The upload box opens the Android document picker; a file from Downloads uploads.
3. [ ] Word and PDF downloads open in the Android share sheet.
4. [ ] Authority Check shows one pane at a time with the Back button.
5. [ ] Changing the server address from the sign-in page works.

## 5. Result
Passed: ____   Failed: ____   Notes: ______________________________________________
