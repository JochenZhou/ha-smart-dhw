"""Standalone logic tests for Smart DHW (no Home Assistant required).

Run:  python3 tests/test_logic.py
"""

from __future__ import annotations

import pathlib
import sys
import types

_ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = _ROOT / "smart_dhw"
if not SRC.is_dir():  # 仓库布局：custom_components/smart_dhw
    SRC = _ROOT / "custom_components" / "smart_dhw"
_pkg = types.ModuleType("smart_dhw")
_pkg.__path__ = [str(SRC)]  # type: ignore[attr-defined]
sys.modules["smart_dhw"] = _pkg

from smart_dhw import const as C  # noqa: E402
from smart_dhw.table import (  # noqa: E402
    KIND_BATH,
    KIND_DAILY,
    BandTracker,
    DhwProfile,
    band_index,
    indoor_trim,
    parse_temperature,
    resolve_band,
)

FAILURES: list[str] = []
CHECKS = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        FAILURES.append(f"{name} :: {detail}")


def eq(name: str, got, want) -> None:
    check(name, got == want, f"got {got!r}, want {want!r}")


# --------------------------------------------------------------------------- #
# 1. band boundaries
# --------------------------------------------------------------------------- #
eq("band 28.0 → hot", resolve_band(28.0)["id"], "hot")
eq("band 27.9 → warm", resolve_band(27.9)["id"], "warm")
eq("band 22.0 → warm", resolve_band(22.0)["id"], "warm")
eq("band 15.0 → mild", resolve_band(15.0)["id"], "mild")
eq("band 8.0 → cool", resolve_band(8.0)["id"], "cool")
eq("band 7.9 → cold", resolve_band(7.9)["id"], "cold")
eq("band -30 → cold", resolve_band(-30.0)["id"], "cold")
eq("band_index monotonic", [band_index(t) for t in (30, 25, 20, 10, 0)], [0, 1, 2, 3, 4])

# --------------------------------------------------------------------------- #
# 2. temperature parsing — the humidity-sensor bug
# --------------------------------------------------------------------------- #
eq(
    "reject humidity-as-temperature",
    parse_temperature("36.0", {"unit_of_measurement": "%", "device_class": "humidity"}),
    None,
)
eq(
    "reject plain number without unit",
    parse_temperature("36.0", {"unit_of_measurement": None}),
    None,
)
eq(
    "accept temperature entity",
    parse_temperature(
        "29.3", {"unit_of_measurement": "°C", "device_class": "temperature"}
    ),
    29.3,
)
eq("accept unit-only celsius", parse_temperature("21.5", {"unit_of_measurement": "°C"}), 21.5)
eq("reject fahrenheit", parse_temperature("85", {"unit_of_measurement": "°F"}), None)
eq("reject unknown", parse_temperature("unknown", {"unit_of_measurement": "°C"}), None)
eq("reject unavailable", parse_temperature("unavailable", {"unit_of_measurement": "°C"}), None)
eq("reject empty", parse_temperature("", {"unit_of_measurement": "°C"}), None)
eq("reject implausible high", parse_temperature("999", {"unit_of_measurement": "°C"}), None)
eq("reject implausible low", parse_temperature("-80", {"unit_of_measurement": "°C"}), None)
eq("reject None state", parse_temperature(None, {}), None)

# --------------------------------------------------------------------------- #
# 3. indoor trim (unchanged semantics)
# --------------------------------------------------------------------------- #
eq("trim off", indoor_trim(10.0, 10.0, False), 0)
eq("trim cold indoor", indoor_trim(17.0, 10.0, True), 1)
eq("trim hot indoor + hot outdoor", indoor_trim(30.0, 27.0, True), -1)
eq("trim hot indoor + cold outdoor", indoor_trim(30.0, 5.0, True), 0)
eq("trim none", indoor_trim(None, 27.0, True), 0)

# --------------------------------------------------------------------------- #
# 4. the flattened-table bug: calibrating one band must not flatten the rest
# --------------------------------------------------------------------------- #
profile = DhwProfile(bath_min=37, bath_max=42, daily_min=35, daily_max=38)
eq("factory table untouched", profile.bath_table, C.FACTORY_BATH)

result = profile.calibrate(KIND_BATH, 42, "warm")
eq("warm calibration honoured exactly", result.value, 42)
eq("warm offset applied", result.applied_offset, 4)
eq("warm calibration not clamped", result.clamped, False)
eq(
    "other bands keep the seasonal gradient",
    profile.bath_table,
    {"hot": 37, "warm": 42, "mild": 39, "cool": 40, "cold": 40},
)
check(
    "table is not flat",
    not profile.flat_tables()[0],
    f"bath table {profile.bath_table}",
)

# a second, different band calibration keeps both values
profile.calibrate(KIND_BATH, 44, "cold")
eq(
    "two bands calibrated independently",
    profile.bath_table,
    {"hot": 37, "warm": 42, "mild": 39, "cool": 40, "cold": 42},
)
eq("cold capped by bath_max", profile.bath_table["cold"], 42)

# daily table is independent from the bath table
profile.calibrate(KIND_DAILY, 36, "mild")
eq("daily table only changed in mild", profile.daily_table["mild"], 36)
eq("bath unchanged by daily calibration", profile.bath_table["warm"], 42)

# --------------------------------------------------------------------------- #
# 5. desired value above the limits is reported, not silently applied
# --------------------------------------------------------------------------- #
fresh = DhwProfile()  # limits 37/40, 35/38
res = fresh.calibrate(KIND_BATH, 43, "warm")
eq("desired clamped to bath_max", res.value, 40)
eq("value_clamped flagged", res.value_clamped, True)
eq("offset request derived from the clamped value", res.requested_offset, 2)
eq("offset itself fits the window", res.applied_offset, 2)
eq("no offset clamping reported", res.clamped, False)
eq("table stays inside limits", max(fresh.bath_table.values()) <= fresh.bath_max, True)

# trim pushes the offset against the window
trim_profile = DhwProfile(bath_min=37, bath_max=42)
res = trim_profile.calibrate(KIND_BATH, 37, "hot", trim=1)
eq("trim + lower bound is clamped", res.clamped, True)
eq("applied offset at window edge", res.applied_offset, 0)

# --------------------------------------------------------------------------- #
# 6. limits never push temperatures up
# --------------------------------------------------------------------------- #
p = DhwProfile(bath_min=37, bath_max=42, daily_min=35, daily_max=38)
for band in C.BAND_IDS:
    p.calibrate(KIND_BATH, 42, band)
eq("all bands at ceiling", set(p.bath_table.values()), {42})
p.set_limits(bath_max=40)
check(
    "lowering the ceiling never raises a value",
    all(v <= 40 for v in p.bath_table.values()),
    f"{p.bath_table}",
)
eq("lowered ceiling applied", max(p.bath_table.values()), 40)
p2 = DhwProfile()
before = dict(p2.bath_table)
p2.set_limits(bath_min=39)
check(
    "raising the floor only lifts bands below the floor",
    all(p2.bath_table[b] >= 39 for b in C.BAND_IDS),
    f"{p2.bath_table}",
)
check(
    "raising the floor keeps previously-higher bands",
    all(p2.bath_table[b] >= min(39, before[b]) for b in C.BAND_IDS),
    f"{before} → {p2.bath_table}",
)

# extreme limits do not explode
p3 = DhwProfile()
p3.set_limits(bath_min=60, bath_max=60)
eq("degenerate window collapses safely", set(p3.bath_table.values()), {60})

# --------------------------------------------------------------------------- #
# 7. invariant: daily <= bath - gap
# --------------------------------------------------------------------------- #
g = DhwProfile(bath_min=37, bath_max=45, daily_min=35, daily_max=45)
g.calibrate(KIND_DAILY, 41, "cold")
g.calibrate(KIND_BATH, 38, "cold")
check(
    "daily kept below bath",
    g.daily_table["cold"] + C.MIN_BATH_DAILY_GAP <= g.bath_table["cold"],
    f"daily={g.daily_table['cold']} bath={g.bath_table['cold']}",
)
for band in C.BAND_IDS:
    check(
        f"gap invariant holds for {band}",
        g.daily_table[band] + C.MIN_BATH_DAILY_GAP <= g.bath_table[band],
        f"daily={g.daily_table[band]} bath={g.bath_table[band]}",
    )

# --------------------------------------------------------------------------- #
# 8. hysteresis + hold
# --------------------------------------------------------------------------- #
t = BandTracker(band_id="warm")
changed, _ = t.update(21.9, now=1000.0, hysteresis=1.0, hold_seconds=1800)
eq("no change inside hysteresis", (changed, t.band_id), (False, "warm"))
eq("no pending candidate inside hysteresis", t.pending_id, None)

changed, remaining = t.update(20.0, now=2000.0, hysteresis=1.0, hold_seconds=1800)
eq("candidate registered", t.pending_id, "mild")
eq("no immediate switch", (changed, t.band_id), (False, "warm"))
eq("hold remaining reported", remaining, 1800)

changed, _ = t.update(20.0, now=2000.0 + 1700, hysteresis=1.0, hold_seconds=1800)
eq("still holding before deadline", (changed, t.band_id), (False, "warm"))
changed, _ = t.update(20.0, now=2000.0 + 1801, hysteresis=1.0, hold_seconds=1800)
eq("switched after hold", (changed, t.band_id), (True, "mild"))

# oscillation resets the pending candidate
t2 = BandTracker(band_id="warm")
t2.update(20.0, now=0.0, hysteresis=1.0, hold_seconds=1800)
t2.update(25.0, now=600.0, hysteresis=1.0, hold_seconds=1800)
eq("oscillation clears candidate", t2.pending_id, None)
changed, _ = t2.update(20.0, now=1000.0, hysteresis=1.0, hold_seconds=1800)
eq("candidate restarts timer", (changed, t2.pending_id), (False, "mild"))
changed, _ = t2.update(20.0, now=1600.0, hysteresis=1.0, hold_seconds=1800)
eq("timer restarted from scratch", (changed, t2.band_id), (False, "warm"))

# bigger jump still needs the hold, then lands on the correct band
t3 = BandTracker(band_id="warm")
t3.update(5.0, now=0.0, hysteresis=1.0, hold_seconds=600)
changed, _ = t3.update(5.0, now=601.0, hysteresis=1.0, hold_seconds=600)
eq("jump to cold band after hold", (changed, t3.band_id), (True, "cold"))

# hysteresis = 0 reproduces instant switching
t4 = BandTracker(band_id="warm")
changed, _ = t4.update(21.9, now=0.0, hysteresis=0.0, hold_seconds=0)
eq("no hysteresis = instant switch", (changed, t4.band_id), (True, "mild"))

# --------------------------------------------------------------------------- #
# 9. storage migration (v2 absolute table → v3 per-band offsets)
# --------------------------------------------------------------------------- #
legacy = {
    "bath_table": {"hot": 42, "warm": 42, "mild": 42, "cool": 42, "cold": 42},
    "daily_table": {"hot": 35, "warm": 35, "mild": 36, "cool": 37, "cold": 38},
    "bath_min": 37,
    "bath_max": 42,
    "daily_min": 35,
    "daily_max": 38,
    "enabled": True,
}
migrated = DhwProfile.from_dict(legacy)
eq("legacy limits preserved", (migrated.bath_min, migrated.bath_max), (37, 42))
eq("legacy daily table preserved", migrated.daily_table, C.FACTORY_DAILY)
check(
    "legacy bath table preserved (no surprise change)",
    all(v == 42 for v in migrated.bath_table.values()),
    f"{migrated.bath_table}",
)
round_trip = DhwProfile.from_dict(migrated.to_dict())
eq("round trip is stable", round_trip.bath_table, migrated.bath_table)

# --------------------------------------------------------------------------- #
# 10. end-to-end setpoint maths for the live production profile
# --------------------------------------------------------------------------- #
live = DhwProfile.from_dict(legacy)
eq(
    "live profile: summer shower value",
    live.value_for(KIND_BATH, "warm"),
    42,
)
eq(
    "live profile: winter daily value",
    live.value_for(KIND_DAILY, "cold"),
    38,
)
live.calibrate(KIND_BATH, 42, "warm")
eq(
    "calibrating warm does not touch cold",
    live.value_for(KIND_BATH, "cold"),
    42,
)

print(f"checks run: {CHECKS}, failures: {len(FAILURES)}")
for failure in FAILURES:
    print("FAIL:", failure)
sys.exit(1 if FAILURES else 0)
