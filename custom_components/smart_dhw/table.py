"""Band table, per-band calibration and hysteresis for Smart DHW.

Pure logic only — no Home Assistant imports, so it is unit-testable standalone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .const import (
    BANDS,
    BAND_IDS,
    BAND_LABELS,
    DEFAULT_BATH_MAX,
    DEFAULT_BATH_MIN,
    DEFAULT_DAILY_MAX,
    DEFAULT_DAILY_MIN,
    FACTORY_BATH,
    FACTORY_DAILY,
    INDOOR_COLD,
    INDOOR_HOT,
    MIN_BATH_DAILY_GAP,
    OUTDOOR_FOR_HOT_TRIM,
    TEMP_PLAUSIBLE_MAX,
    TEMP_PLAUSIBLE_MIN,
)

KIND_BATH = "bath"
KIND_DAILY = "daily"

FACTORY_TABLES = {KIND_BATH: FACTORY_BATH, KIND_DAILY: FACTORY_DAILY}

_TEMP_UNITS = {"°c", "c", "℃", "celsius", "degc"}


def clamp_int(value: float | int, lo: int, hi: int) -> int:
    """Round to int and clamp; an inverted window collapses to its low edge."""
    lo_i, hi_i = int(lo), int(hi)
    if lo_i > hi_i:
        lo_i = hi_i
    return max(lo_i, min(hi_i, int(round(float(value)))))


# --------------------------------------------------------------------------- #
# sensors
# --------------------------------------------------------------------------- #
def parse_temperature(state: Any, attributes: dict[str, Any] | None) -> float | None:
    """Parse a temperature reading, rejecting non-temperature entities.

    Any sensor whose unit is not Celsius (e.g. a humidity sensor wired into the
    temperature field by mistake) is rejected instead of silently producing a
    garbage temperature.
    """
    if state is None:
        return None
    text = str(state).strip()
    if not text or text.lower() in {"unknown", "unavailable", "none", "nan"}:
        return None
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None

    attrs = attributes or {}
    unit = attrs.get("unit_of_measurement")
    device_class = attrs.get("device_class")
    if device_class != "temperature":
        if not isinstance(unit, str) or unit.strip().lower() not in _TEMP_UNITS:
            return None
    if not (TEMP_PLAUSIBLE_MIN <= value <= TEMP_PLAUSIBLE_MAX):
        return None
    return value


# --------------------------------------------------------------------------- #
# bands
# --------------------------------------------------------------------------- #
def band_index(outdoor: float) -> int:
    """Index of the band the outdoor temperature falls into (0 = hottest)."""
    for index, band in enumerate(BANDS):
        if outdoor >= float(band["outdoor_min"]):
            return index
    return len(BANDS) - 1


def band_index_of(band_id: str) -> int:
    try:
        return BAND_IDS.index(band_id)
    except ValueError:
        return len(BANDS) - 1


def resolve_band(outdoor: float) -> dict[str, Any]:
    return BANDS[band_index(outdoor)]


def band_label(band_id: str) -> str:
    return BAND_LABELS.get(band_id, band_id)


def indoor_trim(indoor: float | None, outdoor: float, enabled: bool) -> int:
    """±1 °C nudge from the indoor temperature (unchanged v1 semantics)."""
    if not enabled or indoor is None:
        return 0
    if indoor <= INDOOR_COLD:
        return 1
    if indoor >= INDOOR_HOT and outdoor >= OUTDOOR_FOR_HOT_TRIM:
        return -1
    return 0


@dataclass
class BandTracker:
    """Band selection with hysteresis and a hold time before switching."""

    band_id: str = "mild"
    pending_id: str | None = None
    pending_since: float | None = None

    def update(
        self,
        outdoor: float,
        now: float,
        hysteresis: float = 0.0,
        hold_seconds: float = 0.0,
    ) -> tuple[bool, float | None]:
        """Feed a new outdoor reading.

        Returns ``(changed, hold_remaining)``. A candidate band must stay
        valid for ``hold_seconds`` before it is adopted; ``hysteresis`` keeps
        the reading from flapping around a band boundary.
        """
        current = band_index_of(self.band_id)
        margin = max(0.0, float(hysteresis))
        hotter = band_index(outdoor - margin)
        colder = band_index(outdoor + margin)

        candidate = current
        if hotter < current:
            candidate = hotter
        elif colder > current:
            candidate = colder

        if candidate == current:
            self.pending_id = None
            self.pending_since = None
            return False, None

        target = str(BANDS[candidate]["id"])
        if hold_seconds <= 0:
            self.band_id = target
            self.pending_id = None
            self.pending_since = None
            return True, None
        if self.pending_id == target and self.pending_since is not None:
            remaining = float(hold_seconds) - (now - self.pending_since)
            if remaining <= 0:
                self.band_id = target
                self.pending_id = None
                self.pending_since = None
                return True, None
            return False, remaining

        self.pending_id = target
        self.pending_since = now
        return False, float(hold_seconds)

    def force(self, band_id: str) -> None:
        if band_id in BAND_IDS:
            self.band_id = band_id
        self.pending_id = None
        self.pending_since = None


@dataclass
class CalibrationResult:
    """Outcome of one calibration write."""

    kind: str
    band_id: str
    requested_offset: int
    applied_offset: int
    value: int
    desired: float = 0.0
    value_clamped: bool = False

    @property
    def clamped(self) -> bool:
        return self.requested_offset != self.applied_offset


# --------------------------------------------------------------------------- #
# profile
# --------------------------------------------------------------------------- #
@dataclass
class DhwProfile:
    """Per-home calibration, stored as per-band offsets from the factory tables.

    Storing offsets (instead of absolute tables) keeps the seasonal gradient
    intact: calibrating one band can no longer flatten the whole table, and a
    clamped write stays visible as ``requested != applied``.
    """

    bath_offsets: dict[str, int] = field(
        default_factory=lambda: {band: 0 for band in BAND_IDS}
    )
    daily_offsets: dict[str, int] = field(
        default_factory=lambda: {band: 0 for band in BAND_IDS}
    )
    bath_min: int = DEFAULT_BATH_MIN
    bath_max: int = DEFAULT_BATH_MAX
    daily_min: int = DEFAULT_DAILY_MIN
    daily_max: int = DEFAULT_DAILY_MAX

    # -- serialisation ------------------------------------------------------ #
    def to_dict(self) -> dict[str, Any]:
        return {
            "bath_offsets": dict(self.bath_offsets),
            "daily_offsets": dict(self.daily_offsets),
            "bath_min": int(self.bath_min),
            "bath_max": int(self.bath_max),
            "daily_min": int(self.daily_min),
            "daily_max": int(self.daily_max),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> DhwProfile:
        if not data:
            return cls()
        profile = cls()
        for kind, attr in ((KIND_BATH, "bath_offsets"), (KIND_DAILY, "daily_offsets")):
            raw = data.get(attr)
            if isinstance(raw, dict):
                table = getattr(profile, attr)
                for band in BAND_IDS:
                    if band in raw:
                        table[band] = int(raw[band])
            elif isinstance(data.get(f"{kind}_table"), dict):
                # v1/v2 storage: absolute tables
                old = data[f"{kind}_table"]
                factory = FACTORY_TABLES[kind]
                table = getattr(profile, attr)
                for band in BAND_IDS:
                    table[band] = int(old.get(band, factory[band])) - factory[band]
        for key in ("bath_min", "bath_max", "daily_min", "daily_max"):
            if key in data:
                setattr(profile, key, int(data[key]))
        return profile

    # -- windows & tables --------------------------------------------------- #
    def offsets(self, kind: str) -> dict[str, int]:
        return self.bath_offsets if kind == KIND_BATH else self.daily_offsets

    def limits(self, kind: str) -> tuple[int, int]:
        if kind == KIND_BATH:
            return int(self.bath_min), int(self.bath_max)
        return int(self.daily_min), int(self.daily_max)

    def offset_window(self, kind: str, band_id: str) -> tuple[int, int]:
        """Offset range that keeps ``factory + offset`` inside the limits."""
        low, high = self.limits(kind)
        factory = FACTORY_TABLES[kind][band_id]
        return low - factory, high - factory

    def table(self, kind: str) -> dict[str, int]:
        factory = FACTORY_TABLES[kind]
        low, high = self.limits(kind)
        offsets = self.offsets(kind)
        return {
            band: clamp_int(factory[band] + int(offsets.get(band, 0)), low, high)
            for band in BAND_IDS
        }

    @property
    def bath_table(self) -> dict[str, int]:
        return self.table(KIND_BATH)

    @property
    def daily_table(self) -> dict[str, int]:
        return self.table(KIND_DAILY)

    def value_for(self, kind: str, band_id: str, trim: int = 0) -> int:
        low, high = self.limits(kind)
        return clamp_int(self.table(kind)[band_id] + int(trim), low, high)

    def offset_for(self, kind: str, band_id: str) -> int:
        return int(self.offsets(kind).get(band_id, 0))

    # -- mutations ---------------------------------------------------------- #
    def calibrate(
        self, kind: str, desired: float, band_id: str, trim: int = 0
    ) -> CalibrationResult:
        """Store the offset that makes ``band_id`` deliver ``desired``.

        Only ``band_id`` is touched: the other bands keep their own offsets
        (and therefore the factory seasonal gradient).  Use ``set_offset``
        with ``band="all"`` for an explicit global shift.
        """
        low, high = self.limits(kind)
        raw = float(desired)
        wanted = clamp_int(raw, low, high)
        value_clamped = wanted != int(round(raw))
        factory = FACTORY_TABLES[kind][band_id]
        requested = int(round(wanted - trim - factory))
        win_low, win_high = self.offset_window(kind, band_id)
        applied = clamp_int(requested, win_low, win_high)

        self.offsets(kind)[band_id] = applied
        self.enforce_gap()
        return CalibrationResult(
            kind=kind,
            band_id=band_id,
            requested_offset=requested,
            applied_offset=applied,
            value=self.value_for(kind, band_id, trim),
            desired=raw,
            value_clamped=value_clamped,
        )

    def set_offset(self, kind: str, offset: int, band_id: str | None = None) -> None:
        """Set an offset for one band or for every band ("all")."""
        bands = BAND_IDS if band_id in (None, "", "all") else (band_id,)
        table = self.offsets(kind)
        for band in bands:
            if band not in BAND_IDS:
                continue
            low, high = self.offset_window(kind, band)
            table[band] = clamp_int(offset, low, high)
        self.enforce_gap()

    def enforce_gap(self) -> list[str]:
        """Keep 日常 <= 洗澡 - MIN_BATH_DAILY_GAP on every band."""
        adjusted: list[str] = []
        for band in BAND_IDS:
            bath = self.bath_table[band]
            daily = self.daily_table[band]
            if daily + MIN_BATH_DAILY_GAP <= bath:
                continue
            target = int(bath) - MIN_BATH_DAILY_GAP
            low, high = self.offset_window(KIND_DAILY, band)
            new_offset = clamp_int(target - FACTORY_DAILY[band], low, high)
            if new_offset != int(self.daily_offsets[band]):
                self.daily_offsets[band] = new_offset
                adjusted.append(band)
            if self.daily_table[band] + MIN_BATH_DAILY_GAP > self.bath_table[band]:
                # daily is pinned by its own lower limit → raise bath instead
                low_b, high_b = self.offset_window(KIND_BATH, band)
                new_bath = clamp_int(
                    self.daily_table[band] + MIN_BATH_DAILY_GAP - FACTORY_BATH[band],
                    low_b,
                    high_b,
                )
                if new_bath != int(self.bath_offsets[band]):
                    self.bath_offsets[band] = new_bath
                    if band not in adjusted:
                        adjusted.append(band)
        return adjusted

    def set_limits(
        self,
        *,
        bath_min: int | None = None,
        bath_max: int | None = None,
        daily_min: int | None = None,
        daily_max: int | None = None,
    ) -> list[str]:
        """Update limits by re-fitting the offsets — never by pushing cells up."""
        if bath_min is not None:
            self.bath_min = int(bath_min)
        if bath_max is not None:
            self.bath_max = int(bath_max)
        if daily_min is not None:
            self.daily_min = int(daily_min)
        if daily_max is not None:
            self.daily_max = int(daily_max)
        if self.bath_min > self.bath_max:
            self.bath_min, self.bath_max = self.bath_max, self.bath_min
        if self.daily_min > self.daily_max:
            self.daily_min, self.daily_max = self.daily_max, self.daily_min

        notes: list[str] = []
        for kind in (KIND_BATH, KIND_DAILY):
            table = self.offsets(kind)
            for band in BAND_IDS:
                low, high = self.offset_window(kind, band)
                current = int(table.get(band, 0))
                fitted = clamp_int(current, low, high)
                if fitted != current:
                    notes.append(f"{kind}:{band} 偏移 {current}→{fitted}")
                    table[band] = fitted
        for band in self.enforce_gap():
            notes.append(f"daily:{band} 因 洗澡≥日常+{MIN_BATH_DAILY_GAP} 被下调")
        return notes

    def reset(self) -> None:
        self.bath_offsets = {band: 0 for band in BAND_IDS}
        self.daily_offsets = {band: 0 for band in BAND_IDS}

    # -- diagnostics -------------------------------------------------------- #
    def flat_tables(self) -> tuple[bool, bool]:
        """True when a table has no seasonal spread left (gradient lost)."""
        bath = self.bath_table
        daily = self.daily_table
        return (
            len({int(v) for v in bath.values()}) == 1,
            len({int(v) for v in daily.values()}) == 1,
        )
