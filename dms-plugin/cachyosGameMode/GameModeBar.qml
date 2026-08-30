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

    function refreshStatus() {
        if (!statusProcess.running)
            statusProcess.running = true
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
        command: ["cachyos-sessionctl", "status", "--compact"]

        stdout: StdioCollector {
            onStreamFinished: {
                const output = text.trim()
                if (output)
                    root.statusText = output
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
    popoutHeight: 320

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
            }
        }
    }
}
