import sys
p = "Panel.qml"
s = open(p).read()

def rep(old, new):
    global s
    assert old in s, "MISSING: " + old[:90]
    s = s.replace(old, new, 1)

# ---------------------------------------------------------------- 1. _colorDesired + confirm-schedule props
rep("""  property var _tmpDesired: ({})       // "index" -> desired colorTemperatureK""",
"""  property var _tmpDesired: ({})       // "index" -> desired colorTemperatureK
  property var _colorDesired: ({})     // "index" -> desired colorRgb int (held until API agrees)
  property bool _confirmScheduled: false""")

# ---------------------------------------------------------------- 2. heal: 18 s, clears colors, then re-refresh
rep("""  Timer {
    id: desiredHeal
    interval: 9000
    onTriggered: {
      root._masterHasDesired = false
      root._cardDesired = {}
      root._briDesired = {}
      root._tmpDesired = {}
    }
  }""",
"""  Timer {
    id: desiredHeal
    interval: 18000
    onTriggered: {
      root._masterHasDesired = false
      root._cardDesired = {}
      root._briDesired = {}
      root._tmpDesired = {}
      root._colorDesired = {}
      if (!root.noKey) root.refresh(true)
    }
  }
  function anyPendingDesired() {
    if (root._masterHasDesired) return true
    for (var k1 in root._cardDesired) return true
    for (var k2 in root._briDesired) return true
    for (var k3 in root._tmpDesired) return true
    for (var k4 in root._colorDesired) return true
    return false
  }""")

# ---------------------------------------------------------------- 3. master = any-on (mixed counts as on)
rep("""      root.masterOn = counted > 0 && on === counted
      if (root._masterHasDesired && root.masterOn === root._masterDesired)
        root._masterHasDesired = false""",
"""      root.masterOn = counted > 0 && on > 0
      if (root._masterHasDesired && root.masterOn === root._masterDesired)
        root._masterHasDesired = false""")

# ---------------------------------------------------------------- 4. reconcile _colorDesired + convergence follow-up
rep("""      root._tmpDesired = td
      root.statusText = ""          // any successful refresh clears errors
      root.statusBad = false
    }""",
"""      root._tmpDesired = td
      var kd = {}
      for (var kk in root._colorDesired) {
        var kr = root.rowForIndex(Number(kk))
        if (!(kr && kr.props) || kr.props.colorRgb === undefined
            || kr.props.colorRgb !== root._colorDesired[kk]) kd[kk] = root._colorDesired[kk]
      }
      root._colorDesired = kd
      root.statusText = ""          // any successful refresh clears errors
      root.statusBad = false
      // convergence follow-up: keep polling until every requested value lands
      if (root.anyPendingDesired() && !root._confirmScheduled) {
        root._confirmScheduled = true
        Qt.callLater(function () {
          root._confirmScheduled = false
          if (root.anyPendingDesired() && !root.noKey) root.refresh(true)
        }, 6500)
      }
    }""")

# ---------------------------------------------------------------- 5. state-fail clears colors too
rep("""      root._briDesired = {}
      root._tmpDesired = {}
      var msg = String(d && d.message ? d.message : "state refresh failed")""",
"""      root._briDesired = {}
      root._tmpDesired = {}
      root._colorDesired = {}
      root._confirmScheduled = false
      var msg = String(d && d.message ? d.message : "state refresh failed")""")

# ---------------------------------------------------------------- 6. wake-on-use helper
rep("""  function cardPowerOn(index) {""",
"""  // wake-on-use: turn a lamp on first when a control is touched while off
  function wakeIndex(index) {
    var idx = String(index)
    var pw = {}
    for (var k in root._cardDesired) pw[k] = root._cardDesired[k]
    pw[idx] = true
    root._cardDesired = pw
    root.markDesired()
    root.enqueue(["set", "--device-index", idx, "--instance", "powerSwitch",
                  "--value", "1", "--confirm-physical"])
  }

  function cardPowerOn(index) {""")

# ---------------------------------------------------------------- 7. sliders: remove enabled:, add wake + desired labels
rep("""              PanelSlider {
                id: briSlider
                width: parent.width - parent.leftPadding - parent.rightPadding
                enabled: root.cardPowerOn(modelData.index)
                minimum: (parent.b && parent.b[0]) || 1""",
"""              PanelSlider {
                id: briSlider
                width: parent.width - parent.leftPadding - parent.rightPadding
                minimum: (parent.b && parent.b[0]) || 1""")
rep("""              PanelSlider {
                id: tmpSlider
                width: parent.width
                enabled: root.cardPowerOn(modelData.index)
                minimum: (parent.b && parent.b[0]) || 2000""",
"""              PanelSlider {
                id: tmpSlider
                width: parent.width - parent.leftPadding - parent.rightPadding
                minimum: (parent.b && parent.b[0]) || 2000""")

# bri release: wake + label shows desired
rep("""                  if (cur >= 0 && want === cur) return     // no-op guard
                  var idx = String(modelData.index)
                  var nd = {}
                  for (var k in root._briDesired) nd[k] = root._briDesired[k]
                  nd[idx] = want
                  root._briDesired = nd
                  root.markDesired()
                  root.enqueue(["set", "--device-index", String(modelData.index),
                                "--instance", "brightness",""",
"""                  if (cur >= 0 && want === cur) return     // no-op guard
                  var idx = String(modelData.index)
                  if (!root.cardPowerOn(modelData.index)) root.wakeIndex(modelData.index)
                  var nd = {}
                  for (var k in root._briDesired) nd[k] = root._briDesired[k]
                  nd[idx] = want
                  root._briDesired = nd
                  root.markDesired()
                  root.enqueue(["set", "--device-index", String(modelData.index),
                                "--instance", "brightness",""")
rep("""                text: {
                  var r = root.rowForIndex(modelData.index)
                  return "Brightness" + (r && r.props && r.props.brightness !== undefined
                                         ? " · " + r.props.brightness : "")
                }""",
"""                text: {
                  var r = root.rowForIndex(modelData.index)
                  var idx = String(modelData.index)
                  var v = (idx in root._briDesired) ? root._briDesired[idx]
                        : ((r && r.props) ? r.props.brightness : undefined)
                  return "Brightness" + (v !== undefined ? " · " + v : "")
                }""")

# tmp release: wake
rep("""                  if (cur >= 0 && Math.abs(want - cur) < 50) return  // no-op guard
                  var idx = String(modelData.index)
                  var nd = {}
                  for (var k in root._tmpDesired) nd[k] = root._tmpDesired[k]
                  nd[idx] = want
                  root._tmpDesired = nd
                  root.markDesired()
                  root.enqueue(["set", "--device-index", String(modelData.index),
                                "--instance", "colorTemperatureK",""",
"""                  if (cur >= 0 && Math.abs(want - cur) < 50) return  // no-op guard
                  var idx = String(modelData.index)
                  if (!root.cardPowerOn(modelData.index)) root.wakeIndex(modelData.index)
                  var nd = {}
                  for (var k in root._tmpDesired) nd[k] = root._tmpDesired[k]
                  nd[idx] = want
                  root._tmpDesired = nd
                  root.markDesired()
                  root.enqueue(["set", "--device-index", String(modelData.index),
                                "--instance", "colorTemperatureK",""")
rep("""                text: {
                  var r = root.rowForIndex(modelData.index)
                  var k = (r && r.props) ? r.props.colorTemperatureK : undefined
                  return "Color temp" + (k !== undefined && k > 0 ? " · " + k + "K" : "")
                }""",
"""                text: {
                  var r = root.rowForIndex(modelData.index)
                  var idx = String(modelData.index)
                  var k = (idx in root._tmpDesired) ? root._tmpDesired[idx]
                        : ((r && r.props) ? r.props.colorTemperatureK : 0)
                  return "Color temp" + (k > 0 ? " · " + k + "K" : "")
                }""")

# ---------------------------------------------------------------- 8. swatch: desired-first ring + wake + palette blue
rep("""              property var swatches: [0xE5484D, 0xF76B15, 0xF5D90A, 0x46A758, 0x12A594, 0x8E4EC6]""",
"""              property var swatches: [0xE5484D, 0xF76B15, 0xF5D90A, 0x46A758, 0x3B82F6, 0x8E4EC6]""")
rep("""                  property bool active: root.cardPowerOn(swatchRow.devIndex)
                                        && swatchRow.row && swatchRow.row.props
                                        && swatchRow.row.props.colorRgb === modelData""",
"""                  property bool active: {
                    if (!root.cardPowerOn(swatchRow.devIndex)) return false
                    var sidx = String(swatchRow.devIndex)
                    if (sidx in root._colorDesired) return root._colorDesired[sidx] === modelData
                    return !!(swatchRow.row && swatchRow.row.props
                              && swatchRow.row.props.colorRgb === modelData)
                  }""")
rep("""                    onClicked: {
                      var hex = "#" + ("000000" + modelData.toString(16)).slice(-6)
                      root.enqueue(["set", "--device-index", String(devCol.modelData.index),
                                    "--instance", "colorRgb", "--value", hex,
                                    "--confirm-physical"])
                    }""",
"""                    onClicked: {
                      var didx = swatchRow.devIndex
                      if (!root.cardPowerOn(didx)) root.wakeIndex(didx)
                      var hex = "#" + ("000000" + modelData.toString(16)).slice(-6)
                      var cd = {}
                      for (var ck in root._colorDesired) cd[ck] = root._colorDesired[ck]
                      cd[String(didx)] = modelData
                      root._colorDesired = cd
                      root.enqueue(["set", "--device-index", String(didx),
                                    "--instance", "colorRgb", "--value", hex,
                                    "--confirm-physical"])
                    }""")

open(p, "w").write(s)
print("Panel.qml done; braces:", s.count("{"), s.count("}"))

# ---------------------------------------------------------------- 9. BarWidget poll cadence
p2 = "BarWidget.qml"
s2 = open(p2).read()
s2 = s2.replace("""  Timer {
    id: pollTimer
    interval: 60000
    running: root.panelOpen
    onTriggered: root.refresh()
  }""",
"""  Timer {
    id: pollTimer
    interval: 25000
    running: root.panelOpen
    onTriggered: root.refresh()
  }""")
s2 = s2.replace("""  Timer {
    id: slowTimer
    interval: 90000
    running: true
    repeat: true
    onTriggered: root.refresh()
  }""",
"""  Timer {
    id: slowTimer
    interval: 45000
    running: true
    repeat: true
    onTriggered: root.refresh()
  }""")
open(p2, "w").write(s2)
print("BarWidget done")
