"""
Module de télémétrie et de chronométrage léger pour les commandes CLI PyVolley.

Permet de suivre avec précision la durée et le débit (éléments/seconde)
de chaque étape et sous-étape des pipelines d'importation et de calcul (compute).
L'overhead est négligeable (appels natifs à time.perf_counter).
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Generator, List, Optional

from rich.console import Console
from rich.table import Table


def format_duration(seconds: Optional[float]) -> str:
    """Formate une durée en secondes en texte lisible et adapté.

    Exemples :
        - None      -> "—"
        - < 0 s     -> "0.0s"
        - < 0.001 s -> "420µs"
        - < 1.0 s   -> "340ms"
        - < 60.0 s  -> "4.1s"
        - >= 60.0 s -> "1m 05s"
        - >= 3600 s -> "1h 01m 05s"
    """
    if seconds is None:
        return "—"
    if seconds < 0:
        return "0.0s"
    if seconds < 0.001:
        return f"{seconds * 1_000_000:.0f}µs"
    if seconds < 1.0:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60.0:
        return f"{seconds:.1f}s"

    minutes = int(seconds // 60)
    rem_sec = seconds % 60
    if minutes < 60:
        return f"{minutes}m {rem_sec:02.0f}s"

    hours = int(minutes // 60)
    rem_min = minutes % 60
    return f"{hours}h {rem_min:02d}m {rem_sec:02.0f}s"


def format_rate(
    count: Optional[int | float],
    duration: Optional[float],
    unit: str = "it",
) -> str:
    """Formate un débit en éléments par seconde.

    Exemples :
        - 120 matchs en 2.4s -> "50.0 m/s"
        - 0 ou durée nulle -> "—"
    """
    if count is None or count <= 0 or duration is None or duration <= 0.0001:
        return "—"
    rate = count / duration
    if rate >= 100:
        return f"{rate:.0f} {unit}/s"
    if rate >= 1.0:
        return f"{rate:.1f} {unit}/s"
    per_min = rate * 60
    return f"{per_min:.1f} {unit}/min"


@dataclass
class StepMetric:
    """Métriques enregistrées pour une étape ou sous-étape."""

    name: str
    label: str = ""
    start_time: float = field(default_factory=time.perf_counter)
    end_time: Optional[float] = None
    duration: Optional[float] = None
    items_count: Optional[int] = None
    items_unit: str = "it"
    status: str = "PENDING"  # "PENDING", "RUNNING", "OK", "success", "partial", "warning", "error", "skipped"
    details: dict[str, Any] = field(default_factory=dict)
    sub_steps: list[StepMetric] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.label:
            self.label = self.name

    @property
    def count(self) -> Optional[int]:
        """Alias pour items_count."""
        return self.items_count

    @count.setter
    def count(self, val: Optional[int]) -> None:
        self.items_count = val

    def start(self) -> StepMetric:
        """Démarre ou redémarre la mesure de l'étape."""
        self.start_time = time.perf_counter()
        self.end_time = None
        self.status = "RUNNING"
        return self

    def finish(
        self,
        *,
        items_count: Optional[int] = None,
        count: Optional[int] = None,
        status: str = "success",
        details: Optional[dict[str, Any]] = None,
    ) -> StepMetric:
        """Clôture la mesure de l'étape."""
        self.end_time = time.perf_counter()
        self.duration = max(0.0, self.end_time - self.start_time)
        cnt = count if count is not None else items_count
        if cnt is not None:
            self.items_count = cnt
        self.status = status
        if details:
            self.details.update(details)
        return self


class PipelineTimer:
    """Chronométreur hiérarchique pour les opérations CLI."""

    def __init__(
        self,
        label: str = "Pipeline",
        name: Optional[str] = None,
        console: Optional[Console] = None,
    ) -> None:
        self.label = name or label
        self.console = console
        self.start_time: float = time.perf_counter()
        self.end_time: Optional[float] = None
        self.steps: list[StepMetric] = []
        self._steps_by_name: dict[str, StepMetric] = {}
        self._active_sub_steps: dict[tuple[str, str], StepMetric] = {}
        self._current_step_name: Optional[str] = None

    def start(self) -> None:
        """Démarre le chronomètre global."""
        self.start_time = time.perf_counter()
        self.end_time = None

    def finish(self) -> float:
        """Arrête le chronomètre global et renvoie la durée totale."""
        return self.stop_pipeline()

    @property
    def total_duration(self) -> float:
        """Durée totale écoulée depuis l'initialisation ou jusqu'à stop_pipeline()."""
        end = self.end_time if self.end_time is not None else time.perf_counter()
        return max(0.0, end - self.start_time)

    def stop_pipeline(self) -> float:
        """Arrête le chronomètre global du pipeline."""
        if self.end_time is None:
            self.end_time = time.perf_counter()
        return self.total_duration

    def start_step(
        self,
        name: str,
        label: Optional[str] = None,
        *,
        items_unit: str = "it",
    ) -> StepMetric:
        """Démarre une étape principale."""
        lbl = label or name
        metric = StepMetric(name=name, label=lbl, items_unit=items_unit, status="RUNNING")
        self.steps.append(metric)
        self._steps_by_name[name] = metric
        self._current_step_name = name
        return metric

    def stop_step(
        self,
        name: str,
        *,
        items_count: Optional[int] = None,
        count: Optional[int] = None,
        status: str = "success",
        details: Optional[dict[str, Any]] = None,
    ) -> StepMetric:
        """Arrête une étape principale."""
        metric = self._steps_by_name.get(name)
        if not metric:
            metric = StepMetric(name=name, label=name)
            self.steps.append(metric)
            self._steps_by_name[name] = metric
        metric.finish(items_count=items_count, count=count, status=status, details=details)
        return metric

    @contextmanager
    def step(
        self,
        name: str,
        label: Optional[str] = None,
        *,
        items_unit: str = "it",
    ) -> Generator[StepMetric, None, None]:
        """Gestionnaire de contexte pour une étape principale."""
        metric = self.start_step(name, label, items_unit=items_unit)
        prev_current = self._current_step_name
        self._current_step_name = name
        try:
            yield metric
        except Exception:
            metric.finish(status="error")
            raise
        else:
            if metric.end_time is None:
                metric.finish()
        finally:
            self._current_step_name = prev_current

    def start_sub_step(
        self,
        *args,
        items_unit: str = "it",
        **kwargs,
    ) -> StepMetric:
        """Démarre une sous-étape liée à une étape principale."""
        if len(args) == 1:
            step_name = self._current_step_name or "default"
            sub_name = args[0]
            label = kwargs.get("label") or sub_name
        elif len(args) == 2:
            if self._current_step_name and self._current_step_name != args[0]:
                step_name = self._current_step_name
                sub_name = args[0]
                label = args[1]
            else:
                step_name = args[0]
                sub_name = args[1]
                label = kwargs.get("label") or sub_name
        elif len(args) >= 3:
            step_name = args[0]
            sub_name = args[1]
            label = args[2]
        else:
            raise ValueError("Arguments invalides pour start_sub_step")

        parent = self._steps_by_name.get(step_name)
        if not parent:
            parent = self.start_step(step_name, step_name)
        sub = StepMetric(name=sub_name, label=label, items_unit=items_unit, status="RUNNING")
        parent.sub_steps.append(sub)
        self._active_sub_steps[(step_name, sub_name)] = sub
        return sub

    def stop_sub_step(
        self,
        *args,
        items_count: Optional[int] = None,
        count: Optional[int] = None,
        status: str = "success",
        details: Optional[dict[str, Any]] = None,
    ) -> StepMetric:
        """Arrête une sous-étape."""
        if len(args) == 1:
            step_name = self._current_step_name or "default"
            sub_name = args[0]
        elif len(args) >= 2:
            step_name = args[0]
            sub_name = args[1]
        else:
            raise ValueError("Arguments invalides pour stop_sub_step")

        key = (step_name, sub_name)
        sub = self._active_sub_steps.pop(key, None)
        if not sub:
            parent = self._steps_by_name.get(step_name)
            if not parent:
                parent = self.start_step(step_name, step_name)
            sub = StepMetric(name=sub_name, label=sub_name)
            parent.sub_steps.append(sub)
        sub.finish(items_count=items_count, count=count, status=status, details=details)
        return sub

    @contextmanager
    def sub_step(
        self,
        *args,
        items_unit: str = "it",
        **kwargs,
    ) -> Generator[StepMetric, None, None]:
        """Gestionnaire de contexte pour une sous-étape."""
        sub = self.start_sub_step(*args, items_unit=items_unit, **kwargs)
        try:
            yield sub
        except Exception:
            sub.finish(status="error")
            raise
        else:
            if sub.end_time is None:
                sub.finish()

    def record_sub_step(
        self,
        step_name: str,
        sub_name: str,
        label: str,
        duration: float,
        *,
        items_count: Optional[int] = None,
        items_unit: str = "it",
        status: str = "success",
        details: Optional[dict[str, Any]] = None,
    ) -> StepMetric:
        """Enregistre directement une sous-étape avec une durée déjà mesurée."""
        parent = self._steps_by_name.get(step_name)
        if not parent:
            parent = self.start_step(step_name, step_name)
        now = time.perf_counter()
        sub = StepMetric(
            name=sub_name,
            label=label,
            start_time=now - duration,
            end_time=now,
            duration=max(0.0, duration),
            items_count=items_count,
            items_unit=items_unit,
            status=status,
            details=details or {},
        )
        parent.sub_steps.append(sub)
        return sub

    def display_summary(
        self,
        console: Optional[Console] = None,
        *,
        detail_level: str = "summary",
        detail: Optional[str] = None,
        title: Optional[str] = None,
    ) -> None:
        """Affiche le tableau récapitulatif des temps selon le niveau demandé.

        Niveaux :
            - 'none' ou 'off' : aucun affichage.
            - 'summary'       : grandes étapes avec volume, débit, durée et part relative.
            - 'detailed'      : grandes étapes + sous-étapes hiérarchiques.
        """
        cons = console or self.console or Console()
        lvl = (detail or detail_level or "summary").strip().lower()
        if lvl in ("none", "off", "false", "0"):
            return

        is_detailed = lvl in ("detailed", "detail", "verbose", "full", "all")
        total_time = self.total_duration

        table_title = title or f"⏱️ Récapitulatif des performances : {self.label}"
        table = Table(
            title=f"[bold]{table_title}[/bold]",
            header_style="bold blue",
            border_style="dim",
            show_footer=True,
        )

        table.add_column("Étape / Opération", style="cyan", no_wrap=True)
        table.add_column("Statut", justify="center")
        table.add_column("Volumétrie", justify="right")
        table.add_column("Débit", justify="right")
        table.add_column(
            "Durée",
            justify="right",
            style="bold yellow",
            footer=f"[bold yellow]{format_duration(total_time)}[/bold yellow]",
        )
        table.add_column(
            "% Total",
            justify="right",
            style="dim",
            footer="[bold]100.0%[/bold]",
        )

        def _format_status(status_str: str) -> str:
            if status_str == "success":
                return "[green]✓ Succès[/green]"
            if status_str == "partial":
                return "[yellow]~ Partiel[/yellow]"
            if status_str == "warning":
                return "[yellow]⚠ Warning[/yellow]"
            if status_str == "skipped":
                return "[dim]↷ Ignoré[/dim]"
            if status_str == "error":
                return "[red]✗ Erreur[/red]"
            return status_str

        def _format_volume(metric: StepMetric) -> str:
            if metric.items_count is None:
                return "-"
            return f"{metric.items_count} {metric.items_unit}"

        for step in self.steps:
            pct = (step.duration / total_time * 100.0) if total_time > 0 else 0.0
            table.add_row(
                f"[bold]{step.label}[/bold]",
                _format_status(step.status),
                _format_volume(step),
                format_rate(step.items_count, step.duration, step.items_unit),
                format_duration(step.duration),
                f"{pct:.1f}%",
            )

            if is_detailed and step.sub_steps:
                num_subs = len(step.sub_steps)
                for idx, sub in enumerate(step.sub_steps):
                    is_last = (idx == num_subs - 1)
                    branch = "└── " if is_last else "├── "
                    sub_pct = (sub.duration / total_time * 100.0) if total_time > 0 else 0.0
                    table.add_row(
                        f"  [dim]{branch}[/dim]{sub.label}",
                        _format_status(sub.status),
                        _format_volume(sub),
                        format_rate(sub.items_count, sub.duration, sub.items_unit),
                        format_duration(sub.duration),
                        f"[dim]{sub_pct:.1f}%[/dim]",
                    )

        cons.print("")
        cons.print(table)
