# Workshop 1 — Decisions

Short, dated record of the decisions this project is built on. Every later
workshop inherits them, so changes here are expensive.

| # | Decision | Value | Why |
|---|---|---|---|
| 1 | Geographic scope | **Colombia** — 33 regions (32 departments + Bogotá D.C.) | The indicator is "per region": we need comparable administrative units covered by all four sources. |
| 2 | Historical window | **2018-01-01 → present** (primary baseline) + 2000/2012 → present as per-sensor context | VIIRS NOAA-20 is the only sensor that is both long-lived and still producing data. |
| 3 | Timezone | **UTC everywhere** (storage, joins, aggregation) | FIRMS reports UTC; Open-Meteo returns local time unless `timezone=UTC` is passed. Mixing them shifts events by 5 hours. |
| 4 | Units | FRP **MW**, brightness **K**, precipitation **mm**, wind **km/h**, temperature **°C**, VPD **kPa** | Physical units of each source, declared once. |
| 5 | Baseline unit | **Per sensor and per region**, never pooled raw | MODIS (~1 km) and VIIRS (375 m) detect different numbers of fires for the same day. |
| 6 | Indicator | Anomaly **conditioned on weather**: observed / expected given weather, expressed as a historical percentile | The assignment asks for "unusual relative to historical patterns and weather conditions". |
| 7 | Claim boundary | Describes anomalies; **does not predict fires** | Required by the workshop guidelines ("do not over-claim"). |

## Open questions

- [ ] Confirm the scope with the professor if the *Team Project Assignment*
      mentions a required scope for Team 3.
- [ ] Decide between ERA5 (0.25°) and ERA5-Land (0.1°) as the weather baseline
      (both are available; the choice must be documented and kept fixed).
- [ ] Decide whether the recent weather comes from the Forecast API `past_days`
      or from the Historical Forecast API (model must match to avoid a seam).
