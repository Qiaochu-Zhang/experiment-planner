"""Offline, clickable help for labels, controls and table headers."""
from html import escape
from importlib.resources import files
from weakref import ref

from PySide6.QtCore import QEvent, QObject, QRect, Qt, QTimer, QUrl
from PySide6.QtGui import QCursor, QDesktopServices, QTextCursor
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QListWidget, QPushButton, QTextBrowser, QVBoxLayout
from shiboken6 import isValid


TOPICS = {
    "overview": ("使用说明", "先创建或打开项目；录入实验后设置目标和分母策略，再推荐下一批。"),
    "precision": ("推荐工艺精度 digits", "起点为 0 时，digits=0 表示整数，1 表示一位小数；步长决定间隔，起点决定网格对齐。"),
    "priors": ("先验关系", "为某个输入和基础响应指定已有经验，选择关系、系数、强度并填写来源。"),
    "objectives": ("实验优化目标", "从当前模板的响应和指标中选择一个或多个目标，设置尽量大、尽量小或接近指定值。"),
    "exploration_strength": ("探索强度", "0 保留常规贝叶斯优化评分；越大，对可行且不确定的候选增加的评分越多。"),
    "exploration_count": ("专门探索名额", "从扣除复测后的新条件名额中预留探索点；例如总数 6、无复测、探索 2，另 4 个按常规评分选择。"),
    "ratio_policy": ("比值分母策略", "分母接近零时可限制有效区域、使用稳定化比值或移除比值目标。"),
    "epsilon_nm": ("分母阈值", "分母稳定化或有效区域的正阈值；根据当前模型的单位与测量误差设置，不是探索比例。"),
    "model": ("数值模型", "可选高斯过程 RBF、Matérn 2.5 或贝叶斯线性；单调和弱影响先验仅在线性模型中支持。"),
    "n": ("本轮实验总数", "本轮最多生成的实验记录数，包括新条件、复测和交叉布局。"),
    "mode": ("条件变化模式", "全范围不限制变化项数；单/双变量相对基准；交叉布局生成指定的单 A、单 B、AB 组合。"),
    "baseline": ("基准实验", "单变量、双变量或冻结部分参数时，用所选实验的实际条件作基准。"),
    "variables": ("允许变化的参数", "选中的参数可以变化，其余保持基准值；全不选表示不限制参数名单。"),
    "repeat_ids": ("复测实验", "再次执行所选已完成或部分结果实验的条件，新建记录，保留原实验及不同测量结果。"),
    "pool_size": ("候选池大小", "在合法、未重复的条件中最多保留多少个候选供评分，默认 128；不是实际实验数。"),
    "seed": ("随机种子", "相同数据、设置和计算环境下用于复现候选与抽样，不是工艺参数。"),
    "uncertainty": ("测量不确定度", "填写 ± 值时选择标准不确定度、均值标准误、区间或误差界限；未知不确定度不等于零。"),
    "template": ("可视化模板编辑", "常用设置使用专用表单；其他属性可在树形编辑器逐项增删、修改，无需手写 JSON。"),
    "duplicates": ("同条件重复实验", "允许相同工艺条件对应不同结果；每次真实实验使用独立编号，导入时使用不同 external_id。"),
    "delete_records": ("删除实验记录", "支持鼠标单选或多选，确认后移出当前训练、推荐和导出；删除前数据保留在审计中。"),
    "favorites": ("自定义常用功能", "勾选要显示在常用工作台的功能，设置会保存在当前电脑。"),
    "prediction": ("预测与趋势图", "模型给出潜在响应分布；区间不包含未知的未来量测噪声，原始比值只报告样本分位数。"),
    "fields": ("输入参数与字段名称", "输入参数是实验前可以设定的条件；名称、类型、单位和取值范围由当前模板配置。"),
    "measurements": ("原始测量", "保存实际测量值及不确定度；可选择哪些数值或是否型测量作为模型响应。"),
    "derived_metrics": ("派生指标与公式", "通过已有字段的内部名称编写公式，计算得到新的指标；公式引用、单位和依赖关系会校验。"),
    "import": ("导入与结束标记", "按模板输入顺序，前 30% 向上取整的输入全空时停止；该行及之后的行不导入。"),

}


def help_path():
    return files("experiment_planner").joinpath("resources/help/使用说明.md")


class HelpDialog(QDialog):
    def __init__(self, key="overview", parent=None):
        super().__init__(parent)
        self.setWindowTitle("变量与操作详细说明（离线）")
        self.resize(1040, 730)
        layout = QVBoxLayout(self)
        row = QHBoxLayout(); layout.addLayout(row)
        self.topics = QListWidget(); self.topics.setMaximumWidth(235)
        self.browser = QTextBrowser(); self.browser.setOpenExternalLinks(False)
        self.browser.setMarkdown(help_path().read_text(encoding="utf-8"))
        row.addWidget(self.topics); row.addWidget(self.browser, 1)
        for title, _ in TOPICS.values(): self.topics.addItem(title)
        self.topics.currentRowChanged.connect(self.navigate)
        open_file = QPushButton("打开具体说明文件")
        open_file.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(help_path()))))
        layout.addWidget(open_file)
        self.topics.setCurrentRow(list(TOPICS).index(key) if key in TOPICS else list(TOPICS).index("fields"))

    def navigate(self, row):
        if row < 0: return
        title = list(TOPICS.values())[row][0]
        block = self.browser.document().begin()
        while block.isValid():
            if block.text().strip() == title:
                self.browser.setTextCursor(QTextCursor(block))
                self.browser.ensureCursorVisible()
                return
            block = block.next()


def show_help(key="overview", parent=None):
    dialog = HelpDialog(key, parent)
    dialog.exec()


class HelpPopup(QFrame):
    def __init__(self, key, parent=None, description=None, *, source=None, source_rect=None):
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setStyleSheet("QFrame {background:white;border:1px solid #b9c8dc;border-radius:7px;} QLabel {border:none;padding:6px;}")
        title, brief = TOPICS.get(key, (key, description or TOPICS["fields"][1]))
        layout = QVBoxLayout(self)
        label = QLabel(f"<b>{escape(title)}</b><br>{escape(description or brief)}<br><a style='color:#1565c0' href='details'>详细说明 →</a>")
        label.setWordWrap(True); label.setMaximumWidth(360)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        label.linkActivated.connect(lambda _: (self.hide(), show_help(key if key in TOPICS else "fields", parent)))
        layout.addWidget(label)
        self.source = ref(source) if source is not None else lambda: None
        self.source_rect = source_rect
        self.timer = QTimer(self); self.timer.setInterval(1000); self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.expire)
        # Tracking also detects moving between columns of the same header viewport.
        self.tracker = QTimer(self); self.tracker.setInterval(50)
        self.tracker.timeout.connect(self.check_cursor)

    def cursor_inside(self):
        position = QCursor.pos()
        source = self.source()
        over_source = source is not None and isValid(source) and source.isVisible() and (self.source_rect or source.rect()).contains(source.mapFromGlobal(position))
        return over_source or self.rect().contains(self.mapFromGlobal(position))

    def check_cursor(self):
        if not self.isVisible(): return
        source = self.source()
        if source is None or not isValid(source) or not source.isVisible():
            self.hide()
        elif self.cursor_inside():
            self.timer.stop()
        elif not self.timer.isActive():
            self.timer.start()

    def expire(self):
        if not self.cursor_inside(): self.hide()

    def showEvent(self, event):
        super().showEvent(event)
        self.tracker.start()
        self.check_cursor()

    def hideEvent(self, event):
        self.timer.stop(); self.tracker.stop()
        super().hideEvent(event)

    def enterEvent(self, event):
        self.timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.check_cursor()
        super().leaveEvent(event)


class HelpFilter(QObject):
    def __init__(self, parent):
        super().__init__(parent)
        self.popup = None

    def eventFilter(self, watched, event):
        if self.popup and event.type() in (QEvent.Type.Enter, QEvent.Type.Leave):
            self.popup.check_cursor()
        if event.type() == QEvent.Type.ToolTip:
            key = watched.property("helpKey")
            source_rect = None
            if not key and hasattr(watched.parent(), "logicalIndexAt"):
                header = watched.parent()
                index = header.logicalIndexAt(event.pos())
                table = header.parent()
                item = table.horizontalHeaderItem(index) if hasattr(table, "horizontalHeaderItem") and index >= 0 else None
                if item:
                    key = item.data(Qt.ItemDataRole.UserRole)
                    source_rect = QRect(header.sectionViewportPosition(index), 0, header.sectionSize(index), watched.height())
            if key:
                if self.popup: self.popup.close(); self.popup.deleteLater()
                self.popup = HelpPopup(key, watched.window(), watched.property("helpDescription"), source=watched, source_rect=source_rect)
                self.popup.adjustSize()
                position = event.globalPos()
                screen = watched.screen().availableGeometry()
                position.setX(min(position.x(), screen.right() - self.popup.width()))
                position.setY(min(position.y() + 16, screen.bottom() - self.popup.height()))
                self.popup.move(position); self.popup.show()
                return True
        return super().eventFilter(watched, event)


def attach_help(widget, key, description=None):
    widget.setProperty("helpKey", key)
    if description: widget.setProperty("helpDescription", description)
    widget.setToolTip(TOPICS.get(key, (key, description or "查看详细说明"))[1])
    handler = HelpFilter(widget)
    widget.installEventFilter(handler)
    widget._help_handler = handler
    return widget


def help_label(text, key, description=None):
    label = QLabel(text)
    attach_help(label, key, description)
    return label
