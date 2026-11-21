<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.reservation-assist.watch</string>
  <key>ProgramArguments</key>
  <array>
    <string>__PYTHON__</string>
    <string>__COMPONENT__/skill/scripts/ra.py</string>
    <string>watch</string>
    <string>run</string>
  </array>
  <key>WorkingDirectory</key>
  <string>__HOME__/.reservation-assist</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>RA_ALLOW_SUBMIT</key>
    <string>0</string>
    <key>RA_STATE_DIR</key>
    <string>__HOME__/.reservation-assist</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>ThrottleInterval</key>
  <integer>15</integer>
  <key>StandardOutPath</key>
  <string>__HOME__/.reservation-assist/logs/watch.out.log</string>
  <key>StandardErrorPath</key>
  <string>__HOME__/.reservation-assist/logs/watch.err.log</string>
  <key>ProcessType</key>
  <string>Background</string>
</dict>
</plist>
