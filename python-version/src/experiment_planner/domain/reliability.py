"""Explicit relative data confidence; separate from measured uncertainty."""
import math
from datetime import date, datetime, timezone

from experiment_planner.domain.errors import ValidationError


MIN_WEIGHT = 1e-6


def experiment_time(value):
    """Normalize Excel dates / ISO dates and timestamps to UTC; empty is unknown."""
    if value is None or value == "":
        return None
    try:
        if isinstance(value, datetime):
            result = value
        elif isinstance(value, date):
            result = datetime.combine(value, datetime.min.time())
        else:
            result = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        if result.tzinfo is None:
            result = result.replace(tzinfo=timezone.utc)
        return result.astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValidationError("实验日期须为 YYYY-MM-DD 或 ISO 日期时间（无时区按 UTC）") from exc


def batch_name(value):
    if value is None:
        return ""
    if not isinstance(value, str) or len(value.strip()) > 120:
        raise ValidationError("实验批次名称须为不超过 120 字的文字")
    return value.strip()


def confidence_value(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 1:
        raise ValidationError("批次可信度须大于 0 且不超过 1；1 表示默认权重，并非准确率")
    return float(value)


def validate_weighting(config):
    if not isinstance(config, dict):
        raise ValidationError("数据可信度设置须为对象")
    half_life = config.get("recency_half_life_days", 0)
    if type(half_life) not in (int, float) or not math.isfinite(half_life) or half_life < 0:
        raise ValidationError("近期权重半衰期须为非负有限天数；0 表示关闭")
    batches = config.get("batch_confidence", {})
    if not isinstance(batches, dict):
        raise ValidationError("批次可信度须为批次名称到数值的对应关系")
    for name, value in batches.items():
        if not batch_name(name) or batch_name(name) != name:
            raise ValidationError("可信度设置中的批次名称不能为空或带首尾空格")
        confidence_value(value)


def record_time(record):
    # Legacy records have only an update timestamp. Surface that approximation.
    value = record.get("performed_at") if "performed_at" in record else record.get("updated")
    return experiment_time(value)


def data_weights(template, records):
    """Reference the newest dated usable observation of this response, not wall time."""
    config = template.data.get("data_weighting", {})
    validate_weighting(config)
    half_life = config.get("recency_half_life_days", 0)
    confidence = config.get("batch_confidence", {})
    dates = [record_time(e) for e in records] if half_life else [None] * len(records)
    latest = max((datetime.fromisoformat(d) for d in dates if d), default=None)
    weights, details = [], []
    for record, stamp in zip(records, dates):
        batch = batch_name(record.get("experiment_batch", ""))
        base = confidence.get(batch, 1.)
        age = max(0., (latest - datetime.fromisoformat(stamp)).total_seconds() / 86400) if latest and stamp else 0.
        # Cap the exponent before exponentiation so tiny half-lives are safe.
        decay = 2. ** (-min(age / half_life, 1024.)) if half_life else 1.
        weight = max(MIN_WEIGHT, base * decay)
        weights.append(weight)
        details.append({"experiment_id": record.get("id"), "batch": batch,
                        "confidence": base, "performed_at": stamp, "age_days": age,
                        "weight": weight, "weight_floor_applied": base * decay < MIN_WEIGHT,
                        "legacy_time": bool(half_life and "performed_at" not in record),
                        "unknown_time": bool(half_life and stamp is None)})
    return weights, {"recency_half_life_days": half_life,
                     "reference_time": latest.isoformat() if latest else None,
                     "minimum_weight": MIN_WEIGHT, "records": details}
