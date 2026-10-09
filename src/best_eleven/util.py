from dataclasses import asdict, is_dataclass
import json
import math
import numpy as np


def clean(value):
    if is_dataclass(value):
        return clean(asdict(value))
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [clean(v) for v in value]
    if isinstance(value, np.generic):
        return clean(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def dumps(value, **kwargs):
    return json.dumps(clean(value), allow_nan=False, ensure_ascii=False, **kwargs)
