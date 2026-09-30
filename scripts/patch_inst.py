import sys
p = "Panel.qml"
s = open(p).read()

old_bri = """                value: 50
                onReleased: function (v) {
                  var want = Math.round(v)
                  var r = root.rowForIndex(modelData.index)
                  var cur = (r && r.props && r.props.brightness !== undefined)
                            ? r.props.brightness : -1
                  if (cur >= 0 && want === cur) return     // no-op guard"""
new_bri = """                value: 50
                Component.onCompleted: console.log("omagovee-dbg: bri bounds idx=" + modelData.index
                                                  + " min=" + minimum + " max=" + maximum)
                onReleased: function (v) {
                  var want = Math.round(v)
                  var r = root.rowForIndex(modelData.index)
                  var cur = (r && r.props && r.props.brightness !== undefined)
                            ? r.props.brightness : -1
                  console.log("omagovee-dbg: bri release idx=" + modelData.index
                              + " v=" + v + " want=" + want + " cur=" + cur)
                  if (cur >= 0 && want === cur) return     // no-op guard"""
assert old_bri in s, "bri anchor missing"
s = s.replace(old_bri, new_bri, 1)

old_tmp = """                value: 4000
                onReleased: function (v) {
                  var want = Math.round(v)
                  var r = root.rowForIndex(modelData.index)
                  var cur = (r && r.props && r.props.colorTemperatureK !== undefined)
                            ? r.props.colorTemperatureK : -1
                  if (cur >= 0 && Math.abs(want - cur) < 50) return  // no-op guard"""
new_tmp = """                value: 4000
                Component.onCompleted: console.log("omagovee-dbg: tmp bounds idx=" + modelData.index
                                                  + " min=" + minimum + " max=" + maximum)
                onReleased: function (v) {
                  var want = Math.round(v)
                  var r = root.rowForIndex(modelData.index)
                  var cur = (r && r.props && r.props.colorTemperatureK !== undefined)
                            ? r.props.colorTemperatureK : -1
                  console.log("omagovee-dbg: tmp release idx=" + modelData.index
                              + " v=" + v + " want=" + want + " cur=" + cur)
                  if (cur >= 0 && Math.abs(want - cur) < 50) return  // no-op guard"""
assert old_tmp in s, "tmp anchor missing"
s = s.replace(old_tmp, new_tmp, 1)

open(p, "w").write(s)
print("ok", s.count("bri release"), s.count("tmp release"))
