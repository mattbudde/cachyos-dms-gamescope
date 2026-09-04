import QtQuick
import Quickshell
import Quickshell.Io
import qs.Common
import qs.Services
import qs.Widgets
import qs.Modules.Plugins

PluginComponent {
    id: root

    layerNamespacePlugin: "cachyos-game-mode"

    property string statusText: "Checking session status..."
    property bool actionRunning: false
    property string gamescopeOutput: "auto"
    property var monitors: []

    readonly property var monitorChoices: {
        const choices = [{ connector: "auto", label: "Auto", detail: "Gamescope default" }]
        const thisScreen = root.parentScreen ? root.parentScreen.name : ""
        for (const monitor of root.monitors) {
            const detail = [monitor.label]
            if (!monitor.present)
                detail.push("not connected")
            else if (!monitor.enabled)
                detail.push("off on desktop")
            if (monitor.connector === thisScreen)
                detail.push("(this screen)")
            choices.push({
                connector: monitor.connector,
                label: monitor.connector,
                detail: detail.join(" · ")
            })
        }
        return choices
    }

    function refreshStatus() {
        if (!statusProcess.running)
            statusProcess.running = true
    }

    function chooseGamescopeOutput(connector) {
        if (displayProcess.running)
            return
        actionRunning = true
        displayProcess.command = ["cachyos-sessionctl", "display", "set", "gamescope", connector]
        displayProcess.running = true
    }

    function rememberSession(target) {
        if (setProcess.running)
            return
        actionRunning = true
        setProcess.target = target
        setProcess.command = ["cachyos-sessionctl", "set", target]
        setProcess.running = true
    }

    function enterGameMode() {
        closePopout()
        Quickshell.execDetached([
            "cachyos-sessionctl",
            "switch",
            "gamescope",
            "--confirm"
        ])
    }

    Process {
        id: statusProcess
        command: ["cachyos-sessionctl", "status", "--json"]

        stdout: StdioCollector {
            onStreamFinished: {
                const output = text.trim()
                if (!output)
                    return
                try {
                    const report = JSON.parse(output)
                    root.statusText = "Active: " + report.active + "; next/remembered: " + report.remembered
                    root.gamescopeOutput = report.display.gamescope_output || "auto"
                    root.monitors = report.display.monitors || []
                } catch (error) {
                    root.statusText = output
                }
            }
        }

        stderr: StdioCollector {
            onStreamFinished: {
                const output = text.trim()
                if (output)
                    root.statusText = output
            }
        }

        onExited: exitCode => {
            if (exitCode !== 0 && root.statusText === "Checking session status...")
                root.statusText = "Unable to read session status"
        }
    }

    Process {
        id: setProcess

        property string target: ""

        stdout: StdioCollector {
            onStreamFinished: {
                const output = text.trim()
                if (output)
                    ToastService.showInfo("CachyOS Game Mode", output)
            }
        }

        stderr: StdioCollector {
            onStreamFinished: {
                const output = text.trim()
                if (output)
                    ToastService.showError("CachyOS Game Mode", output)
            }
        }

        onExited: exitCode => {
            root.actionRunning = false
            if (exitCode === 0)
                root.refreshStatus()
        }
    }

    Process {
        id: displayProcess

        stdout: StdioCollector {
            onStreamFinished: {
                const output = text.trim()
                if (output)
                    ToastService.showInfo("CachyOS Game Mode", output)
            }
        }

        stderr: StdioCollector {
            onStreamFinished: {
                const output = text.trim()
                if (output)
                    ToastService.showError("CachyOS Game Mode", output)
            }
        }

        onExited: exitCode => {
            root.actionRunning = false
            root.refreshStatus()
        }
    }

    Component.onCompleted: refreshStatus()

    horizontalBarPill: Component {
        Row {
            spacing: Theme.spacingXS

            DankIcon {
                anchors.verticalCenter: parent.verticalCenter
                name: "sports_esports"
                size: root.iconSize
                color: Theme.primary
            }

            StyledText {
                anchors.verticalCenter: parent.verticalCenter
                text: "Game Mode"
                color: Theme.surfaceText
                font.pixelSize: Theme.fontSizeMedium
            }
        }
    }

    verticalBarPill: Component {
        DankIcon {
            name: "sports_esports"
            size: root.iconSize
            color: Theme.primary
        }
    }

    popoutWidth: 380
    popoutHeight: 360 + Math.ceil(monitorChoices.length / 2) * (56 + Theme.spacingS)

    popoutContent: Component {
        PopoutComponent {
            id: popup

            headerText: "CachyOS Game Mode"
            detailsText: "Switch sessions or choose which one DMS remembers."
            showCloseButton: true

            function onOpened() {
                root.refreshStatus()
            }

            Column {
                width: parent.width
                spacing: Theme.spacingM

                StyledRect {
                    width: parent.width
                    height: statusLabel.implicitHeight + Theme.spacingM * 2
                    radius: Theme.cornerRadius
                    color: Theme.surfaceContainerHigh

                    Row {
                        anchors.fill: parent
                        anchors.margins: Theme.spacingM
                        spacing: Theme.spacingS

                        DankIcon {
                            anchors.verticalCenter: parent.verticalCenter
                            name: "info"
                            size: Theme.iconSize - 4
                            color: Theme.primary
                        }

                        StyledText {
                            id: statusLabel
                            anchors.verticalCenter: parent.verticalCenter
                            width: parent.width - Theme.iconSize - Theme.spacingS
                            text: root.statusText
                            color: Theme.surfaceText
                            font.pixelSize: Theme.fontSizeSmall
                            wrapMode: Text.WordWrap
                        }
                    }
                }

                StyledRect {
                    width: parent.width
                    height: 52
                    radius: Theme.cornerRadius
                    color: enterMouse.containsMouse ? Theme.primaryContainer : Theme.primary

                    Row {
                        anchors.centerIn: parent
                        spacing: Theme.spacingS

                        DankIcon {
                            anchors.verticalCenter: parent.verticalCenter
                            name: "sports_esports"
                            size: Theme.iconSize
                            color: enterMouse.containsMouse ? Theme.onPrimaryContainer : Theme.onPrimary
                        }

                        StyledText {
                            anchors.verticalCenter: parent.verticalCenter
                            text: "Enter Game Mode"
                            color: enterMouse.containsMouse ? Theme.onPrimaryContainer : Theme.onPrimary
                            font.pixelSize: Theme.fontSizeMedium
                            font.weight: Font.Bold
                        }
                    }

                    MouseArea {
                        id: enterMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.enterGameMode()
                    }
                }

                StyledText {
                    text: "Remember for next login"
                    color: Theme.surfaceVariantText
                    font.pixelSize: Theme.fontSizeSmall
                    font.weight: Font.Medium
                }

                Row {
                    width: parent.width
                    spacing: Theme.spacingS

                    Repeater {
                        model: [
                            {
                                label: "Desktop",
                                icon: "desktop_windows",
                                target: "desktop"
                            },
                            {
                                label: "Game Mode",
                                icon: "sports_esports",
                                target: "gamescope"
                            }
                        ]

                        StyledRect {
                            required property var modelData

                            width: (parent.width - Theme.spacingS) / 2
                            height: 48
                            radius: Theme.cornerRadius
                            color: rememberMouse.containsMouse
                                ? Theme.surfaceContainerHighest
                                : Theme.surfaceContainerHigh
                            opacity: root.actionRunning ? 0.6 : 1

                            Row {
                                anchors.centerIn: parent
                                spacing: Theme.spacingXS

                                DankIcon {
                                    anchors.verticalCenter: parent.verticalCenter
                                    name: modelData.icon
                                    size: Theme.iconSize - 4
                                    color: Theme.primary
                                }

                                StyledText {
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: modelData.label
                                    color: Theme.surfaceText
                                    font.pixelSize: Theme.fontSizeSmall
                                }
                            }

                            MouseArea {
                                id: rememberMouse
                                anchors.fill: parent
                                enabled: !root.actionRunning
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: root.rememberSession(modelData.target)
                            }
                        }
                    }
                }

                StyledText {
                    text: "Game Mode monitor"
                    color: Theme.surfaceVariantText
                    font.pixelSize: Theme.fontSizeSmall
                    font.weight: Font.Medium
                }

                Flow {
                    width: parent.width
                    spacing: Theme.spacingS

                    Repeater {
                        model: root.monitorChoices

                        StyledRect {
                            required property var modelData

                            readonly property bool selected: modelData.connector === root.gamescopeOutput

                            width: (parent.width - Theme.spacingS) / 2
                            height: 56
                            radius: Theme.cornerRadius
                            color: selected
                                ? Theme.primaryContainer
                                : (monitorMouse.containsMouse
                                    ? Theme.surfaceContainerHighest
                                    : Theme.surfaceContainerHigh)
                            opacity: root.actionRunning ? 0.6 : 1

                            Row {
                                anchors.fill: parent
                                anchors.margins: Theme.spacingS
                                spacing: Theme.spacingXS

                                DankIcon {
                                    anchors.verticalCenter: parent.verticalCenter
                                    name: modelData.connector === "auto" ? "auto_awesome" : "monitor"
                                    size: Theme.iconSize - 4
                                    color: selected ? Theme.onPrimaryContainer : Theme.primary
                                }

                                Column {
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: parent.width - Theme.iconSize - Theme.spacingXS

                                    StyledText {
                                        width: parent.width
                                        text: modelData.label
                                        color: selected ? Theme.onPrimaryContainer : Theme.surfaceText
                                        font.pixelSize: Theme.fontSizeSmall
                                        font.weight: selected ? Font.Bold : Font.Normal
                                        elide: Text.ElideRight
                                    }

                                    StyledText {
                                        width: parent.width
                                        visible: text.length > 0
                                        text: modelData.detail
                                        color: selected ? Theme.onPrimaryContainer : Theme.surfaceVariantText
                                        font.pixelSize: Theme.fontSizeSmall - 2
                                        elide: Text.ElideRight
                                    }
                                }
                            }

                            MouseArea {
                                id: monitorMouse
                                anchors.fill: parent
                                enabled: !root.actionRunning
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: root.chooseGamescopeOutput(modelData.connector)
                            }
                        }
                    }
                }
            }
        }
    }
}
