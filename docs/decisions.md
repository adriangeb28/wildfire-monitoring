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

## Scope and coverage (confirmed against the Team Project Assignment)

- **Team 3 may choose a global scope, a region, or Colombia.** Colombia is
  therefore confirmed, and it is covered by all four sources: NASA FIRMS and
  Open-Meteo are both listed as **global** sources in the assignment.
- **Explicit exclusions** (required section of the report):
  - **No US-only sources.** NWS observations/forecasts/alerts, NOAA GHCN-Daily,
    NOAA Storm Events and USGS hazard products are out of scope: they contain no
    data for Colombia. This is why the incremental weather source is the
    Open-Meteo Forecast API and not NWS.
  - **No Colombian national sources adopted at this stage.** Servicio Geológico
    Colombiano, IDEAM and UNGRD are welcome as *additional* sources, but the
    assignment requires their **programmatic access to be demonstrated in
    Workshop 1 before they are adopted**. They are not part of the four
    validated sources: adopting one without evidence would put 5 of the 20
    points at risk.
  - **No burned-area products** and no Global Forest Watch: not part of the
    assigned source set.
  - **No prediction.** The system describes anomalous activity; it does not
    forecast fires.

## Open questions

- [ ] Decide between ERA5 (0.25°) and ERA5-Land (0.1°) as the weather baseline
      (both are available; the choice must be documented and kept fixed).
- [ ] Decide whether the recent weather comes from the Forecast API `past_days`
      or from the Historical Forecast API (model must match to avoid a seam).
