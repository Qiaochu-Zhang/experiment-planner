"""Review and export each experiment's frozen last prediction and scores."""
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QPlainTextEdit, QFileDialog, QMessageBox, QDialogButtonBox, QHeaderView)

from experiment_planner.application.prediction_scoring import SCORING_FORMULAS
from experiment_planner.io.score_export import prediction_score_tables, export_prediction_scores
from experiment_planner.ui.messages import user_error
from experiment_planner.ui.tree_editor import chinese_buttons


class PredictionScoresDialog(QDialog):
    def __init__(self, report, parent=None):
        super().__init__(parent)
        self.report = report
        self.setWindowTitle("上次模型预测 / 测量回填评分"); self.resize(1180, 760)
        layout = QVBoxLayout(self)
        hint = QLabel("将测量结果当作真实结果，对上次保存的预测计算误差与区间得分，越小越好。回填不重新拟合。\n"
                      "条件或公式改变时不混算；预测时已有结果的记录会标注。每个指标一行，横向滚动查看完整内容。")
        hint.setWordWrap(True); layout.addWidget(hint)
        rows, summaries, _, _ = prediction_score_tables(report)
        self.table = QTableWidget(); self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        headers = ["实验编号", "指标名称", "上次预测中心", "中心类型", "测量对照值", "绝对误差 AE", "区间覆盖",
                   "区间宽度", "区间得分 IS95（越小越好）", "Brier 概率得分", "上次预测下限2.5%", "上次预测上限97.5%",
                   "对照类型", "状态 / 说明", "预测记录时间", "模型"]
        labels = [header.replace("上次预测中心", "上次预测\n中心").replace("测量对照值", "测量\n对照值")
                  .replace("绝对误差 AE", "绝对误差\nAE").replace("IS95（越小越好）", "IS95\n（越小越好）")
                  .replace("上次预测下限2.5%", "上次预测下限\n2.5%")
                  .replace("上次预测上限97.5%", "上次预测上限\n97.5%") for header in headers]
        self.table.setColumnCount(len(headers)); self.table.setHorizontalHeaderLabels(labels); self.table.setRowCount(len(rows))
        self.table.horizontalHeader().setMinimumHeight(50)
        for i, row in enumerate(rows):
            for j, header in enumerate(headers):
                value = row.get(header)
                text = "—" if value is None else "是" if value is True else "否" if value is False else f"{value:.6g}" if isinstance(value, float) else str(value)
                item = QTableWidgetItem(text); item.setToolTip(text); self.table.setItem(i, j, item)
        self.table.resizeColumnsToContents()
        for j in range(self.table.columnCount()):
            self.table.setColumnWidth(j, max(95, min(230, self.table.columnWidth(j))))
            self.table.horizontalHeaderItem(j).setToolTip(headers[j])
        layout.addWidget(self.table)
        self.summary = QPlainTextEdit(); self.summary.setReadOnly(True); self.summary.setMaximumHeight(140)
        lines = [f"共 {len(report['entries'])} 条实验；数据版本 {report['revision']}。按指标、单位和模型等权汇总，各类评分分别计数。"]
        def number(value): return "—" if value is None else f"{value:.6g}"
        for s in summaries:
            coverage = "—" if s["覆盖率"] is None else f"{100*s['覆盖率']:.2f}%"
            lines.append(f"{s['指标名称']} [{s['单位']}] · {s['模型'] or '旧模型'}：点误差 {s['有效点误差条数']} 条，"
                         f"MAE={number(s['MAE'])}，RMSE={number(s['RMSE'])}；区间 {s['有效区间条数']} 条，"
                         f"覆盖率={coverage}，平均 IS95={number(s['平均 IS95（越小越好）'])}；平均 Brier={number(s['平均 Brier'])}；"
                         f"预测时已有结果对照 {s['预测时已有结果的对照条数']} 条。")
        self.summary.setPlainText("\n".join(lines)); layout.addWidget(self.summary)
        actions = QHBoxLayout(); layout.addLayout(actions)
        self.export_button = QPushButton("导出上次预测与评分 Excel / CSV"); self.export_button.clicked.connect(self.export); actions.addWidget(self.export_button)
        self.formulas_button = QPushButton("查看打分公式"); self.formulas_button.clicked.connect(self.show_formulas); actions.addWidget(self.formulas_button)
        buttons = chinese_buttons(QDialogButtonBox(QDialogButtonBox.StandardButton.Close)); buttons.rejected.connect(self.reject); actions.addWidget(buttons)

    def export(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出上次预测与评分", "上次预测与评分.xlsx", "Excel (*.xlsx);;CSV (*.csv)")
        if path:
            try: export_prediction_scores(self.report, path)
            except Exception as exc: QMessageBox.warning(self, "导出未完成", user_error(exc))

    def show_formulas(self):
        dialog = QDialog(self); dialog.setWindowTitle("预测评分公式与含义"); dialog.resize(850, 600)
        layout = QVBoxLayout(dialog); text = QPlainTextEdit(); text.setReadOnly(True)
        text.setPlainText("\n\n".join(f"{label}\n{formula}" for label, formula in SCORING_FORMULAS)); layout.addWidget(text)
        buttons = chinese_buttons(QDialogButtonBox(QDialogButtonBox.StandardButton.Close)); buttons.rejected.connect(dialog.reject); layout.addWidget(buttons)
        dialog.exec()
