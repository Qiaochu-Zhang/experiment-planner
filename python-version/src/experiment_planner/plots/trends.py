"""Local, version-labelled slices; only legal final execution values are plotted."""
import math
import numpy as np
from matplotlib.figure import Figure
from matplotlib.font_manager import FontProperties
from importlib.resources import files

from experiment_planner.domain.errors import ValidationError
from experiment_planner.engine.objectives import prediction_summary
from experiment_planner.precision.rounding import quantize, grid_spec


def plot_ranges(template, variables, ranges=None):
    """Validate display bounds without changing the template or model encoder."""
    if len(variables) not in (1,2) or len(set(variables)) != len(variables):
        raise ValidationError("趋势图需要一项或两项不同的数值输入")
    if ranges is None:
        ranges = {}
    if not isinstance(ranges, dict) or set(ranges) - set(variables):
        raise ValidationError("绘图范围只能包含已选择的趋势变量")
    result = {}
    for name in variables:
        field = next((p for p in template.parameters if p["name"] == name), None)
        if field is None or field.get("value_type", "float") not in ("float", "int") or "bounds" not in field:
            raise ValidationError("此图仅支持有范围的数值输入")
        bounds = ranges.get(name, field["bounds"])
        label = field.get("label", name)
        if (not isinstance(bounds, (list, tuple)) or len(bounds) != 2
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in bounds)):
            raise ValidationError(f"{label}：绘图上下限需要两个有限数值")
        lo, hi = bounds
        if lo >= hi:
            raise ValidationError(f"{label}：绘图下限必须小于上限")
        if lo < field["bounds"][0] or hi > field["bounds"][1]:
            raise ValidationError(f"{label}：绘图范围必须在模板范围 {field['bounds']} 内")
        result[name] = [lo, hi]
    return result


def slice_conditions(template, baseline, variables, points=25, ranges=None):
    template.validate_conditions(baseline)
    if type(points) is not int or not 2 <= points <= 30:
        raise ValidationError("每个趋势图轴需要 2–30 个采样点")
    ranges = plot_ranges(template, variables, ranges)
    axes=[]
    for name in variables:
        field = next(p for p in template.parameters if p["name"] == name)
        lo, hi = ranges[name]
        rule = field.get("execution_rounding", {})
        # Integer inputs also have a grid even when no execution rule was set.
        if field.get("value_type") == "int" and grid_spec(rule) is None:
            rule = {"mode": "digits", "digits": 0}
        values = {quantize(v, rule) for v in np.linspace(lo, hi, points)}
        # Rounding an endpoint can move it outside the requested window.
        axes.append(sorted(v for v in values if lo <= v <= hi))
    conditions=[]
    import itertools
    for row in itertools.product(*axes):
        c={**baseline,**dict(zip(variables,row))}
        try:template.validate_conditions(c)
        except ValidationError:continue
        conditions.append(c)
    if not conditions:
        raise ValidationError("绘图范围内没有满足执行精度和约束的合法条件，请扩大范围或调整固定条件")
    if any(len({c[name] for c in conditions}) < 2 for name in variables):
        raise ValidationError("每个趋势变量至少需要两个合法取值，请扩大绘图范围或调整执行精度、固定条件")
    return conditions


def plot_slice(model,encoder,names,template,baseline,variables,metric,path,revision,points=25,seed=0,ranges=None):
    ranges = plot_ranges(template, variables, ranges)
    conditions=slice_conditions(template,baseline,variables,points,ranges)
    predictions=prediction_summary(model,encoder,names,template,conditions,seed=seed)
    if metric not in predictions[0]:raise ValidationError("该响应无法预测；剩余厚度预测需要初始条件及专门误差传播")
    for i, prediction in enumerate(predictions):
        item = prediction[metric]
        q = item.get("quantiles")
        if not q or not all(math.isfinite(value) for value in q):
            error = ValidationError(f"趋势指标 {metric} 在条件 {i+1} 没有可用的有限分位数。"
                                    + item.get("summary_notice", "请检查比值分母和模型数据。"))
            error.add_note(f"绘图输入条件：{conditions[i]!r}\n指标统计：{item!r}")
            raise error
    partial = any(p[metric].get("nonfinite_sample_count", 0) for p in predictions)
    notices = (["部分绘图点存在非有限样本；区间仅描述有限样本，不能视为完整预测分布的区间。"]
               if partial else [])
    with_input = bool(predictions[0].get("input_uncertainty"))
    if with_input:
        notices.append("趋势图已包含所选输入的执行波动；输入确定时的对照结果保存在技术详情和导出表中。")
    figure=Figure(figsize=(9,6),layout="constrained");ax=figure.subplots()
    quantiles=np.array([p[metric]["quantiles"] for p in predictions],dtype=float)
    font=FontProperties(fname=str(files("experiment_planner").joinpath("resources/fonts/NotoSansCJK-Regular.ttc")))
    labels={p["name"]:f"{p.get('label',p['name'])} ({p.get('unit','1')})" for p in template.fields}
    metric_label=labels.get(metric,metric)
    if len(variables)==1:
        x=[c[variables[0]] for c in conditions]
        ax.plot(x,quantiles[:,1],label="后验中位数")
        ax.fill_between(x,quantiles[:,0],quantiles[:,2],alpha=.25,
                        label="有限样本中央 95% 区间" if partial else "含输入波动的中央 95% 区间" if with_input else "潜在响应中央 95% 区间")
        if ranges[variables[0]][0] <= baseline[variables[0]] <= ranges[variables[0]][1]:
            ax.axvline(baseline[variables[0]],ls="--",color="gray",label="基准输入")
        ax.set_ylabel(metric_label,fontproperties=font);ax.legend(prop=font)
    else:
        x=[c[variables[0]] for c in conditions];y=[c[variables[1]] for c in conditions]
        scatter=ax.scatter(x,y,c=quantiles[:,1],cmap="viridis");colorbar=figure.colorbar(scatter,ax=ax);colorbar.set_label(f"{metric_label}：后验中位数",fontproperties=font)
        if all(ranges[v][0] <= baseline[v] <= ranges[v][1] for v in variables):
            ax.scatter([baseline[variables[0]]],[baseline[variables[1]]],marker="x",color="red",label="基准");ax.legend(prop=font)
        ax.set_ylabel(labels[variables[1]],fontproperties=font)
        ax.set_ylim(*ranges[variables[1]])
    ax.set_xlim(*ranges[variables[0]])
    ax.set_xlabel(labels[variables[0]],fontproperties=font)
    fixed={k:v for k,v in baseline.items() if k not in variables}
    fixed_text="，".join(f"{labels.get(k,k)}={v:g}" if isinstance(v,(int,float)) else f"{labels.get(k,k)}={v}" for k,v in fixed.items())
    warning = "\n" + " ".join(notices) if notices else ""
    fixed_label = "固定设定值（所选输入仍有执行波动）" if with_input else "固定条件"
    figure.suptitle(f"模型预测切片 | 数据版本 {revision}\n{fixed_label}：{fixed_text}{warning}",fontsize=9,fontproperties=font)
    figure.savefig(path,dpi=140)
    return {"revision":revision,"template_version":template.data["template_version"],"conditions":conditions,"predictions":predictions,"fixed":fixed,"ranges":ranges,"interval_kind":"latent_response_with_input_uncertainty" if with_input else "latent_response","seed":seed,"notices":notices}
