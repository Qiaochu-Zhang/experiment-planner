"""M0 minimal desktop prototype. Production form suite awaits Windows validation."""
import json
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QFileDialog, QMessageBox, QTabWidget, QTableWidget, QTableWidgetItem,
    QComboBox, QSpinBox, QLineEdit, QFormLayout, QDialog, QDialogButtonBox,
    QScrollArea, QAbstractItemView, QPlainTextEdit)

from experiment_planner.application.service import PlannerService
from experiment_planner.domain.template import Template
from experiment_planner.domain.errors import ValidationError
from experiment_planner.io.exchange import preview_import, export_records
from experiment_planner.storage.project import Project
from experiment_planner.precision.rounding import display


def button(text, callback, layout):
    result = QPushButton(text)
    result.clicked.connect(callback)
    layout.addWidget(result)
    return result


class RecordDialog(QDialog):
    def __init__(self, template, record=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("录入 / 更正实验")
        self.resize(860,700)
        self.inputs, self.cells = {}, {}
        self.record = record or {}
        outer = QVBoxLayout(self)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        content = QWidget(); form = QFormLayout(content)
        scroll.setWidget(content); outer.addWidget(scroll)
        for f in template.parameters:
            name = f["name"]
            value = self.record.get("actual", {}).get(name, f.get("fixed_value", ""))
            editor = QLineEdit(str(value)); editor.setObjectName(name)
            if "bounds" in f: editor.setPlaceholderText(f"{f['bounds'][0]} – {f['bounds'][1]}")
            note = QLineEdit(self.record.get("field_notes",{}).get(name,"")); note.setPlaceholderText("参数备注")
            row = QHBoxLayout(); row.addWidget(editor); row.addWidget(note)
            form.addRow(f"{f['label']} ({f.get('unit','1')})", row)
            self.inputs[name] = editor, note
        form.addRow(QLabel("原始测量：留空表示未测；± 值必须选择含义"))
        for f in template.measurements:
            name=f["name"]; cell=self.record.get("observations",{}).get(name,{})
            value=QLineEdit("" if cell.get("value") is None else str(cell["value"]))
            value.setObjectName(name)
            uncertainty=cell.get("uncertainty") or {}
            amount=QLineEdit("" if uncertainty.get("amount") is None else str(uncertainty["amount"]))
            amount.setPlaceholderText("± 值")
            kind=QComboBox()
            for label,code in (("含义未指定","unspecified"),("标准不确定度 1σ","std"),("均值标准误 SEM","sem"),("确定误差界限","bounds")):
                kind.addItem(label,code)
            if kind.findData(uncertainty.get("kind","unspecified"))<0:
                kind.addItem("保留已保存的区间/非对称设置",uncertainty["kind"])
            kind.setCurrentIndex(max(0,kind.findData(uncertainty.get("kind","unspecified"))))
            note=QLineEdit(cell.get("note",""));note.setPlaceholderText("测量备注")
            row=QHBoxLayout()
            for widget in (value,amount,kind,note): row.addWidget(widget)
            form.addRow(f"{f['label']} ({f.get('unit','1')})",row)
            self.cells[name]=value,amount,kind,note,uncertainty
        self.status=QComboBox()
        for label,code in (("完成","completed"),("部分结果","partial"),("进行中","running"),("失败","failed"),("取消","cancelled")):
            self.status.addItem(label,code)
        self.status.setCurrentIndex(max(0,self.status.findData(self.record.get("status","completed"))))
        self.note=QLineEdit(self.record.get("note",""))
        form.addRow("实验状态",self.status);form.addRow("整组备注",self.note)
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);outer.addWidget(buttons)

    def values(self):
        measurements={}
        for name,(value,amount,kind,note,original) in self.cells.items():
            uncertainty={**original,"kind":kind.currentData(),"amount":float(amount.text()) if amount.text().strip() else None}
            measurements[name]={"value":value.text(),"uncertainty":uncertainty,"note":note.text()}
        return {"conditions":{n:editor.text() for n,(editor,_) in self.inputs.items()},"observations":measurements,"status":self.status.currentData(),"note":self.note.text(),"field_notes":{n:note.text() for n,(_,note) in self.inputs.items()}}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        from experiment_planner.ui.theme import apply_light_theme
        apply_light_theme()
        from experiment_planner.ui.fonts import load_local_font
        load_local_font()
        self.service=None; self.task=None
        self.setWindowTitle("实验规划助手 · 开发原型 0.1")
        self.resize(1280,820)
        root=QWidget();self.setCentralWidget(root);layout=QVBoxLayout(root)
        toolbar=QHBoxLayout();layout.addLayout(toolbar)
        for label,callback in (("新建项目",self.create_project),("打开项目",self.open_project),("关闭项目",self.close_project),("导入 CSV / Excel",self.import_data),("导出记录",self.export_data),("一致性备份",self.backup),("模板导出",self.export_template),("从模板新建",self.create_from_template)):
            button(label,lambda checked=False, f=callback:self.guard(f),toolbar)
        self.summary=QLabel("请选择或新建本地项目。当前为模拟验证原型，Windows 与正式离线发布尚未验收。")
        self.summary.setWordWrap(True);layout.addWidget(self.summary)
        self.tabs=QTabWidget();layout.addWidget(self.tabs)
        records=QWidget();record_layout=QVBoxLayout(records);actions=QHBoxLayout();record_layout.addLayout(actions)
        button("录入实验",lambda:self.guard(self.add_record),actions)
        button("更正选中实验 / 回填",lambda:self.guard(self.edit_record),actions)
        self.table=QTableWidget();self.table.setSelectionBehavior(QAbstractItemView.SelectRows);self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        record_layout.addWidget(self.table);self.tabs.addTab(records,"实验记录")
        next_page=QWidget();form=QFormLayout(next_page)
        self.ratio=QComboBox()
        for label,code in (("需要设置分母策略","require_configuration"),("有效区域内原始比值","valid_region"),("稳定化比值（不同于原始比值）","stabilized"),("移除比值目标","remove")): self.ratio.addItem(label,code)
        self.epsilon=QLineEdit();self.epsilon.setPlaceholderText("按量测口径填写正数，单位 nm")
        form.addRow("比值目标",self.ratio);form.addRow("epsilon (nm)",self.epsilon)
        save_ratio=QPushButton("保存目标策略版本");save_ratio.clicked.connect(lambda:self.guard(self.save_ratio));form.addRow(save_ratio)
        self.model=QComboBox()
        for label,code in (("默认 GP / RBF","gp_rbf_v1"),("GP / Matérn 2.5","gp_matern25_v1"),("贝叶斯线性回归（非 GP）","bayesian_linear_v1")): self.model.addItem(label,code)
        self.n=QSpinBox();self.n.setRange(1,100);self.n.setValue(6)
        self.mode=QComboBox()
        for label,code in (("全范围探索","full_space"),("相对基准恰好改变一项","single"),("相对基准最多改变两项","double")): self.mode.addItem(label,code)
        self.baseline=QComboBox()
        self.variables=QLineEdit();self.variables.setPlaceholderText("可选：内部字段名，逗号分隔；留空自动选择")
        self.repeats=QLineEdit();self.repeats.setPlaceholderText("可选：实验编号，逗号分隔；全部计入本轮 n")
        for label,widget in (("数值模型",self.model),("本轮新增总数 n",self.n),("变化模式",self.mode),("基准实验",self.baseline),("允许变化的字段",self.variables),("复测实验编号",self.repeats)):form.addRow(label,widget)
        self.generate_button=QPushButton("计算并保存下一批实验")
        self.generate_button.clicked.connect(lambda:self.guard(self.generate));form.addRow(self.generate_button)
        self.cancel_button=QPushButton("取消计算");self.cancel_button.clicked.connect(self.cancel);form.addRow(self.cancel_button)
        self.details=QPlainTextEdit();self.details.setReadOnly(True);form.addRow("批次说明与预测",self.details)
        self.tabs.addTab(next_page,"下一批实验")
        self.timer=QTimer(self);self.timer.setInterval(200);self.timer.timeout.connect(self.poll)
        self.setStyleSheet("QMainWindow {background:#f4f7fa;} QPushButton {padding:7px 10px;} QTabWidget::pane {border:1px solid #d9e1e8;} QLineEdit,QComboBox,QSpinBox {padding:5px;} QTableWidget {background:white;}")

    def guard(self, callback):
        try: callback()
        except Exception as exc: QMessageBox.warning(self,"操作未完成",str(exc))

    def require_project(self):
        if self.service is None: raise ValidationError("请先打开或新建项目")
        return self.service.project

    def set_project(self,project):
        self.close_project();self.service=PlannerService(project);self.refresh()

    def create_project(self,template=None):
        path,_=QFileDialog.getSaveFileName(self,"新建项目数据库","project.sqlite","项目 (*.sqlite)")
        if path:self.set_project(Project.create(path,Path(path).stem,template))

    def create_from_template(self):
        path,_=QFileDialog.getOpenFileName(self,"选择 schema v2 模板","","JSON (*.json)")
        if path:self.create_project(Template.read(path))

    def open_project(self):
        path,_=QFileDialog.getOpenFileName(self,"打开项目或备份","","项目 (*.sqlite)")
        if path:self.set_project(Project(path))

    def close_project(self):
        self.cancel()
        if self.service:self.service.project.close();self.service=None
        self.table.clear();self.table.setRowCount(0);self.baseline.clear();self.details.clear()
        self.summary.setText("项目已关闭；可新建或打开本地项目。")

    def refresh(self):
        p=self.require_project();records=p.experiments();fields=p.template.parameters+p.template.metrics
        headers=["编号","状态",*[f"{f['label']} ({f.get('unit','1')})" for f in fields],"备注"]
        self.table.setColumnCount(len(headers));self.table.setHorizontalHeaderLabels(headers);self.table.setRowCount(len(records))
        status_names={"completed":"完成","partial":"部分结果","failed":"失败","cancelled":"取消","pending":"待做","running":"进行中"}
        self.baseline.clear();self.baseline.addItem("不指定",None)
        for i,e in enumerate(records):
            cells=[e["id"],status_names[e["status"]]]
            for f in fields:
                value=e["actual"].get(f["name"],e["derived"].get(f["name"],{}).get("value"))
                cells.append(display(value,f.get("display_digits")))
            cells.append(e["note"])
            for j,value in enumerate(cells):
                item=QTableWidgetItem(str(value));item.setToolTip(str(value));self.table.setItem(i,j,item)
            self.baseline.addItem(f"实验 {e['id']} · {status_names[e['status']]}",e["id"])
        self.table.resizeColumnsToContents()
        for column in range(self.table.columnCount()):
            self.table.setColumnWidth(column,min(165,self.table.columnWidth(column)))
        policy=p.template.data.get("ratio_policy",{})
        self.ratio.setCurrentIndex(max(0,self.ratio.findData(policy.get("mode"))))
        self.epsilon.setText("" if policy.get("epsilon_nm") is None else str(policy["epsilon_nm"]))
        pending=sum(e["status"] in ("pending","running") for e in records)
        self.summary.setText(f"{p.name} | 数据版本 {p.revision} | 模板版本 {p.template.data['template_version']} | 实验 {len(records)} 条 | 待做/进行中 {pending} 条\n{p.path}")
        batches=p.batches()
        if batches:self.details.setPlainText(json.dumps({k:v for k,v in batches[-1].items() if k!="ax_snapshot"},ensure_ascii=False,indent=2))

    def add_record(self):
        p=self.require_project();dialog=RecordDialog(p.template,parent=self)
        if dialog.exec():self.service.add_record(**dialog.values());self.refresh()

    def edit_record(self):
        p=self.require_project();row=self.table.currentRow()
        if row<0:raise ValidationError("请先选择实验行")
        eid=int(self.table.item(row,0).text());dialog=RecordDialog(p.template,p.experiment(eid),self)
        if dialog.exec():self.service.revise_record(eid,**dialog.values());self.refresh()

    def save_ratio(self):
        p=self.require_project();mode=self.ratio.currentData()
        epsilon=float(self.epsilon.text()) if mode in ("valid_region","stabilized") else None
        self.service.update_template(p.template.revised(ratio_policy={**p.template.data["ratio_policy"],"mode":mode,"epsilon_nm":epsilon}));self.refresh()

    def import_data(self):
        self.require_project();path,_=QFileDialog.getOpenFileName(self,"选择历史记录","","表格 (*.csv *.xlsx)")
        if not path:return
        preview=preview_import(self.service,path)
        if preview.errors:raise ValidationError("\n".join(f"第 {e['row']} 行：{e['message']}" for e in preview.errors[:20]))
        dialog=QDialog(self);dialog.setWindowTitle("导入预览 · 确认后写入");dialog.resize(900,600);layout=QVBoxLayout(dialog)
        content=QPlainTextEdit();content.setReadOnly(True);content.setPlainText(json.dumps(preview.records,ensure_ascii=False,indent=2));layout.addWidget(content)
        actions=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel);actions.accepted.connect(dialog.accept);actions.rejected.connect(dialog.reject);layout.addWidget(actions)
        if dialog.exec():preview.commit(self.service);self.refresh()

    def export_data(self):
        p=self.require_project();path,_=QFileDialog.getSaveFileName(self,"导出完整精度记录","experiments.xlsx","Excel (*.xlsx);;CSV (*.csv);;完整项目快照 (*.json)")
        if path:export_records(p,path)

    def backup(self):
        p=self.require_project();path,_=QFileDialog.getSaveFileName(self,"一致性备份","backup.sqlite","项目 (*.sqlite)")
        if path:p.backup(path)

    def export_template(self):
        p=self.require_project();path,_=QFileDialog.getSaveFileName(self,"导出模板快照","template.json","JSON (*.json)")
        if path:p.template.write(path)

    def generate(self):
        p=self.require_project()
        from experiment_planner.engine.space import BatchRequest
        from experiment_planner.worker.process import CalculationTask
        request=BatchRequest(n=self.n.value(),mode=self.mode.currentData(),baseline_id=self.baseline.currentData(),variables=[x.strip() for x in self.variables.text().split(",") if x.strip()],repeat_ids=[int(x) for x in self.repeats.text().split(",") if x.strip()],model=self.model.currentData())
        p.template.require_ratio_configuration()
        self.task=CalculationTask(p,request);self.generate_button.setEnabled(False);self.details.setPlainText("正在本地后台计算；可取消。期间修改数据会使本次计算过期。");self.timer.start()

    def poll(self):
        if self.task is None:return
        result=self.task.poll()
        if result is None:return
        self.task=None;self.timer.stop();self.generate_button.setEnabled(True)
        def finish():
            if "error" in result:raise ValidationError(result["error"])
            self.service.commit_batch(result["result"]);self.refresh()
        self.guard(finish)

    def cancel(self):
        if self.task:self.task.cancel();self.task=None
        self.timer.stop();self.generate_button.setEnabled(True)

    def closeEvent(self,event):
        self.close_project();event.accept()
