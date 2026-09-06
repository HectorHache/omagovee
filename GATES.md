# GATES — omagovee
- [x] G1: helper offline tests pass with no key configured
  CWD: repo-root
  CHECK: python3 scripts/test_govee.py        EXPECT: ALL HELPER TESTS PASSED
- [x] G2: manifest validates against Omarchy plugin schema
  CHECK: OMARCHY_PATH=/usr/share/omarchy omarchy-plugin-validate .   EXPECT: valid
- [x] G3: helper reaches real API and reads both configured lights
  CHECK: python3 scripts/govee.py doctor      EXPECT: DOCTOR OK
- [x] G3b: no-op control echo (end of P2; no physical effect, no supervision needed)
  CHECK: python3 scripts/govee.py set --device-index 0 --instance powerSwitch --echo-current
  EXPECT: CONTROL OK (value echoed; no visible change)
- [ ] G4: plugin installed and enabled on the shell
  CHECK: OMARCHY_PATH=/usr/share/omarchy omarchy-plugin-list | grep -i omagovee   EXPECT: enabled
- [ ] G5: shell loaded the plugin without QML errors
  CHECK: journalctl --user -t omarchy-shell --since -5min | grep -iE "omagovee.*(error|fail)"
  EXPECT: NO_OMAGOVEE_ERRORS
- [x] G6: no hardcoded colors in QML
  CHECK: ! grep -rnE '#[0-9a-fA-F]{3,8}\b' --include='*.qml' .   EXPECT: NO_HEX_COLORS
- [ ] G7a: live control round-trip, RIGHT lamp, user physically watching
  CHECK: python3 scripts/govee.py set --device-index 0 --instance powerSwitch --value 1 --confirm-physical
  EXPECT: CONTROL OK STATE powerSwitch=1
- [ ] G7b: master fan-out toggles both lamps (user watching)
  CHECK: python3 scripts/govee.py set --master --value 0 --confirm-physical
  EXPECT: CONTROL OK (both lamps off, then back on)
- [ ] G7c: OPTIONAL group-endpoint attempt (only if G7b green; not a v1 requirement)
  CHECK: python3 scripts/govee.py set --group --value 1 --confirm-physical   EXPECT: CONTROL OK or SKIPPED
- [ ] G8: personal-info audit clean (tree)
  CHECK: python3 scripts/audit_personal_info.py   EXPECT: AUDIT CLEAN
- [ ] G8b: git-history secret scan (before public flip only)
  CHECK: git log -p | grep -E '(^|[^0-9A-Za-z])[0-9A-Za-z]{36}([^0-9A-Za-z]|$)'; git log -p | grep -iE '[0-9a-f]{2}(:[0-9a-f]{2}){5}'
  EXPECT: NO_SECRETS_IN_HISTORY
