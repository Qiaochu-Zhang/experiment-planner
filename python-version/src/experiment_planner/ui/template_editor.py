"""Mouse/keyboard forms for common template settings, with a full typed editor."""
import copy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox,
    QTabWidget, QTableWidget, QVBoxLayout, QWidget, QHeaderView)

from experiment_planner.domain.template import Template
from experiment_planner.domain.errors import ValidationError
from experiment_planner.knowledge.priors import check_capabilities
from experiment_planner.ui.help import attach_help, help_label, show_help
from experiment_planner.ui.tree_editor import JsonTreeEditor, chinese_buttons
from experiment_planner.ui.messages import user_error


def combo(items, selected=None):
    widget=QComboBox()
    for title,value in items:widget.addItem(title,value)
    if selected is not None:widget.setCurrentIndex(max(0,widget.findData(selected)))
    return widget


class CompactNumber(QDoubleSpinBox):
    def textFromValue(self,value):
        return f"{value:.{self.decimals()}f}".rstrip("0").rstrip(".") if self.decimals() else str(int(value))


def number(value=0, minimum=-1e12, maximum=1e12, decimals=8):
    widget=CompactNumber();widget.setDecimals(decimals);widget.setRange(minimum,maximum);widget.setValue(value)
    widget.setKeyboardTracking(False)
    return widget


def integer(value=0,minimum=-12,maximum=12):
    widget=QSpinBox();widget.setRange(minimum,maximum);widget.setValue(value);return widget


def table(headers):
    result=QTableWidget(0,len(headers));result.setHorizontalHeaderLabels(headers)
    result.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    result.horizontalHeader().setStretchLastSection(True);result.setAlternatingRowColors(True)
    return result


class TemplateEditor(QDialog):
    def __init__(self, template, parent=None, section="precision", creating=False):
        super().__init__(parent)
        self.data=copy.deepcopy(template.data)
        self.result_template=None
        self.creating=creating
        self.setWindowTitle("新建模板" if creating else "编辑项目模板")
        self.resize(1160,760)
        outer=QVBoxLayout(self)
        info=QLabel("通过下列表单设置精度、先验和目标。其他配置请点“全部属性”。保存后产生新的模板版本。")
        info.setWordWrap(True);outer.addWidget(info)
        top=QHBoxLayout();outer.addLayout(top)
        self.name=QLineEdit(self.data.get("name","实验模板"));top.addWidget(QLabel("模板名称"));top.addWidget(self.name)
        full=QPushButton("全部属性（字段 / 公式 / 范围 / 约束）");full.clicked.connect(self.edit_all);top.addWidget(full)
        help_button=QPushButton("变量与设置说明");help_button.clicked.connect(lambda:show_help("template",self));top.addWidget(help_button)
        self.tabs=QTabWidget();outer.addWidget(self.tabs)
        self.build_pages()
        self.tabs.setCurrentIndex({"precision":0,"priors":1,"objectives":2}.get(section,0))
        self.buttons=chinese_buttons(QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel))
        self.buttons.accepted.connect(self.save);self.buttons.rejected.connect(self.reject);outer.addWidget(self.buttons)

    def build_pages(self):
        while self.tabs.count():
            page=self.tabs.widget(0);self.tabs.removeTab(0);page.deleteLater()
        page=QWidget();layout=QVBoxLayout(page)
        layout.addWidget(help_label("执行精度决定新推荐条件；显示精度只改变表格外观。悬停查看详细说明。","precision"))
        self.precision=table(["工艺参数", "执行模式", "小数位数", "步长", "网格起点", "显示小数位数"])
        self.precision_rows=[]
        for p in self.data["parameters"]:
            row=self.precision.rowCount();self.precision.insertRow(row)
            rule=p.get("execution_rounding",{})
            label=help_label(f"{p.get('label',p['name'])} ({p.get('unit','1')})",p["name"],p.get("note") or None)
            mode=combo([("不限制","none"),("小数位数","digits"),("指定步长","step")],rule.get("mode","none"))
            digits=integer(rule.get("digits") or 0)
            step=number(rule.get("step") or 1,1e-12,1e12,12);origin=number(rule.get("origin",0),decimals=12)
            display=combo([("原始精度",None),*[(str(i),i) for i in range(-12,13)]],p.get("display_digits"))
            for col,w in enumerate((label,mode,digits,step,origin,display)):self.precision.setCellWidget(row,col,w)
            for w in (mode,digits,step,origin,display):attach_help(w,"precision")
            self.precision_rows.append((p,mode,digits,step,origin,display))
            numeric=p.get("value_type","float") in ("float","int")
            mode.setEnabled(numeric)
            def sync(_, m=mode,d=digits,s=step,o=origin,allowed=numeric):
                d.setEnabled(allowed and m.currentData()=="digits");s.setEnabled(allowed and m.currentData()=="step");o.setEnabled(allowed and m.currentData()!="none")
            mode.currentIndexChanged.connect(sync);sync(0)
        layout.addWidget(self.precision)
        bulk=QHBoxLayout();layout.addLayout(bulk)
        self.bulk_digits=integer(0);bulk.addWidget(QLabel("所有数值参数统一小数位数"));bulk.addWidget(self.bulk_digits)
        apply=QPushButton("应用到所有工艺参数");apply.clicked.connect(self.apply_digits);bulk.addWidget(apply);bulk.addStretch()
        self.tabs.addTab(page,"推荐工艺精度")

        page=QWidget();layout=QVBoxLayout(page)
        layout.addWidget(help_label("先验必须填写来源。系数使用响应单位 / 输入单位；强度不是置信百分比。","priors"))
        self.prior_table=table(["启用", "输入参数", "基础响应", "关系", "系数", "强度", "来源"])
        self.prior_rows=[]
        for prior in self.data.get("knowledge_priors",[]):self.add_prior(prior)
        layout.addWidget(self.prior_table)
        actions=QHBoxLayout();layout.addLayout(actions)
        add=QPushButton("添加先验");add.clicked.connect(lambda:self.add_prior({}));actions.addWidget(add)
        remove=QPushButton("删除选中先验");remove.clicked.connect(self.remove_prior);actions.addWidget(remove)
        self.tabs.addTab(page,"先验关系")

        page=QWidget();layout=QVBoxLayout(page)
        layout.addWidget(help_label("勾选要参与的目标，可同时选择多个；“接近指定值”采用距离最小化。","objectives"))
        mode_row=QHBoxLayout();layout.addLayout(mode_row)
        mode_row.addWidget(QLabel("优化方式"))
        self.optimization=combo([("多目标折中（Pareto）","pareto"),("单目标","single"),("加权目标","weighted")],self.data["optimization"]["mode"])
        mode_row.addWidget(self.optimization)
        self.model=combo([("高斯过程 RBF","gp_rbf_v1"),("高斯过程 Matérn 2.5","gp_matern25_v1"),("贝叶斯线性","bayesian_linear_v1")],self.data["optimization"].get("default_model_preset","gp_rbf_v1"))
        mode_row.addWidget(QLabel("默认模型"));mode_row.addWidget(self.model);attach_help(self.model,"model")
        self.objective_table=table(["启用", "响应 / 指标", "变换", "方向", "目标值", "权重", "归一化尺度"])
        self.objective_rows=[]
        existing={o["metric"]:o for o in self.data.get("objectives",[])}
        fields=[f for f in self.data.get("measurements",[])+self.data.get("derived_metrics",[]) if f.get("is_response") or f["name"] in existing]
        active=[o for o in self.data.get("objectives",[]) if not (self.data.get("ratio_policy",{}).get("mode")=="remove" and o["metric"]==self.data.get("ratio_policy",{}).get("original_metric"))]
        for f in fields:
            obj=existing.get(f["name"],{"metric":f["name"],"transform":"identity","direction":"maximize"})
            enabled=QCheckBox();enabled.setChecked(f["name"] in existing)
            label=help_label(f.get("label",f["name"]),f["name"])
            transform=combo([("原值","identity"),("绝对值","abs"),("距指定值的距离","absolute_distance")],obj.get("transform","identity"))
            direction=combo([("尽量大","maximize"),("尽量小","minimize")],obj["direction"])
            target=number(obj.get("target",0));target.setEnabled(transform.currentData()=="absolute_distance")
            def sync_target(_, t=transform,d=direction,v=target):
                v.setEnabled(t.currentData()=="absolute_distance")
                if t.currentData()=="absolute_distance":d.setCurrentIndex(d.findData("minimize"))
            transform.currentIndexChanged.connect(sync_target)
            index=next((i for i,o in enumerate(active) if o["metric"]==f["name"]),None)
            config=self.data["optimization"]
            weight=number((config.get("weights") or [])[index] if index is not None and index<len(config.get("weights") or []) else 1,0)
            scale=number((config.get("scales") or [])[index] if index is not None and index<len(config.get("scales") or []) else 1,1e-8)
            row=self.objective_table.rowCount();self.objective_table.insertRow(row)
            for col,w in enumerate((enabled,label,transform,direction,target,weight,scale)):self.objective_table.setCellWidget(row,col,w)
            self.objective_rows.append((obj,enabled,transform,direction,target,weight,scale))
            for w in (enabled,transform,direction,target,weight,scale):attach_help(w,"objectives")
        def weighting_changed(_):
            for *_,weight,scale in self.objective_rows:
                weight.setEnabled(self.optimization.currentData()=="weighted")
                scale.setEnabled(self.optimization.currentData()=="weighted")
        self.optimization.currentIndexChanged.connect(weighting_changed);weighting_changed(0)
        layout.addWidget(self.objective_table)
        ratio_form=QFormLayout();layout.addLayout(ratio_form)
        policy=self.data.get("ratio_policy",{"mode":"remove"})
        self.ratio=combo([("先不设置（推荐前需选择）","require_configuration"),("有效区域内比值","valid_region"),("稳定化比值","stabilized"),("移除比值目标","remove")],policy["mode"])
        self.epsilon=number(policy.get("epsilon_nm") or 1,1e-12,1e12,12)
        self.ratio.currentIndexChanged.connect(lambda _:self.epsilon.setEnabled(self.ratio.currentData() in ("valid_region","stabilized")))
        self.epsilon.setEnabled(self.ratio.currentData() in ("valid_region","stabilized"))
        ratio_form.addRow(help_label("分母策略","ratio_policy"),self.ratio);ratio_form.addRow(help_label("分母阈值（nm）","epsilon_nm"),self.epsilon)
        newer=QPushButton("应用新版 ICP 目标：A 尽量大、B 接近零、A/B 尽量大")
        newer.clicked.connect(self.new_goals);layout.addWidget(newer)
        self.tabs.addTab(page,"实验优化目标")

    def apply_digits(self):
        for p,mode,digits,_,_,_ in self.precision_rows:
            if p.get("value_type","float") in ("float","int"):
                mode.setCurrentIndex(mode.findData("digits"));digits.setValue(self.bulk_digits.value())

    def add_prior(self,prior):
        enabled=QCheckBox();enabled.setChecked(prior.get("enabled",True))
        inputs=combo([(p.get("label",p["name"]),p["name"]) for p in self.data["parameters"]],prior.get("input"))
        responses=combo([(f.get("label",f["name"]),f["name"]) for f in self.data.get("measurements",[])+self.data.get("derived_metrics",[]) if f.get("is_response") and f.get("model_base",True)],prior.get("response"))
        relation=combo([("无关","independent"),("线性趋势","linear"),("比例趋势（软先验）","proportional"),("单调趋势（线性模型）","monotonic"),("弱影响（线性模型）","weak")],prior.get("relation","linear"))
        coefficient=number(prior.get("coefficient",0));strength=number(prior.get("strength",1),1e-8)
        source=QLineEdit(prior.get("source",""));source.setPlaceholderText("实验记录或文献依据")
        row=self.prior_table.rowCount();self.prior_table.insertRow(row)
        for col,w in enumerate((enabled,inputs,responses,relation,coefficient,strength,source)):self.prior_table.setCellWidget(row,col,w);attach_help(w,"priors")
        self.prior_rows.append((copy.deepcopy(prior),enabled,inputs,responses,relation,coefficient,strength,source))

    def remove_prior(self):
        row=self.prior_table.currentRow()
        if row>=0:self.prior_table.removeRow(row);self.prior_rows.pop(row)

    def collect(self):
        data=copy.deepcopy(self.data);data["name"]=self.name.text().strip() or "实验模板"
        by_name={p["name"]:p for p in data["parameters"]}
        for old,mode,digits,step,origin,display in self.precision_rows:
            p=by_name[old["name"]];selected=mode.currentData()
            p["execution_rounding"]={"mode":selected,"digits":digits.value() if selected=="digits" else None,"step":step.value() if selected=="step" else None}
            if selected!="none":p["execution_rounding"]["origin"]=origin.value()
            p["display_digits"]=display.currentData()
        data["knowledge_priors"]=[]
        for prior,enabled,inputs,responses,relation,coefficient,strength,source in self.prior_rows:
            data["knowledge_priors"].append({**prior,"enabled":enabled.isChecked(),"input":inputs.currentData(),"response":responses.currentData(),"relation":relation.currentData(),"coefficient":coefficient.value(),"strength":strength.value(),"source":source.text().strip()})
        objectives=[];weights=[];scales=[]
        for old,enabled,transform,direction,target,weight,scale in self.objective_rows:
            if not enabled.isChecked():continue
            obj={**old,"transform":transform.currentData(),"direction":direction.currentData()}
            if obj["transform"]=="absolute_distance":obj["target"]=target.value()
            else:obj.pop("target",None)
            objectives.append(obj)
            if not (self.ratio.currentData()=="remove" and obj["metric"]==data.get("ratio_policy",{}).get("original_metric")):
                weights.append(weight.value());scales.append(scale.value())
        data["objectives"]=objectives
        data["optimization"].update(mode=self.optimization.currentData(),default_model_preset=self.model.currentData())
        if self.optimization.currentData()=="weighted":data["optimization"].update(weights=weights,scales=scales)
        else:data["optimization"].update(weights=None,scales=None)
        data.setdefault("ratio_policy",{}).update(mode=self.ratio.currentData(),epsilon_nm=self.epsilon.value() if self.ratio.currentData() in ("stabilized","valid_region") else None)
        return data

    def new_goals(self):
        data=self.collect();builtin=Template.builtin().data
        names={f["name"] for f in data.get("derived_metrics",[])}
        if not {"sio2_loss_nm","sin_loss_nm"}<=names:
            QMessageBox.warning(self,"无法应用","此快捷设置需要 SiO2 和 SiN 两项刻蚀量基础响应。");return
        data["derived_metrics"]=[m for m in data["derived_metrics"] if m["name"]!="selectivity"]+[copy.deepcopy(builtin["derived_metrics"][-1])]
        data["objectives"]=copy.deepcopy(builtin["objectives"])
        data["optimization"].update(mode="pareto",weights=None,scales=None)
        data["ratio_policy"].update(original_metric="selectivity",stable_metric_name="selectivity_stable")
        self.data=data;self.build_pages();self.tabs.setCurrentIndex(2)

    def edit_all(self):
        dialog=JsonTreeEditor(self.collect(),self)
        while dialog.exec():
            try:
                data=dialog.data();Template(data)
            except Exception as exc:QMessageBox.warning(self,"模板需要调整",user_error(exc));continue
            self.data=data;self.name.setText(data.get("name",""));self.build_pages();break

    def save(self):
        try:
            data=self.collect();data["template_version"]=self.data["template_version"]+1
            result=Template(data)
            check_capabilities(result,self.model.currentData())
            self.result_template=result
        except Exception as exc:
            QMessageBox.warning(self,"设置未保存",user_error(exc));return
        self.accept()
