import sys
p = "Panel.qml"
s = open(p).read()

def rep(old, new):
    global s
    assert old in s, "MISSING: " + old[:90]
    s = s.replace(old, new, 1)

# ================================================================ A. single-source master
# A1 props: drop separate master-flag props; masterOn becomes derived any-on
rep("""  property bool masterOn: false
  // optimistic desired state — caller owns ToggleSwitch.checked (never set it
  // imperatively); these flip declaratively and reset when refresh lands
  property bool _masterDesired: false
  property bool _masterHasDesired: false""",
"""  // optimistic desired state — caller owns ToggleSwitch.checked (never set it
  // imperatively); these flip declaratively. Master is DERIVED from the card
  // desired/states (single source of truth: master and card toggles can never
  // disagree). Desireds hold until the API read agrees or the heal fires.
  property bool masterOn: false""")

# A2 cardPowerOn: per-card desired else state (no master consult)
rep("""  function cardPowerOn(index) {
    var idx = String(index)
    if (idx in root._cardDesired) return root._cardDesired[idx]
    if (root._masterHasDesired) return root._masterDesired
    var r = root.rowForIndex(index)
    return !!(r && r.props && r.props.powerSwitch === 1)
  }""",
"""  function cardPowerOn(index) {
    var idx = String(index)
    if (idx in root._cardDesired) return root._cardDesired[idx]
    var r = root.rowForIndex(index)
    return !!(r && r.props && r.props.powerSwitch === 1)
  }

  // master = any rich card on (mixed shows ON)
  function anyCardOn() {
    for (var i = 0; i < root.devices.length; i++) {
      var d = root.devices[i]
      if (d.kind !== "rich") continue
      if (root.cardPowerOn(d.index)) return true
    }
    return false
  }

  // set the desired power of every rich card (used by the master toggle)
  function setAllCardsDesired(target) {
    var nd = {}
    for (var k in root._cardDesired) nd[k] = root._cardDesired[k]
    for (var i = 0; i < root.devices.length; i++) {
      var d = root.devices[i]
      if (d.kind === "rich") nd[String(d.index)] = target
    }
    root._cardDesired = nd
  }""")

# A3 heal: 45 s; drop every desired; re-refresh
rep("""  Timer {
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
  }""",
"""  Timer {
    id: desiredHeal
    interval: 45000
    onTriggered: {
      root._cardDesired = {}
      root._briDesired = {}
      root._tmpDesired = {}
      root._colorDesired = {}
      if (!root.noKey) root.refresh(true)
    }
  }
  function anyPendingDesired() {
    for (var k1 in root._cardDesired) return true
    for (var k2 in root._briDesired) return true
    for (var k3 in root._tmpDesired) return true
    for (var k4 in root._colorDesired) return true
    return false
  }""")

# A4 markDesired no longer sets master flag
rep("""  function markDesired() {
    root._masterHasDesired = true
    desiredHeal.restart()
  }""",
"""  function markDesired() {
    desiredHeal.restart()
  }""")

# A5 state ok: no match-drop reconcile, no master-flag reconcile; derive masterOn
rep("""      root.masterOn = counted > 0 && on > 0
      if (root._masterHasDesired && root.masterOn === root._masterDesired)
        root._masterHasDesired = false
      var cd = {}
      for (var ck in root._cardDesired) {
        var cr = root.rowForIndex(Number(ck))
        if (!(cr && cr.props) || cr.props.powerSwitch === undefined
            || cr.props.powerSwitch !== (root._cardDesired[ck] ? 1 : 0)) cd[ck] = root._cardDesired[ck]
      }
      root._cardDesired = cd
      var bd = {}
      for (var bk in root._briDesired) {
        var br = root.rowForIndex(Number(bk))
        if (!(br && br.props) || br.props.brightness === undefined
            || br.props.brightness !== root._briDesired[bk]) bd[bk] = root._briDesired[bk]
      }
      root._briDesired = bd
      var td = {}
      for (var tk in root._tmpDesired) {
        var tr = root.rowForIndex(Number(tk))
        if (!(tr && tr.props) || tr.props.colorTemperatureK === undefined
            || Math.abs(tr.props.colorTemperatureK - root._tmpDesired[tk]) > 60) td[tk] = root._tmpDesired[tk]
      }
      root._tmpDesired = td
      var kd = {}
      for (var kk in root._colorDesired) {
        var kr = root.rowForIndex(Number(kk))
        if (!(kr && kr.props) || kr.props.colorRgb === undefined
            || kr.props.colorRgb !== root._colorDesired[kk]) kd[kk] = root._colorDesired[kk]
      }
      root._colorDesired = kd
      root.statusText = ""          // any successful refresh clears errors
      root.statusBad = false""",
"""      // NOTE: desireds are held (no match-drop reconcile): Govee cloud reads
      // can lag 30-60 s behind controls, so an early "match" may be a stale
      // echo that bounces back. Our command is truth until the heal fires.
      root.masterOn = root.anyCardOn()
      root.statusText = ""          // any successful refresh clears errors
      root.statusBad = false""")

# A6 state-fail clears: drop master flag line
rep("""      root.states = []
      root._masterHasDesired = false
      root._cardDesired = {}
      root._briDesired = {}
      root._tmpDesired = {}
      root._colorDesired = {}
      root._confirmScheduled = false""",
"""      root.states = []
      root._cardDesired = {}
      root._briDesired = {}
      root._tmpDesired = {}
      root._colorDesired = {}
      root._confirmScheduled = false""")

# A7 failed-job clear: master flag line out
rep("""    if (failed && (root._queue.length === 0 || !root._draining)) {
      root._masterHasDesired = false
      root._cardDesired = {}
    }""",
"""    if (failed && (root._queue.length === 0 || !root._draining)) {
      root._cardDesired = {}
    }""")

# A8 refresh throttle pending check
rep("""      var pendingDesired = root._masterHasDesired
      for (var pk in root._cardDesired) { pendingDesired = true; break }""",
"""      var pendingDesired = root.anyPendingDesired()""")

# A9 master switch: derived checked + fan-out both states
rep("""          id: masterSwitch
          anchors.verticalCenter: parent.verticalCenter
          checked: root._masterHasDesired ? root._masterDesired : root.masterOn
          onToggled: {
            root._masterDesired = !(root._masterHasDesired ? root._masterDesired : root.masterOn)
            root.markDesired()
            root.enqueue(["set", "--master", "--value",
                          root._masterDesired ? "1" : "0", "--confirm-physical"])
          }""",
"""          id: masterSwitch
          anchors.verticalCenter: parent.verticalCenter
          checked: root.masterOn
          onToggled: {
            var target = !root.anyCardOn()
            root.setAllCardsDesired(target)
            root.markDesired()
            root.say(target ? "Turning all lights on…" : "Turning all lights off…", false)
            root.enqueue(["set", "--master", "--value",
                          target ? "1" : "0", "--confirm-physical"])
          }""")

# A10 card toggle: clear master's blanket by design (no flag), keep per-card desired
rep("""              onToggled: {
                var idx = String(modelData.index)
                var cur = false
                var r3 = root.rowForIndex(modelData.index)
                if (r3 && r3.props) cur = r3.props.powerSwitch === 1
                var desired = !((idx in root._cardDesired) ? root._cardDesired[idx] : cur)
                var next = {}
                for (var k in root._cardDesired) next[k] = root._cardDesired[k]
                next[idx] = desired
                root._cardDesired = next
                root.enqueue(["set", "--device-index", idx,
                              "--instance", "powerSwitch",
                              "--value", desired ? "1" : "0", "--confirm-physical"])
              }""",
"""              onToggled: {
                var idx = String(modelData.index)
                var cur = false
                var r3 = root.rowForIndex(modelData.index)
                if (r3 && r3.props) cur = r3.props.powerSwitch === 1
                var desired = !((idx in root._cardDesired) ? root._cardDesired[idx] : cur)
                var next = {}
                for (var k in root._cardDesired) next[k] = root._cardDesired[k]
                next[idx] = desired
                root._cardDesired = next
                root.markDesired()
                root.enqueue(["set", "--device-index", idx,
                              "--instance", "powerSwitch",
                              "--value", desired ? "1" : "0", "--confirm-physical"])
              }""")

# ================================================================ B. color/temp mode mutual exclusion
rep("""                  if (cur >= 0 && Math.abs(want - cur) < 50) return  // no-op guard
                  var idx = String(modelData.index)
                  if (!root.cardPowerOn(modelData.index)) root.wakeIndex(modelData.index)
                  var nd = {}
                  for (var k in root._tmpDesired) nd[k] = root._tmpDesired[k]
                  nd[idx] = want
                  root._tmpDesired = nd""",
"""                  if (cur >= 0 && Math.abs(want - cur) < 50) return  // no-op guard
                  var idx = String(modelData.index)
                  if (!root.cardPowerOn(modelData.index)) root.wakeIndex(modelData.index)
                  var nd = {}
                  for (var k in root._tmpDesired) nd[k] = root._tmpDesired[k]
                  nd[idx] = want
                  // white mode supersedes color mode
                  var ccd = {}
                  for (var ck in root._colorDesired) ccd[ck] = root._colorDesired[ck]
                  delete ccd[idx]
                  root._colorDesired = ccd""")
rep("""                      if (!root.cardPowerOn(didx)) root.wakeIndex(didx)
                      var hex = "#" + ("000000" + modelData.toString(16)).slice(-6)
                      var cd = {}
                      for (var ck in root._colorDesired) cd[ck] = root._colorDesired[ck]
                      cd[String(didx)] = modelData
                      root._colorDesired = cd""",
"""                      if (!root.cardPowerOn(didx)) root.wakeIndex(didx)
                      var hex = "#" + ("000000" + modelData.toString(16)).slice(-6)
                      var cd = {}
                      for (var ck in root._colorDesired) cd[ck] = root._colorDesired[ck]
                      cd[String(didx)] = modelData
                      // color mode supersedes white mode (drop held temp)
                      var tdd = {}
                      for (var tk in root._tmpDesired) tdd[tk] = root._tmpDesired[tk]
                      delete tdd[String(didx)]
                      root._tmpDesired = tdd""")

# C: temp label hidden while a color selection is pending (mode = color)
rep("""                text: {
                  var r = root.rowForIndex(modelData.index)
                  var idx = String(modelData.index)
                  var k = (idx in root._tmpDesired) ? root._tmpDesired[idx]
                        : ((r && r.props) ? r.props.colorTemperatureK : 0)
                  return "Color temp" + (k > 0 ? " · " + k + "K" : "")
                }""",
"""                text: {
                  var r = root.rowForIndex(modelData.index)
                  var idx = String(modelData.index)
                  var k = (idx in root._tmpDesired) ? root._tmpDesired[idx]
                        : ((r && r.props) ? r.props.colorTemperatureK : 0)
                  var colorPending = idx in root._colorDesired
                  return "Color temp" + (!colorPending && k > 0 ? " · " + k + "K" : "")
                }""")

open(p, "w").write(s)
print("done; braces:", s.count("{"), s.count("}"))
