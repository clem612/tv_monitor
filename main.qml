import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: window
    visible: true; width: 600; height: 800
    minimumWidth: 400; minimumHeight: 500
    title: "Clem Router Monitor"
    
    color: themeMode === "System" ? sysPal.window : "#000000"

    property real uiScale: 1.0
    property string themeMode: "System"
    property var historyModel: []
    property var deviceList: []
    property var expandedStates: ({})
    property string globalUp: "0 B/s"; property string globalDown: "0 B/s"
    property string histUp: "0 B"; property string histDown: "0 B"
    property bool isSyncing: false

    property var sysPal: ({ "window": "#111", "text": "#eee", "highlight": "#00FF41", "base": "#1a1a1a", "mid": "#333" })

    Component.onCompleted: {
        uiScale = parseFloat(con.get_setting("uiScale"))
        themeMode = con.get_setting("themeMode")
        var colors = con.get_theme_colors()
        sysPal = colors
        con.get_device_list()
        con.set_active_filters(timeFilter.currentText, modeFilter.currentText, deviceFilter.currentValue)
    }

    Connections {
        target: con
        function onDeviceListReady(list) { deviceList = list }
        function onGlobalTotalsReady(up, down) { globalUp = up; globalDown = down }
        function onHistoryDataReady(data, up, down) { 
            // STEADY-SCROLL LOGIC: 
            // 1. If the user is currently scrolling (flicking) or moving the list, 
            //    we ignore the update so the list doesn't jump under their finger.
            if (hList.flicking || hList.moving) return;

            // 2. We capture the current scroll position (contentY)
            var savedY = hList.contentY
            
            historyModel = data
            histUp = up; histDown = down
            isSyncing = false 

            // 3. We force the list back to the saved position after the data loads
            hList.contentY = savedY
        }
    }

    Dialog {
        id: renameDialog
        title: "Rename Device"
        x: (window.width - width) / 2; y: (window.height - height) / 2
        modal: true; focus: true
        property string targetIp: ""
        background: Rectangle { color: sysPal.window; border.color: sysPal.mid; radius: 10 }
        ColumnLayout {
            anchors.fill: parent; anchors.margins: 20; spacing: 15
            Text { text: "IP: " + renameDialog.targetIp; color: sysPal.text; opacity: 0.5; font.pixelSize: 10 }
            TextField { id: nameInput; placeholderText: "New Name..."; Layout.fillWidth: true; color: sysPal.text }
            RowLayout { 
                Layout.alignment: Qt.AlignRight
                Button { text: "Cancel"; onClicked: renameDialog.close() }
                Button { text: "Save"; highlighted: true; onClicked: { con.set_nickname(renameDialog.targetIp, nameInput.text); nameInput.text = ""; renameDialog.close(); con.set_active_filters(timeFilter.currentText, modeFilter.currentText, deviceFilter.currentValue) } } 
            }
        }
    }

    Drawer {
        id: settingsDrawer; width: Math.min(window.width * 0.8, 400 * uiScale); height: window.height
        background: Rectangle { color: sysPal.window; border.color: sysPal.mid }
        Flickable {
            anchors.fill: parent; contentHeight: settingsCol.height + 100; clip: true
            Column {
                id: settingsCol; width: parent.width; padding: 30 * uiScale; spacing: 25 * uiScale
                Text { text: "RADAR SETTINGS"; color: sysPal.highlight; font.bold: true; font.pixelSize: 20 * uiScale }
                Column {
                    width: parent.width - 60 * uiScale; spacing: 10 * uiScale
                    Text { text: "UI THEME"; color: sysPal.text; font.pixelSize: 12 * uiScale }
                    ComboBox {
                        width: parent.width; model: ["System", "True Black"]
                        currentIndex: themeMode === "System" ? 0 : 1
                        onActivated: { themeMode = currentText; con.save_setting("themeMode", currentText) }
                    }
                }
                Button { text: "Clear History Data"; width: parent.width - 60 * uiScale; onClicked: con.clear_database() }
            }
        }
    }

    header: ColumnLayout {
        spacing: 0
        ToolBar {
            Layout.fillWidth: true; background: Rectangle { color: themeMode === "System" ? sysPal.base : "#000" }
            RowLayout {
                anchors.fill: parent; anchors.margins: 10 * uiScale
                Text { text: "ROUTER RADAR"; color: sysPal.highlight; font.bold: true; font.pixelSize: 14 * uiScale; Layout.fillWidth: true }
                ToolButton { onClicked: settingsDrawer.open(); contentItem: Text { text: "⚙"; font.pixelSize: 24 * uiScale; color: sysPal.text } }
            }
        }
        TabBar {
            id: tabBar; Layout.fillWidth: true; background: Rectangle { color: sysPal.base }
            TabButton { text: "SPEED" }
            TabButton { text: "HISTORY" }
        }
    }

    StackLayout {
        anchors.fill: parent; currentIndex: tabBar.currentIndex
        ColumnLayout {
            Rectangle {
                Layout.fillWidth: true; Layout.preferredHeight: 150 * uiScale; color: sysPal.window
                ColumnLayout {
                    anchors.centerIn: parent
                    Text { text: "TOTAL THROUGHPUT"; color: sysPal.text; opacity: 0.5; font.pixelSize: 9 * uiScale; Layout.alignment: Qt.AlignHCenter }
                    Text { text: "↑ " + globalUp + "  ↓ " + globalDown; color: sysPal.highlight; font.pixelSize: 26 * uiScale; font.bold: true }
                }
            }
            Rectangle { Layout.fillWidth: true; Layout.fillHeight: true; color: themeMode === "System" ? sysPal.base : "black" }
        }
        ColumnLayout {
            spacing: 0
            Column {
                Layout.fillWidth: true; spacing: 0
                Rectangle {
                    width: parent.width; height: 80 * uiScale; color: sysPal.base
                    Row {
                        anchors.centerIn: parent; spacing: 10 * uiScale
                        ComboBox { id: timeFilter; width: 120 * uiScale; model: ["Last Hour", "Today", "This Month", "Lifetime"]; onActivated: { isSyncing = true; con.set_active_filters(currentText, modeFilter.currentText, deviceFilter.currentValue) } }
                        ComboBox { id: modeFilter; width: 140 * uiScale; model: ["Group by Date", "Group by Device"]; onActivated: { isSyncing = true; con.set_active_filters(timeFilter.currentText, currentText, deviceFilter.currentValue) } }
                        ComboBox { id: deviceFilter; width: 140 * uiScale; model: deviceList; textRole: "name"; valueRole: "ip"; onActivated: { isSyncing = true; con.set_active_filters(timeFilter.currentText, modeFilter.currentText, currentValue) } }
                    }
                }
                Rectangle {
                    width: parent.width; height: 50 * uiScale; color: sysPal.window
                    Text { anchors.centerIn: parent; text: isSyncing ? "SYNCING..." : "FILTERED SUM: ↑ " + histUp + "  ↓ " + histDown; color: sysPal.highlight; font.pixelSize: 11 * uiScale; font.bold: true }
                }
            }
            ListView {
                id: hList; Layout.fillWidth: true; Layout.fillHeight: true; model: isSyncing ? 0 : historyModel; spacing: 8 * uiScale; anchors.margins: 10 * uiScale; clip: true; opacity: isSyncing ? 0.3 : 1.0
                
                // IMPORTANT: Tells the view how to behave when the model changes
                // This helps prevent aggressive jumps.
                add: Transition { NumberAnimation { properties: "opacity"; from: 0; to: 1; duration: 200 } }
                displaced: Transition { NumberAnimation { properties: "y"; duration: 200 } }

                delegate: Column {
                    width: hList.width; spacing: 2 * uiScale
                    property bool isExpanded: window.expandedStates[modelData.header] || false
                    Rectangle {
                        width: parent.width; height: 55 * uiScale; color: sysPal.base; radius: 4; border.color: sysPal.mid; border.width: 1
                        RowLayout {
                            anchors.fill: parent; anchors.margins: 15
                            Text { text: (isExpanded ? "▼ " : "▶ ") + modelData.header; color: sysPal.text; font.bold: true; Layout.fillWidth: true; font.pixelSize: 12 * uiScale }
                            Text { text: modelData.total; color: sysPal.text; opacity: 0.6; font.pixelSize: 10 * uiScale }
                            ToolButton { 
                                visible: modeFilter.currentText === "Group by Device" && modelData.ip !== "none"
                                contentItem: Text { text: "✎"; color: sysPal.text; opacity: 0.4; font.pixelSize: 16 * uiScale }
                                onClicked: { renameDialog.targetIp = modelData.ip; renameDialog.open() }
                            }
                        }
                        MouseArea { anchors.fill: parent; onClicked: { isExpanded = !isExpanded; window.expandedStates[modelData.header] = isExpanded; } }
                    }
                    Column {
                        width: parent.width; visible: isExpanded; spacing: 1
                        Repeater {
                            model: modelData.items
                            Rectangle {
                                width: parent.width; height: 45 * uiScale; color: sysPal.window; opacity: 0.8
                                RowLayout {
                                    anchors.fill: parent; anchors.margins: 15
                                    Column {
                                        Layout.fillWidth: true
                                        Text { text: "• " + modelData.label; color: sysPal.text; font.pixelSize: 11 * uiScale }
                                        Text { text: "  " + modelData.ip; color: sysPal.text; opacity: 0.3; font.pixelSize: 8 * uiScale; visible: modeFilter.currentText === "Group by Date" }
                                    }
                                    Text { text: modelData.val; color: sysPal.highlight; font.pixelSize: 10 * uiScale }
                                    ToolButton { 
                                        visible: modeFilter.currentText === "Group by Date"
                                        contentItem: Text { text: "✎"; color: sysPal.text; opacity: 0.3; font.pixelSize: 14 * uiScale }
                                        onClicked: { renameDialog.targetIp = modelData.ip; renameDialog.open() }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
