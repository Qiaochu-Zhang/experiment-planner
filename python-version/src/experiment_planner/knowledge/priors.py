from experiment_planner.domain.errors import CapabilityError, ValidationError


PRESETS = {
    "gp_rbf_v1": {"label": "默认 GP / RBF", "family": "gp", "kernel": "RBF", "noise": "known variance or inferred homoskedastic"},
    "gp_matern25_v1": {"label": "GP / Matérn 2.5", "family": "gp", "kernel": "Matern(nu=2.5)", "noise": "known variance or inferred homoskedastic"},
    "bayesian_linear_v1": {"label": "贝叶斯线性回归", "family": "linear", "noise": "known variance or explicit empirical estimate"},
    "bernoulli_response_v1": {"label": "布尔响应概率模型", "family": "bernoulli", "likelihood": "Bernoulli-logit", "inference": "Laplace Gaussian coefficient posterior"},
}


def check_capabilities(template, preset):
    if preset not in PRESETS or preset == "bernoulli_response_v1": raise CapabilityError("请选择数值模型预设；布尔模型按响应自动组合")
    base = {f["name"]: f for f in template.responses}
    inputs = {p["name"]: p for p in template.parameters}
    if not any(p.get("use_as_model_input",True) for p in template.parameters):
        raise CapabilityError("当前引擎至少需要一个模型输入")
    if any(f.get("use_as_model_input") for f in template.measurements + template.metrics):
        raise CapabilityError("当前引擎尚未支持额外实验前条件或派生输入；模板可保存，推荐已阻止")
    for prior in template.data.get("knowledge_priors", []):
        if not prior.get("enabled", True): continue
        if prior.get("response") not in base or prior.get("input") not in inputs:
            raise CapabilityError("先验必须指向可控输入与基础响应；派生先验需要专用适配")
        relation = prior.get("relation")
        if relation not in ("independent", "linear", "proportional", "monotonic", "weak"):
            raise CapabilityError("未实现此关系先验")
        if prior.get("strict") and relation != "independent": raise CapabilityError("当前不支持严格比例或全域形状保证")
        if prior.get("range") is not None: raise CapabilityError("局部范围先验尚未适配，不能自动推广为全域")
        if relation != "independent":
            if inputs[prior["input"]].get("value_type", "float") not in ("float", "int"):
                raise CapabilityError("当前系数先验仅支持数值输入")
            if base[prior["response"]].get("value_type") == "bool": raise CapabilityError("布尔模型的结构化系数先验尚未适配")
            if relation in ("monotonic", "weak") and preset != "bayesian_linear_v1":
                raise CapabilityError("单调/弱影响先验当前仅支持贝叶斯线性模型；GP 导数虚拟观测尚未实现")
            if prior.get("strength", 0) <= 0: raise ValidationError("先验强度必须大于零")
            if relation != "weak" and "coefficient" not in prior: raise ValidationError("此先验需要有符号系数估计（响应单位/输入单位）")
        if not prior.get("source"): raise ValidationError("先验需要记录来源")
    if template.data.get("cross_output_covariance") or template.data.get("correlated_observations"):
        raise CapabilityError("当前独立响应模型未适配跨输出/跨实验相关观测噪声")
    for field in template.fields:
        if field.get("modeling_rounding", {}).get("mode", "none") != "none":
            raise CapabilityError("建模取整变换尚未接入；显示与执行取整可用")
        if field in template.parameters and field.get("input_uncertainty"):
            raise CapabilityError("输入位置误差尚未接入预测积分")
