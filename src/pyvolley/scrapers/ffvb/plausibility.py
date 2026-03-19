"""Vérifications de plausibilité appliquées aux données issues du scraper FFVB."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass
class ScrapePlausibilityIssue:
    rule_id: str
    field: str
    reason: str
    action: str
    old_value: Optional[object] = None
    new_value: Optional[object] = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "rule_id": self.rule_id,
            "field": self.field,
            "reason": self.reason,
            "action": self.action,
        }
        if self.old_value is not None:
            payload["old_value"] = self.old_value
        if self.new_value is not None:
            payload["new_value"] = self.new_value
        return payload


def _parse_season_bounds(saison: str) -> tuple[Optional[int], Optional[int]]:
    if not saison:
        return None, None
    cleaned = saison.strip().replace("-", "/")
    parts = cleaned.split("/")
    if len(parts) != 2:
        return None, None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None, None


def _score_sets_indicates_played(score_sets: Optional[str]) -> bool:
    """True si ``score_sets`` correspond à un résultat réellement joué.

    ``0/0`` (ou équivalent) n'est pas un résultat joué.
    """
    if not score_sets or "/" not in score_sets:
        return False

    left_raw, right_raw = score_sets.split("/", 1)
    left = left_raw.strip().upper()
    right = right_raw.strip().upper()

    if left == "P" or right == "P":
        return True

    if left.isdigit() and right.isdigit():
        return (int(left) + int(right)) > 0

    return False


class ScrapePlausibilityEngine:
    def apply(self, match: "ExportMatchInfo") -> list[ScrapePlausibilityIssue]:
        issues: list[ScrapePlausibilityIssue] = []
        issues.extend(self._check_date_season(match))
        issues.extend(self._check_hour(match))
        issues.extend(self._check_club_codes(match))
        issues.extend(self._check_score_consistency(match))
        return issues

    def _check_date_season(self, match: "ExportMatchInfo") -> list[ScrapePlausibilityIssue]:
        if not match.date_match:
            return []

        season_start, season_end = _parse_season_bounds(match.saison)
        if season_start is None or season_end is None:
            return []

        month = match.date_match.month
        expected_year = season_end if month <= 7 else season_start
        if match.date_match.year == expected_year:
            return []

        original = match.date_match
        try:
            corrected = date(expected_year, original.month, original.day)
        except ValueError:
            match.date_match = None
            return [
                ScrapePlausibilityIssue(
                    rule_id="scrape-date-season",
                    field="date_match",
                    reason="Date incompatible avec la saison et impossible à corriger",
                    action="removed",
                    old_value=original.isoformat(),
                )
            ]

        match.date_match = corrected
        return [
            ScrapePlausibilityIssue(
                rule_id="scrape-date-season",
                field="date_match",
                reason="Date incohérente avec la saison, année corrigée",
                action="corrected",
                old_value=original.isoformat(),
                new_value=corrected.isoformat(),
            )
        ]

    def _check_hour(self, match: "ExportMatchInfo") -> list[ScrapePlausibilityIssue]:
        if not match.heure:
            return []
        raw = match.heure.strip()
        parts = raw.split(":")
        if len(parts) != 2:
            match.heure = None
            return [
                ScrapePlausibilityIssue(
                    rule_id="scrape-hour-format",
                    field="heure",
                    reason="Heure invalide",
                    action="removed",
                    old_value=raw,
                )
            ]

        try:
            hour = int(parts[0])
            minute = int(parts[1])
        except ValueError:
            match.heure = None
            return [
                ScrapePlausibilityIssue(
                    rule_id="scrape-hour-format",
                    field="heure",
                    reason="Heure invalide",
                    action="removed",
                    old_value=raw,
                )
            ]

        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            match.heure = None
            return [
                ScrapePlausibilityIssue(
                    rule_id="scrape-hour-format",
                    field="heure",
                    reason="Heure hors plage",
                    action="removed",
                    old_value=raw,
                )
            ]

        normalized = f"{hour:02d}:{minute:02d}"
        if normalized != raw:
            match.heure = normalized
            return [
                ScrapePlausibilityIssue(
                    rule_id="scrape-hour-format",
                    field="heure",
                    reason="Heure normalisée",
                    action="corrected",
                    old_value=raw,
                    new_value=normalized,
                )
            ]

        return []

    def _check_club_codes(self, match: "ExportMatchInfo") -> list[ScrapePlausibilityIssue]:
        issues: list[ScrapePlausibilityIssue] = []
        for attr in ("club_a_code_ffvb", "club_b_code_ffvb"):
            value = getattr(match, attr)
            if not value:
                continue
            cleaned = value.strip()
            if len(cleaned) == 7 and cleaned.isdigit():
                if cleaned != value:
                    setattr(match, attr, cleaned)
                    issues.append(
                        ScrapePlausibilityIssue(
                            rule_id="scrape-club-code-format",
                            field=attr,
                            reason="Code club normalisé",
                            action="corrected",
                            old_value=value,
                            new_value=cleaned,
                        )
                    )
                continue

            setattr(match, attr, None)
            issues.append(
                ScrapePlausibilityIssue(
                    rule_id="scrape-club-code-format",
                    field=attr,
                    reason="Code club FFVB invalide",
                    action="removed",
                    old_value=value,
                )
            )
        return issues

    def _check_score_consistency(self, match: "ExportMatchInfo") -> list[ScrapePlausibilityIssue]:
        issues: list[ScrapePlausibilityIssue] = []

        set_wins_a = sum(1 for a, b in match.sets if a > b)
        set_wins_b = sum(1 for a, b in match.sets if b > a)
        derived_score = None
        if match.sets:
            derived_score = f"{set_wins_a}/{set_wins_b}"

        if match.score_sets and "/" in match.score_sets:
            left, right = match.score_sets.split("/", 1)
            if left.isdigit() and right.isdigit():
                score_a = int(left)
                score_b = int(right)
                if score_a > 3 or score_b > 3:
                    old_score = match.score_sets
                    match.score_sets = derived_score
                    issues.append(
                        ScrapePlausibilityIssue(
                            rule_id="scrape-score-sets-range",
                            field="score_sets",
                            reason="Score sets hors plage",
                            action="corrected" if derived_score else "removed",
                            old_value=old_score,
                            new_value=derived_score,
                        )
                    )
                elif derived_score and derived_score != match.score_sets:
                    old_score = match.score_sets
                    match.score_sets = derived_score
                    issues.append(
                        ScrapePlausibilityIssue(
                            rule_id="scrape-score-sets-consistency",
                            field="score_sets",
                            reason="Score sets incohérent avec les sets détaillés",
                            action="corrected",
                            old_value=old_score,
                            new_value=derived_score,
                        )
                    )

        if match.sets and not match.score_sets:
            match.score_sets = derived_score
            issues.append(
                ScrapePlausibilityIssue(
                    rule_id="scrape-score-sets-missing",
                    field="score_sets",
                    reason="Score sets reconstruit depuis les sets détaillés",
                    action="corrected",
                    new_value=derived_score,
                )
            )

        if match.sets and match.vainqueur is None and not match.forfait:
            if set_wins_a > set_wins_b and match.equipe_a_nom:
                match.vainqueur = match.equipe_a_nom
                issues.append(
                    ScrapePlausibilityIssue(
                        rule_id="scrape-winner-inference",
                        field="vainqueur",
                        reason="Vainqueur déduit des sets",
                        action="corrected",
                        new_value=match.vainqueur,
                    )
                )
            elif set_wins_b > set_wins_a and match.equipe_b_nom:
                match.vainqueur = match.equipe_b_nom
                issues.append(
                    ScrapePlausibilityIssue(
                        rule_id="scrape-winner-inference",
                        field="vainqueur",
                        reason="Vainqueur déduit des sets",
                        action="corrected",
                        new_value=match.vainqueur,
                    )
                )

        should_be_played = bool(
            match.forfait
            or match.sets
            or _score_sets_indicates_played(match.score_sets)
        )
        if should_be_played and not match.match_joue:
            match.match_joue = True
            issues.append(
                ScrapePlausibilityIssue(
                    rule_id="scrape-match-joue-sync",
                    field="match_joue",
                    reason="match_joue activé car le match a un résultat",
                    action="corrected",
                    old_value=False,
                    new_value=True,
                )
            )
        elif (not should_be_played) and match.match_joue:
            match.match_joue = False
            issues.append(
                ScrapePlausibilityIssue(
                    rule_id="scrape-match-joue-sync",
                    field="match_joue",
                    reason="match_joue désactivé car aucun résultat exploitable",
                    action="corrected",
                    old_value=True,
                    new_value=False,
                )
            )

        if not should_be_played and match.score_sets:
            old_score = match.score_sets
            match.score_sets = None
            issues.append(
                ScrapePlausibilityIssue(
                    rule_id="scrape-score-empty-result",
                    field="score_sets",
                    reason="Score sets supprimé car le match n'est pas joué",
                    action="removed",
                    old_value=old_score,
                )
            )

        return issues


def summarize_scrape_issues(issues: list[ScrapePlausibilityIssue]) -> dict[str, object]:
    by_action: dict[str, int] = {}
    by_rule: dict[str, int] = {}
    for issue in issues:
        by_action[issue.action] = by_action.get(issue.action, 0) + 1
        by_rule[issue.rule_id] = by_rule.get(issue.rule_id, 0) + 1
    return {
        "total": len(issues),
        "by_action": by_action,
        "by_rule": by_rule,
    }
