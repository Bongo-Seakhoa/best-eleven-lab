"""Fail-closed data gate for future field-policy research. This is not a field optimiser."""
REQUIRED = {"match_id", "innings", "ordinal", "field_before", "shot_trajectory", "delivery_context", "outcome", "capture_status"}


def assess_spatial_evidence(records, expected_delivery_ids=None):
    if not records:
        return {"status": "unavailable", "recommendations": [], "reason": "No spatial tracking records have been supplied."}
    problems, ids = [], set()
    for r in records:
        missing = REQUIRED - r.keys()
        if missing:
            problems.append("Required fields absent: " + ", ".join(sorted(missing)))
            continue
        key = (str(r["match_id"]), int(r["innings"]), int(r["ordinal"]))
        if key in ids:
            problems.append("Duplicate delivery identity")
        ids.add(key)
        if r["capture_status"] != "observed":
            problems.append("Missing or outcome-selected capture")
        if not isinstance(r["field_before"], list) or len(r["field_before"]) != 11:
            problems.append("Complete pre-delivery field, including bowler and keeper, is required")
    if expected_delivery_ids is None:
        problems.append("No independently defined delivery universe; capture completeness is unknown")
    elif ids != set(expected_delivery_ids):
        problems.append("Spatial records do not cover the full expected delivery universe")
    return {"status": "blocked" if problems else "research_inputs_present", "recommendations": [], "problems": sorted(set(problems)),
        "reason": "Complete tracking alone does not identify the effect of changing a field. Validate legality, overlap, logging policy and confounding before causal recommendations."}
