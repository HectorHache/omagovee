import sys
p = "Panel.qml"
s = open(p).read()

def rep(old, new):
    global s
    assert old in s, "MISSING: " + old[:90]
    s = s.replace(old, new, 1)

# ---------------------------------------------------------------- 1. refresh(force)
rep("""  function refresh() {
    if (hState.busy) return
    var now = Date.now()
    var pendingDesired = root._masterHasDesired
    for (var pk in root._cardDesired) { pendingDesired = true; break }
    if (!pendingDesired && now - root._lastRefreshMs < 8000) return  // burst guard
    root._lastRefreshMs = now
    hState.run("state", ["state"])
  }

  function open() {                 // host + click route lands here
    if (!root.noKey) root.refresh()
    root.controller.show()
  }""",
"""  function refresh(force) {
    if (hState.busy) return
    var now = Date.now()
    if (!force) {
      var pendingDesired = root._masterHasDesired
      for (var pk in root._cardDesired) { pendingDesired = true; break }
      if (!pendingDesired && now - root._lastRefreshMs < 8000) return  // burst guard
    }
    root._lastRefreshMs = now
    hState.run("state", ["state"])
  }

  function open() {                 // host + click route lands here
    if (!root.noKey) root.refresh(true)
    root.controller.show()
  }""")

# ---------------------------------------------------------------- 2. drain refresh forced
rep("""      Qt.callLater(function () { if (!root.busy) root.refresh() }, 2500)""",
"""      Qt.callLater(function () { if (!root.busy) root.refresh(true) }, 2500)""")

# ---------------------------------------------------------------- 3. power desired reconcile (keep until matched)
rep("""      root.masterOn = counted > 0 && on === counted
      root._masterHasDesired = false
      root._cardDesired = {}
      var bd = {}""",
"""      root.masterOn = counted > 0 && on === counted
      if (root._masterHasDesired && root.masterOn === root._masterDesired)
        root._masterHasDesired = false
      var cd = {}
      for (var ck in root._cardDesired) {
        var cr = root.rowForIndex(Number(ck))
        if (!(cr && cr.props) || cr.props.powerSwitch === undefined
            || cr.props.powerSwitch !== (root._cardDesired[ck] ? 1 : 0)) cd[ck] = root._cardDesired[ck]
      }
      root._cardDesired = cd
      var bd = {}""")

# ---------------------------------------------------------------- 4. sliders: true drag value via moved()
rep("""              PanelSlider {
                id: briSlider
                width: parent.width - parent.leftPadding - parent.rightPadding
                minimum: (parent.b && parent.b[0]) || 1
                maximum: (parent.b && parent.b[1]) || 100
                step: 1
                integer: true
                value: 50
                Component.onCompleted: console.log("omagovee-dbg: bri bounds idx=" + modelData.index
                                                  + " min=" + minimum + " max=" + maximum)
                onReleased: function (v) {
                  var want = Math.round(v)
                  var r = root.rowForIndex(modelData.index)
                  var cur = (r && r.props && r.props.brightness !== undefined)
                            ? r.props.brightness : -1
                  console.log("omagovee-dbg: bri release idx=" + modelData.index
                              + " v=" + v + " want=" + want + " cur=" + cur)""",
"""              PanelSlider {
                id: briSlider
                width: parent.width - parent.leftPadding - parent.rightPadding
                minimum: (parent.b && parent.b[0]) || 1
                maximum: (parent.b && parent.b[1]) || 100
                step: 1
                integer: true
                value: 50
                property real _dragLast: -1
                onMoved: function (mv) { briSlider._dragLast = mv }
                Component.onCompleted: console.log("omagovee-dbg: bri bounds idx=" + modelData.index
                                                  + " min=" + minimum + " max=" + maximum)
                onReleased: function (v) {
                  // PanelSlider clobbers liveValue to the resnapped value before
                  // emitting released() (onValueChanged sync), so the emitted v
                  // may be the OLD state, not the drag target. moved() fired on
                  // press and every drag tick carries the true value.
                  var eff = (briSlider._dragLast >= 0
                             && Math.abs(v - briSlider._dragLast) > 1)
                            ? briSlider._dragLast : v
                  var want = Math.round(eff)
                  var r = root.rowForIndex(modelData.index)
                  var cur = (r && r.props && r.props.brightness !== undefined)
                            ? r.props.brightness : -1
                  console.log("omagovee-dbg: bri release idx=" + modelData.index
                              + " v=" + v + " drag=" + briSlider._dragLast
                              + " want=" + want + " cur=" + cur)""")

rep("""              PanelSlider {
                id: tmpSlider
                width: parent.width
                minimum: (parent.b && parent.b[0]) || 2000
                maximum: (parent.b && parent.b[1]) || 9000
                step: 100
                integer: true
                value: 4000
                Component.onCompleted: console.log("omagovee-dbg: tmp bounds idx=" + modelData.index
                                                  + " min=" + minimum + " max=" + maximum)
                onReleased: function (v) {
                  var want = Math.round(v)
                  var r = root.rowForIndex(modelData.index)
                  var cur = (r && r.props && r.props.colorTemperatureK !== undefined)
                            ? r.props.colorTemperatureK : -1
                  console.log("omagovee-dbg: tmp release idx=" + modelData.index
                              + " v=" + v + " want=" + want + " cur=" + cur)""",
"""              PanelSlider {
                id: tmpSlider
                width: parent.width - parent.leftPadding - parent.rightPadding
                minimum: (parent.b && parent.b[0]) || 2000
                maximum: (parent.b && parent.b[1]) || 9000
                step: 100
                integer: true
                value: 4000
                property real _dragLast: -1
                onMoved: function (mv) { tmpSlider._dragLast = mv }
                Component.onCompleted: console.log("omagovee-dbg: tmp bounds idx=" + modelData.index
                                                  + " min=" + minimum + " max=" + maximum)
                onReleased: function (v) {
                  var eff = (tmpSlider._dragLast >= 0
                             && Math.abs(v - tmpSlider._dragLast) > 1)
                            ? tmpSlider._dragLast : v
                  var want = Math.round(eff)
                  var r = root.rowForIndex(modelData.index)
                  var cur = (r && r.props && r.props.colorTemperatureK !== undefined)
                            ? r.props.colorTemperatureK : -1
                  console.log("omagovee-dbg: tmp release idx=" + modelData.index
                              + " v=" + v + " drag=" + tmpSlider._dragLast
                              + " want=" + want + " cur=" + cur)""")

# ---------------------------------------------------------------- 5. swatch selection visual (opacity + white ring)
rep("""                  color: M.colorFromRgbInt(modelData)
                  border.color: (swatchRow.row && swatchRow.row.props
                                 && swatchRow.row.props.colorRgb === modelData)
                                ? Color.accent : Color.popups.border
                  border.width: (swatchRow.row && swatchRow.row.props
                                 && swatchRow.row.props.colorRgb === modelData) ? 2 : 1""",
"""                  color: M.colorFromRgbInt(modelData)
                  opacity: (swatchRow.row && swatchRow.row.props
                            && swatchRow.row.props.colorRgb === modelData) ? 1.0 : 0.55
                  border.color: (swatchRow.row && swatchRow.row.props
                                 && swatchRow.row.props.colorRgb === modelData)
                                ? "#ffffff" : Color.popups.border
                  border.width: (swatchRow.row && swatchRow.row.props
                                 && swatchRow.row.props.colorRgb === modelData) ? 2 : 1""")

open(p, "w").write(s)
print("done; braces:", s.count("{"), s.count("}"))
