"""Keep the light desktop interface readable under dark system themes."""
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


def apply_light_theme():
    app = QApplication.instance()
    # Fusion uses the supplied palette consistently across desktop platforms.
    app.setStyle("Fusion")
    palette = QPalette()
    role = QPalette.ColorRole
    colors = {
        role.Window: "#f4f7fa", role.WindowText: "#1f2937",
        role.Base: "#ffffff", role.AlternateBase: "#f1f5f9",
        role.Text: "#1f2937", role.PlaceholderText: "#64748b",
        role.Button: "#e9eef4", role.ButtonText: "#1f2937",
        role.ToolTipBase: "#ffffff", role.ToolTipText: "#1f2937",
        role.Highlight: "#2563eb", role.HighlightedText: "#ffffff",
        role.Link: "#1d4ed8", role.LinkVisited: "#6d28d9",
        role.Light: "#ffffff", role.Midlight: "#e2e8f0",
        role.Mid: "#94a3b8", role.Dark: "#64748b", role.Shadow: "#334155",
        role.BrightText: "#ffffff", role.Accent: "#2563eb",
    }
    for color_role, color in colors.items():
        palette.setColor(color_role, QColor(color))
    disabled = QPalette.ColorGroup.Disabled
    for color_role in (role.Text, role.WindowText, role.ButtonText, role.PlaceholderText):
        palette.setColor(disabled, color_role, QColor("#64748b"))
    for color_role in (role.Base, role.Button):
        palette.setColor(disabled, color_role, QColor("#e9eef4"))
    palette.setColor(disabled, role.Highlight, QColor("#cbd5e1"))
    palette.setColor(disabled, role.HighlightedText, QColor("#334155"))
    app.setPalette(palette)
