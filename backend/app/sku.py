"""Turn Tally stock item names into SKU attributes: oil family, pack type, pack size
and kg of oil per billing unit. Item names carry the pack size ("1LT POUCH BOX",
"15KGS TINS", "5LT PC"); boxes carry units-per-box in altquantity."""
import re
from functools import lru_cache

import numpy as np
import pandas as pd

from . import config

_SIZE_RE = re.compile(r"(?<![\d/\\])(\d+(?:\.\d+)?)\s*(LTRS?|LTS?|LT|L|KGS?|KG)\b")
_HALF_RE = re.compile(r"1\s*[/\\]\s*2\s*(LTRS?|LTS?|LT|L|KGS?|KG)\b")


def _clean(s):
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return ""
    s = str(s).strip()
    return "" if s.upper() in ("[NULL]", "NONE", "NAN") else s


def oil_family(stockgroup, item):
    g = _clean(stockgroup).upper()
    if g in config.OIL_FAMILY_BY_GROUP:
        return config.OIL_FAMILY_BY_GROUP[g]
    name = (_clean(item) + " " + g).upper()
    if "SEED" in name and ("GROUND" in name or "GROUD" in name):
        return "Groundnut seed"
    for kw, fam in config.OIL_FAMILY_KEYWORDS:
        if kw in name:
            return fam
    return "Other"


@lru_cache(maxsize=4096)
def parse_item(item: str):
    """Return dict(size, measure, pack_type, is_box, is_pet) from an item name."""
    n = _clean(item).upper().replace("\\", "/")
    size = measure = None
    m = _HALF_RE.search(n)
    if m:
        size, measure = 0.5, ("KG" if m.group(1).startswith("K") else "L")
    else:
        m = _SIZE_RE.search(n)
        if m:
            size = float(m.group(1))
            measure = "KG" if m.group(2).startswith("K") else "L"
    is_box = bool(re.search(r"\bBOX\b", n))
    is_pet = "PET" in n
    if "POUCH" in n or re.search(r"\bP\s+BOX\b", n):   # "1/2 LT P BOX" = half-litre pouch box
        inner = "Pouch"
    elif is_pet:
        inner = "PET bottle"
    elif re.search(r"\bPC\b|PLASTIC CAN|\bCANS?\b", n):
        inner = "Plastic can"
    elif "TIN" in n:
        inner = "Tin"
    elif "PACK" in n:
        inner = "Pack"
    else:
        inner = None
    return {"size": size, "measure": measure, "inner": inner, "is_box": is_box, "is_pet": is_pet}


def _size_label(size, measure):
    if size is None:
        return "Loose"
    s = "½" if size == 0.5 else (f"{size:g}")
    return f"{s} {'L' if measure == 'L' else 'kg'}"


def sku_attributes(item, uom, alt_per_unit=None):
    """Attributes for one (item, uom) pair. alt_per_unit = altquantity/quantity on box lines."""
    p = parse_item(_clean(item))
    uom = _clean(uom).upper()
    if uom in ("KGS", "KG") and not p["is_box"] and p["size"] is None:
        return {"pack_type": "Loose (kg)", "pack_size": "Loose", "units_per_box": 1, "kg_per_unit": 1.0}
    size, measure = p["size"], p["measure"]
    unit_kg = None
    if size is not None:
        unit_kg = size * (config.KG_PER_LITRE if measure == "L" else 1.0)
    if uom in ("KGS", "KG"):  # e.g. "GROUDNUT SEED 1 KG PACK" billed per kg
        return {"pack_type": (p["inner"] or "Pack"), "pack_size": _size_label(size, measure),
                "units_per_box": 1, "kg_per_unit": 1.0}
    if p["is_box"] or uom == "BOX":
        upb = None
        if alt_per_unit and alt_per_unit > 1:
            upb = round(float(alt_per_unit))
        if not upb and size is not None:
            table = config.DEFAULT_UNITS_PER_BOX_PET if p["is_pet"] else config.DEFAULT_UNITS_PER_BOX
            upb = table.get(size)
        inner = p["inner"] or ("Pack" if size else None)
        label = f"{_size_label(size, measure)} {inner.lower() if inner else ''} box".replace("  ", " ")
        return {"pack_type": "Box", "pack_size": label.strip(), "units_per_box": upb,
                "kg_per_unit": (unit_kg * upb) if (unit_kg and upb) else None}
    return {"pack_type": p["inner"] or "Unit", "pack_size": _size_label(size, measure),
            "units_per_box": 1, "kg_per_unit": unit_kg}


def enrich(df, item_col="stockitemname", group_col="stockgroupl1", uom_col="actualuom",
           qty_col="quantity", altqty_col="altquantity"):
    """Add oil_family, pack_type, pack_size, kg_per_unit and kg columns to a line-level frame."""
    df = df.copy()
    if df.empty:
        for c in ("oil_family", "pack_type", "pack_size", "kg_per_unit", "kg"):
            df[c] = pd.Series(dtype="object")
        return df
    q = pd.to_numeric(df.get(qty_col), errors="coerce")
    alt = pd.to_numeric(df.get(altqty_col), errors="coerce") if altqty_col in df else pd.Series(np.nan, index=df.index)
    alt_per = (alt.abs() / q.abs()).where(q.abs() > 0)
    # one units-per-box value per item (most common ratio), so lines without altqty still convert
    tmp = pd.DataFrame({"item": df[item_col].map(_clean), "uom": df[uom_col].map(_clean).str.upper(), "ap": alt_per.round(0)})
    upb = (tmp[tmp.ap > 1].groupby(["item", "uom"]).ap.agg(lambda s: s.mode().iloc[0]))
    keys = tmp[["item", "uom"]].drop_duplicates()
    rows = []
    for item, uom in keys.itertuples(index=False):
        a = upb.get((item, uom))
        rows.append({"item": item, "uom": uom, **sku_attributes(item, uom, a)})
    attrs = pd.DataFrame(rows)
    merged = tmp[["item", "uom"]].merge(attrs, on=["item", "uom"], how="left")
    merged.index = df.index
    df["pack_type"] = merged["pack_type"]
    df["pack_size"] = merged["pack_size"]
    df["kg_per_unit"] = pd.to_numeric(merged["kg_per_unit"], errors="coerce")
    df["oil_family"] = [oil_family(g, i) for g, i in zip(df.get(group_col, pd.Series("", index=df.index)), df[item_col])]
    df["kg"] = q * df["kg_per_unit"]
    return df
