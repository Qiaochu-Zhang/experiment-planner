"""Synthetic demonstration only; no physical accuracy claim."""
import random


def synthetic_records(template, count=12, seed=17):
    rng = random.Random(seed)
    rows = []
    for i in range(count):
        condition = {p["name"]: rng.uniform(*p["bounds"]) for p in template.parameters}
        a = 5 + .2*condition["cl2_sccm"] + .025*condition["icp_w"] + .04*condition["etch_time_s"]
        b = 1 + .06*condition["rf_w"] + .03*condition["bcl3_sccm"]
        measurements = {"sio2_initial_nm":150., "sin_initial_nm":100., "sio2_remaining_nm":150-a, "sin_remaining_nm":100-b}
        rows.append({"conditions":condition,"observations":{n:{"value":v,"unit":"nm","uncertainty":{"kind":"std","amount":.2}} for n,v in measurements.items()},"note":f"合成案例 {i+1}，不代表机台物理规律"})
    return rows
