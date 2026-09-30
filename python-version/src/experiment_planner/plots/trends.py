"""Local, version-labelled slices; only legal final execution values are plotted."""
from dataclasses import asdict
import numpy as np
from matplotlib.figure import Figure
from matplotlib.font_manager import FontProperties
from importlib.resources import files

from experiment_planner.domain.errors import ValidationError
from experiment_planner.engine.objectives import prediction_summary
from experiment_planner.precision.rounding import quantize


def slice_conditions(template, baseline, variables, points=25):
    template.validate_conditions(baseline)
    if len(variables) not in (1,2) or len(set(variables)) != len(variables):
        raise ValidationError("趋势图需要一项或两项不同的数值输入")
    axes=[]
    for name in variables:
        field=next((p for p in template.parameters if p["name"]==name),None)
        if field is None or "bounds" not in field:raise ValidationError("此图仅支持有范围的数值输入")
        axes.append(sorted(set(quantize(v,field.get("execution_rounding",{})) for v in np.linspace(*field["bounds"],points))))
    conditions=[]
    import itertools
    for row in itertools.product(*axes):
        c={**baseline,**dict(zip(variables,row))}
        try:template.validate_conditions(c)
        except ValidationError:continue
        conditions.append(c)
    return conditions


def plot_slice(model,encoder,names,template,baseline,variables,metric,path,revision,points=25,seed=0):
    conditions=slice_conditions(template,baseline,variables,points)
    if not conditions:raise ValidationError("切片内没有合法条件")
    predictions=prediction_summary(model,encoder,names,template,conditions,seed=seed)
    if metric not in predictions[0]:raise ValidationError("该响应无法预测；剩余厚度预测需要初始条件及专门误差传播")
    figure=Figure(figsize=(9,6),layout="constrained");ax=figure.subplots()
    if any(not p[metric].get("quantiles") for p in predictions):
        raise ValidationError("趋势指标没有可用的有限分位数，请检查比值分母和模型数据")
    quantiles=np.array([p[metric]["quantiles"] for p in predictions],dtype=float)
    font=FontProperties(fname=str(files("experiment_planner").joinpath("resources/fonts/NotoSansCJK-Regular.ttc")))
    labels={p["name"]:f"{p.get('label',p['name'])} ({p.get('unit','1')})" for p in template.fields}
    metric_label=labels.get(metric,metric)
    if len(variables)==1:
        x=[c[variables[0]] for c in conditions]
        ax.plot(x,quantiles[:,1],label="后验中位数")
        ax.fill_between(x,quantiles[:,0],quantiles[:,2],alpha=.25,label="潜在响应中央 95% 区间")
        ax.axvline(baseline[variables[0]],ls="--",color="gray",label="基准输入")
        ax.set_ylabel(metric_label,fontproperties=font);ax.legend(prop=font)
    else:
        x=[c[variables[0]] for c in conditions];y=[c[variables[1]] for c in conditions]
        scatter=ax.scatter(x,y,c=quantiles[:,1],cmap="viridis");colorbar=figure.colorbar(scatter,ax=ax);colorbar.set_label(f"{metric_label}：后验中位数",fontproperties=font)
        ax.scatter([baseline[variables[0]]],[baseline[variables[1]]],marker="x",color="red",label="基准");ax.legend(prop=font);ax.set_ylabel(labels[variables[1]],fontproperties=font)
    ax.set_xlabel(labels[variables[0]],fontproperties=font)
    fixed={k:v for k,v in baseline.items() if k not in variables}
    fixed_text="，".join(f"{labels.get(k,k)}={v:g}" if isinstance(v,(int,float)) else f"{labels.get(k,k)}={v}" for k,v in fixed.items())
    figure.suptitle(f"模型预测切片 | 数据版本 {revision}\n固定条件：{fixed_text}",fontsize=9,fontproperties=font)
    figure.savefig(path,dpi=140)
    return {"revision":revision,"template_version":template.data["template_version"],"conditions":conditions,"predictions":predictions,"fixed":fixed,"interval_kind":"latent_response","seed":seed}
