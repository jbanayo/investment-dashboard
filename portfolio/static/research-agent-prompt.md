# Investment research JSON prompt

Research **[INSTRUMENT NAME]** (**[TICKER]**) for a personal portfolio review.

Use current, public sources. Prefer company filings, investor-relations releases,
exchange or regulator disclosures, earnings materials, then reputable financial
news. Separate facts from interpretation. Do not invent targets, consensus, or
citations. Include material risks and conflicting evidence. This is research,
not financial advice.

Return **only valid JSON** matching this shape. Use `null` when a value is not
supported by evidence. Use an empty array only when no verifiable sources are
available.

```json
{
  "stance": "buy | hold | reduce | sell | watch | avoid",
  "summary": "A concise, balanced thesis.",
  "supporting_points": ["Source-backed point"],
  "risks": ["Material risk"],
  "confidence": "low | medium | high",
  "confidence_reason": "Why confidence is limited or supported.",
  "time_horizon": "Example: 6–12 months",
  "trigger_type": "none | at_or_below | at_or_above | event",
  "trigger_price": null,
  "trigger_currency": null,
  "event_trigger": null,
  "source_target": null,
  "source_target_currency": null,
  "source_target_issuer": null,
  "sources": [
    {
      "title": "Source title",
      "publisher": "Publisher",
      "url": "https://example.com/source",
      "published_at": "YYYY-MM-DD or null",
      "source_type": "filing | company | exchange | news | research | other"
    }
  ]
}
```
