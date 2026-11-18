"""Unit tests for the parts that do not need the database.
Run:  cd backend && pytest -q
Set DEMO_EXCEL to the Excel extract to also run the end-to-end smoke test."""
import os

import numpy as np
import pandas as pd
import pytest

from app import sku
from app.kpi import receivables as R
from app.kpi.forecast import _scenario, holt


@pytest.mark.parametrize("item,uom,alt,expect_kg,pack", [
    ("KURNOOL GROUND NUT DOUBLE FILTER OIL  1LT POUCH BOX", "BOX", 16, 14.56, "Box"),
    ("KURNOOL GROUND NUT DOUBLE FILTER OIL 1/2 LT P BOX", "BOX", 32, 14.56, "Box"),
    ("KURNOOL GROUND NUT DOUBLE FILTER OIL  15KGS TINS", "NOS", None, 15.0, "Tin"),
    ("KURNOOL REFINED SUNFLOWER OIL TINS 15LT", "NOS", None, 13.65, "Tin"),
    ("KURNOOL GROUND NUT DOUBLE FILTER OIL  5LT PC", "NOS", None, 4.55, "Plastic can"),
    ("KURNOOL GROUND NUT DOUBLE FILTER OIL  1LT POUCHES", "NOS", None, 0.91, "Pouch"),
    ("SUNFLOWER REFINED OIL", "KGS", None, 1.0, "Loose (kg)"),
    ("KURNOOL PLUS MULTI SOUCE EDIBLE OIL 5 LT BOX", "BOX", None, 18.2, "Box"),   # default 4 per box
])
def test_sku_kg(item, uom, alt, expect_kg, pack):
    a = sku.sku_attributes(item, uom, alt)
    assert a["pack_type"] == pack
    assert a["kg_per_unit"] == pytest.approx(expect_kg, rel=1e-6)


def test_oil_family():
    assert sku.oil_family("GROUNDNUT DOUBLE FILTERED OIL", "x") == "Groundnut"
    assert sku.oil_family(None, "SURYA OIL 1 LT POUCH") == "Rice bran"
    assert sku.oil_family(None, "KURNOOL PLUS MULTI SOURCE EDIBLE 15 KG TIN") == "Vegetable (blended)"


def test_buckets():
    assert R.bucket(0) == "Not due"
    assert R.bucket(15) == "1-30 days"
    assert R.bucket(200) == "180+ days"


def test_scenario_uses_last_year_shape():
    # two years of weekly data with a clear seasonal bump in week 60-63 of the series
    base = np.full(110, 100.0)
    base[60:64] = 200.0      # last year's bump, 52 weeks before weeks 112-115
    s = pd.Series(base)
    f, lo, hi, yrs = _scenario(s, horizon=12, max_years=1, level_weeks=8)
    assert yrs == 1
    assert f[2] == pytest.approx(200.0, rel=0.05) and f[0] == pytest.approx(100.0, rel=0.05)
    assert (lo <= f).all() and (hi >= f).all()


def test_holt_trend():
    f, trend = holt(pd.Series([100, 102, 104, 106, 108]), 2)
    assert trend > 0 and f[1] > f[0] > 108


@pytest.mark.skipif(not os.getenv("DEMO_EXCEL"), reason="set DEMO_EXCEL to run the end-to-end check")
def test_all_routes_on_demo_data():
    from app.api import ROUTES, handle
    for path in ROUTES:
        status, body = handle(path, {})
        assert status == 200, (path, body)
