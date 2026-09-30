import QtQuick
import qs.Commons
import qs.Ui
import "Model.js" as M

// Govee Lights — control panel.
// Opens from the bar glyph. Master toggle (fan-out), per-device power,
// brightness + color-temperature sliders (commit on release — B6),
// RGB swatches, scenes (all 110 via searchable dropdown, favorites as
// name-based chips resolved per device — B4/D3), onboarding flow when no
// key is present (key reaches the helper via Process env, never argv).
// Control calls go through ONE serial queue; the helper owns rate buckets,
// caches and the key. Zero hex colors: every color is a qs.Commons token.
Panel {
  id: root
  moduleName: "io.github.pythonmalone.omagovee"
  ipcTarget: "io.github.pythonmalone.omagovee"
  manageIpc: false  // hotkey/IPC routes through the bar widget host contract

  property var anchorItem: null
  property var hostWidget: null   // BarWidget root (refresh + key state)
  property var widget: null

  property var devices: []        // list rows (kinds + bounds)
  property var states: []         // state rows
  property var sceneNames: []     // all scene names of the first rich device
  property var favorites: []      // favorite scene NAMES
  property string statusText: ""
  property bool statusBad: false
  property bool localNoKey: false
  property string currentSceneName: ""
  // optimistic desired state — caller owns ToggleSwitch.checked (never set it
  // imperatively); these flip declaratively. Master is DERIVED from the card
  // desired/states (single source of truth: master and card toggles can never
  // disagree). Desireds hold until the API read agrees or the heal fires.
  property bool masterOn: false
  property var _cardDesired: ({})      // "index" -> desired power bool
  property var _briDesired: ({})       // "index" -> desired brightness (held until API agrees)
  property var _tmpDesired: ({})       // "index" -> desired colorTemperatureK
  property var _colorDesired: ({})     // "index" -> desired colorRgb int (held until API agrees)
  property bool _confirmScheduled: false
  property int _lastRefreshMs: 0
  property var _lastJob: null
  Timer {
    id: desiredHeal
    interval: 90000
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
  }
  function markDesired() {
    desiredHeal.restart()
    root.pushWidgetView()
  }

  // Failure taxonomy: transient = budget/cloud hiccups (rate limits, network,
  // 5xx, bad responses) — NEVER user-visible, never clear truth. Red/error
  // text is reserved for meaningful failures (no_key, refusals, hard API
  // errors like 400/404 on a control).
  function isTransient(err) {
    if (err === undefined || err === null || err === "") return true
    var e = String(err).toLowerCase()
    return e === "rate_limited" || e === "network" || e === "bad_response"
        || e === "timeout" || e === "500" || e === "502" || e === "503" || e === "504"
  }

  // UI-only pre-store on drag ticks: the slider binding then sees the target
  // the instant dragging drops, so release can never flash the stale state
  function dragDesired(instance, idx, val) {
    if (instance === "brightness") {
      var m1 = {}
      for (var k1 in root._briDesired) m1[k1] = root._briDesired[k1]
      m1[idx] = val
      root._briDesired = m1
    } else {
      var m2 = {}
      for (var k2 in root._tmpDesired) m2[k2] = root._tmpDesired[k2]
      m2[idx] = val
      root._tmpDesired = m2
    }
  }

  // push the EFFECTIVE view (desired over state) so the bar dot/tooltip
  // reflect command truth immediately instead of waiting for the next read
  function pushWidgetView() {
    if (!hostWidget) return
    var out = []
    for (var i = 0; i < root.states.length; i++) {
      var row = root.states[i]
      var idx = String(row.index)
      var copy = {
        index: row.index, name: row.name, sku: row.sku, kind: row.kind,
        online: row.online, props: {}
      }
      for (var pk in row.props) copy.props[pk] = row.props[pk]
      if (idx in root._cardDesired) copy.props.powerSwitch = root._cardDesired[idx] ? 1 : 0
      if (idx in root._briDesired) copy.props.brightness = root._briDesired[idx]
      if (idx in root._tmpDesired) copy.props.colorTemperatureK = root._tmpDesired[idx]
      if (idx in root._colorDesired) copy.props.colorRgb = root._colorDesired[idx]
      out.push(copy)
    }
    hostWidget.states = out
  }

  readonly property bool busy: hSet.busy || hState.busy || hList.busy
                               || hScenes.busy || hFav.busy || hOnboard.busy
  readonly property bool noKey: (hostWidget ? !hostWidget.hasKey : false) || root.localNoKey

  function scriptPath() { return Qt.resolvedUrl("scripts/govee.py").toString().replace("file://", "") }
  function say(msg, bad) {
    root.statusText = msg; root.statusBad = !!bad
    root.statusTimer.restart()
  }
  function clearSay() { if (!root.statusBad) root.statusText = "" }
  Timer {
    id: statusTimer
    interval: 6000
    repeat: false
    onTriggered: {
      console.log("omagovee-dbg: status self-cleared after timeout")
      root.statusText = ""; root.statusBad = false
    }
  }

  // ------------------------------------------------------------------ helpers
  Helper {
    id: hList
    script: scriptPath()
    onOk: function (op, d) {
      console.log("omagovee-dbg: panel list ok n=" + (d.devices ? d.devices.length : "none"))
      root.devices = d.devices || []
      root.localNoKey = false
      root.refresh()
      // scenes + favorites once the inventory tells us the first rich index
      var firstRich = -1
      for (var i = 0; i < root.devices.length; i++)
        if (root.devices[i].kind === "rich") { firstRich = i; break }
      if (firstRich >= 0) hScenes.run("scenes", ["scenes", "--device-index", String(firstRich)])
      hFav.run("fav", ["favorites", "list"])
    }
    onFailed: function (op, d) {
      var msg = String(d && d.message ? d.message : "cannot reach Govee")
      if (d && d.error === "no_key") root.localNoKey = true
      root.say(msg, true)
    }
  }
  Helper {
    id: hScenes
    script: scriptPath()
    onOk: function (op, d) {
      var names = []
      var arr = d.scenes || []
      for (var j = 0; j < arr.length; j++) names.push(arr[j].name)
      root.sceneNames = names
      // keep only favorites this account still has
      var keep = []
      for (var k = 0; k < root.favorites.length; k++)
        if (names.indexOf(root.favorites[k]) >= 0) keep.push(root.favorites[k])
      root.favorites = keep
    }
  }
  Helper {
    id: hFav
    script: scriptPath()
    onOk: function (op, d) { root.favorites = d.names || [] }
    onFailed: function (op, d) { root.say("could not update favorites", true) }
  }
  Helper {
    id: hState
    script: scriptPath()
    onOk: function (op, d) {
      console.log("omagovee-dbg: panel state ok n=" + (d.devices ? d.devices.length : "none"))
      root.states = d.devices || []
      root.pushWidgetView()
      if (hostWidget) hostWidget.errorText = ""
      root.localNoKey = false
      // aggregate master (sliders follow reactively via Binding, drag-guarded)
      var counted = 0, on = 0
      for (var i = 0; i < root.states.length; i++) {
        var st = root.states[i]
        if (st.virtual || (st.kind !== "rich" && st.kind !== "scenic")) continue
        counted++
        if (st.online === false) continue
        if (st.props && st.props.powerSwitch === 1) on++
      }
      // NOTE: desireds are held (no match-drop reconcile): Govee cloud reads
      // can lag 30-60 s behind controls, so an early "match" may be a stale
      // echo that bounces back. Our command is truth until the heal fires.
      root.masterOn = root.anyCardOn()
      root.statusText = ""          // any successful refresh clears errors
      root.statusBad = false
    }
    onFailed: function (op, d) {
      // Reads NEVER wipe command truth or last-known states. Transient errors
      // (rate limits, network, 5xx) are silent — the next poll retries and
      // desireds stay authoritative. Only meaningful failures surface, and
      // no_key routes to onboarding.
      if (d && d.error === "no_key") {
        root.localNoKey = true
        if (hostWidget) { hostWidget.errorText = "no_key"; hostWidget.states = [] }
        return
      }
      if (root.isTransient(d && d.error)) {
        Qt.callLater(function () { if (!root.busy) root.refresh(false) }, 10000)
        return
      }
      var msg = String(d && d.message ? d.message : "state refresh failed")
      if (hostWidget) hostWidget.errorText = msg
      root.say(msg, true)
    }
  }
  Helper {
    id: hOnboard
    script: scriptPath()
    onOk: function (op, d) {
      root.localNoKey = false
      if (hostWidget) { hostWidget.errorText = ""; hostWidget.refresh() }
      root.loadEverything()
    }
    onFailed: function (op, d) {
      var msg = String(d && d.message ? d.message : "key rejected")
      if (d && d.error === "no_key") root.localNoKey = true
      root.say(msg, true)
    }
  }

  // Serial control queue — user actions never race each other or the bucket.
  Helper {
    id: hSet
    script: scriptPath()
    onOk: function (op, d) {
      console.log("omagovee-dbg: set OK " + String(d.op || ""))
      root._afterJob(d, false)
    }
    onFailed: function (op, d) {
      console.log("omagovee-dbg: set FAILED " + (d && d.error) + " " + String(d && d.message))
      root._afterJob(d, true)
    }
  }
  property var _queue: []
  property bool _draining: false
  property int _requeueCount: 0
  property var _lastWakeAt: {}   // device-index -> ts of last power-on send

  function _purgeSuperseded(args) {
    // A newer user intent for the same target makes older queued jobs stale:
    // drop queued jobs matching (device, instance), queued masters for a
    // newer per-card power, and per-card powers for a newer master.
    var isMaster = args.indexOf("--master") >= 0
    var mi = args.indexOf("--device-index")
    var mdev = mi >= 0 ? args[mi + 1] : null
    var ii = args.indexOf("--instance")
    var minst = ii >= 0 ? args[ii + 1] : null
    var keep = []
    for (var i = 0; i < root._queue.length; i++) {
      var q = root._queue[i]
      var qMaster = q.indexOf("--master") >= 0
      var qi = q.indexOf("--device-index")
      var qdev = qi >= 0 ? q[qi + 1] : null
      var qj = q.indexOf("--instance")
      var qinst = qj >= 0 ? q[qj + 1] : null
      if (isMaster) {
        if (qMaster || (qinst === "powerSwitch" && qdev !== null)) continue
      } else if (minst === "powerSwitch" && qMaster) {
        continue
      }
      if (qdev === mdev && qinst === minst) continue
      keep.push(q)
    }
    root._queue = keep
  }

  function enqueue(args) {
    if (root._queue.length === 0 && !root._draining) root._requeueCount = 0
    root._purgeSuperseded(args)
    root._queue.push(args)
    root._drain()
  }

  function _drain() {
    if (root._draining || hSet.busy || root._queue.length === 0) return
    root._draining = true
    var args = root._queue.shift()
    root._lastJob = args
    var wi = args.indexOf("--device-index")
    var wj = args.indexOf("--instance")
    var wv = args.indexOf("--value")
    var wIdx = wi >= 0 ? String(args[wi + 1]) : null
    if (wIdx !== null && wj >= 0 && args[wj] === "powerSwitch"
        && wv >= 0 && String(args[wv]) === "1") {
      root._lastWakeAt[wIdx] = Date.now()   // lamp is booting; settings will be
                                            // ignored until it settles (~2.5 s)
    }
    hSet.run("set", args)
  }

  function _afterJob(d, failed) {
    root._draining = false
    var terr = failed && root.isTransient(d && d.error)
    if (failed && !terr) {
      if (d && d.error === "scene_not_found") {
        // B4: this device simply has no such scene — skip silently
      } else {
        root.say(String(d && d.message ? d.message : "control failed"), true)
      }
    } else if (terr) {
      // Transient control failure: requeue silently with a growing delay that
      // honors the API's retry_after. Attempt budget: rate limits get 6 tries
      // (the disk bucket fails BEFORE any API call, so retries are free),
      // other transients 3. Past that we hold the desired — never redden, and
      // the heal timer reconciles the UI with physical truth at 90 s.
      var budget = (d && d.error === "rate_limited") ? 6 : 3
      if (root._lastJob && root._requeueCount < budget) {
        root._requeueCount++
        var wait = (d && d.retry_after) ? (d.retry_after * 1000 + 500)
                                       : (10000 * root._requeueCount)
        console.log("omagovee-dbg: transient requeue #" + root._requeueCount
                    + " in " + wait + "ms (" + d.error + ")")
        root._queue.unshift(root._lastJob)
        Qt.callLater(function () { root._drain() }, wait)
      } else {
        console.log("omagovee-dbg: transient budget exhausted, holding desired ("
                    + d.error + ")")
      }
      return
    }
    if (failed && !terr && (root._queue.length === 0 || !root._draining) && root._lastJob) {
      // targeted clear: only the failed job's device+instance loses its desire
      var aj = root._lastJob
      var ai = aj.indexOf("--device-index")
      var aidx = ai >= 0 ? String(aj[ai + 1]) : null
      var ii = aj.indexOf("--instance")
      var ainst = ii >= 0 ? aj[ii + 1] : null
      if (aidx !== null) {
        var c1 = {}
        for (var ck in root._cardDesired) if (ck !== aidx) c1[ck] = root._cardDesired[ck]
        root._cardDesired = c1
        if (ainst === "brightness") {
          var c2 = {}
          for (var k2 in root._briDesired) if (k2 !== aidx) c2[k2] = root._briDesired[k2]
          root._briDesired = c2
        }
        if (ainst === "colorTemperatureK") {
          var c3 = {}
          for (var k3 in root._tmpDesired) if (k3 !== aidx) c3[k3] = root._tmpDesired[k3]
          root._tmpDesired = c3
        }
        if (ainst === "colorRgb") {
          var c4 = {}
          for (var k4 in root._colorDesired) if (k4 !== aidx) c4[k4] = root._colorDesired[k4]
          root._colorDesired = c4
        }
      }
    }
    if (root._queue.length > 0) {
      // pace jobs: Govee ignores settings applied during lamp boot and the API
      // budget is per-device-per-minute. Base gap 900 ms; a settings job for a
      // device woken <3 s ago waits until the boot window has passed.
      var nx = root._queue[0]
      var ni = nx.indexOf("--device-index")
      var nj = nx.indexOf("--instance")
      var delay = 900
      if (ni >= 0 && nj >= 0 && nx[nj] !== "powerSwitch") {
        var nIdx = String(nx[ni + 1])
        var wakeAge = Date.now() - (root._lastWakeAt[nIdx] || 0)
        if (wakeAge < 2600) delay = 2600 - wakeAge
      }
      Qt.callLater(root._drain, delay)
    } else {
      // one confirming refresh after the whole queue drains, throttled to one
      // per 15 s window so rapid-fire clicking cannot blow the read budget
      var now2 = Date.now()
      if (now2 - root._lastRefreshMs > 15000) {
        Qt.callLater(function () { if (!root.busy) root.refresh(true) }, 2500)
      }
    }
  }

  function refresh(force) {
    if (hState.busy) return
    var now = Date.now()
    if (!force) {
      var pendingDesired = root.anyPendingDesired()
      if (!pendingDesired && now - root._lastRefreshMs < 8000) return  // burst guard
    }
    root._lastRefreshMs = now
    hState.run("state", ["state"])
  }

  function open() {                 // host + click route lands here
    if (!root.noKey) root.refresh(true)
    root.controller.show()
  }

  // ------------------------------------------------------------- data loading
  function loadEverything() {
    if (hList.busy || hScenes.busy || hFav.busy) return
    hList.run("list", ["list"])
  }

  function starScene() {
    var name = root.currentSceneName
    if (!name || hFav.busy) return
    var isFav = root.favorites.indexOf(name) >= 0
    hFav.run("fav", ["favorites", isFav ? "remove" : "add", "--name", name])
  }

  function applySceneToAll(name) {
    if (!name || root.busy) return
    // queue one set per rich device; helper skips scenes a device lacks
    for (var i = 0; i < root.devices.length; i++)
      if (root.devices[i].kind === "rich")
        root.enqueue(["set", "--scene-name", name,
                      "--device-index", String(root.devices[i].index),
                      "--confirm-physical"])
  }

  // ------------------------------------------------------------ state wiring
  function rowForIndex(index) {
    for (var i = 0; i < root.states.length; i++)
      if (root.states[i].index === index) return root.states[i]
    return null
  }
  // effective power for a card: per-card desired > master desired > state truth
  // wake-on-use: turn a lamp on first when a control is touched while off
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

  function cardPowerOn(index) {
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
  }

  function boundsForIndex(index, instance) {
    for (var i = 0; i < root.devices.length; i++) {
      var d = root.devices[i]
      if (d.index === index) return (d.bounds || {})[instance] || null
    }
    return null
  }

  Component.onCompleted: {
    if (hostWidget && hostWidget.devices && hostWidget.devices.length > 0) {
      root.devices = hostWidget.devices
      root.refresh()
      root.loadEverything() // no-op re-entrancy guard handles dupes
    } else {
      root.loadEverything()
    }
  }

  // ---------------------------------------------------------------------- UI
  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root
    bar: root.bar
    open: root.opened
    contentWidth: panel.fittedContentWidth(Style.space(400))
    contentHeight: panel.fittedContentHeight(col.implicitHeight + Style.space(14))

    Column {
      id: col
      anchors.fill: parent
      spacing: Style.space(6)

      // header: title + master
      Row {
        width: parent.width
        spacing: Style.space(10)
        Text {
          id: titleText
          text: "Govee Lights"
          color: Color.popups.text
          font.pixelSize: Style.font.body
          font.bold: true
          anchors.verticalCenter: parent.verticalCenter
        }
        Item { width: 10; height: 1 }
        ToggleSwitch {
          id: masterSwitch
          anchors.verticalCenter: parent.verticalCenter
          checked: root.masterOn
          onToggled: {
            var target = !root.anyCardOn()
            root.setAllCardsDesired(target)
            root.markDesired()
            root.say(target ? "Turning all lights on…" : "Turning all lights off…", false)
            // master = per-device power jobs: each device keeps its own budget
            // and a newer per-card click can supersede its half of the fan-out
            for (var i = 0; i < root.devices.length; i++) {
              var dd = root.devices[i]
              if (dd.kind === "rich") {
                root.enqueue(["set", "--device-index", String(dd.index),
                              "--instance", "powerSwitch",
                              "--value", target ? "1" : "0", "--confirm-physical"])
              }
            }
          }
        }
        Text {
          id: miniStatus
          anchors.verticalCenter: parent.verticalCenter
          width: Math.max(40, col.width - titleText.implicitWidth - masterSwitch.width
                              - Style.space(44))
          text: root.statusText
          color: root.statusBad ? Color.urgent : Color.accent
          visible: root.statusText !== ""
          font.pixelSize: Style.font.body
          elide: Text.ElideRight
          horizontalAlignment: Text.AlignRight
        }
      }



      // onboarding (no key)
      Column {
        width: parent.width
        visible: root.noKey
        spacing: Style.space(6)
        Text { text: "Connect your Govee account"
               color: Color.popups.text; font.pixelSize: Style.font.body; font.bold: true }
        Text {
          width: parent.width
          text: "1) Get an API key at developer.govee.com (user center).\n2) Paste it below — it is stored on this machine only (chmod 600)."
          color: Color.popups.text; opacity: 0.75; font.pixelSize: Style.font.body
          wrapMode: Text.Wrap
        }
        Rectangle {
          width: parent.width
          height: Style.space(36)
          radius: Math.max(2, Style.cornerRadius / 2)
          color: Color.popups.background
          border.color: Color.popups.border
          border.width: 1
          TextInput {
            id: keyField
            anchors.fill: parent
            anchors.leftMargin: Style.space(8)
            anchors.rightMargin: Style.space(8)
            verticalAlignment: Text.AlignVCenter
            color: Color.popups.text
            font.pixelSize: Style.font.body
            echoMode: TextInput.PasswordEchoOnEdit
            clip: true
          }
        }
        WidgetButton {
          id: connectBtn
          text: "Save & connect"
          horizontalMargin: 8
          enabled: keyField.text.length > 10
          onPressed: function (b) {
            if (b !== Qt.LeftButton) return
            root.say("Validating key…", false)
            hOnboard.useEnvironment = true
            hOnboard.environment = { "GOVEE_ONBOARD_KEY": keyField.text }
            hOnboard.run("onboard", ["onboard"])
          }
        }
      }

      // device cards
      Repeater {
        model: root.devices
        delegate: Column {
          id: devCol
          required property var modelData
          width: parent.width
          visible: modelData.kind === "rich"
          spacing: Style.space(4)

          // power row
          Row {
            width: parent.width
            spacing: Style.space(8)
            Rectangle {
              width: 7; height: 7; radius: width / 2
              anchors.verticalCenter: parent.verticalCenter
              color: {
                var r = root.rowForIndex(modelData.index)
                if (!r) return (bar ? bar.barForeground : Color.foreground)
                if (r.online === false) return (bar ? bar.urgent : Color.urgent)
                return (r.props && r.props.powerSwitch === 1)
                       ? Color.accent : (bar ? bar.barForeground : Color.foreground)
              }
              opacity: {
                var r2 = root.rowForIndex(modelData.index)
                return r2 && r2.online === false ? 0.6 : 0.9
              }
            }
            Text {
              text: modelData.name
              color: Color.popups.text
              font.pixelSize: Style.font.body
              elide: Text.ElideRight
              width: parent.width - toggle.width - Style.space(32)
              anchors.verticalCenter: parent.verticalCenter
            }
            ToggleSwitch {
              id: toggle
              anchors.verticalCenter: parent.verticalCenter
              checked: {
                var idx = String(modelData.index)
                if (idx in root._cardDesired) return root._cardDesired[idx]
                var r3 = root.rowForIndex(modelData.index)
                return r3 && r3.props ? r3.props.powerSwitch === 1 : false
              }
              onToggled: {
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
              }
            }
          }

          // rich controls
          Column {
            width: parent.width
            leftPadding: Style.space(16)
            rightPadding: Style.space(4)
            spacing: Style.space(4)
            visible: modelData.kind === "rich"

            Column {
              width: parent.width - parent.leftPadding - parent.rightPadding
              spacing: 2
              readonly property var row: root.rowForIndex(modelData.index)
              readonly property var b: root.boundsForIndex(modelData.index, "brightness")
              readonly property bool showable: row && row.props
                                               && row.props.brightness !== undefined
              visible: showable
              opacity: root.cardPowerOn(modelData.index) ? 1 : 0.45
              Text {
                text: {
                  var r = root.rowForIndex(modelData.index)
                  var idx = String(modelData.index)
                  var v = (idx in root._briDesired) ? root._briDesired[idx]
                        : ((r && r.props) ? r.props.brightness : undefined)
                  return "Brightness" + (v !== undefined ? " · " + v : "")
                }
                color: Color.popups.text; opacity: 0.7; font.pixelSize: Style.font.body
              }
              PanelSlider {
                id: briSlider
                width: parent.width - parent.leftPadding - parent.rightPadding
                minimum: (parent.b && parent.b[0]) || 1
                maximum: (parent.b && parent.b[1]) || 100
                step: 1
                integer: true
                value: 50
                property real _dragLast: -1
                onMoved: function (mv) {
                  briSlider._dragLast = mv
                  root.dragDesired("brightness", String(modelData.index), Math.round(mv))
                }
                Component.onCompleted: console.log("omagovee-dbg: bri bounds idx=" + modelData.index
                                                  + " min=" + minimum + " max=" + maximum)
                onReleased: function (v) {
                  // PanelSlider clobbers liveValue to the resnapped value before
                  // emitting released() (onValueChanged sync), so the emitted v
                  // may be the OLD state, not the drag target. moved() fired on
                  // press and every drag tick carries the true value.
                  // v (emitted liveValue) is truth UNLESS it equals the stale
                  // state resnap (PanelSlider clobbers liveValue before emit);
                  // only then fall back to the last drag position.
                  var r = root.rowForIndex(modelData.index)
                  var cur = (r && r.props && r.props.brightness !== undefined)
                            ? r.props.brightness : -1
                  // cur MUST be set before this rule — var hoisting made it
                  // undefined here before, NaN-poisoning the whole comparison.
                  var eff = (v !== cur && Math.abs(v - cur) > 1) ? v
                          : ((briSlider._dragLast >= 0
                              && briSlider._dragLast !== cur
                              && Math.abs(briSlider._dragLast - cur) > 1)
                             ? briSlider._dragLast : v)
                  var want = Math.round(eff)
                  console.log("omagovee-dbg: bri release idx=" + modelData.index
                              + " v=" + v + " drag=" + briSlider._dragLast
                              + " want=" + want + " cur=" + cur)
                  if (cur >= 0 && want === cur) return     // no-op guard
                  var idx = String(modelData.index)
                  if (!root.cardPowerOn(modelData.index)) root.wakeIndex(modelData.index)
                  var nd = {}
                  for (var k in root._briDesired) nd[k] = root._briDesired[k]
                  nd[idx] = want
                  root._briDesired = nd
                  root.markDesired()
                  root.enqueue(["set", "--device-index", String(modelData.index),
                                "--instance", "brightness",
                                "--value", String(want), "--confirm-physical"])
                }
              }
              // remote -> slider, but never while the user is dragging (B6)
              Binding {
                target: briSlider
                property: "value"
                when: !briSlider.dragging
                value: {
                  var r = root.rowForIndex(modelData.index)
                  var idx = String(modelData.index)
                  if (idx in root._briDesired) return root._briDesired[idx]
                  return (r && r.props && r.props.brightness !== undefined)
                         ? r.props.brightness : briSlider.value
                }
              }
            }

            Column {
              width: parent.width - parent.leftPadding - parent.rightPadding
              spacing: 2
              readonly property var row: root.rowForIndex(modelData.index)
              readonly property var b: root.boundsForIndex(modelData.index, "colorTemperatureK")
              readonly property bool showable: row && row.props
                                               && row.props.colorTemperatureK !== undefined
              visible: showable
              opacity: root.cardPowerOn(modelData.index) ? 1 : 0.45
              Text {
                text: {
                  var r = root.rowForIndex(modelData.index)
                  var idx = String(modelData.index)
                  var k = (idx in root._tmpDesired) ? root._tmpDesired[idx]
                        : ((r && r.props) ? r.props.colorTemperatureK : 0)
                  var colorPending = idx in root._colorDesired
                  return "Color temp" + (!colorPending && k > 0 ? " · " + k + "K" : "")
                }
                color: Color.popups.text; opacity: 0.7; font.pixelSize: Style.font.body
              }
              PanelSlider {
                id: tmpSlider
                width: parent.width - parent.leftPadding - parent.rightPadding
                minimum: (parent.b && parent.b[0]) || 2000
                maximum: (parent.b && parent.b[1]) || 9000
                step: 100
                integer: true
                value: 4000
                property real _dragLast: -1
                onMoved: function (mv) {
                  tmpSlider._dragLast = mv
                  root.dragDesired("colorTemperatureK", String(modelData.index), Math.round(mv))
                }
                Component.onCompleted: console.log("omagovee-dbg: tmp bounds idx=" + modelData.index
                                                  + " min=" + minimum + " max=" + maximum)
                onReleased: function (v) {
                  var r = root.rowForIndex(modelData.index)
                  var cur = (r && r.props && r.props.colorTemperatureK !== undefined)
                            ? r.props.colorTemperatureK : -1
                  // cur MUST be set before this rule — var hoisting made it
                  // undefined here before, NaN-poisoning the whole comparison.
                  var eff = (v !== cur && Math.abs(v - cur) > 1) ? v
                          : ((tmpSlider._dragLast >= 0
                              && tmpSlider._dragLast !== cur
                              && Math.abs(tmpSlider._dragLast - cur) > 1)
                             ? tmpSlider._dragLast : v)
                  var want = Math.round(eff)
                  console.log("omagovee-dbg: tmp release idx=" + modelData.index
                              + " v=" + v + " drag=" + tmpSlider._dragLast
                              + " want=" + want + " cur=" + cur)
                  if (cur >= 0 && Math.abs(want - cur) < 50) return  // no-op guard
                  var idx = String(modelData.index)
                  if (!root.cardPowerOn(modelData.index)) root.wakeIndex(modelData.index)
                  var nd = {}
                  for (var k in root._tmpDesired) nd[k] = root._tmpDesired[k]
                  nd[idx] = want
                  root._tmpDesired = nd
                  // white mode supersedes color mode
                  var ccd = {}
                  for (var ck in root._colorDesired) ccd[ck] = root._colorDesired[ck]
                  delete ccd[idx]
                  root._colorDesired = ccd
                  root.markDesired()
                  root.enqueue(["set", "--device-index", String(modelData.index),
                                "--instance", "colorTemperatureK",
                                "--value", String(want), "--confirm-physical"])
                }
              }
              // resnap only from a real white-mode value; in color mode the
              // lamp reports 0 and the slider keeps the user's last position
              Binding {
                target: tmpSlider
                property: "value"
                when: !tmpSlider.dragging
                value: {
                  var idx = String(modelData.index)
                  if (idx in root._tmpDesired) return root._tmpDesired[idx]
                  var r = root.rowForIndex(modelData.index)
                  var k = (r && r.props) ? r.props.colorTemperatureK : 0
                  return (k > 0) ? k : tmpSlider.value
                }
              }
            }

            Row {
              id: swatchRow
              spacing: Style.space(6)
              readonly property int devIndex: modelData.index
              readonly property var row: root.rowForIndex(modelData.index)
              readonly property bool showable: row && row.props
                                               && row.props.colorRgb !== undefined
              visible: showable
              property var swatches: [0xE5484D, 0xF76B15, 0xF5D90A, 0x46A758, 0x3B82F6, 0x8E4EC6]
              Repeater {
                model: parent.swatches
                delegate: Rectangle {
                  required property int modelData
                  width: Style.space(20); height: Style.space(20)
                  radius: width / 2
                  color: M.colorFromRgbInt(modelData)
                  property bool active: {
                    if (!root.cardPowerOn(swatchRow.devIndex)) return false
                    var sidx = String(swatchRow.devIndex)
                    if (sidx in root._colorDesired) return root._colorDesired[sidx] === modelData
                    // white-mode intent supersedes a lagged color read
                    if (sidx in root._tmpDesired) return false
                    return !!(swatchRow.row && swatchRow.row.props
                              && swatchRow.row.props.colorRgb === modelData)
                  }
                  opacity: root.cardPowerOn(swatchRow.devIndex)
                           ? (active ? 1.0 : 0.55) : 0.3
                  border.color: active ? "#ffffff" : Color.popups.border
                  border.width: active ? 2 : 1
                  MouseArea {
                    anchors.fill: parent
                    onClicked: {
                      var didx = swatchRow.devIndex
                      if (!root.cardPowerOn(didx)) root.wakeIndex(didx)
                      var hex = "#" + ("000000" + modelData.toString(16)).slice(-6)
                      var cd = {}
                      for (var ck in root._colorDesired) cd[ck] = root._colorDesired[ck]
                      cd[String(didx)] = modelData
                      root._colorDesired = cd
                      // color mode supersedes white mode (drop held temp)
                      var tdd = {}
                      for (var tk in root._tmpDesired) tdd[tk] = root._tmpDesired[tk]
                      delete tdd[String(didx)]
                      root._tmpDesired = tdd
                      root.markDesired()
                      root.enqueue(["set", "--device-index", String(didx),
                                    "--instance", "colorRgb", "--value", hex,
                                    "--confirm-physical"])
                    }
                  }
                }
              }
            }
          }
        }
      }

      // scenes
      Column {
        width: parent.width
        visible: root.sceneNames.length > 0
        spacing: Style.space(4)
        Text { text: "Scenes"
               color: Color.popups.text; opacity: 0.7; font.pixelSize: Style.font.body }

        Flow {
          width: parent.width
          spacing: Style.space(4)
          visible: root.favorites.length > 0
          Repeater {
            model: root.favorites
            delegate: Rectangle {
              required property string modelData
              height: Style.space(24)
              width: chipText.implicitWidth + Style.space(16)
              radius: height / 2
              color: Style.selectedFillFor(Color.popups.text, Color.accent)
              Text {
                id: chipText
                anchors.centerIn: parent
                text: modelData
                color: Color.popups.text
                font.pixelSize: Style.font.body
              }
              MouseArea {
                anchors.fill: parent
                onClicked: root.applySceneToAll(modelData)
              }
            }
          }
        }

        Row {
          width: parent.width
          spacing: Style.space(6)
          SearchableDropdown {
            id: scenePick
            width: parent.width - applyBtn.width - starBtn.width - Style.space(12)
            value: root.currentSceneName
            options: root.sceneNames
            placeholderText: "Search scenes…"
            onChanged: function (v) {
              if (v !== root.currentSceneName) root.currentSceneName = v
            }
          }
          WidgetButton {
            id: applyBtn
            text: "Apply"
            horizontalMargin: 8
            onPressed: function (b) { if (b === Qt.LeftButton) root.applySceneToAll(root.currentSceneName) }
          }
          WidgetButton {
            id: starBtn
            text: root.favorites.indexOf(root.currentSceneName) >= 0 ? "\u2605" : "\u2606"
            horizontalMargin: 8
            onPressed: function (b) { if (b === Qt.LeftButton) root.starScene() }
          }
        }
      }

      Text {
        width: parent.width
        visible: root.states.length > 0
        text: "Refresh: on open, after changes, and every 60 s while open"
        color: Color.popups.text; opacity: 0.4; font.pixelSize: Style.font.body
      }
    }
  }
}