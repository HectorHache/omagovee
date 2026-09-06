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

  property var bar: null
  property var settings: ({})
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
  property bool masterOn: false

  readonly property bool busy: queue.busy || hState.busy || hList.busy
                               || hScenes.busy || hFav.busy || hOnboard.busy
  readonly property bool noKey: (hostWidget ? !hostWidget.hasKey : false) || root.localNoKey

  function scriptPath() { return Qt.resolvedUrl("scripts/govee.py").toString().replace("file://", "") }
  function say(msg, bad) { root.statusText = msg; root.statusBad = !!bad }
  function clearSay() { if (!root.statusBad) root.statusText = "" }

  // ------------------------------------------------------------------ helpers
  Helper { id: hList; script: scriptPath() }
  Helper { id: hState; script: scriptPath() }
  Helper { id: hScenes; script: scriptPath() }
  Helper { id: hFav; script: scriptPath() }
  Helper { id: hOnboard; script: scriptPath() }

  // Serial control queue — user actions never race each other or the bucket.
  Helper { id: hSet; script: scriptPath() }
  property var _queue: []
  property bool _draining: false

  function enqueue(args) { root._queue.push(args); root._drain() }

  function _drain() {
    if (root._draining || hSet.busy || root._queue.length === 0) return
    root._draining = true
    var args = root._queue.shift()
    hSet.run("set", args)
    hSet.onOk = function (op, d) { root._afterJob(d, false) }
    hSet.onFailed = function (op, d) { root._afterJob(d, true) }
  }

  function _afterJob(d, failed) {
    root._draining = false
    if (failed) {
      if (d && d.error === "scene_not_found") {
        // B4: this device simply has no such scene — skip silently
      } else {
        root.say(String(d && d.message ? d.message : "control failed"), true)
      }
    }
    if (root._queue.length > 0) {
      Qt.callLater(root._drain)
    } else {
      // one confirming refresh after the whole queue drains (cheap: the
      // helper's 60 s cache absorbs repeat reads; control invalidated it)
      Qt.callLater(function () { if (!root.busy) root.refresh() })
    }
  }

  function refresh() {
    if (hState.busy) return
    hState.run("state", ["state"])
  }

  // ------------------------------------------------------------- data loading
  function loadEverything() {
    if (hList.busy || hScenes.busy || hFav.busy) return
    hList.run("list", ["list"])
    hList.onOk = function (op, d) {
      root.devices = d.devices || []
      root.localNoKey = false
      root.refresh()
      // scenes + favorites once the inventory tells us the first rich index
      var firstRich = -1
      for (var i = 0; i < root.devices.length; i++)
        if (root.devices[i].kind === "rich") { firstRich = i; break }
      if (firstRich >= 0) {
        hScenes.run("scenes", ["scenes", "--device-index", String(firstRich)])
        hScenes.onOk = function (op2, d2) {
          var names = []
          for (var j = 0; j < d2.scenes.length; j++) names.push(d2.scenes[j].name)
          root.sceneNames = names
          // keep only favorites this account still has
          var keep = []
          for (var k = 0; k < root.favorites.length; k++)
            if (names.indexOf(root.favorites[k]) >= 0) keep.push(root.favorites[k])
          root.favorites = keep
        }
      }
      hFav.run("fav", ["favorites", "list"])
      hFav.onOk = function (op2, d2) { root.favorites = d2.names || [] }
    }
    hList.onFailed = function (op, d) {
      var msg = String(d && d.message ? d.message : "cannot reach Govee")
      if (d && d.error === "no_key") root.localNoKey = true
      root.say(msg, true)
    }
  }

  function starScene() {
    var name = root.currentSceneName
    if (!name || hFav.busy) return
    var isFav = root.favorites.indexOf(name) >= 0
    hFav.run("fav", ["favorites", isFav ? "remove" : "add", "--name", name])
    hFav.onOk = function (op, d) { root.favorites = d.names || [] }
    hFav.onFailed = function (op, d) { root.say("could not update favorites", true) }
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
  function boundsForIndex(index, instance) {
    for (var i = 0; i < root.devices.length; i++) {
      var d = root.devices[i]
      if (d.index === index) return (d.bounds || {})[instance] || null
    }
    return null
  }

  hState.onOk = function (op, d) {
    root.states = d.devices || []
    if (hostWidget) { hostWidget.states = root.states; hostWidget.errorText = "" }
    root.localNoKey = false
    // aggregate master (sliders follow reactively via Binding, drag-guarded)
    var counted = 0, on = 0
    for (var i = 0; i < root.states.length; i++) {
      var s = root.states[i]
      if (s.virtual || (s.kind !== "rich" && s.kind !== "scenic")) continue
      counted++
      if (s.online === false) continue
      if (s.props && s.props.powerSwitch === 1) on++
    }
    root.masterOn = counted > 0 && on === counted
    root.clearSay()
  }
  hState.onFailed = function (op, d) {
    root.states = []
    var msg = String(d && d.message ? d.message : "state refresh failed")
    if (d && d.error === "no_key") root.localNoKey = true
    if (hostWidget) { hostWidget.states = []; hostWidget.errorText = msg }
    root.say(msg, true)
  }
  hOnboard.onOk = function (op, d) {
    root.localNoKey = false
    if (hostWidget) { hostWidget.errorText = ""; hostWidget.refresh() }
    root.loadEverything()
  }
  hOnboard.onFailed = function (op, d) {
    var msg = String(d && d.message ? d.message : "key rejected")
    if (d && d.error === "no_key") root.localNoKey = true
    root.say(msg, true)
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
  PopupCard {
    id: card
    anchorItem: root.anchorItem
    contentWidth: card.fittedContentWidth(Style.space(400))
    contentHeight: card.fittedContentHeight(col.implicitHeight + Style.space(14))

    Column {
      id: col
      anchors.fill: parent
      anchors.margins: card.padding
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
            if (root.busy) { checked = !checked; return }
            root.enqueue(["set", "--master", "--value", checked ? "1" : "0", "--confirm-physical"])
          }
        }
      }

      // status banner
      Text {
        width: parent.width
        text: root.statusText
        color: root.statusBad ? Color.urgent : Color.accent
        visible: root.statusText !== ""
        font.pixelSize: Style.font.body
        wrapMode: Text.Wrap
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
          visible: modelData.kind === "rich" || modelData.kind === "scenic"
                   || modelData.kind === "simple"
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
                var r3 = root.rowForIndex(modelData.index)
                return r3 && r3.props ? r3.props.powerSwitch === 1 : false
              }
              onToggled: {
                if (root.busy) { checked = !checked; return }
                root.enqueue(["set", "--device-index", String(modelData.index),
                              "--instance", "powerSwitch",
                              "--value", checked ? "1" : "0", "--confirm-physical"])
              }
            }
          }

          // rich controls
          Column {
            width: parent.width
            leftPadding: Style.space(16)
            spacing: Style.space(4)
            visible: modelData.kind === "rich"

            Column {
              width: parent.width
              spacing: 2
              readonly property var row: root.rowForIndex(modelData.index)
              readonly property var b: root.boundsForIndex(modelData.index, "brightness")
              readonly property bool showable: row && row.props
                                               && row.props.brightness !== undefined
              visible: showable
              Text {
                text: {
                  var r = root.rowForIndex(modelData.index)
                  return "Brightness" + (r && r.props && r.props.brightness !== undefined
                                         ? " · " + r.props.brightness : "")
                }
                color: Color.popups.text; opacity: 0.7; font.pixelSize: Style.font.body
              }
              PanelSlider {
                id: briSlider
                width: parent.width
                minimum: (parent.b && parent.b[0]) || 1
                maximum: (parent.b && parent.b[1]) || 100
                step: 1
                integer: true
                value: 50
                onReleased: function (v) {
                  if (root.busy) return
                  root.enqueue(["set", "--device-index", String(modelData.index),
                                "--instance", "brightness",
                                "--value", String(Math.round(v)), "--confirm-physical"])
                }
              }
              // remote -> slider, but never while the user is dragging (B6)
              Binding {
                target: briSlider
                property: "value"
                when: !briSlider.dragging
                value: {
                  var r = root.rowForIndex(modelData.index)
                  return (r && r.props && r.props.brightness !== undefined)
                         ? r.props.brightness : briSlider.value
                }
              }
            }

            Column {
              width: parent.width
              spacing: 2
              readonly property var row: root.rowForIndex(modelData.index)
              readonly property var b: root.boundsForIndex(modelData.index, "colorTemperatureK")
              readonly property bool showable: row && row.props
                                               && row.props.colorTemperatureK !== undefined
              visible: showable
              Text {
                text: {
                  var r = root.rowForIndex(modelData.index)
                  return "Color temp" + (r && r.props && r.props.colorTemperatureK !== undefined
                                         ? " · " + r.props.colorTemperatureK + "K" : "")
                }
                color: Color.popups.text; opacity: 0.7; font.pixelSize: Style.font.body
              }
              PanelSlider {
                id: tmpSlider
                width: parent.width
                minimum: (parent.b && parent.b[0]) || 2000
                maximum: (parent.b && parent.b[1]) || 9000
                step: 100
                integer: true
                value: 4000
                onReleased: function (v) {
                  if (root.busy) return
                  root.enqueue(["set", "--device-index", String(modelData.index),
                                "--instance", "colorTemperatureK",
                                "--value", String(Math.round(v)), "--confirm-physical"])
                }
              }
              Binding {
                target: tmpSlider
                property: "value"
                when: !tmpSlider.dragging
                value: {
                  var r = root.rowForIndex(modelData.index)
                  return (r && r.props && r.props.colorTemperatureK !== undefined)
                         ? r.props.colorTemperatureK : tmpSlider.value
                }
              }
            }

            Row {
              spacing: Style.space(6)
              readonly property var row: root.rowForIndex(modelData.index)
              readonly property bool showable: row && row.props
                                               && row.props.colorRgb !== undefined
              visible: showable
              property var swatches: [0xE5484D, 0xF76B15, 0xF5D90A, 0x46A758, 0x12A594, 0x8E4EC6]
              Repeater {
                model: parent.swatches
                delegate: Rectangle {
                  required property int modelData
                  width: Style.space(20); height: Style.space(20)
                  radius: width / 2
                  color: M.colorFromRgbInt(modelData)
                  border.color: Color.popups.border
                  border.width: 1
                  MouseArea {
                    anchors.fill: parent
                    onClicked: {
                      if (root.busy) return
                      var hex = "#" + ("000000" + modelData.toString(16)).slice(-6)
                      root.enqueue(["set", "--device-index", String(modelData.index),
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
