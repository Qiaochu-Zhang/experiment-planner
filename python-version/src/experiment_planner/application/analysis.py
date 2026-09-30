"""Read-only prediction and plotting from an immutable project snapshot."""
from experiment_planner.domain.errors import ValidationError
from experiment_planner.domain.template import Template


def analyze(snapshot, request):
    from experiment_planner.engine.runtime import configure_offline_runtime
    from experiment_planner.engine.models import fit_models
    from experiment_planner.engine.objectives import prediction_summary

    configure_offline_runtime()
    template = Template(snapshot["template"])
    conditions = request.get("conditions")
    if not isinstance(conditions, list) or not conditions:
        raise ValidationError("预测需要至少一组完整条件")
    conditions = [template.validate_conditions(c) for c in conditions]
    preset = request.get("model", "gp_rbf_v1")
    seed = request.get("seed", 0)
    model, encoder, names, datasets, notices = fit_models(
        template, snapshot["experiments"], preset, seed
    )
    result = {
        "revision": snapshot["revision"],
        "template_version": template.data["template_version"],
        "model": preset,
        "conditions": conditions,
        "notices": notices,
        "model_datasets": datasets,
        "predictions": prediction_summary(
            model, encoder, names, template, conditions, seed=seed
        ),
    }
    if request.get("plot_path"):
        from experiment_planner.plots.trends import plot_slice
        points = request.get("points", 15)
        if type(points) is not int or not 2 <= points <= 30:
            raise ValidationError("每个趋势图轴需要 2–30 个采样点")
        result["plot"] = plot_slice(
            model, encoder, names, template, conditions[0],
            request.get("variables", []), request.get("metric", names[0]),
            request["plot_path"], snapshot["revision"], points=points, seed=seed,
        )
        result["plot_path"] = str(request["plot_path"])
    for field in template.parameters:
        if field["name"] == "etch_time_s" and field.get("unit") == "s":
            result["notices"].append("刻蚀时间输入单位为秒；内置 SiO2 / SiN 刻蚀量响应是累计厚度差（nm），没有除以秒或分钟。趋势是固定其他条件的模型切片，不是物理定律。")
    return result
