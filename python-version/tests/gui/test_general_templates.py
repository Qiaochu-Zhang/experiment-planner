import copy

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QFileDialog, QMessageBox

from experiment_planner.application.service import PlannerService
from experiment_planner.application.template_editing import blank_template, remove_fields, rename_field
from experiment_planner.domain.errors import ValidationError
from experiment_planner.domain.template import Template
from experiment_planner.engine.models import fit_models
from experiment_planner.engine.objectives import prediction_summary
from experiment_planner.storage.project import Project
from experiment_planner.ui.desktop import PythonWindow
from experiment_planner.ui.field_editor import FieldDialog, FieldsEditor
from experiment_planner.ui.help import HelpDialog, TOPICS, help_path
from experiment_planner.ui.template_editor import TemplateEditor
from experiment_planner.ui.tree_editor import JsonTreeEditor
from experiment_planner.ui.window import RecordDialog

pytestmark = pytest.mark.gui


def new_fields():
    parameter = FieldDialog('parameters')
    parameter.name.setText('speed'); parameter.label.setText('速度')
    parameter.lower.setText('0'); parameter.upper.setText('10')
    x = parameter.value(); parameter.close()
    measurement = FieldDialog('measurements')
    measurement.name.setText('quality'); measurement.label.setText('质量得分')
    y = measurement.value(); measurement.close()
    return x, y


def custom_template():
    fields = FieldsEditor(blank_template())
    x, y = new_fields()
    fields.set_field('parameters', x); fields.set_field('measurements', y)
    result = Template(fields.data); fields.close()
    return result


def test_empty_draft_to_custom_template_record_and_real_prediction(qt_application, tmp_path):
    editor = TemplateEditor(blank_template(), creating=True)
    assert not editor.data['parameters'] and not editor.data['measurements']
    def add_fields():
        fields = QApplication.activeModalWidget(); assert isinstance(fields, FieldsEditor)
        x, y = new_fields()
        fields.set_field('parameters', x); fields.set_field('measurements', y)
        fields.accept()
    QTimer.singleShot(0, add_fields); editor.edit_fields()
    editor.model.setCurrentIndex(editor.model.findData('bayesian_linear_v1'))
    editor.save(); assert editor.result() == QDialog.DialogCode.Accepted
    result = editor.result_template
    assert result.data['template_version'] == 1
    assert [p['name'] for p in result.parameters] == ['speed']
    assert result.data['objectives'][0]['metric'] == 'quality'
    path = tmp_path / 'new.json'; result.write(path)
    window = PythonWindow(); window.set_project(Project.create(tmp_path / 'new.sqlite', '全新实验', Template.read(path)))
    for speed in (1, 3, 6):
        record = RecordDialog(result)
        record.inputs['speed'][0].setText(str(speed)); record.cells['quality'][0].setText(str(2 * speed + 1))
        record.validate_accept(); assert record.result() == QDialog.DialogCode.Accepted
        window.service.add_record(**record.values()); record.close()
    window.refresh(); assert window.table.rowCount() == 3 and window.plot_metric.text() == 'quality'
    model, encoder, names, _, _ = fit_models(result, window.require_project().experiments(), 'bayesian_linear_v1')
    predicted = prediction_summary(model, encoder, names, result, [{'speed': 4}])
    assert predicted[0]['quality']['mean'] == pytest.approx(9, abs=.1)
    window.close(); editor.close()


def test_name_change_updates_references_and_delete_cascades(qt_application):
    original = custom_template().data
    original.update(derived_metrics=[{'name': 'twice', 'expression': 'quality * 2', 'unit': '1', 'is_response': True, 'model_base': False},
                                     {'name': 'shifted', 'expression': 'twice + 1', 'unit': '1', 'model_base': False}],
        objectives=[{'metric': 'twice', 'direction': 'maximize'}],
        knowledge_priors=[{'input': 'speed', 'response': 'quality', 'relation': 'independent', 'source': '测试'}],
        input_constraints=[{'coefficients': {'speed': 1}, 'op': '<=', 'rhs': 9}],
        outcome_constraints=[{'metric': 'quality', 'op': '>=', 'bound': 0}],
        batch_defaults={'changed_parameter_names': ['speed'], 'cross_values': {'speed': 2}})
    before = copy.deepcopy(original)
    changed = rename_field(rename_field(original, 'speed', 'rate'), 'quality', 'score')
    assert original == before
    assert changed['derived_metrics'][0]['expression'] == 'score * 2'
    assert changed['knowledge_priors'][0]['input'] == 'rate' and changed['knowledge_priors'][0]['response'] == 'score'
    assert changed['input_constraints'][0]['coefficients'] == {'rate': 1}
    assert changed['batch_defaults']['cross_values'] == {'rate': 2}
    assert changed['batch_defaults']['changed_parameter_names'] == ['rate']
    assert changed['outcome_constraints'][0]['metric'] == 'score'
    Template(changed)
    deleted, names = remove_fields(changed, ['score'])
    assert set(names) == {'score', 'twice', 'shifted'}
    assert deleted['derived_metrics'] == deleted['objectives'] == deleted['knowledge_priors'] == deleted['outcome_constraints'] == []
    assert deleted['parameters'][0]['name'] == 'rate'
    with pytest.raises(ValidationError): rename_field(original, 'speed', 'quality')


def test_empty_project_accepts_structure_and_existing_data_is_not_reinterpreted(qt_application, service, conditions, measurements):
    custom = custom_template()
    target = Template({**custom.data, 'template_version': service.project.template.data['template_version'] + 1})
    service.update_template(target)
    assert service.project.template.parameters[0]['name'] == 'speed'
    service.add_record({'speed': 2}, {'quality': 4})
    before = service.project.snapshot()
    changed = rename_field(target.data, 'speed', 'rate'); changed['template_version'] += 1
    with pytest.raises(ValidationError, match='另存'): service.update_template(Template(changed))
    assert service.project.snapshot() == before


def test_existing_project_can_save_structural_edits_as_template(qt_application, tmp_path, conditions, measurements, monkeypatch):
    window = PythonWindow(); window.set_project(Project.create(tmp_path / 'old.sqlite', '已有记录'))
    window.service.add_record(conditions, measurements)
    before = window.require_project().snapshot(); saved = tmp_path / 'modified.json'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args, **kwargs: (str(saved), ''))
    def modify():
        editor = QApplication.activeModalWidget(); assert isinstance(editor, TemplateEditor)
        editor.data = rename_field(editor.data, 'cl2_sccm', 'new_input')
        editor.build_pages(); editor.save()
        QTimer.singleShot(0, choose_save)
    def choose_save():
        box = QApplication.activeModalWidget(); assert isinstance(box, QMessageBox)
        next(b for b in box.buttons() if b.text() == '另存模板文件').click()
    QTimer.singleShot(0, modify); window.edit_template()
    assert Template.read(saved).parameters[0]['name'] == 'new_input'
    assert window.require_project().snapshot() == before
    window.close()


@pytest.mark.parametrize('source', ['blank', 'file'])
def test_create_dialog_starts_blank_or_opens_existing_file(qt_application, tmp_path, monkeypatch, source):
    window = PythonWindow(); saved = tmp_path / 'saved.json'; existing = tmp_path / 'existing.json'
    custom_template().write(existing)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *a, **k: (str(existing), ''))
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: (str(saved), ''))
    def choose():
        dialog = QApplication.activeModalWidget(); box = dialog.findChild(QComboBox)
        box.setCurrentIndex(box.findData(source)); dialog.accept(); QTimer.singleShot(0, edit)
    def edit():
        editor = QApplication.activeModalWidget(); assert isinstance(editor, TemplateEditor)
        if source == 'blank':
            assert editor.data['parameters'] == []
            fields = FieldsEditor(editor.data); x, y = new_fields()
            fields.set_field('parameters', x); fields.set_field('measurements', y)
            editor.data = fields.data; fields.close()
        else:
            editor.data = rename_field(editor.data, 'speed', 'new_speed')
        editor.build_pages(); editor.name.setText('独立模板'); editor.save()
    QTimer.singleShot(0, choose); window.create_template()
    result = Template.read(saved)
    assert result.data['name'] == '独立模板'
    assert result.parameters[0]['name'] == ('speed' if source == 'blank' else 'new_speed')
    window.close()


def test_full_property_editor_keeps_draft_editable(qt_application):
    editor = TemplateEditor(blank_template(), creating=True)
    def change_tree():
        tree = QApplication.activeModalWidget(); assert isinstance(tree, JsonTreeEditor)
        root = tree.tree.topLevelItem(0)
        tree.fill(root, 'custom_setting', {'enabled': True, 'description': '扩展配置'})
        tree.accept()
    QTimer.singleShot(0, change_tree); editor.edit_all()
    assert editor.data['custom_setting']['enabled'] is True and not editor.data['parameters']
    editor.close()


def test_generic_help_has_no_default_template_topics(qt_application):
    text = help_path().read_text(encoding='utf-8')
    for word in ('cl2', 'Cl2', 'SiO2', 'SiN', 'BCl3', 'sio2_loss_nm'):
        assert word not in text
    assert 'cl2_sccm' not in TOPICS
    help_dialog = HelpDialog('brand_new_parameter')
    assert help_dialog.topics.currentItem().text() == '输入参数与字段名称'
    help_dialog.close()


def test_fixed_category_and_boolean_fields_work_in_prediction_form(qt_application, tmp_path):
    base = custom_template().data
    for name, kind, value in [('batch_type', 'category', 'standard'), ('enabled', 'bool', 'false')]:
        dialog = FieldDialog('parameters'); dialog.name.setText(name)
        dialog.kind.setCurrentIndex(dialog.kind.findData(kind))
        dialog.domain.setCurrentIndex(dialog.domain.findData('fixed_value')); dialog.fixed.setText(value)
        base['parameters'].append(dialog.value()); dialog.close()
    template = Template(base)
    window = PythonWindow(); window.set_project(Project.create(tmp_path / 'fixed.sqlite', '固定参数', template))
    window.conditions.editors['speed'].setText('2')
    assert template.validate_conditions(window.conditions.values()) == {'speed': 2., 'batch_type': 'standard', 'enabled': False}
    for speed in (1., 2., 4.): window.service.add_record({'speed': speed, 'batch_type': 'standard', 'enabled': False}, {'quality': speed})
    model, encoder, names, _, _ = fit_models(template, window.require_project().experiments(), 'bayesian_linear_v1')
    assert prediction_summary(model, encoder, names, template, [window.conditions.values()])[0]['quality']['mean'] == pytest.approx(2, abs=.1)
    window.close()


def test_custom_unit_and_advanced_attributes_survive_save(qt_application):
    data=custom_template().data
    data['measurements'][0]['unit']='kg'
    data['derived_metrics']=[{'name':'double_quality','expression':'quality * 2','unit':'kg','is_response':True,'model_base':False}]
    data['parameters'][0]['execution_rounding']={'mode':'none','custom_note':'保留扩展'}
    editor=TemplateEditor(Template(data),creating=True)
    editor.save()
    assert editor.result()==QDialog.DialogCode.Accepted
    assert editor.result_template.graph.evaluate({'quality':3})['double_quality'].value==6
    assert editor.result_template.parameters[0]['execution_rounding']['custom_note']=='保留扩展'
    editor.close()


def test_save_explains_unusable_objective(qt_application, monkeypatch):
    data=custom_template().data
    data['measurements'][0]['model_base']=False
    editor=TemplateEditor(Template(data),creating=True)
    messages=[];monkeypatch.setattr(QMessageBox,'warning',lambda *args:messages.append(args[-1]))
    editor.save()
    assert editor.result_template is None and '基础响应' in messages[0]
    editor.close()
