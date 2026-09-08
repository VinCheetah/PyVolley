"""Utilitaires de filtre temporel pour les routes web.

Supporte :
- Une ou plusieurs saisons
- Intervalle précis (date_from / date_to)
- Avant / après une date (before_date / after_date)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass(frozen=True)
class TimeFilter:
    season_ids: list[int]
    date_from: Optional[date] = None
    date_to: Optional[date] = None

    @property
    def is_active(self) -> bool:
        return bool(self.season_ids or self.date_from or self.date_to)

    def to_context(self) -> dict:
        return {
            "season_ids": self.season_ids,
            "date_from": self.date_from.isoformat() if self.date_from else "",
            "date_to": self.date_to.isoformat() if self.date_to else "",
        }

    def apply_to_match_stmt(self, stmt, match_model):
        if self.season_ids:
            stmt = stmt.where(match_model.saison_id.in_(self.season_ids))
        if self.date_from:
            stmt = stmt.where(match_model.date_match >= self.date_from)
        if self.date_to:
            stmt = stmt.where(match_model.date_match <= self.date_to)
        return stmt

    def match_passes(self, match) -> bool:
        if self.season_ids and (match.saison_id not in self.season_ids):
            return False
        match_date = match.date_match
        if self.date_from and (match_date is None or match_date < self.date_from):
            return False
        if self.date_to and (match_date is None or match_date > self.date_to):
            return False
        return True


def _parse_iso_date(value: Optional[str]) -> Optional[date]:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def build_time_filter(
    *,
    season_ids: Optional[list[int]] = None,
    season_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    after_date: Optional[str] = None,
    before_date: Optional[str] = None,
) -> TimeFilter:
    normalized_seasons: list[int] = []
    for season_value in season_ids or []:
        if season_value not in normalized_seasons:
            normalized_seasons.append(season_value)
    if season_id is not None and season_id not in normalized_seasons:
        normalized_seasons.append(season_id)

    from_dt = _parse_iso_date(date_from) or _parse_iso_date(after_date)
    to_dt = _parse_iso_date(date_to) or _parse_iso_date(before_date)

    if from_dt and to_dt and from_dt > to_dt:
        from_dt, to_dt = to_dt, from_dt

    return TimeFilter(
        season_ids=normalized_seasons,
        date_from=from_dt,
        date_to=to_dt,
    )
