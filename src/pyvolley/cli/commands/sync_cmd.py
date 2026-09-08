"""Commandes de synchronisation des données externes (logos de clubs, etc.)."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from pyvolley.cli.helpers import make_progress

console = Console()
sync_app = typer.Typer(
    help="🔄 Synchronisation des données externes (logos, etc.)",
    no_args_is_help=True,
)


@sync_app.command("logos")
def sync_logos(
    limit: int = typer.Option(0, "--limit", "-n", help="Nombre max de clubs (0 = tous)."),
    min_score: float = typer.Option(
        0.55,
        "--min-score",
        help="Score minimal de matching pour accepter un logo (0.0 à 1.0).",
    ),
    only_missing: bool = typer.Option(
        True,
        "--only-missing/--all",
        help="Ne traiter que les clubs sans logo_url.",
    ),
    provider: str = typer.Option(
        "all",
        "--provider",
        "-p",
        help="Source de logos: 'all', 'volleybox', 'wikipedia', 'badge'.",
    ),
    refresh_cache: bool = typer.Option(
        False,
        "--refresh-cache",
        help="Télécharge et actualise le catalogue complet Volleybox (~22 pages).",
    ),
    badge_fallback: bool = typer.Option(
        False,
        "--badge-fallback",
        help="Générer un blason SVG vectoriel aux couleurs FFVB pour les clubs sans logo trouvé.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Simuler les correspondances sans modifier la base de données.",
    ),
    review: bool = typer.Option(
        False,
        "--review/--no-review",
        help="Demander une confirmation manuelle pour chaque association.",
    ),
    request_timeout: float = typer.Option(
        15.0,
        "--request-timeout",
        help="Timeout HTTP (secondes) pour les requêtes logos.",
    ),
):
    """🖼 Synchronise les logos des clubs depuis Volleybox, Wikipedia ou blason SVG."""
    from sqlalchemy import select

    from pyvolley.database.connection import DatabaseSession, init_db
    from pyvolley.database.models import ClubDB
    from pyvolley.scrapers.logos import ClubLogoService, WikipediaLogoProvider
    from pyvolley.scrapers.volleybox import VolleyboxLogoScraper

    init_db()

    vb_scraper = VolleyboxLogoScraper(
        timeout=max(5.0, request_timeout),
        cache_path="data/cache/volleybox_catalog.json",
    )
    wiki_provider = WikipediaLogoProvider(timeout=max(3.0, request_timeout))
    service = ClubLogoService(
        volleybox_scraper=vb_scraper,
        wikipedia_provider=wiki_provider,
        cache_path="data/cache/volleybox_catalog.json",
    )

    stats = service.get_catalog_stats()
    enable_vb = provider in {"all", "volleybox"}
    enable_wiki = provider in {"all", "wikipedia"}
    enable_badge = (provider == "badge") or badge_fallback
    prefer_wiki = provider == "wikipedia"

    if enable_vb and (refresh_cache or not stats["cached"]):
        console.print("[cyan]Actualisation du catalogue complet des clubs Volleybox...[/cyan]")
        try:
            total_vb = service.refresh_catalog()
            console.print(f"[green]✓ Catalogue Volleybox synchronisé ({total_vb} clubs répertoriés)[/green]")
        except Exception as exc:
            console.print(f"[yellow]⚠️ Impossible d'actualiser Volleybox en ligne: {exc}[/yellow]")
    elif enable_vb and stats["cached"]:
        console.print(
            f"[dim]Catalogue Volleybox en cache ({stats['total_clubs']} clubs, "
            f"{stats['clubs_with_logo']} avec logo)[/dim]"
        )

    with DatabaseSession() as session:
        stmt = select(ClubDB).where(ClubDB.code_ffvb.is_not(None)).order_by(ClubDB.nom.asc())
        if only_missing:
            stmt = stmt.where(ClubDB.logo_url.is_(None))

        clubs = session.execute(stmt).scalars().all()
        if limit > 0:
            clubs = clubs[:limit]

        if not clubs:
            console.print("[yellow]Aucun club à traiter avec les filtres actuels.[/yellow]")
            return

        updated = 0
        skipped = 0
        associations: list[tuple[str, str, str, str, float]] = []
        skip_reasons = {
            "aucun_candidat_logo": 0,
            "score_trop_faible": 0,
            "rejet_manuel": 0,
        }

        with make_progress(console) as progress:
            task_id = progress.add_task("[cyan]Recherche logos clubs", total=max(1, len(clubs)))

            for club in clubs:
                progress.update(task_id, description=f"[cyan]Recherche logo: {club.nom[:42]}")

                alias_list = [alias.alias for alias in (club.aliases or []) if alias.alias]
                res = service.resolve_logo(
                    nom=club.nom,
                    nom_court=club.nom_court,
                    ville=club.ville,
                    departement=club.departement,
                    couleurs=club.couleurs,
                    aliases=alias_list,
                    min_score=min_score,
                    enable_volleybox=enable_vb,
                    enable_wikipedia=enable_wiki,
                    enable_badge_fallback=enable_badge,
                    prefer_wikipedia=prefer_wiki,
                )

                if not res:
                    skipped += 1
                    skip_reasons["aucun_candidat_logo"] += 1
                    progress.advance(task_id)
                    continue

                if res.confidence < min_score and not res.is_fallback:
                    skipped += 1
                    skip_reasons["score_trop_faible"] += 1
                    progress.advance(task_id)
                    continue

                display_logo = (
                    res.logo_url if not res.is_fallback else f"[dim]{res.logo_url[:35]}...[/dim]"
                )
                console.print(
                    f"[cyan][TROUVÉ][/cyan] {club.nom} -> {display_logo} "
                    f"([magenta]{res.source}[/magenta], conf={res.confidence:.2f}, match={res.matched_name})"
                )

                if review and not typer.confirm("Confirmer cette association ?", default=True):
                    skipped += 1
                    skip_reasons["rejet_manuel"] += 1
                    progress.advance(task_id)
                    continue

                if not dry_run:
                    club.logo_url = res.logo_url

                updated += 1
                associations.append(
                    (
                        club.nom,
                        res.source,
                        res.reference_url or "",
                        res.logo_url,
                        res.confidence,
                    )
                )
                progress.advance(task_id)

        if not dry_run:
            session.commit()

    if associations:
        summary = Table(title=f"Récapitulatif associations logos ({'SIMULATION' if dry_run else 'ENREGISTRÉ'})")
        summary.add_column("Club", style="cyan")
        summary.add_column("Source", style="magenta")
        summary.add_column("Score", style="yellow", justify="right")
        summary.add_column("Logo / Blason", style="green")
        for club_name, src, ref, l_url, score in associations:
            short_url = l_url if len(l_url) <= 65 else f"{l_url[:62]}..."
            summary.add_row(club_name, src, f"{score:.2f}", short_url)
        console.print(summary)

    reason_table = Table(title="Raisons des clubs ignorés")
    reason_table.add_column("Raison", style="yellow")
    reason_table.add_column("Nombre", style="red", justify="right")
    for reason, count in skip_reasons.items():
        reason_table.add_row(reason, str(count))
    console.print(reason_table)

    console.print(
        Panel(
            f"[green]{updated} logo(s) {'trouvé(s) (simulation)' if dry_run else 'mis à jour'}[/green]\n"
            f"[yellow]{skipped} club(s) ignoré(s)[/yellow]",
            title="Résultat Synchronisation Logos",
        )
    )

    if updated == 0:
        console.print(
            "[yellow]Aucun logo validé. Astuce: relancer avec "
            "--min-score 0.4 ou --badge-fallback pour générer des blasons.[/yellow]"
        )
