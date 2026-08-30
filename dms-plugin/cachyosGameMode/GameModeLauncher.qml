import QtQuick
import Quickshell
import Quickshell.Io
import qs.Services

Item {
    id: root

    property var pluginService: null
    property string trigger: ":session"
    signal itemsChanged()

    function getItems(query) {
        const items = [
            {
                name: "Enter Game Mode",
                icon: "material:sports_esports",
                comment: "End this desktop session and start Gamescope + Steam",
                action: "switch:gamescope",
                categories: ["CachyOS Game Mode"]
            },
            {
                name: "Switch to Desktop",
                icon: "material:desktop_windows",
                comment: "End Game Mode and start the configured desktop session",
                action: "switch:desktop",
                categories: ["CachyOS Game Mode"]
            },
            {
                name: "Use Game Mode on Next Login",
                icon: "material:save",
                comment: "Remember Gamescope without ending this session",
                action: "set:gamescope",
                categories: ["CachyOS Game Mode"]
            },
            {
                name: "Use Desktop on Next Login",
                icon: "material:save",
                comment: "Remember the desktop without ending this session",
                action: "set:desktop",
                categories: ["CachyOS Game Mode"]
            },
            {
                name: "Game Mode Status",
                icon: "material:info",
                comment: "Show the active and remembered sessions",
                action: "status",
                categories: ["CachyOS Game Mode"]
            }
        ]

        if (!query)
            return items
        const needle = query.toLowerCase()
        return items.filter(item => item.name.toLowerCase().includes(needle)
            || item.comment.toLowerCase().includes(needle))
    }

    function executeItem(item) {
        if (!item || !item.action)
            return

        const parts = item.action.split(":")
        const action = parts[0]
        const target = parts.length > 1 ? parts[1] : ""

        if (action === "switch") {
            Quickshell.execDetached(["cachyos-sessionctl", "switch", target, "--confirm"])
            return
        }
        if (action === "set") {
            setProcess.target = target
            setProcess.command = ["cachyos-sessionctl", "set", target]
            setProcess.running = true
            return
        }
        if (action === "status") {
            statusProcess.running = true
            return
        }
    }

    Process {
        id: setProcess
        property string target: ""
        running: false

        stdout: StdioCollector {
            onStreamFinished: {
                if (typeof ToastService !== "undefined")
                    ToastService.showInfo("CachyOS Game Mode", text.trim())
            }
        }
        stderr: StdioCollector {
            onStreamFinished: {
                if (text.trim() && typeof ToastService !== "undefined")
                    ToastService.showError("CachyOS Game Mode", text.trim())
            }
        }
    }

    Process {
        id: statusProcess
        command: ["cachyos-sessionctl", "status", "--compact"]
        running: false

        stdout: StdioCollector {
            onStreamFinished: {
                if (typeof ToastService !== "undefined")
                    ToastService.showInfo("CachyOS Game Mode", text.trim())
            }
        }
        stderr: StdioCollector {
            onStreamFinished: {
                if (text.trim() && typeof ToastService !== "undefined")
                    ToastService.showError("CachyOS Game Mode", text.trim())
            }
        }
    }
}
