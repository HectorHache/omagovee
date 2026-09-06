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
  property bool busy: helper.busy || (panelLoader.item ? panelLoader.item.busy : false)
  property bool panelOpen: panelLoader.item ? panelLoader.item.opened : false
  property int updatedTs: 0

  readonly property bool hasKey: root.errorText.indexOf("no_key") < 0
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

  function togglePanel() { if (panelLoader.item) panelLoader.item.toggle() }
  function openPanel() { if (panelLoader.item) panelLoader.item.open() }
  readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
    onLoaded: { root.injectPanel(); Qt.callLater(root.injectPanel) }
  }

  // ---- data ----------------------------------------------------------------
  Helper {
    id: helper
    script: Qt.resolvedUrl("scripts/govee.py").toString().replace("file://", "")
    onOk: function (op, d) {
      if (op === "state") {
        root.states = d.devices || []
        root.errorText = ""
        root.updatedTs = Math.floor(Date.now() / 1000)
      } else if (op === "list") {
        root.devices = d.devices || []
        // chain: after the first inventory, pull values (helper cache keeps
        // this cheap; each Helper runs one process at a time)
        if (!helper.busy) helper.run("state", ["state"])
      }
    }
    onFailed: function (op, d) {
      root.errorText = (d && d.error === "no_key")
                       ? "no_key"
                       : String(d.message || d.error || "unknown error")
      if (op === "list") root.devices = []
      if (op === "state") root.states = []
    }
  }

  function refresh() {
    if (helper.busy) return
    if (root.devices.length === 0) helper.run("list", ["list"])
    else helper.run("state", ["state"])
  }

  // Poll only while the panel is open (D4); helper cache absorbs repeats.
  Timer {
    id: pollTimer
    interval: 60000
    running: root.panelOpen
    onTriggered: root.refresh()
  }

  Component.onCompleted: root.refresh()

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
      // middle click reserved for v1.1 scene cycling (mouse-less-first design
      // lands there with keybinds/touchpad); left opens the panel
      if (b !== Qt.MiddleButton) root.togglePanel()
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
