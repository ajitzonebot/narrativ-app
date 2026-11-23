#!/bin/bash
# Installs the latest APK on the CI emulator, opens each screen via the `route` extra, takes screenshots.
set -x
mkdir -p shots
adb install -r app.apk
adb shell settings put global window_animation_scale 0
for route in home "stock:TALBROAUTO.NS" "stock:BLS.NS" "tab:TALBROAUTO.NS@2" "tab:TALBROAUTO.NS@7" "tab:TALBROAUTO.NS@8" settings; do
  name=$(echo "$route" | tr ':.' '__')
  adb shell am force-stop com.narrativ.app
  adb shell am start -n com.narrativ.app/.MainActivity --es route "$route" --ez ci true
  sleep 15
  adb exec-out screencap -p > "shots/$name.png"
  if [ "$route" = "home" ] || [ "$route" = "stock:TALBROAUTO.NS" ] || [ "$route" = "stock:BLS.NS" ] || [ "$route" = "tab:TALBROAUTO.NS@2" ]; then
    adb shell input swipe 540 1900 540 500 400; sleep 3
    adb exec-out screencap -p > "shots/${name}_2.png"
    adb shell input swipe 540 1900 540 500 400; sleep 3
    adb exec-out screencap -p > "shots/${name}_3.png"
    adb shell input swipe 540 1900 540 500 400; sleep 3
    adb exec-out screencap -p > "shots/${name}_4.png"
  fi
done
adb logcat -d -b crash > shots/crash.txt || true
adb logcat -d | grep -E "AndroidRuntime|FATAL" > shots/fatal.txt || true
echo done
