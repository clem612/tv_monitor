import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: window
    visible: true
    width: 600
    height: 800
    title: "Clem Router Monitor"
    color: themeMode === "System" ? "#0a0a0a" : "#000000"

    property real uiScale: 1.0
    property string themeMode: "System"
    property var historyModel: []
    property var deviceList: []
    
    property string globalUp: "0 B/s"
    property string globalDown: "0 B/s"
    property string histUp: "0 B"
    property string histDown: "0 B"

    Component.onCompleted: {
        uiScale = parseFloat(con.get_setting("uiScale"))
        themeMode = con.get_setting("themeMode")
        con.get_device_list()
    }

    Connections {
        target: con
        function onDeviceListReady(list) { deviceList = list }
        function onGlobalTotalsReady(up, down) { 
            globalUp = up
            globalDown = down 
        }
        function onHistoryDataReady(data, up, down) { 
            historyModel = data
            histUp = up
            histDown = down
        }
    }

    // FIX: Settings Drawer redesign to prevent empty space and clipping
    Drawer {
        id: settingsDrawer
        width: Math.min(window.width * 0.8, 400 * uiScale)
        height: window.height
        background: Rectangle { color: "#111"; border.color: "#333" }
        
        Flickable {
            anchors.fill: parent
            contentHeight: settingsCol.height + 100
            clip: true
            
            Column {
                id: settingsCol
                width: parent.width
                padding: 30 * uiScale
                spacing: 25 * uiScale

                Text { text: "RADAR SETTINGS"; color: "#00FF41"; font.bold: true; font.pixelSize: 20 * uiScale }
                
                Rectangle { width: parent.width - 60 * uiScale; height: 1; color: "#222" }

                Column {
                    width: parent.width - 60 * uiScale
                    spacing: 10 * uiScale
                    Text { text: "INTERFACE SCALING (" + uiScale.toFixed(1) + "x)"; color: "white"; font.pixelSize: 12 * uiScale }
                    Slider {
                        width: parent.width
                        from: 0.5; to: 2.0; value: uiScale
                        onMoved: { uiScale = value; con.save_setting("uiScale", value.toString()) }
                    }
                }

                Column {
                    width: parent.width - 60 * uiScale
                    spacing: 10 * uiScale
                    Text { text: "UI THEME"; color: "white"; font.pixelSize: 12 * uiScale }
                    ComboBox {
                        width: parent.width
                        model: ["System", "True Black"]
                        currentIndex: themeMode === "System" ? 0 : 1
                        onActivated: { themeMode = currentText; con.save_setting("themeMode", currentText) }
                    }
                }

                Button {
                    text: "Clear History Data"
                    width: parent.width - 60 * uiScale
                    onClicked: con.clear_database()
                }

                Button {
                    text: "Reset Radar"
                    width: parent.width - 60 * uiScale
                    onClicked: {
                        uiScale = 1.0
                        themeMode = "System"
                        con.save_setting("uiScale", "1.0")
                        con.save_setting("themeMode", "System")
                    }
                }
            }
        }
    }

    Dialog {
        id: renameDialog
        title: "Rename Device"
        x: (window.width - width) / 2
        y: (window.height - height) / 2
        modal: true; focus: true
        property string targetIp: ""
        background: Rectangle { color: "#111"; border.color: "#333"; radius: 10 }
        ColumnLayout {
            anchors.fill: parent; anchors.margins: 20; spacing: 15
            Text { text: "IP: " + renameDialog.targetIp; color: "#666"; font.pixelSize: 10 }
            TextField { id: nameInput; placeholderText: "New Name..."; Layout.fillWidth: true; color: "white" }
            RowLayout { 
                Layout.alignment: Qt.AlignRight
                Button { text: "Cancel"; onClicked: renameDialog.close() }
                Button { text: "Save"; highlighted: true; onClicked: { con.set_nickname(renameDialog.targetIp, nameInput.text); nameInput.text = ""; renameDialog.close(); con.fetch_history(timeFilter.currentText, modeFilter.currentText, deviceFilter.currentValue) } } 
            }
        }
    }

    header: ColumnLayout {
        spacing: 0
        ToolBar {
            Layout.fillWidth: true; background: Rectangle { color: "#000" }
            RowLayout {
                anchors.fill: parent; anchors.margins: 10 * uiScale
                Text { text: "ROUTER RADAR"; color: "#00FF41"; font.bold: true; font.pixelSize: 14 * uiScale; font.letterSpacing: 2; Layout.fillWidth: true }
                ToolButton { 
                    onClicked: settingsDrawer.open()
                    contentItem: Text { text: "⚙"; font.pixelSize: 24 * uiScale; color: "white"; horizontalAlignment: Text.AlignHCenter }
                }
            }
        }
        TabBar {
            id: tabBar; Layout.fillWidth: true; background: Rectangle { color: "#111" }
            TabButton { text: "SPEED"; contentItem: Text { text: parent.text; color: parent.checked ? "#00FF41" : "gray"; font.bold: true; horizontalAlignment: Text.AlignHCenter; font.pixelSize: 9 * uiScale }}
            TabButton { text: "HISTORY"; contentItem: Text { text: parent.text; color: parent.checked ? "#00FF41" : "gray"; font.bold: true; horizontalAlignment: Text.AlignHCenter; font.pixelSize: 9 * uiScale }}
        }
    }

    StackLayout {
        anchors.fill: parent
        currentIndex: tabBar.currentIndex

        // SPEED TAB
        ColumnLayout {
            Rectangle {
                Layout.fillWidth: true; Layout.preferredHeight: 100 * uiScale; color: "#050505"
                ColumnLayout {
                    anchors.centerIn: parent
                    Text { text: "TOTAL THROUGHPUT"; color: "#666"; font.pixelSize: 9 * uiScale; font.italic: true; Layout.alignment: Qt.AlignHCenter }
                    Text { text: "↑ " + globalUp + "  ↓ " + globalDown; color: "white"; font.pixelSize: 22 * uiScale; font.bold: true }
                }
            }
            Rectangle { Layout.fillWidth: true; Layout.fillHeight: true; color: "black" }
        }

        // HISTORY TAB
        ColumnLayout {
            spacing: 0
            
            // FIX: Unified container for filters and sum to prevent overlapping
            Column {
                Layout.fillWidth: true
                spacing: 0
                
                Rectangle {
                    width: parent.width; height: 80 * uiScale; color: "#111"
                    Row {
                        anchors.centerIn: parent; spacing: 5 * uiScale
                        ComboBox { id: timeFilter; width: 110 * uiScale; model: ["Last Hour", "Last Day", "Last Month", "Lifetime"]; onActivated: con.fetch_history(timeFilter.currentText, modeFilter.currentText, deviceFilter.currentValue) }
                        ComboBox { id: modeFilter; width: 130 * uiScale; model: ["Group by Date", "Group by Device"]; onActivated: con.fetch_history(timeFilter.currentText, modeFilter.currentText, deviceFilter.currentValue) }
                        ComboBox { 
                            id: deviceFilter; width: 130 * uiScale; model: deviceList; textRole: "name"; valueRole: "ip"
                            onActivated: con.fetch_history(timeFilter.currentText, modeFilter.currentText, currentValue)
                        }
                    }
                }

                Rectangle {
                    width: parent.width; height: 50 * uiScale; color: "#050505"
                    Text { anchors.centerIn: parent; text: "FILTERED SUM: ↑ " + histUp + "  ↓ " + histDown; color: "#00FF41"; font.pixelSize: 11 * uiScale; font.bold: true }
                }
            }

            ListView {
                id: hList; Layout.fillWidth: true; Layout.fillHeight: true; model: historyModel; spacing: 8 * uiScale; anchors.margins: 10 * uiScale; clip: true
                Component.onCompleted: con.fetch_history("Lifetime", "Group by Date", "all")
                
                delegate: Column {
                    width: hList.width; spacing: 2 * uiScale
                    property bool isExpanded: false

                    // FOLDER HEADER
                    Rectangle {
                        width: parent.width; height: 50 * uiScale; color: "#1a1a1a"; radius: 4
                        RowLayout {
                            anchors.fill: parent; anchors.margins: 15
                            Text { text: (isExpanded ? "▼ " : "▶ ") + modelData.header; color: "white"; font.bold: true; Layout.fillWidth: true; font.pixelSize: 12 * uiScale }
                            Text { text: modelData.total; color: "#666"; font.pixelSize: 10 * uiScale }
                            ToolButton { 
                                visible: modeFilter.currentText === "Group by Device" && modelData.ip !== "none"
                                contentItem: Text { text: "✎"; color: "#444"; font.pixelSize: 16 * uiScale }
                                onClicked: { renameDialog.targetIp = modelData.ip; renameDialog.open() }
                            }
                        }
                        MouseArea { anchors.fill: parent; onClicked: isExpanded = !isExpanded }
                    }

                    // FOLDER CONTENT
                    Column {
                        width: parent.width; visible: isExpanded; spacing: 1
                        Repeater {
                            model: modelData.items
                            Rectangle {
                                width: parent.width; height: 45 * uiScale; color: "#0d0d0d"
                                RowLayout {
                                    anchors.fill: parent; anchors.margins: 15
                                    Column {
                                        Layout.fillWidth: true
                                        Text { text: "• " + modelData.label; color: "#aaa"; font.pixelSize: 11 * uiScale }
                                        Text { text: "  " + modelData.ip; color: "#444"; font.pixelSize: 8 * uiScale; visible: modeFilter.currentText === "Group by Date" }
                                    }
                                    Text { text: modelData.val; color: "#00FF41"; font.pixelSize: 10 * uiScale }
                                    ToolButton { 
                                        visible: modeFilter.currentText === "Group by Date"
                                        contentItem: Text { text: "✎"; color: "#333"; font.pixelSize: 14 * uiScale }
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
