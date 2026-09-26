"""Server-side geometry for the inline SVG portfolio chart."""

from decimal import Decimal


def chart_geometry(points, mode="value", width=760, height=260):
    values = [p["value_base"] if mode == "value" else p.get("cumulative_return") for p in points]
    finite = [Decimal(str(v)) for v in values if v is not None]
    if not finite:
        return {"width": width, "height": height, "segments": [], "gaps": [],
                "assumed": 0, "baseline": None, "markers": []}
    low, high = min(finite), max(finite)
    if mode == "return": low, high = min(low, Decimal("0")), max(high, Decimal("0"))
    if low == high: high += Decimal("1")
    def xy(index, value):
        x = 40 + (width - 56) * index / max(len(points) - 1, 1)
        y = 16 + (height - 42) * float((high - Decimal(str(value))) / (high - low))
        return round(x, 2), round(y, 2)
    segments, current, gaps = [], [], []
    for index, value in enumerate(values):
        if value is None:
            if current: segments.append(" ".join(f"{x},{y}" for x, y in current)); current = []
            gaps.append(index)
        else: current.append(xy(index, value))
    if current: segments.append(" ".join(f"{x},{y}" for x, y in current))
    baseline = xy(0, Decimal("0"))[1] if mode == "return" else None
    markers = []
    for index, point in enumerate(points):
        if point.get("transfers"):
            x = 40 + (width - 56) * index / max(len(points) - 1, 1)
            amount = sum(Decimal(str(row["net_amount"])) for row in point["transfers"])
            markers.append({"x": round(x, 2), "direction": "in" if amount >= 0 else "out", "amount": amount})
    assumed = sum(1 for point in points if point.get("assumed"))
    return {"width": width, "height": height, "segments": segments, "gaps": gaps,
            "assumed": assumed, "baseline": baseline, "markers": markers}
