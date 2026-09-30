import sys
p = "Panel.qml"
s = open(p).read()

def rep(old, new):
    global s
    assert old in s, "MISSING: " + old[:90]
    s = s.replace(old, new, 1)

# ---------------------------------------------------------------- 1. effective power helper
rep("""  function boundsForIndex(index, instance) {""",
"""  // effective power for a card: per-card desired > master desired > state truth
  function cardPowerOn(index) {
    var idx = String(index)
    if (idx in root._cardDesired) return root._cardDesired[idx]
    if (root._masterHasDesired) return root._masterDesired
    var r = root.rowForIndex(index)
    return !!(r && r.props && r.props.powerSwitch === 1)
  }

  function boundsForIndex(index, instance) {""")

# ---------------------------------------------------------------- 2. brightness group: grey when off
rep("""              readonly property var b: root.boundsForIndex(modelData.index, "brightness")
              readonly property bool showable: row && row.props
                                               && row.props.brightness !== undefined
              visible: showable
              Text {
                text: {
                  var r = root.rowForIndex(modelData.index)
                  return "Brightness" + (r && r.props && r.props.brightness !== undefined
                                         ? " · " + r.props.brightness : "")""",
"""              readonly property var b: root.boundsForIndex(modelData.index, "brightness")
              readonly property bool showable: row && row.props
                                               && row.props.brightness !== undefined
              visible: showable
              opacity: root.cardPowerOn(modelData.index) ? 1 : 0.45
              Text {
                text: {
                  var r = root.rowForIndex(modelData.index)
                  return "Brightness" + (r && r.props && r.props.brightness !== undefined
                                         ? " · " + r.props.brightness : "")""")
rep("""              PanelSlider {
                id: briSlider
                width: parent.width - parent.leftPadding - parent.rightPadding
                minimum: (parent.b && parent.b[0]) || 1""",
"""              PanelSlider {
                id: briSlider
                width: parent.width - parent.leftPadding - parent.rightPadding
                enabled: root.cardPowerOn(modelData.index)
                minimum: (parent.b && parent.b[0]) || 1""")

# ---------------------------------------------------------------- 3. temp group: grey when off
rep("""              readonly property var b: root.boundsForIndex(modelData.index, "colorTemperatureK")
              readonly property bool showable: row && row.props
                                               && row.props.colorTemperatureK !== undefined
              visible: showable""",
"""              readonly property var b: root.boundsForIndex(modelData.index, "colorTemperatureK")
              readonly property bool showable: row && row.props
                                               && row.props.colorTemperatureK !== undefined
              visible: showable
              opacity: root.cardPowerOn(modelData.index) ? 1 : 0.45""")
rep("""              PanelSlider {
                id: tmpSlider
                width: parent.width - parent.leftPadding - parent.rightPadding
                minimum: (parent.b && parent.b[0]) || 2000""",
"""              PanelSlider {
                id: tmpSlider
                width: parent.width
                enabled: root.cardPowerOn(modelData.index)
                minimum: (parent.b && parent.b[0]) || 2000""")

# ---------------------------------------------------------------- 4. swatches: highlight only when the lamp is ON
rep("""            Row {
              id: swatchRow
              spacing: Style.space(6)
              readonly property var row: root.rowForIndex(modelData.index)""",
"""            Row {
              id: swatchRow
              spacing: Style.space(6)
              readonly property int devIndex: modelData.index
              readonly property var row: root.rowForIndex(modelData.index)""")
rep("""                  color: M.colorFromRgbInt(modelData)
                  opacity: (swatchRow.row && swatchRow.row.props
                            && swatchRow.row.props.colorRgb === modelData) ? 1.0 : 0.55
                  border.color: (swatchRow.row && swatchRow.row.props
                                 && swatchRow.row.props.colorRgb === modelData)
                                ? "#ffffff" : Color.popups.border
                  border.width: (swatchRow.row && swatchRow.row.props
                                 && swatchRow.row.props.colorRgb === modelData) ? 2 : 1""",
"""                  color: M.colorFromRgbInt(modelData)
                  property bool active: root.cardPowerOn(swatchRow.devIndex)
                                        && swatchRow.row && swatchRow.row.props
                                        && swatchRow.row.props.colorRgb === modelData
                  opacity: root.cardPowerOn(swatchRow.devIndex)
                           ? (active ? 1.0 : 0.55) : 0.3
                  border.color: active ? "#ffffff" : Color.popups.border
                  border.width: active ? 2 : 1""")

open(p, "w").write(s)
print("done; braces:", s.count("{"), s.count("}"))
