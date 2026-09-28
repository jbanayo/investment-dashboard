---
format_version: 1
instrument: "[INSTRUMENT NAME]"
ticker: "[TICKER]"
research_date: YYYY-MM-DD
stance: hold
confidence: medium
time_horizon: "6-12 months"
trigger_type: none
---

# Thesis

Write a concise, balanced thesis that separates verified facts from interpretation.

## Supporting points

- Add a source-backed supporting point.
- Add another supporting point when the evidence supports it.

## Risks

- Add a material risk or condition that would weaken the thesis.

## Sources

- [Source title](https://example.com/source) — Publisher | YYYY-MM-DD | company

<!--
Allowed stance values: buy, hold, reduce, sell, watch, avoid.
Allowed confidence values: low, medium, high.
Allowed trigger_type values: none, at_or_below, at_or_above, event.

For at_or_below or at_or_above, add these frontmatter fields:
trigger_price: 250
trigger_currency: USD

For event, add this frontmatter field:
event_trigger: "Describe the event that should prompt a review."

Allowed source types: filing, company, exchange, news, research, other.
Use one source per line in the displayed format. Publication date may be omitted
when it is unavailable.
-->
