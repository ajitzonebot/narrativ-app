#!/bin/bash
# Installs the latest APK on the CI emulator, opens each screen via the `route` extra, takes screenshots
# (top plus SCROLLS more screens per route). Used for UI checks; changes nothing in the app.
set -x
mkdir -p shots
adb install -r app.apk
adb shell settings put global window_animation_scale 0
adb shell pm disable-user --user 0 com.google.android.apps.nexuslauncher >/dev/null 2>&1 || true  # its ANR dialogs covered shots
SCROLLS=${SCROLLS:-3}
ROUTES=(home screener market quadrant portfolio settings track advanced data release calendar queue search feedback
  "stock:TALBROAUTO.NS" "stock:SAHYADRI.NS" "stock:BLS.NS")
for i in 0 1 2 3 4 5 6 7 8; do ROUTES+=("tab:TALBROAUTO.NS@$i"); done
ROUTES+=("tab:SAHYADRI.NS@7" "tab:SAHYADRI.NS@8")
for route in "${ROUTES[@]}"; do
  name=$(echo "$route" | tr ':.@' '___')
  adb shell am force-stop com.narrativ.app
  adb shell am broadcast -a android.intent.action.CLOSE_SYSTEM_DIALOGS >/dev/null 2>&1  # launcher "isn't responding" dialog
  adb shell am start -n com.narrativ.app/.MainActivity --es route "$route" --ez ci true
  sleep 12
  if adb shell dumpsys window | grep -q "Application Not Responding\|isn't responding"; then
    adb shell am broadcast -a android.intent.action.CLOSE_SYSTEM_DIALOGS; adb shell input keyevent KEYCODE_BACK; sleep 1
    adb shell am start -n com.narrativ.app/.MainActivity --es route "$route" --ez ci true; sleep 10
  fi
  adb exec-out screencap -p > "shots/${name}_1.png"
  for k in $(seq 2 $((SCROLLS + 1))); do
    adb shell input swipe 540 1900 540 500 400; sleep 2
    adb exec-out screencap -p > "shots/${name}_$k.png"
  done
done
adb logcat -d -b crash > shots/crash.txt || true
adb logcat -d | grep -E "AndroidRuntime|FATAL" > shots/fatal.txt || true
echo done
