"""Desktop access to template revisions, restricted batches and local analysis."""
import json
from pathlib import Path

from PySide6.QtCore import QTimer, Qt, QSettings
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QWidget, QFormLayout, QVBoxLayout, QHBoxLayout, QPushButton, QCheckBox,
    QLineEdit, QPlainTextEdit, QDialog, QDialogButtonBox, QFileDialog, QLabel,
    QComboBox, QDoubleSpinBox, QSpinBox, QListWidget, QListWidgetItem, QGridLayout, QTabWidget, QScrollArea, QTableWidget, QTableWidgetItem, QMessageBox,
)

from experiment_planner.domain.errors import ValidationError
from experiment_planner.domain.template import Template
from experiment_planner.application.template_editing import blank_template
from experiment_planner.io.exchange import preview_import, export_import_template, export_analysis
from experiment_planner.ui.window import MainWindow, button
from experiment_planner.ui.template_editor import TemplateEditor
from experiment_planner.ui.conditions import ConditionsForm
from experiment_planner.ui.help import attach_help, help_label, show_help
from experiment_planner.ui.tree_editor import chinese_buttons
from experiment_planner.ui.messages import analysis_text


class PythonWindow(MainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("实验规划助手 · 0.3.0 · Python 3.12 / 3.13")
        self.loaded_template_key = None
        self.analysis_report = None
        self.summary.setText("新建或打开本地项目，录入实验后规划下一批条件。")
        self.analysis_task = None
        self.analysis_timer = QTimer(self)
        self.analysis_timer.setInterval(200)
        self.analysis_timer.timeout.connect(self.poll_analysis)

        form = self.tabs.widget(1).layout()
        self.mode.addItem("基准 / 单 A / 单 B / AB 交叉布局", "cross")
        self.exact_two = QCheckBox("双变量模式恰好改变两项")
        self.cross_fields = [QComboBox(), QComboBox()]
        self.cross_inputs = [QLineEdit(), QLineEdit()]
        cross_row = QHBoxLayout()
        for field, value in zip(self.cross_fields,self.cross_inputs):
            cross_row.addWidget(field);cross_row.addWidget(value)
            value.setPlaceholderText("新值")
        self.repeat_baseline = QCheckBox("交叉布局包含基准复测（4 组；不选为 3 组）")
        self.repeat_baseline.setChecked(True)
        form.insertRow(8, "双变量限制", self.exact_two)
        form.insertRow(9, "交叉布局的两个参数和新值", cross_row)
        form.insertRow(10, self.repeat_baseline)
        def layout_changed(_):
            cross=self.mode.currentData()=="cross"
            form.setRowVisible(cross_row,cross);form.setRowVisible(self.repeat_baseline,cross)
            form.setRowVisible(self.exact_two,self.mode.currentData()=="double")
        self.mode.currentIndexChanged.connect(layout_changed);layout_changed(0)

        self.exploration_strength = QDoubleSpinBox();self.exploration_strength.setRange(0,100);self.exploration_strength.setDecimals(2);self.exploration_strength.setSingleStep(.25)
        self.exploration_count = QSpinBox();self.exploration_count.setRange(0,100)
        self.pool_size = QSpinBox();self.pool_size.setRange(1,10000);self.pool_size.setValue(128)
        self.seed = QSpinBox();self.seed.setRange(0,2147483647)
        for key, title, widget in (("exploration_strength","探索强度",self.exploration_strength),("exploration_count","专门探索名额",self.exploration_count),("pool_size","候选池大小",self.pool_size),("seed","随机种子",self.seed)):
            form.insertRow(form.rowCount()-3,help_label(title,key),attach_help(widget,key))
        self.quota_hint=QLabel();self.quota_hint.setWordWrap(True)
        form.insertRow(form.rowCount()-3,self.quota_hint)
        for w in (self.n,self.exploration_count):w.valueChanged.connect(self.update_quota_hint)
        self.repeats.textChanged.connect(self.update_quota_hint)
        self.mode.currentIndexChanged.connect(self.update_quota_hint)
        self.repeat_baseline.toggled.connect(self.update_quota_hint)
        choose_variables=QPushButton("勾选允许变化的参数");choose_variables.clicked.connect(lambda:self.guard(self.choose_variables))
        choose_repeats=QPushButton("勾选复测实验");choose_repeats.clicked.connect(lambda:self.guard(self.choose_repeats))
        form.insertRow(form.rowCount()-3,choose_variables);form.insertRow(form.rowCount()-3,choose_repeats)
        save_defaults=QPushButton("保存为本项目的推荐默认设置");save_defaults.clicked.connect(lambda:self.guard(self.save_batch_defaults))
        form.insertRow(form.rowCount()-3,save_defaults)
        technical=QPushButton("本批次技术详情");technical.clicked.connect(lambda:self.guard(self.show_batch_details));form.addRow(technical)
        for key,w in (("n",self.n),("mode",self.mode),("baseline",self.baseline),("variables",self.variables),("repeat_ids",self.repeats),("model",self.model),("ratio_policy",self.ratio),("epsilon_nm",self.epsilon)):
            attach_help(w,key)
            label=form.labelForField(w)
            if label:attach_help(label,key)
        self.update_quota_hint()
        template_page = QWidget()
        layout = QVBoxLayout(template_page)
        label = QLabel("编辑模板的字段、公式、目标、精度、误差与先验；保存时校验并重算派生值。\n"
                       "支持空白新建、复制当前模板或修改模板文件。已有记录且结构不兼容时，可直接另存模板或用新模板创建项目。")
        label.setWordWrap(True)
        layout.addWidget(label)
        actions = QHBoxLayout()
        layout.addLayout(actions)
        button("编辑项目模板", lambda: self.guard(self.edit_template), actions)
        button("新建 / 复制 / 修改模板文件", lambda:self.guard(self.create_template),actions)
        button("模板导出",lambda:self.guard(self.export_template),actions)
        button("从模板新建项目",lambda:self.guard(self.create_from_template),actions)
        button("查看修订历史", lambda: self.guard(self.show_history), actions)
        self.template_view = QPlainTextEdit()
        self.template_view.setReadOnly(True)
        layout.addWidget(self.template_view)
        self.tabs.addTab(template_page, "项目与模板")
        utilities=QHBoxLayout();layout.addLayout(utilities)
        for text,callback in (("导入 CSV / Excel",self.import_data),("下载导入 CSV / Excel 模板",self.download_import_template),("导出实验记录",self.export_data),("一致性备份",self.backup)):
            button(text,lambda checked=False,f=callback:self.guard(f),utilities)

        analysis_page = QWidget()
        analysis_layout = QVBoxLayout(analysis_page)
        self.conditions = ConditionsForm()
        condition_scroll=QScrollArea();condition_scroll.setWidgetResizable(True);condition_scroll.setWidget(self.conditions)
        condition_scroll.setMinimumHeight(190)
        button("从选中实验复制条件", lambda: self.guard(self.copy_conditions), analysis_layout)
        analysis_layout.addWidget(condition_scroll)
        settings = QFormLayout()
        analysis_layout.addLayout(settings)
        self.plot_variables = QLineEdit()
        self.plot_variables.setPlaceholderText("使用下方按钮选择 1 或 2 项；空白表示只预测")
        self.plot_metric = QLineEdit()
        settings.addRow("趋势图变量（1 或 2 项）", self.plot_variables)
        settings.addRow("趋势图响应/指标", self.plot_metric)
        choose_plot=QPushButton("选择趋势图变量 / 指标")
        choose_plot.clicked.connect(lambda:self.guard(self.choose_plot));settings.addRow(choose_plot)
        self.analyze_button = QPushButton("按「下一批实验」所选模型预测 / 绘图")
        self.analyze_button.clicked.connect(lambda: self.guard(self.start_analysis))
        analysis_layout.addWidget(self.analyze_button)
        button("取消分析", self.cancel_analysis, analysis_layout)
        button("导出预测 / 图线 Excel 数据", lambda:self.guard(self.export_analysis_data), analysis_layout)
        self.analysis_output = QPlainTextEdit()
        self.analysis_output.setReadOnly(True)
        analysis_layout.addWidget(self.analysis_output)
        self.plot_image = QLabel()
        self.plot_image.setAlignment(Qt.AlignCenter)
        analysis_layout.addWidget(self.plot_image)
        self.tabs.addTab(analysis_page, "预测 / 趋势图")
        button("预测技术详情",lambda:self.guard(lambda:self.show_details(self.analysis_report or {})),analysis_layout)
        self.build_workspace()

    def download_import_template(self):
        template = self.require_project().template
        path, _ = QFileDialog.getSaveFileName(self, "保存当前模板的导入空表", "实验导入模板.xlsx", "Excel (*.xlsx);;CSV (*.csv)")
        if path: export_import_template(template, path)

    def export_analysis_data(self):
        self.require_project()
        if not self.analysis_report: raise ValidationError("请先完成预测或趋势图计算")
        path, _ = QFileDialog.getSaveFileName(self, "导出当前预测 / 图线数据", "预测与趋势数据.xlsx", "Excel (*.xlsx);;CSV (*.csv)")
        if path: export_analysis(self.analysis_report, self.analysis_template, path)

    def batch_request(self):
        request = super().batch_request()
        request.exact_two = self.exact_two.isChecked()
        request.repeat_baseline = self.repeat_baseline.isChecked()
        if request.mode == "cross":
            from experiment_planner.domain.template import parse_value
            template=self.require_project().template
            fields={p["name"]:p for p in template.parameters}
            names=[w.currentData() for w in self.cross_fields]
            if len(set(names))!=2:raise ValidationError("交叉布局请选择两个不同参数")
            request.cross_values={name:parse_value(w.text(),fields[name]) for name,w in zip(names,self.cross_inputs)}
        request.exploration_strength=self.exploration_strength.value()
        request.exploration_count=self.exploration_count.value()
        request.pool_size=self.pool_size.value()
        request.seed=self.seed.value()
        return request

    def refresh(self):
        selected_baseline=self.baseline.currentData()
        super().refresh()
        if hasattr(self, "template_view"):
            project=self.require_project();template=project.template
            key=(str(project.path),template.data["template_version"])
            if key!=self.loaded_template_key:
                self.conditions.set_template(template)
                metrics=template.metrics or template.responses
                if self.plot_metric.text() not in {f["name"] for f in template.fields}:
                    self.plot_metric.setText(metrics[0]["name"] if metrics else "")
                for index,box in enumerate(self.cross_fields):
                    box.clear()
                    for p in template.parameters:box.addItem(p.get("label",p["name"]),p["name"])
                    box.setCurrentIndex(min(index,box.count()-1))
                defaults=template.data.get("batch_defaults",{})
                self.n.setValue(defaults.get("total_count",6));self.exploration_strength.setValue(defaults.get("exploration_strength",0));self.exploration_count.setValue(defaults.get("exploration_count",0))
                self.pool_size.setValue(defaults.get("pool_size",128));self.seed.setValue(defaults.get("seed",0))
                self.model.setCurrentIndex(max(0,self.model.findData(template.data["optimization"].get("default_model_preset","gp_rbf_v1"))))
                self.mode.setCurrentIndex(max(0,self.mode.findData(defaults.get("search_mode","full_space"))))
                self.baseline.setCurrentIndex(max(0,self.baseline.findData(defaults.get("baseline_experiment_id"))))
                self.variables.setText(",".join(defaults.get("changed_parameter_names",[])))
                self.repeats.setText(",".join(map(str,defaults.get("repeat_ids",[]))))
                self.exact_two.setChecked(defaults.get("exact_two",False));self.repeat_baseline.setChecked(defaults.get("repeat_baseline",True))
                for index,(name,value) in enumerate(list(defaults.get("cross_values",{}).items())[:2]):
                    self.cross_fields[index].setCurrentIndex(max(0,self.cross_fields[index].findData(name)))
                    self.cross_inputs[index].setText(str(value))
                self.loaded_template_key=key
            elif selected_baseline is not None:
                self.baseline.setCurrentIndex(max(0,self.baseline.findData(selected_baseline)))
            labels={f["name"]:f.get("label",f["name"]) for f in template.fields}
            goals="\n".join(f"• {labels.get(o['metric'],o['metric'])}："+{"identity":"原值","abs":"绝对值","absolute_distance":f"距 {o.get('target',0)} 的距离"}.get(o.get("transform","identity"),"")+"，"+{"maximize":"尽量大","minimize":"尽量小"}[o["direction"]] for o in template.data["objectives"])
            self.template_view.setPlainText(f"模板：{template.data.get('name','')}\n版本：{template.data['template_version']}\n\n当前目标：\n{goals}\n\n先验关系：{len(template.data.get('knowledge_priors',[]))} 条\n\n所有设置均可通过“编辑项目模板”修改；全部属性使用树形表单。旧项目目标保留原定义。")
            if hasattr(self,"home_summary"):self.home_summary.setText(self.summary.text()+"\n\n"+goals)

    def close_project(self):
        super().close_project()
        self.loaded_template_key=None
        self.analysis_report=None
        if hasattr(self,"home_summary"):self.home_summary.setText("请新建或打开项目。")
        for name in ("template_view", "conditions", "analysis_output", "plot_image"):
            if hasattr(self, name):
                getattr(self, name).clear()

    def edit_template(self, section="precision"):
        project=self.require_project()
        dialog=TemplateEditor(project.template,self,section=section)
        while dialog.exec():
            try:self.service.update_template(dialog.result_template)
            except ValidationError as exc:
                choice=QMessageBox(self);choice.setWindowTitle("保留修改后的模板")
                choice.setText(str(exc));choice.setInformativeText("当前修改已保留，可用它直接创建独立项目或另存模板文件。原项目数据保持原来的字段含义。")
                new_project=choice.addButton("用此模板新建项目",QMessageBox.ButtonRole.AcceptRole)
                save_file=choice.addButton("另存模板文件",QMessageBox.ButtonRole.ActionRole)
                choice.addButton("返回继续编辑",QMessageBox.ButtonRole.RejectRole)
                choice.exec()
                if choice.clickedButton()==new_project:
                    self.create_project(dialog.result_template)
                    if self.service.project is not project:return
                elif choice.clickedButton()==save_file:
                    path,_=QFileDialog.getSaveFileName(self,"另存修改后的模板","修改后的模板.json","模板 (*.json)")
                    if path:dialog.result_template.write(path);return
                continue
            self.refresh();break

    def show_history(self):
        self.template_view.setPlainText(json.dumps(self.require_project().history(), ensure_ascii=False, indent=2))

    def copy_conditions(self):
        project = self.require_project()
        row = self.table.currentRow()
        if row < 0:
            raise ValidationError("请先在实验记录页选择一行")
        eid = int(self.table.item(row, 0).text())
        self.conditions.setPlainText(json.dumps(project.experiment(eid)["actual"], ensure_ascii=False, indent=2))

    def start_analysis(self):
        from experiment_planner.worker.process import CalculationTask
        project = self.require_project()
        condition = project.template.validate_conditions(self.conditions.values())
        request = {"conditions": [condition], "model": self.model.currentData(), "seed": self.seed.value()}
        variables = [v.strip() for v in self.plot_variables.text().split(",") if v.strip()]
        if variables:
            from experiment_planner.plots.trends import slice_conditions
            slice_conditions(project.template, condition, variables, points=15)
            path, _ = QFileDialog.getSaveFileName(self, "保存趋势图", "trend.png", "PNG (*.png)")
            if not path:
                return
            request.update(plot_path=path, variables=variables, metric=self.plot_metric.text().strip())
        self.analysis_template = project.template
        self.analysis_report = None
        self.analysis_task = CalculationTask(project, request, operation="analyze")
        self.analyze_button.setEnabled(False)
        self.analysis_output.setPlainText("正在本地拟合与预测；区间表示潜在响应，不包含未知的未来量测误差。")
        self.plot_image.clear()
        self.analysis_timer.start()

    def poll_analysis(self):
        if self.analysis_task is None:
            return
        result = self.analysis_task.poll()
        if result is None:
            return
        self.analysis_task = None
        self.analysis_timer.stop()
        self.analyze_button.setEnabled(True)
        if "error" in result:
            self.analysis_output.setPlainText(result["error"])
            return
        report = result["result"]
        self.analysis_report=report
        message = analysis_text(report,self.analysis_template)
        if report["revision"] != self.require_project().revision:
            message = "项目已更改：以下分析属于旧数据版本，请重新计算。\n" + message
        self.analysis_output.setPlainText(message)
        if report.get("plot_path"):
            pixmap = QPixmap(report["plot_path"])
            self.plot_image.setPixmap(pixmap.scaled(720, 350, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def cancel_analysis(self):
        if getattr(self, "analysis_task", None):
            self.analysis_task.cancel()
            self.analysis_task = None
        if hasattr(self, "analysis_timer"):
            self.analysis_timer.stop()
            self.analyze_button.setEnabled(True)

    def cancel(self):
        self.cancel_analysis()
        super().cancel()

    def import_data(self):
        from experiment_planner.io.exchange import read_headers
        project=self.require_project()
        path,_=QFileDialog.getOpenFileName(self,"选择历史实验记录","","表格 (*.csv *.xlsx)")
        if not path:return
        headers=read_headers(path)
        dialog=QDialog(self);dialog.setWindowTitle("导入列对应关系与预览");dialog.resize(1050,750)
        layout=QVBoxLayout(dialog)
        hint=QLabel("表头一致时保留自动识别；复测使用独立外部编号。按模板输入顺序，前 30%（向上取整）全空的行视为结束，该行及后续行不导入。")
        hint.setWordWrap(True);layout.addWidget(hint)
        mapping_table=QTableWidget(len(headers),2);mapping_table.setHorizontalHeaderLabels(["文件中的列名","对应的程序字段"]);layout.addWidget(mapping_table)
        choices=[("自动识别",None),("外部实验编号","external_id"),("实验状态","status"),("整组备注","note")]
        for f in project.template.parameters+project.template.measurements:
            choices.append((f.get("label",f["name"]),f["name"]))
            for suffix,label in (("_uncertainty","误差大小"),("_uncertainty_kind","误差类型"),("_distribution","误差分布"),("_note","备注"),("_unit","单位"),("_confidence","置信水平"),("_coverage_factor","覆盖因子")):
                choices.append((f.get("label",f["name"])+" · "+label,f["name"]+suffix))
        editors=[]
        for i,header in enumerate(headers):
            item=QTableWidgetItem(str(header));item.setFlags(item.flags()&~Qt.ItemFlag.ItemIsEditable);mapping_table.setItem(i,0,item)
            box=QComboBox()
            for label,value in choices:box.addItem(label,value)
            mapping_table.setCellWidget(i,1,box);editors.append(box)
        mapping_table.resizeColumnsToContents()
        output=QPlainTextEdit();output.setReadOnly(True);layout.addWidget(output)
        buttons=chinese_buttons(QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel))
        buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(False);layout.addWidget(buttons)
        preview=None
        def refresh_preview():
            nonlocal preview
            preview=None;buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(False)
            mapping={h:w.currentData() for h,w in zip(headers,editors) if w.currentData()}
            preview=preview_import(self.service,path,mapping)
            if preview.errors:output.setPlainText("\n".join(f"第 {e['row']} 行：{e['message']}" for e in preview.errors))
            else:
                labels={f["name"]:f.get("label",f["name"]) for f in project.template.fields}
                lines=[f"校验通过：{len(preview.records)} 条待导入记录（提交时按外部编号 / 内容去重）。"]
                for i,record in enumerate(preview.records,1):
                    lines.append(f"\n第 {i} 条，外部编号：{record.get('external_id') or '未填'}")
                    lines.append("，".join(f"{labels.get(k,k)}={v}" for k,v in record["conditions"].items()))
                    lines.append("，".join(f"{labels.get(k,k)}={v.get('value')}" for k,v in record["observations"].items()))
                output.setPlainText("\n".join(lines))
            if preview.stop_message:output.appendPlainText("\n"+preview.stop_message)
            buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(not preview.errors)
        def commit():
            if preview is None:raise ValidationError("请先校验并预览")
            ids=preview.commit(self.service);self.refresh();dialog.accept()
            QMessageBox.information(self,"导入完成",f"新增 {len(ids)} 条实验；相同编号的相同记录已跳过。")
        for w in editors:w.currentIndexChanged.connect(lambda _:buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(False))
        button("校验并预览",lambda:self.guard(refresh_preview),layout)
        buttons.accepted.connect(lambda:self.guard(commit));buttons.rejected.connect(dialog.reject)
        self.guard(refresh_preview);dialog.exec()

    def build_workspace(self):
        self.navigation=QTabWidget()
        self.centralWidget().layout().replaceWidget(self.tabs,self.navigation)
        home=QWidget();layout=QVBoxLayout(home)
        title=QLabel("常用工作台");title.setStyleSheet("font-size:23px;font-weight:600;padding:8px 0;");layout.addWidget(title)
        self.home_summary=QLabel("新建或打开项目后，可在这里完成记录、设置和推荐。");self.home_summary.setWordWrap(True);layout.addWidget(self.home_summary)
        bar=QHBoxLayout();layout.addLayout(bar)
        button("自定义常用功能",self.customize_favorites,bar)
        button("变量与操作详细说明",lambda:show_help("overview",self),bar)
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        from experiment_planner.ui.help import help_path
        button("打开说明文件",lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(help_path()))),bar)
        self.favorite_grid=QGridLayout();layout.addLayout(self.favorite_grid);layout.addStretch()
        self.actions={
            "precision":("推荐工艺精度",lambda:self.edit_template("precision"),"设置整数、小数位数与设备步长"),
            "priors":("先验关系定义",lambda:self.edit_template("priors"),"选择输入和响应，填写关系与来源"),
            "objectives":("实验优化目标",lambda:self.edit_template("objectives"),"选择单目标、多目标和分母策略"),
            "recommend":("推荐下一批实验",lambda:self.go_to(1),"设置探索强度、专门探索名额及复测"),
            "record":("录入实验 / 复测结果",self.add_record,"允许相同条件保存不同测量结果"),
            "records":("查看与回填实验",lambda:self.go_to(0),"查看历史、选择待做记录回填"),
            "prediction":("预测与趋势图",lambda:self.go_to(3),"通过参数表单输入条件并预测"),
            "import":("导入 CSV / Excel",self.import_data,"匹配列、校验预览后保存"),
            "import_template":("下载导入 CSV / Excel 模板",self.download_import_template,"按当前实验模板生成空白导入表"),
            "export":("导出实验记录",self.export_data,"导出完整精度数据"),
            "template":("新建 / 复制 / 修改模板",self.create_template,"从空白、当前模板或本地文件开始"),
            "backup":("备份项目",self.backup,"备份完整数据库和历史"),
        }
        self.preferences=QSettings("ExperimentPlanner","Desktop")
        stored=self.preferences.value("favorites",["precision","priors","objectives","recommend","record","records","import","import_template","prediction"])
        self.favorite_ids=stored if isinstance(stored,list) else [stored]
        self.favorite_ids=list(dict.fromkeys(["precision","priors","objectives",*[k for k in self.favorite_ids if k in self.actions]]))
        # Upgrade existing preferences once; later user removal remains respected.
        if not self.preferences.value("import_favorite_initialized",False,type=bool):
            if "import" not in self.favorite_ids:self.favorite_ids.append("import")
            self.preferences.setValue("favorites",self.favorite_ids)
            self.preferences.setValue("import_favorite_initialized",True)
            self.preferences.sync()
        self.render_favorites()
        self.navigation.addTab(home,"常用功能");self.navigation.addTab(self.tabs,"更多功能")
        self.navigation.setCurrentIndex(0)
        self.setStyleSheet(self.styleSheet()+" QTabBar::tab {padding:10px 18px;} QGroupBox {font-weight:bold;} QPushButton {min-height:24px;} QHeaderView::section {background:#e9eef7;padding:7px;border:1px solid #d4deed;}")
        # Keep long recommendation forms usable on smaller screens.
        for i in (1,2):
            page=self.tabs.widget(i);title=self.tabs.tabText(i)
            self.tabs.removeTab(i);scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(page);self.tabs.insertTab(i,scroll,title)

    def render_favorites(self):
        while self.favorite_grid.count():
            item=self.favorite_grid.takeAt(0)
            if item.widget():item.widget().deleteLater()
        for i,key in enumerate(self.favorite_ids):
            title,callback,brief=self.actions[key]
            b=QPushButton(title+"\n"+brief);b.setMinimumHeight(92)
            b.setStyleSheet("text-align:left;padding:16px;background:white;border:1px solid #d7e2ee;border-radius:9px;font-size:14px;")
            b.clicked.connect(lambda checked=False,f=callback:self.guard(f))
            attach_help(b,key if key in ("precision","priors","objectives","prediction","template","import","import_template") else "overview")
            self.favorite_grid.addWidget(b,i//3,i%3)

    def customize_favorites(self):
        dialog=QDialog(self);dialog.setWindowTitle("自定义常用功能");layout=QVBoxLayout(dialog)
        layout.addWidget(QLabel("精度、先验和目标固定保留；其余可自由勾选。"));choices=QListWidget();layout.addWidget(choices)
        for key,(title,_,_) in self.actions.items():
            item=QListWidgetItem(title);item.setData(Qt.ItemDataRole.UserRole,key);item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if key in self.favorite_ids else Qt.CheckState.Unchecked)
            if key in ("precision","priors","objectives"):item.setFlags(item.flags()&~Qt.ItemFlag.ItemIsEnabled)
            choices.addItem(item)
        actions=chinese_buttons(QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel));layout.addWidget(actions)
        actions.accepted.connect(dialog.accept);actions.rejected.connect(dialog.reject)
        if dialog.exec():
            self.favorite_ids=[choices.item(i).data(Qt.ItemDataRole.UserRole) for i in range(choices.count()) if choices.item(i).checkState()==Qt.CheckState.Checked]
            self.preferences.setValue("favorites",self.favorite_ids);self.preferences.sync();self.render_favorites()

    def go_to(self,index):self.navigation.setCurrentIndex(1);self.tabs.setCurrentIndex(index)

    def update_quota_hint(self):
        count=len([x for x in self.repeats.text().split(",") if x.strip()])
        if self.mode.currentData()=="cross":
            layout_count=4 if self.repeat_baseline.isChecked() else 3
            self.quota_hint.setText(f"交叉布局：{layout_count} 组 + 额外复测 {count} 次，需要 {layout_count+count} 个名额；其余名额不自动填充。专门探索应设为 0，探索强度不改变指定布局。")
            return
        remaining=self.n.value()-count-self.exploration_count.value()
        self.quota_hint.setText(f"名额预览：复测 {count} + 专门探索 {self.exploration_count.value()} + 常规新条件 {remaining} = 总数 {self.n.value()}。"+(" 名额超出，请调整。" if remaining<0 else " 数据不足时新条件均使用初始化策略。"))

    def select_items(self,title,items,selected):
        dialog=QDialog(self);dialog.setWindowTitle(title);dialog.resize(480,500);layout=QVBoxLayout(dialog);choices=QListWidget();layout.addWidget(choices)
        for label,value in items:
            item=QListWidgetItem(label);item.setData(Qt.ItemDataRole.UserRole,value);item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable);item.setCheckState(Qt.CheckState.Checked if value in selected else Qt.CheckState.Unchecked);choices.addItem(item)
        actions=chinese_buttons(QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel));layout.addWidget(actions);actions.accepted.connect(dialog.accept);actions.rejected.connect(dialog.reject)
        if dialog.exec():return [choices.item(i).data(Qt.ItemDataRole.UserRole) for i in range(choices.count()) if choices.item(i).checkState()==Qt.CheckState.Checked]
        return None

    def choose_variables(self):
        selected=self.select_items("允许变化的工艺参数",[(p.get("label",p["name"]),p["name"]) for p in self.require_project().template.parameters],self.variables.text().split(","))
        if selected is not None:self.variables.setText(",".join(selected))

    def choose_repeats(self):
        rows=self.require_project().experiments()
        selected=self.select_items("选择复测实验",[(f"实验 {r['id']} · {r.get('note','')}",str(r["id"])) for r in rows if r["status"] in ("completed","partial")],self.repeats.text().split(","))
        if selected is not None:self.repeats.setText(",".join(selected))

    def choose_plot(self):
        template=self.require_project().template
        selected=self.select_items("选择趋势图变量（最多两项）",[(p.get("label",p["name"]),p["name"]) for p in template.parameters if p.get("value_type","float") in ("float","int")],self.plot_variables.text().split(","))
        if selected is None:return
        if len(selected)>2:raise ValidationError("趋势图最多选择两个变量")
        self.plot_variables.setText(",".join(selected))
        metrics=[f for f in template.fields if f.get("is_response")]
        from PySide6.QtWidgets import QInputDialog
        labels=[f.get("label",f["name"]) for f in metrics]
        label,ok=QInputDialog.getItem(self,"选择趋势图指标","响应 / 指标",labels,0,False)
        if ok:self.plot_metric.setText(metrics[labels.index(label)]["name"])

    def save_batch_defaults(self):
        p=self.require_project();request=self.batch_request()
        if request.baseline_id is not None:request.baseline=p.experiment(request.baseline_id)["actual"]
        request.validate(p.template)
        defaults={**p.template.data.get("batch_defaults",{}),"total_count":request.n,"exploration_strength":request.exploration_strength,"exploration_count":request.exploration_count,"pool_size":request.pool_size,"seed":request.seed,"search_mode":request.mode,"baseline_experiment_id":request.baseline_id,"changed_parameter_names":request.variables,"repeat_ids":request.repeat_ids,"exact_two":request.exact_two,"repeat_baseline":request.repeat_baseline,"cross_values":request.cross_values}
        optimization={**p.template.data["optimization"],"default_model_preset":request.model}
        self.service.update_template(p.template.revised(batch_defaults=defaults,optimization=optimization));self.refresh()

    def create_template(self):
        chooser=QDialog(self);chooser.setWindowTitle("选择模板起点");layout=QVBoxLayout(chooser)
        layout.addWidget(QLabel("全新模板不包含任何默认工艺字段；也可复制或修改已有模板。"))
        source=QComboBox()
        for label,code in (("从空白创建全新模板","blank"),("复制当前项目模板","current"),("打开并修改本地模板文件","file"),("复制内置示例模板","builtin")):
            if code!="current" or self.service:source.addItem(label,code)
        layout.addWidget(source)
        actions=chinese_buttons(QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel))
        actions.accepted.connect(chooser.accept);actions.rejected.connect(chooser.reject);layout.addWidget(actions)
        if not chooser.exec():return
        if source.currentData()=="blank":base=blank_template()
        elif source.currentData()=="current":base=self.require_project().template
        elif source.currentData()=="builtin":base=Template.builtin()
        else:
            path,_=QFileDialog.getOpenFileName(self,"打开模板文件","","模板 (*.json)")
            if not path:return
            base=Template.read(path)
        dialog=TemplateEditor(base,self,creating=True)
        if not dialog.exec():return
        path,_=QFileDialog.getSaveFileName(self,"保存新模板","新模板.json","模板 (*.json)")
        if path:dialog.result_template.write(path)

    def show_details(self,value):
        dialog=QDialog(self);dialog.setWindowTitle("技术详情（含原始字段名和依赖库诊断）");dialog.resize(1000,700);layout=QVBoxLayout(dialog)
        text=QPlainTextEdit();text.setReadOnly(True);text.setPlainText(json.dumps(value,ensure_ascii=False,indent=2));layout.addWidget(text)
        actions=chinese_buttons(QDialogButtonBox(QDialogButtonBox.StandardButton.Close));actions.rejected.connect(dialog.reject);layout.addWidget(actions);dialog.exec()

    def show_batch_details(self):
        batches=self.require_project().batches()
        self.show_details({k:v for k,v in batches[-1].items() if k!="ax_snapshot"} if batches else {})
