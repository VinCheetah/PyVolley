"""Contrôles de vraisemblance des données parsées.

Ce module implémente un moteur extensible basé sur des règles.
Chaque règle peut :
- détecter une donnée suspecte,
- proposer une correction automatique,
- supprimer la donnée si elle est invraisemblable,
- ou simplement la signaler.

Le moteur conserve une traçabilité complète des actions effectuées.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as dt_date
from enum import Enum
from typing import Callable, Optional
import abc
import re

from pyvolley.core.models import Match
from pyvolley.parsers.diagnostics import Diagnostic, DiagnosticCategory as Cat


class PlausibilityAction(str, Enum):
    """Action décidée pour une anomalie de vraisemblance."""

    CORRECTED = "corrected"
    REMOVED = "removed"
    FLAGGED = "flagged"
    IGNORED = "ignored"


class PlausibilitySeverity(str, Enum):
    """Sévérité d'un contrôle de vraisemblance."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


PlausibilityPolicy = str
ApprovalCallback = Callable[["PlausibilityIssue"], bool]


@dataclass
class PlausibilityIssue:
    """Événement de vraisemblance détecté pendant le post-traitement."""

    rule_id: str
    title: str
    field: str
    reason: str
    severity: PlausibilitySeverity
    action: PlausibilityAction
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    requires_review: bool = False
    reviewed: Optional[bool] = None

    def to_dict(self) -> dict[str, object]:
        return {
            "rule_id": self.rule_id,
            "title": self.title,
            "field": self.field,
            "reason": self.reason,
            "severity": self.severity.value,
            "action": self.action.value,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "requires_review": self.requires_review,
            "reviewed": self.reviewed,
        }


@dataclass
class PlausibilityReport:
    """Rapport consolidé des contrôles de vraisemblance."""

    policy: PlausibilityPolicy
    issues: list[PlausibilityIssue] = field(default_factory=list)

    @property
    def corrected_count(self) -> int:
        return sum(1 for i in self.issues if i.action == PlausibilityAction.CORRECTED)

    @property
    def removed_count(self) -> int:
        return sum(1 for i in self.issues if i.action == PlausibilityAction.REMOVED)

    @property
    def flagged_count(self) -> int:
        return sum(1 for i in self.issues if i.action == PlausibilityAction.FLAGGED)

    @property
    def ignored_count(self) -> int:
        return sum(1 for i in self.issues if i.action == PlausibilityAction.IGNORED)

    @property
    def touched_count(self) -> int:
        return self.corrected_count + self.removed_count

    def summary(self) -> dict[str, object]:
        by_rule: dict[str, int] = {}
        by_action: dict[str, int] = {}

        for issue in self.issues:
            by_rule[issue.rule_id] = by_rule.get(issue.rule_id, 0) + 1
            key = issue.action.value
            by_action[key] = by_action.get(key, 0) + 1

        return {
            "policy": self.policy,
            "total": len(self.issues),
            "touched": self.touched_count,
            "corrected": self.corrected_count,
            "removed": self.removed_count,
            "flagged": self.flagged_count,
            "ignored": self.ignored_count,
            "by_rule": by_rule,
            "by_action": by_action,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "summary": self.summary(),
            "issues": [i.to_dict() for i in self.issues],
        }


@dataclass
class PlausibilityContext:
    """Contexte d'exécution des règles de vraisemblance."""

    policy: PlausibilityPolicy
    now: dt_date
    approve: Optional[ApprovalCallback] = None


class BasePlausibilityRule(abc.ABC):
    """Interface de règle de vraisemblance."""

    rule_id: str = "base"
    title: str = "Règle"

    @abc.abstractmethod
    def apply(
        self,
        match: Match,
        report: PlausibilityReport,
        ctx: PlausibilityContext,
    ) -> None:
        """Applique la règle sur un match."""

    def _record_change(
        self,
        *,
        report: PlausibilityReport,
        ctx: PlausibilityContext,
        field: str,
        reason: str,
        severity: PlausibilitySeverity,
        old_value: Optional[object],
        new_value: Optional[object],
        change_type: str,
        requires_review: bool = False,
    ) -> PlausibilityIssue:
        old_s = _to_string(old_value)
        new_s = _to_string(new_value)

        reviewed: Optional[bool] = None
        approved = True
        if requires_review and ctx.approve is not None:
            preview = PlausibilityIssue(
                rule_id=self.rule_id,
                title=self.title,
                field=field,
                reason=reason,
                severity=severity,
                action=PlausibilityAction.FLAGGED,
                old_value=old_s,
                new_value=new_s,
                requires_review=True,
            )
            approved = bool(ctx.approve(preview))
            reviewed = approved

        if ctx.policy == "report-only":
            action = PlausibilityAction.FLAGGED
        elif (requires_review and ctx.approve is not None and not approved):
            action = PlausibilityAction.IGNORED
        elif change_type == "correct":
            action = PlausibilityAction.CORRECTED
        elif change_type == "remove":
            action = PlausibilityAction.REMOVED
        else:
            action = PlausibilityAction.FLAGGED

        issue = PlausibilityIssue(
            rule_id=self.rule_id,
            title=self.title,
            field=field,
            reason=reason,
            severity=severity,
            action=action,
            old_value=old_s,
            new_value=new_s,
            requires_review=requires_review,
            reviewed=reviewed,
        )
        report.issues.append(issue)
        return issue


class DateSeasonRule(BasePlausibilityRule):
    """Vérifie la cohérence de la date avec la saison."""

    rule_id = "date-season"
    title = "Cohérence date/saison"

    def apply(
        self,
        match: Match,
        report: PlausibilityReport,
        ctx: PlausibilityContext,
    ) -> None:
        if not match.date:
            return

        season_bounds = _season_bounds(match.saison)
        if season_bounds:
            start, end = season_bounds
            if start <= match.date <= end:
                return

            expected_year = start.year if match.date.month >= 8 else end.year
            corrected: Optional[dt_date] = None
            try:
                corrected = dt_date(expected_year, match.date.month, match.date.day)
            except ValueError:
                corrected = None

            if corrected and start <= corrected <= end:
                issue = self._record_change(
                    report=report,
                    ctx=ctx,
                    field="date",
                    reason=(
                        f"Date hors saison {match.saison}; année ajustée "
                        f"vers {expected_year}"
                    ),
                    severity=PlausibilitySeverity.WARNING,
                    old_value=match.date,
                    new_value=corrected,
                    change_type="correct",
                    requires_review=True,
                )
                if issue.action == PlausibilityAction.CORRECTED:
                    match.date = corrected
                return

            issue = self._record_change(
                report=report,
                ctx=ctx,
                field="date",
                reason=(
                    f"Date hors saison {match.saison} et correction impossible"
                ),
                severity=PlausibilitySeverity.CRITICAL,
                old_value=match.date,
                new_value=None,
                change_type="remove",
            )
            if issue.action == PlausibilityAction.REMOVED:
                match.date = None
            return

        if match.date.year < 2000 or match.date.year > (ctx.now.year + 1):
            issue = self._record_change(
                report=report,
                ctx=ctx,
                field="date",
                reason="Année de date invraisemblable",
                severity=PlausibilitySeverity.CRITICAL,
                old_value=match.date,
                new_value=None,
                change_type="remove",
            )
            if issue.action == PlausibilityAction.REMOVED:
                match.date = None


class MatchDurationRule(BasePlausibilityRule):
    """Vérifie la durée totale du match."""

    rule_id = "match-duration"
    title = "Durée totale du match"

    def apply(
        self,
        match: Match,
        report: PlausibilityReport,
        ctx: PlausibilityContext,
    ) -> None:
        if not match.duree_totale:
            return

        parsed = _parse_duration_to_minutes(match.duree_totale)
        if not parsed:
            issue = self._record_change(
                report=report,
                ctx=ctx,
                field="duree_totale",
                reason="Format de durée non reconnu",
                severity=PlausibilitySeverity.WARNING,
                old_value=match.duree_totale,
                new_value=None,
                change_type="remove",
            )
            if issue.action == PlausibilityAction.REMOVED:
                match.duree_totale = None
            return

        total_minutes, normalized = parsed
        min_allowed = 20
        max_allowed = 240

        if total_minutes < min_allowed or total_minutes > max_allowed:
            sets_sum = _sum_set_durations(match)
            if sets_sum and min_allowed <= sets_sum <= max_allowed:
                corrected = _minutes_to_duration(sets_sum)
                issue = self._record_change(
                    report=report,
                    ctx=ctx,
                    field="duree_totale",
                    reason=(
                        f"Durée totale invraisemblable ({total_minutes} min), "
                        "remplacée par la somme des sets"
                    ),
                    severity=PlausibilitySeverity.WARNING,
                    old_value=match.duree_totale,
                    new_value=corrected,
                    change_type="correct",
                    requires_review=True,
                )
                if issue.action == PlausibilityAction.CORRECTED:
                    match.duree_totale = corrected
                return

            issue = self._record_change(
                report=report,
                ctx=ctx,
                field="duree_totale",
                reason=f"Durée totale invraisemblable ({total_minutes} min)",
                severity=PlausibilitySeverity.CRITICAL,
                old_value=match.duree_totale,
                new_value=None,
                change_type="remove",
            )
            if issue.action == PlausibilityAction.REMOVED:
                match.duree_totale = None
            return

        if normalized != match.duree_totale:
            issue = self._record_change(
                report=report,
                ctx=ctx,
                field="duree_totale",
                reason="Format de durée normalisé",
                severity=PlausibilitySeverity.INFO,
                old_value=match.duree_totale,
                new_value=normalized,
                change_type="correct",
            )
            if issue.action == PlausibilityAction.CORRECTED:
                match.duree_totale = normalized


class ScoreConsistencyRule(BasePlausibilityRule):
    """Vérifie la cohérence score final / sets."""

    rule_id = "score-consistency"
    title = "Cohérence score/sets"

    def apply(
        self,
        match: Match,
        report: PlausibilityReport,
        ctx: PlausibilityContext,
    ) -> None:
        computed_a = sum(
            1 for s in match.sets
            if s.score_a is not None and s.score_b is not None and s.score_a > s.score_b
        )
        computed_b = sum(
            1 for s in match.sets
            if s.score_a is not None and s.score_b is not None and s.score_b > s.score_a
        )
        computed_known = (computed_a + computed_b) > 0

        parsed_score = _parse_sets_score(match.score_final)
        parsed_known = parsed_score is not None

        if parsed_known:
            score_a, score_b = parsed_score
            if score_a > 3 or score_b > 3:
                issue = self._record_change(
                    report=report,
                    ctx=ctx,
                    field="score_final",
                    reason="Score final invraisemblable (> 3 sets gagnés)",
                    severity=PlausibilitySeverity.CRITICAL,
                    old_value=match.score_final,
                    new_value=None,
                    change_type="remove",
                )
                if issue.action == PlausibilityAction.REMOVED:
                    match.score_final = None
                    if not computed_known:
                        match.sets_a = 0
                        match.sets_b = 0

        if computed_known:
            expected = f"{computed_a}/{computed_b}"
            if (match.sets_a, match.sets_b) != (computed_a, computed_b):
                issue = self._record_change(
                    report=report,
                    ctx=ctx,
                    field="sets_a,sets_b",
                    reason="Sets gagnés incohérents avec les scores de sets",
                    severity=PlausibilitySeverity.WARNING,
                    old_value=f"{match.sets_a}/{match.sets_b}",
                    new_value=expected,
                    change_type="correct",
                )
                if issue.action == PlausibilityAction.CORRECTED:
                    match.sets_a = computed_a
                    match.sets_b = computed_b

            if match.score_final != expected:
                issue = self._record_change(
                    report=report,
                    ctx=ctx,
                    field="score_final",
                    reason="Score final réaligné avec les sets détaillés",
                    severity=PlausibilitySeverity.WARNING,
                    old_value=match.score_final,
                    new_value=expected,
                    change_type="correct",
                )
                if issue.action == PlausibilityAction.CORRECTED:
                    match.score_final = expected


class PlausibilityEngine:
    """Moteur central de vraisemblance (extensible par règles)."""

    def __init__(self, rules: Optional[list[BasePlausibilityRule]] = None):
        self._rules = rules or [
            DateSeasonRule(),
            MatchDurationRule(),
            ScoreConsistencyRule(),
        ]

    @property
    def rules(self) -> list[BasePlausibilityRule]:
        return list(self._rules)

    def add_rule(self, rule: BasePlausibilityRule) -> None:
        self._rules.append(rule)

    def check(
        self,
        match: Match,
        *,
        policy: PlausibilityPolicy = "auto",
        approve: Optional[ApprovalCallback] = None,
        now: Optional[dt_date] = None,
    ) -> PlausibilityReport:
        if policy not in {"auto", "report-only", "strict"}:
            policy = "auto"

        report = PlausibilityReport(policy=policy)
        ctx = PlausibilityContext(
            policy=policy,
            now=now or dt_date.today(),
            approve=approve,
        )

        for rule in self._rules:
            rule.apply(match, report, ctx)

        return report


def issues_to_diagnostics(issues: list[PlausibilityIssue]) -> list[Diagnostic]:
    """Convertit les anomalies de vraisemblance en diagnostics parser."""
    diagnostics: list[Diagnostic] = []

    for issue in issues:
        category = _category_for_field(issue.field)
        message = (
            f"[{issue.rule_id}] {issue.reason}"
            f" (action={issue.action.value}, field={issue.field}, "
            f"old={issue.old_value}, new={issue.new_value})"
        )
        if issue.severity == PlausibilitySeverity.CRITICAL:
            diagnostics.append(Diagnostic.parse_warning(category, message))
        else:
            diagnostics.append(Diagnostic.data_warning(category, message))

    return diagnostics


def _category_for_field(field: str) -> Cat:
    field_l = field.lower()
    if "date" in field_l:
        return Cat.DATE
    if "duree" in field_l:
        return Cat.DUREE
    if "score" in field_l or "set" in field_l:
        return Cat.SCORE
    return Cat.COHERENCE


def _to_string(value: Optional[object]) -> Optional[str]:
    if value is None:
        return None
    return str(value)


def _season_bounds(saison: Optional[str]) -> Optional[tuple[dt_date, dt_date]]:
    if not saison:
        return None
    m = re.match(r"^(\d{4})[-/](\d{4})$", saison.strip())
    if not m:
        return None
    a0 = int(m.group(1))
    a1 = int(m.group(2))
    try:
        return dt_date(a0, 8, 1), dt_date(a1, 7, 31)
    except ValueError:
        return None


def _parse_duration_to_minutes(raw: Optional[str]) -> Optional[tuple[int, str]]:
    if not raw:
        return None
    value = raw.strip()
    if not value:
        return None

    m = re.match(r"^(\d{1,2})h(\d{1,2})$", value)
    if m:
        h = int(m.group(1))
        mn = int(m.group(2))
        if mn >= 60:
            return None
        total = h * 60 + mn
        return total, f"{h}h{mn:02d}"

    m = re.match(r"^(\d{1,2}):(\d{2})$", value)
    if m:
        h = int(m.group(1))
        mn = int(m.group(2))
        if mn >= 60:
            return None
        total = h * 60 + mn
        return total, f"{h}h{mn:02d}"

    m = re.match(r"^(\d{1,3})'$", value)
    if m:
        total = int(m.group(1))
        return total, _minutes_to_duration(total)

    return None


def _minutes_to_duration(total_minutes: int) -> str:
    hours = total_minutes // 60
    minutes = total_minutes % 60
    return f"{hours}h{minutes:02d}"


def _sum_set_durations(match: Match) -> Optional[int]:
    durations = [
        int(s.duree_minutes)
        for s in match.sets
        if s.duree_minutes is not None and 8 <= int(s.duree_minutes) <= 90
    ]
    if not durations:
        return None
    return sum(durations)


def _parse_sets_score(raw: Optional[str]) -> Optional[tuple[int, int]]:
    if not raw:
        return None
    value = raw.strip()
    m = re.match(r"^(\d)\s*[/\-]\s*(\d)$", value)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))
