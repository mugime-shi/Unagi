"""
Tests for ENTSO-E A77/A80 outage ingest (parser, pagination, upsert, withdrawn)
and the per-day view / GET /api/v1/generation/outages.
"""

import io
import zipfile
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.main import app
from app.models.generation_outage import GenerationOutage
from app.services import entsoe_client
from app.services.entsoe_client import EntsoEError, _parse_unavailability_xml, fetch_unavailability
from app.services.outage_service import fetch_and_store_outages, normalize_unit_name, outages_for_day
from app.utils.timezone import stockholm_day_range_utc

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

UTC = timezone.utc
SE3_EIC = "10Y1001A1001A46L"
NS = "urn:iec62325.351:tc57wg16:451-6:outagedocument:3:0"


def utc(*a) -> datetime:
    return datetime(*a, tzinfo=UTC)


def doc_xml(
    mrid="doc1",
    name="Ringhals 4",
    start="2026-10-06T08:00Z",
    end="2026-10-09T11:00Z",
    points=((1, 0),),
    resolution="PT1M",
    biz="A53",
    status=None,
    nominal=1134,
    psr="B14",
    reason="Test of new equipment.",
    zone=SE3_EIC,
) -> str:
    d, t = start.split("T")
    ed, et = end.split("T")
    pts = "".join(f"<Point><position>{p}</position><quantity>{q}</quantity></Point>" for p, q in points)
    status_xml = f"<docStatus><value>{status}</value></docStatus>" if status else ""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Unavailability_MarketDocument xmlns="{NS}">
  <mRID>{mrid}</mRID><revisionNumber>5</revisionNumber><type>A77</type>
  <createdDateTime>2026-10-05T06:57:06Z</createdDateTime>{status_xml}
  <TimeSeries>
    <mRID>1</mRID><businessType>{biz}</businessType>
    <biddingZone_Domain.mRID codingScheme="A01">{zone}</biddingZone_Domain.mRID>
    <start_DateAndOrTime.date>{d}</start_DateAndOrTime.date><start_DateAndOrTime.time>{t[:-1]}:00Z</start_DateAndOrTime.time>
    <end_DateAndOrTime.date>{ed}</end_DateAndOrTime.date><end_DateAndOrTime.time>{et[:-1]}:00Z</end_DateAndOrTime.time>
    <production_RegisteredResource.mRID codingScheme="A01">EIC-{name}</production_RegisteredResource.mRID>
    <production_RegisteredResource.name>{name}</production_RegisteredResource.name>
    <production_RegisteredResource.pSRType.psrType>{psr}</production_RegisteredResource.pSRType.psrType>
    <production_RegisteredResource.pSRType.powerSystemResources.nominalP unit="MAW">{nominal}.0</production_RegisteredResource.pSRType.powerSystemResources.nominalP>
    <Available_Period>
      <timeInterval><start>{start}</start><end>{end}</end></timeInterval>
      <resolution>{resolution}</resolution>{pts}
    </Available_Period>
    <Reason><code>A95</code><text>{reason}</text></Reason>
  </TimeSeries>
  <Reason><code>B19</code></Reason>
</Unavailability_MarketDocument>"""


def ack_xml(code="999", text="No matching data found") -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Acknowledgement_MarketDocument xmlns="urn:iec62325.351:tc57wg16:451-1:acknowledgementdocument:7:0">
  <mRID>x</mRID><Reason><code>{code}</code><text>{text}</text></Reason>
</Acknowledgement_MarketDocument>"""


def make_zip(xmls: list[str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for i, x in enumerate(xmls):
            zf.writestr(f"doc{i}.xml", x)
    return buf.getvalue()


def resp(content: bytes, status=200) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.content = content
    r.text = content[:200].decode("utf-8", "ignore")
    return r


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def db():
    s = TestingSessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def client(db):
    def override():
        yield db

    app.dependency_overrides[get_db] = override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def add_row(db, name="Ringhals 3", mrid=None, start=utc(2026, 10, 10), end=utc(2026, 10, 20), periods=None, **kw):
    nominal = kw.pop("nominal_mw", 1063)
    row = GenerationOutage(
        mrid=mrid or f"m-{name}-{start.isoformat()}-{end.isoformat()}",
        revision=1,
        document_type=kw.pop("document_type", "A77"),
        business_type=kw.pop("business_type", "A53"),
        status=kw.pop("status", "active"),
        area=kw.pop("area", "SE3"),
        resource_eic=kw.pop("resource_eic", f"EIC-{name}"),
        resource_name=name,
        psr_type=kw.pop("psr_type", "B14"),
        nominal_mw=nominal,
        start_utc=start,
        end_utc=end,
        available_periods=periods
        if periods is not None
        else [{"start": start.isoformat(), "end": end.isoformat(), "mw": 0.0}],
        reason_code="A95",
        reason_text=kw.pop("reason_text", "Revision"),
        last_seen_utc=utc(2026, 10, 1),
    )
    db.add(row)
    db.commit()
    return row


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def test_parse_basic_document():
    [o] = _parse_unavailability_xml(doc_xml())
    assert o["mrid"] == "doc1" and o["revision"] == 5 and o["document_type"] == "A77"
    assert o["business_type"] == "A53" and o["status"] == "active" and o["area"] == "SE3"
    assert o["resource_name"] == "Ringhals 4" and o["psr_type"] == "B14" and o["nominal_mw"] == 1134.0
    assert o["start_utc"] == utc(2026, 10, 6, 8) and o["end_utc"] == utc(2026, 10, 9, 11)
    assert o["available_periods"] == [
        {"start": "2026-10-06T08:00:00+00:00", "end": "2026-10-09T11:00:00+00:00", "mw": 0.0}
    ]
    assert o["reason_code"] == "A95" and o["reason_text"] == "Test of new equipment."
    assert o["created_utc"] == utc(2026, 10, 5, 6, 57, 6)


def test_parse_cancelled():
    [o] = _parse_unavailability_xml(doc_xml(status="A09"))
    assert o["status"] == "cancelled"


def test_parse_step_points_pt1m_to_periods():
    # 08:00 start, 1-min steps: 0 MW for 60 min, 500 for 30 min, 500 again (merged), then 900 until the end
    xml = doc_xml(start="2026-10-06T08:00Z", end="2026-10-06T10:00Z", points=[(1, 0), (61, 500), (76, 500), (91, 900)])
    [o] = _parse_unavailability_xml(xml)
    assert o["available_periods"] == [
        {"start": "2026-10-06T08:00:00+00:00", "end": "2026-10-06T09:00:00+00:00", "mw": 0.0},
        {"start": "2026-10-06T09:00:00+00:00", "end": "2026-10-06T09:30:00+00:00", "mw": 500.0},
        {"start": "2026-10-06T09:30:00+00:00", "end": "2026-10-06T10:00:00+00:00", "mw": 900.0},
    ]


def test_parse_pt15m_and_pt60m_resolution():
    xml = doc_xml(start="2026-10-06T08:00Z", end="2026-10-06T10:00Z", points=[(1, 100), (2, 200)], resolution="PT15M")
    [o] = _parse_unavailability_xml(xml)
    assert o["available_periods"][0]["end"] == "2026-10-06T08:15:00+00:00"
    xml = doc_xml(start="2026-10-06T08:00Z", end="2026-10-06T12:00Z", points=[(1, 100), (3, 200)], resolution="PT60M")
    [o] = _parse_unavailability_xml(xml)
    assert o["available_periods"][0] == {
        "start": "2026-10-06T08:00:00+00:00",
        "end": "2026-10-06T10:00:00+00:00",
        "mw": 100.0,
    }


def test_parse_ack_999_is_empty_and_other_ack_raises():
    assert _parse_unavailability_xml(ack_xml("999")) == []
    with pytest.raises(EntsoEError, match="401"):
        _parse_unavailability_xml(ack_xml("401", "Unauthorized"))


# ---------------------------------------------------------------------------
# fetch_unavailability (httpx mocked)
# ---------------------------------------------------------------------------


def _patch_get(responses):
    client = MagicMock()
    client.get.side_effect = responses
    cm = MagicMock()
    cm.__enter__.return_value = client
    return patch.object(entsoe_client.httpx, "Client", return_value=cm), client


def test_fetch_zip_and_params():
    p, client = _patch_get([resp(make_zip([doc_xml("a"), doc_xml("b", name="Forsmark block 1")]))])
    with p:
        out = fetch_unavailability("SE3", "A77", utc(2026, 10, 1), utc(2026, 10, 5, 12, 30), api_key="k")
    assert [o["mrid"] for o in out] == ["a", "b"]
    params = client.get.call_args.kwargs["params"]
    assert params["documentType"] == "A77" and params["biddingZone_Domain"] == SE3_EIC
    assert params["periodStart"] == "202610010000" and params["periodEnd"] == "202610051230"
    assert "offset" not in params and "businessType" not in params


def test_fetch_ack_999_returns_empty():
    p, _ = _patch_get([resp(ack_xml().encode())])
    with p:
        assert fetch_unavailability("SE1", "A80", utc(2026, 10, 1), utc(2026, 10, 5), api_key="k") == []


def test_fetch_non_999_ack_and_http_error_raise():
    p, _ = _patch_get([resp(ack_xml("400", "bad").encode())])
    with p, pytest.raises(EntsoEError):
        fetch_unavailability("SE1", "A80", utc(2026, 10, 1), utc(2026, 10, 5), api_key="k")
    p, _ = _patch_get([resp(b"oops", status=503)])
    with p, pytest.raises(EntsoEError, match="503"):
        fetch_unavailability("SE1", "A80", utc(2026, 10, 1), utc(2026, 10, 5), api_key="k")


def test_fetch_paginates_with_offset():
    page1 = make_zip([doc_xml(f"p1-{i}") for i in range(200)])
    page2 = make_zip([doc_xml(f"p2-{i}") for i in range(5)])
    p, client = _patch_get([resp(page1), resp(page2)])
    with p:
        out = fetch_unavailability("SE3", "A77", utc(2026, 10, 1), utc(2026, 10, 5), api_key="k")
    assert len(out) == 205
    assert client.get.call_count == 2
    assert client.get.call_args_list[1].kwargs["params"]["offset"] == 200


def test_fetch_page_of_exactly_200_then_ack():
    p, client = _patch_get([resp(make_zip([doc_xml(f"x{i}") for i in range(200)])), resp(ack_xml().encode())])
    with p:
        out = fetch_unavailability("SE3", "A77", utc(2026, 10, 1), utc(2026, 10, 5), api_key="k")
    assert len(out) == 200 and client.get.call_count == 2


# ---------------------------------------------------------------------------
# fetch_and_store_outages
# ---------------------------------------------------------------------------


def parsed(**kw) -> dict:
    return _parse_unavailability_xml(doc_xml(**kw))[0]


W_START, W_END = utc(2026, 10, 1), utc(2026, 12, 1)


def run_store(db, mapping, areas=("SE3",)):
    """mapping: (area, doc_type) -> list[dict] | Exception"""

    def fake(area, doc_type, s, e):
        v = mapping.get((area, doc_type), [])
        if isinstance(v, Exception):
            raise v
        return v

    with patch("app.services.outage_service.fetch_unavailability", side_effect=fake):
        return fetch_and_store_outages(db, W_START, W_END, list(areas))


def test_upsert_by_mrid_replaces_fields(db):
    run_store(db, {("SE3", "A77"): [parsed(mrid="d1", points=[(1, 0)])]})
    s = run_store(db, {("SE3", "A77"): [parsed(mrid="d1", points=[(1, 400)], reason="changed")]})
    rows = db.query(GenerationOutage).all()
    assert len(rows) == 1 and s["updated"] == 1 and s["inserted"] == 0
    assert rows[0].reason_text == "changed" and rows[0].available_periods[0]["mw"] == 400.0
    assert rows[0].last_seen_utc is not None


def test_cancelled_document_status(db):
    s = run_store(db, {("SE3", "A77"): [parsed(mrid="d1", status="A09")]})
    assert db.query(GenerationOutage).one().status == "cancelled" and s["cancelled"] == 1


def test_missing_active_doc_is_withdrawn(db):
    run_store(db, {("SE3", "A77"): [parsed(mrid="old"), parsed(mrid="keep", name="Ringhals 3")]})
    s = run_store(db, {("SE3", "A77"): [parsed(mrid="keep", name="Ringhals 3")]})
    st = {r.mrid: r.status for r in db.query(GenerationOutage)}
    assert st == {"old": "withdrawn", "keep": "active"} and s["withdrawn"] == 1


def test_withdrawn_only_for_fetched_area_and_window(db):
    add_row(db, mrid="se4row", area="SE4", start=utc(2026, 10, 10), end=utc(2026, 10, 12))  # other area, not fetched
    add_row(db, mrid="past", start=utc(2026, 8, 1), end=utc(2026, 8, 5))  # outside the window
    add_row(db, mrid="cancelled-one", status="cancelled")
    run_store(db, {("SE3", "A77"): []})
    st = {r.mrid: r.status for r in db.query(GenerationOutage)}
    assert st == {"se4row": "active", "past": "active", "cancelled-one": "cancelled"}


def test_failed_fetch_does_not_withdraw_and_does_not_stop_others(db):
    add_row(db, mrid="se3row")
    s = run_store(
        db,
        {("SE3", "A77"): EntsoEError("boom"), ("SE4", "A77"): [parsed(mrid="se4")]},
        areas=("SE3", "SE4"),
    )
    assert db.query(GenerationOutage).filter_by(mrid="se3row").one().status == "active"
    assert db.query(GenerationOutage).filter_by(mrid="se4").count() == 1
    assert s["errors"] == 1 and "SE3/A77" in s["failures"][0]


# ---------------------------------------------------------------------------
# outages_for_day
# ---------------------------------------------------------------------------

DAY = date(2026, 10, 15)


def unit(res, name):
    return next(u for u in res["nuclear"] if u["name"] == name)


def test_empty_db_all_six_running(db):
    res = outages_for_day(db, DAY)
    assert [u["name"] for u in res["nuclear"]] == [
        "Forsmark 1",
        "Forsmark 2",
        "Forsmark 3",
        "Ringhals 3",
        "Ringhals 4",
        "Oskarshamn 3",
    ]
    assert all(
        u["status"] == "running" and u["outage"] is None and u["available_mw"] == u["nominal_mw"]
        for u in res["nuclear"]
    )
    assert res["nuclear_offline_mw"] == 0 and res["other"] == [] and res["date"] == "2026-10-15"


def test_offline_reduced_and_name_normalisation(db):
    add_row(
        db, name="Forsmark block 1", nominal_mw=1100, start=utc(2026, 10, 1), end=utc(2026, 10, 30), business_type="A54"
    )
    add_row(
        db,
        name="Ringhals 3",
        periods=[{"start": utc(2026, 10, 10).isoformat(), "end": utc(2026, 10, 20).isoformat(), "mw": 800.0}],
    )
    res = outages_for_day(db, DAY)
    f1, r3 = unit(res, "Forsmark 1"), unit(res, "Ringhals 3")
    assert f1["status"] == "offline" and f1["available_mw"] == 0 and f1["outage"]["type"] == "forced"
    assert f1["outage"]["reason"] == "Revision"
    assert r3["status"] == "reduced" and r3["available_mw"] == 800
    assert res["nuclear_offline_mw"] == 1100 + (1063 - 800)


def test_cancelled_and_withdrawn_ignored(db):
    add_row(db, name="Ringhals 4", nominal_mw=1134, status="cancelled")
    add_row(db, name="Ringhals 3", status="withdrawn")
    res = outages_for_day(db, DAY)
    assert res["nuclear_offline_mw"] == 0


def test_overlapping_planned_and_forced_takes_min_latest_end_on_tie(db):
    add_row(
        db,
        name="Ringhals 4",
        nominal_mw=1134,
        mrid="planned",
        business_type="A53",
        periods=[{"start": utc(2026, 10, 10).isoformat(), "end": utc(2026, 10, 25).isoformat(), "mw": 500.0}],
        start=utc(2026, 10, 10),
        end=utc(2026, 10, 25),
        reason_text="planned",
    )
    add_row(
        db,
        name="Ringhals 4",
        nominal_mw=1134,
        mrid="forced",
        business_type="A54",
        periods=[{"start": utc(2026, 10, 14).isoformat(), "end": utc(2026, 10, 16).isoformat(), "mw": 0.0}],
        start=utc(2026, 10, 14),
        end=utc(2026, 10, 16),
        reason_text="forced",
    )
    u = unit(outages_for_day(db, DAY), "Ringhals 4")
    assert u["available_mw"] == 0 and u["outage"]["type"] == "forced"
    # tie on 0 MW: latest end wins
    add_row(
        db,
        name="Ringhals 4",
        nominal_mw=1134,
        mrid="forced2",
        business_type="A54",
        periods=[{"start": utc(2026, 10, 14).isoformat(), "end": utc(2026, 10, 18).isoformat(), "mw": 0.0}],
        start=utc(2026, 10, 14),
        end=utc(2026, 10, 18),
        reason_text="forced2",
    )
    u = unit(outages_for_day(db, DAY), "Ringhals 4")
    assert u["outage"]["reason"] == "forced2"


def test_min_only_over_part_inside_day(db):
    # Deep dip 0 MW happens on Oct 16 only; on Oct 15 the unit is at 600
    add_row(
        db,
        name="Oskarshamn 3",
        nominal_mw=1400,
        start=utc(2026, 10, 10),
        end=utc(2026, 10, 20),
        periods=[
            {"start": utc(2026, 10, 10).isoformat(), "end": utc(2026, 10, 16).isoformat(), "mw": 600.0},
            {"start": utc(2026, 10, 16).isoformat(), "end": utc(2026, 10, 20).isoformat(), "mw": 0.0},
        ],
    )
    assert unit(outages_for_day(db, DAY), "Oskarshamn 3")["available_mw"] == 600
    assert unit(outages_for_day(db, date(2026, 10, 17)), "Oskarshamn 3")["available_mw"] == 0


def test_stockholm_day_boundary_cest(db):
    # 2026-10-15 is CEST: Stockholm day = 2026-10-14T22:00Z .. 2026-10-15T22:00Z
    add_row(
        db, name="Forsmark 2", nominal_mw=1121, start=utc(2026, 10, 14, 21), end=utc(2026, 10, 14, 22)
    )  # ends at day start
    assert unit(outages_for_day(db, DAY), "Forsmark 2")["status"] == "running"
    add_row(db, name="Forsmark 3", nominal_mw=1172, start=utc(2026, 10, 15, 21, 59), end=utc(2026, 10, 15, 23))
    assert unit(outages_for_day(db, DAY), "Forsmark 3")["status"] == "offline"
    add_row(db, name="Ringhals 3", start=utc(2026, 10, 15, 22), end=utc(2026, 10, 16))  # starts at day end
    assert unit(outages_for_day(db, DAY), "Ringhals 3")["status"] == "running"


def test_stockholm_day_boundary_dst_25h_day(db):
    day = date(2026, 10, 25)
    s, e = stockholm_day_range_utc(day)
    assert e - s == timedelta(hours=25) and s == utc(2026, 10, 24, 22) and e == utc(2026, 10, 25, 23)
    # outage entirely in the extra 25th hour (23:00-24:00 Stockholm = 22:00Z-23:00Z) still belongs to this day
    add_row(db, name="Ringhals 4", nominal_mw=1134, start=utc(2026, 10, 25, 22, 30), end=utc(2026, 10, 25, 23))
    assert unit(outages_for_day(db, day), "Ringhals 4")["status"] == "offline"
    # ...and not to the next day
    assert unit(outages_for_day(db, date(2026, 10, 26)), "Ringhals 4")["status"] == "running"


def test_other_outages_threshold_and_sorting(db):
    add_row(
        db,
        name="Big Hydro",
        nominal_mw=800,
        area="SE2",
        psr_type="B12",
        resource_eic="E1",
        periods=[{"start": utc(2026, 10, 10).isoformat(), "end": utc(2026, 10, 20).isoformat(), "mw": 100.0}],
    )  # 700 down
    add_row(
        db,
        name="Edge",
        nominal_mw=500,
        area="SE3",
        psr_type="B04",
        resource_eic="E2",
        periods=[{"start": utc(2026, 10, 10).isoformat(), "end": utc(2026, 10, 20).isoformat(), "mw": 200.0}],
    )  # 300 down: in
    add_row(
        db,
        name="Small",
        nominal_mw=500,
        area="SE3",
        psr_type="B04",
        resource_eic="E3",
        periods=[{"start": utc(2026, 10, 10).isoformat(), "end": utc(2026, 10, 20).isoformat(), "mw": 201.0}],
    )  # 299: out
    add_row(
        db,
        name="Huge Wind",
        nominal_mw=1000,
        area="SE1",
        psr_type="B19",
        resource_eic="E4",
        periods=[{"start": utc(2026, 10, 10).isoformat(), "end": utc(2026, 10, 20).isoformat(), "mw": 0.0}],
    )
    other = outages_for_day(db, DAY)["other"]
    assert [o["name"] for o in other] == ["Huge Wind", "Big Hydro", "Edge"]
    assert other[1]["available_mw"] == 100 and other[1]["area"] == "SE2" and other[1]["outage"]["type"] == "planned"


def _periods(mw):
    return [{"start": utc(2026, 10, 10).isoformat(), "end": utc(2026, 10, 20).isoformat(), "mw": mw}]


def test_other_outages_default_filters_small_and_min_mw_zero_includes(db):
    add_row(db, name="Tiny", nominal_mw=100, resource_eic="EIC-TINY", periods=_periods(50.0))  # 50 down
    add_row(db, name="Healthy", nominal_mw=100, resource_eic="EIC-OK", periods=_periods(100.0))  # 0 down
    assert outages_for_day(db, DAY)["other"] == []
    other = outages_for_day(db, DAY, min_mw=0)["other"]
    assert [o["name"] for o in other] == ["Tiny"]
    assert other[0]["resource_eic"] == "EIC-TINY"


def test_normalize_unit_name():
    assert normalize_unit_name("Forsmark block 1") == normalize_unit_name("Forsmark 1") == "forsmark 1"
    assert normalize_unit_name(None) == ""


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


def test_endpoint_shape(client, db):
    add_row(db, name="Ringhals 3", nominal_mw=1063)
    res = client.get("/api/v1/generation/outages", params={"date": "2026-10-15"})
    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"date", "nuclear", "nuclear_offline_mw", "other"}
    assert body["date"] == "2026-10-15" and len(body["nuclear"]) == 6
    r3 = next(u for u in body["nuclear"] if u["name"] == "Ringhals 3")
    assert r3["status"] == "offline" and r3["outage"]["type"] == "planned"
    assert set(r3) == {"name", "area", "nominal_mw", "status", "available_mw", "outage"}
    assert body["nuclear_offline_mw"] == 1063


def test_endpoint_min_mw(client, db):
    add_row(db, name="Tiny", nominal_mw=100, resource_eic="EIC-TINY", periods=_periods(50.0))
    p = {"date": "2026-10-15"}
    assert client.get("/api/v1/generation/outages", params=p).json()["other"] == []
    res = client.get("/api/v1/generation/outages", params={**p, "min_mw": 0})
    assert res.status_code == 200
    assert res.json()["other"][0]["resource_eic"] == "EIC-TINY"
    assert client.get("/api/v1/generation/outages", params={**p, "min_mw": -1}).status_code == 422


def test_endpoint_default_today_and_bad_date(client):
    assert client.get("/api/v1/generation/outages").status_code == 200
    assert client.get("/api/v1/generation/outages", params={"date": "not-a-date"}).status_code == 422


# ---------------------------------------------------------------------------
# Scheduler wiring
# ---------------------------------------------------------------------------


def test_scheduler_helper_never_raises():
    from app.tasks import fetch_prices as fp

    with patch.object(fp, "fetch_and_store_outages", side_effect=RuntimeError("db down")):
        r = fp._fetch_outages()
    assert r["status"] == "error" and r["market"] == "outages"


def test_backfill_outages_event_runs_only_outages():
    from app.tasks import fetch_prices as fp

    with (
        patch.object(fp, "_fetch_outages", return_value={"market": "outages", "status": "ok"}) as m,
        patch.object(fp, "fetch_dates") as prices,
    ):
        out = fp.lambda_handler({"backfill_outages": 90}, None)
    m.assert_called_once()
    assert m.call_args.kwargs["past_days"] == 90
    prices.assert_not_called()
    assert out["mode"] == "backfill_outages" and out["statusCode"] == 200
