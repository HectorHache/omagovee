import QtQuick
import qs.Commons
import qs.Ui
import "Model.js" as M

// Govee Lights — bar glyph.
// One minimal glyph colored by aggregate state: all on -> accent,
// mixed -> accent/foreground blend, off -> dim foreground,
// no key / error -> urgent. Tooltip carries the summary.
// Left click opens the panel. No idle polling: refresh happens on load,
// panel open, and while the panel is open (timer) — the helper's 60 s
// state cache keeps repeat reads free (D4).
BarWidget {
  id: root
  moduleName: "io.github.pythonmalone.omagovee"

  property var devices: []           // list-cmd rows (kinds/bounds), cached
  property var states: []            // state-cmd rows (values)
  property string errorText: ""      // last helper error message ("" = clean)
  property bool busy: hList.busy || hState.busy || (panelLoader.item ? panelLoader.item.busy : false)
  property bool panelOpen: panelLoader.item ? panelLoader.item.opened : false
  property int updatedTs: 0

  readonly property bool hasKey: String(root.errorText || "").indexOf("no_key") < 0

  // Same taxonomy as the panel: transient cloud/budget hiccups are silent;
  // errorText (red) is reserved for meaningful failures.
  function isTransient(err) {
    if (err === undefined || err === null || err === "") return true
    var e = String(err).toLowerCase()
    return e === "rate_limited" || e === "network" || e === "bad_response"
        || e === "timeout" || e === "500" || e === "502" || e === "503" || e === "504"
  }
  readonly property string agg: M.aggregate(root.states, root.errorText, root.hasKey)

  // ---- state-driven colors ------------------------------------------------
  property bool everLoaded: false
  property bool checking: false

  readonly property color dotColor:
    root.agg === "on" ? Color.accent :
    root.agg === "mixed" ? M.blend(Color.accent, (bar ? bar.barForeground : Color.foreground), 0.55) :
    root.agg === "error" ? (bar ? bar.urgent : Color.urgent) :
    root.agg === "nokey" ? (bar ? bar.urgent : Color.urgent) :
    root.agg === "offline" || root.agg === "empty" || root.agg === "checking" ? (bar ? bar.barForeground : Color.foreground) :
    (bar ? bar.barForeground : Color.foreground) // off
  readonly property real dotOpacity:
    root.agg === "on" ? 1.0 :
    root.agg === "mixed" ? 0.9 :
    root.agg === "error" || root.agg === "nokey" ? 1.0 :
    root.agg === "offline" || root.agg === "checking" ? 0.55 : 0.35 // off/empty -> dim

  // ---- panel ---------------------------------------------------------------
  function injectPanel() {
    var t = panelLoader.item
    if (!t) return
    if ("bar" in t) t.bar = root.bar
    if ("settings" in t) t.settings = root.settings
    if ("anchorItem" in t) t.anchorItem = button
    if ("hostWidget" in t) t.hostWidget = root
    if ("widget" in t) t.widget = root
  }

  // Host contract — Bar.summonBarWidget/hideBarWidget/isBarWidgetOpen call
  // open()/close()/opened on the live widget (hotkeys, popout switching).
  function open() { if (panelLoader.item) panelLoader.item.open() }
  function close() { if (panelLoader.item) panelLoader.item.close() }
  function togglePanel() { if (panelLoader.item) panelLoader.item.toggle() }
  readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false
  readonly property bool popoutSwitchClosing: panelLoader.item ? panelLoader.item.popoutSwitchClosing === true : false
  function closeForPopoutSwitch() { if (panelLoader.item) panelLoader.item.closeForPopoutSwitch() }
  onBarChanged: root.injectPanel()
  onSettingsChanged: root.injectPanel()

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
    onLoaded: { root.injectPanel(); Qt.callLater(root.injectPanel) }
  }

  // ---- data ----------------------------------------------------------------
  Helper {
    id: hList
    script: Qt.resolvedUrl("scripts/govee.py").toString().replace("file://", "")
    onOk: function (op, d) {
      console.log("omagovee-dbg: widget list ok n=" + (d.devices ? d.devices.length : "none"))
      root.devices = d.devices || []
      root.errorText = ""
      root.updatedTs = Math.floor(Date.now() / 1000)
      if (!hState.busy) hState.run("state", ["state"])
    }
    onFailed: function (op, d) {
      if (d && d.error === "no_key") { root.errorText = "no_key"; root.devices = []; return }
      if (root.isTransient(d && d.error)) {
        Qt.callLater(function () { if (!root.busy) root.refresh() }, 10000)
        return  // silent: keep last list, fast retry after rate walls
      }
      root.errorText = String(d.message || d.error || "unknown error")
    }
  }
  Helper {
    id: hState
    script: Qt.resolvedUrl("scripts/govee.py").toString().replace("file://", "")
    onOk: function (op, d) {
      console.log("omagovee-dbg: widget state ok n=" + (d.devices ? d.devices.length : "none"))
      root.states = d.devices || []
      root.errorText = ""
      root.updatedTs = Math.floor(Date.now() / 1000)
    }
    onFailed: function (op, d) {
      console.log("omagovee-dbg: widget state failed " + (d && d.error) + " " + (d && d.message))
      if (d && d.error === "no_key") { root.errorText = "no_key"; root.states = []; return }
      if (root.isTransient(d && d.error)) {
        Qt.callLater(function () { if (!root.busy) root.refresh() }, 10000)
        return  // silent: keep last states, fast retry after rate walls
      }
      root.errorText = String(d.message || d.error || "unknown error")
    }
  }

  function refresh() {
    console.log("omagovee-dbg: refresh devices=" + root.devices.length + " busy=" + (hList.busy || hState.busy))
    if (hList.busy || hState.busy) return
    if (root.devices.length === 0) hList.run("list", ["list"])
    else hState.run("state", ["state"])
  }

  // Glyph freshness: poll while the panel is open (60 s) AND a slow always-on
  // tick (90 s) so externally-changed lamps (phone app) eventually surface.
  // The helper's 60 s state cache absorbs the overlap.
  Timer {
    id: pollTimer
    interval: 30000
    running: root.panelOpen
    onTriggered: root.refresh()
  }
  Timer {
    id: slowTimer
    interval: 45000
    running: true
    repeat: true
    onTriggered: root.refresh()
  }

  Component.onCompleted: { console.log("omagovee-dbg: BarWidget onCompleted"); root.refresh() }



  // ---- glyph ----------------------------------------------------------------
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: ""
    labelVisible: false
    hasVisualContent: true
    horizontalMargin: 7
    tooltipText: M.tooltip(root.agg, root.states, root.updatedTs, root.hasKey, root.errorText)

    onPressed: function (b) {
      if (!root.bar) return
      if (b === Qt.MiddleButton) { root.refresh(); return }
      // left/right open the panel; middle = manual refresh (host convention)
      root.togglePanel()
    }

    Rectangle {
      id: dot
      anchors.centerIn: parent
      width: 9
      height: 9
      radius: width / 2
      color: root.dotColor
      opacity: root.dotOpacity
      Behavior on color { ColorAnimation { duration: 180 } }
      Behavior on opacity { NumberAnimation { duration: 180 } }
    }
  }
}
