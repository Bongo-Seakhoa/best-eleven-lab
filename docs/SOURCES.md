# Sources and attribution

Source contracts were inspected for the build on 9 October 2026. Some web responses were cached; no claim is made that cached fixture counts or schema text establish current dataset completeness. The build environment could read the documentation but could not retrieve the bulk ZIPs.

| Source | Use | Boundary |
|---|---|---|
| [Cricsheet downloads](https://cricsheet.org/downloads) | National and league archive discovery; the source manifest uses the published archive patterns, including SA20 `sat_male_json.zip`. | A supported URL is not proof of a successful fetch or full fixture coverage. |
| [Cricsheet JSON format](https://cricsheet.org/format/json) | Delivery, extras, wicket, registry, innings and metadata semantics. | This project reviews 1.0.0/1.1.0 only. It does not infer tracking or captaincy records absent from the source. |
| [Cricsheet coverage](https://cricsheet.org/coverage/) | Coverage limitations and future fixture-reconciliation planning. | Not an all-time database and not automatically complete for every country and period. |
| [Cricsheet people register](https://cricsheet.org/register/) | Stable-identity and external-identifier enrichment design. | The external full register is not downloaded by this release; per-match registry IDs are used. Physical styles need separate sourced metadata. |
| [SciPy MILP documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.milp.html) | Integer optimization API, constraints and termination status. | Solver optimality refers to the declared model, not cricket truth. |

The synthetic generator, example player names, demo match outcomes and rendered demonstration statistics are original fictional material. They are not Cricsheet observations. Unit fixtures are also invented and isolated to temporary test databases. References to real players in the research protocol are questions, not asserted findings.
