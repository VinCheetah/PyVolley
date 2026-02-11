"""Lancement du visualiseur de simulation de match.

Ce module transforme les données d'un match parsé en une page HTML interactive
qui peut être ouverte dans le navigateur pour visualiser le déroulé du match.
"""

from __future__ import annotations

import json
import socket
import tempfile
import threading
import webbrowser
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from pyvolley.core.models import Match

TEMPLATE_DIR = Path(__file__).parent / "templates"
TEMPLATE_FILE = TEMPLATE_DIR / "match_viewer.html"


def _find_free_port() -> int:
    """Trouve un port TCP libre."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


class _SingleFileHandler(SimpleHTTPRequestHandler):
    """Handler HTTP qui sert un seul fichier HTML."""

    def __init__(self, *args, html_path: Path, **kwargs):
        self._html_path = html_path
        super().__init__(*args, **kwargs)

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(self._html_path.read_bytes())

    def log_message(self, format, *args):
        pass  # Silencieux


def _convert_flat_sets_to_nested(match_data: dict) -> dict:
    """Convertit les sets du format plat vers le format imbriqué SetTeamData.

    Le JSON de test utilise formation_a, services_a, timeouts_a, changements_a
    au niveau du set, mais le modèle Pydantic attend equipe_a.formation, etc.
    Gère aussi les renommages de champs au niveau match.
    """
    # Renommages au niveau match
    if "vainqueur_nom" in match_data and "vainqueur" not in match_data:
        match_data["vainqueur"] = match_data.pop("vainqueur_nom")
    if "score_final" in match_data and "score_sets" not in match_data:
        match_data["score_sets"] = match_data.pop("score_final")

    # Suppression de champs inconnus
    for key in ("vainqueur_id", "equipe_a_id", "equipe_b_id"):
        match_data.pop(key, None)

    # Nettoyage des équipes
    for side in ("equipe_a", "equipe_b"):
        eq = match_data.get(side, {})
        if eq:
            eq.pop("id", None)
            eq.pop("club_id", None)
            eq.pop("nom_court", None)
            eq.pop("club", None)
            # Retirer le champ liberos dupliqué (les liberos sont dans joueurs)
            eq.pop("liberos", None)

    sets = match_data.get("sets", [])
    for s in sets:
        for suffix in ("a", "b"):
            team_key = f"equipe_{suffix}"
            # Si le format imbriqué existe déjà et est peuplé, on le garde
            existing = s.get(team_key)
            if existing and isinstance(existing, dict):
                has_data = (
                    existing.get("formation")
                    or existing.get("services")
                    or existing.get("timeouts")
                    or existing.get("changements")
                )
                if has_data:
                    continue

            # Construire la structure imbriquée depuis les champs plats
            team_data = {}

            # Formation
            fkey = f"formation_{suffix}"
            formation = s.pop(fkey, None)
            if formation and isinstance(formation, dict):
                team_data["formation"] = formation

            # Services
            skey = f"services_{suffix}"
            services = s.pop(skey, None)
            if services and isinstance(services, dict):
                team_data["services"] = services

            # Timeouts
            tkey = f"timeouts_{suffix}"
            timeouts = s.pop(tkey, None)
            if timeouts and isinstance(timeouts, list):
                team_data["timeouts"] = timeouts

            # Changements
            ckey = f"changements_{suffix}"
            changements = s.pop(ckey, None)
            if changements and isinstance(changements, list):
                team_data["changements"] = changements

            if team_data:
                s[team_key] = team_data

    return match_data


def match_to_json(match) -> str:
    """Sérialise un objet Match en JSON compatible avec le visualiseur.

    Gère la conversion des champs spéciaux (dates, enums, etc.)
    et la structure attendue par le JavaScript.
    Le JS attend des champs plats par set : formation_a/b, services_a/b,
    timeouts_a/b, changements_a/b (pas la structure SetTeamData imbriquée).
    """
    data = match.model_dump(mode="json", exclude_none=False)

    # Nettoyer les champs non nécessaires pour la simulation
    for key in ("id", "equipe_a_id", "equipe_b_id", "vainqueur_id", "parsed_at"):
        data.pop(key, None)

    # Nettoyer dans les joueurs
    for side in ("equipe_a", "equipe_b"):
        eq = data.get(side, {})
        for j in eq.get("joueurs", []):
            j.pop("id", None)

    # Aplatir les sets : convertir SetTeamData imbriqué → champs plats
    for s in data.get("sets", []):
        s.pop("id", None)

        for team_suffix in ("a", "b"):
            team_key = f"equipe_{team_suffix}"
            team_data = s.pop(team_key, None) or {}

            # Formation
            fkey = f"formation_{team_suffix}"
            if fkey not in s or not s[fkey] or all(
                not v for v in (s.get(fkey) or {}).values()
            ):
                formation = team_data.get("formation")
                if formation and isinstance(formation, dict):
                    s[fkey] = formation
                elif not s.get(fkey):
                    s[fkey] = {f"position_{i}": "" for i in range(1, 7)}

            # Services
            skey = f"services_{team_suffix}"
            if skey not in s or not s.get(skey):
                s[skey] = team_data.get("services", {})

            # Timeouts
            tkey = f"timeouts_{team_suffix}"
            if tkey not in s or not s.get(tkey):
                s[tkey] = team_data.get("timeouts", [])

            # Changements
            ckey = f"changements_{team_suffix}"
            if ckey not in s or not s.get(ckey):
                s[ckey] = team_data.get("changements", [])

    # Ajouter vainqueur_nom pour compatibilité JS
    if data.get("vainqueur") and not data.get("vainqueur_nom"):
        data["vainqueur_nom"] = data["vainqueur"]

    return json.dumps(data, ensure_ascii=False, indent=None)


def generate_html(match, output_path: Optional[Path] = None) -> Path:
    """Génère un fichier HTML autonome avec les données du match intégrées.

    Args:
        match: objet Match parsé.
        output_path: chemin de sortie pour le HTML. Si None, un fichier
                     temporaire est créé.

    Returns:
        Le chemin du fichier HTML généré.
    """
    template = TEMPLATE_FILE.read_text(encoding="utf-8")
    match_json = match_to_json(match)

    html = template.replace("__MATCH_DATA__", match_json)

    if output_path is None:
        # Créer un fichier temporaire qui ne sera pas supprimé immédiatement
        tmp = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".html",
            prefix="pyvolley_sim_",
            delete=False,
            encoding="utf-8",
        )
        tmp.write(html)
        tmp.close()
        output_path = Path(tmp.name)
    else:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html, encoding="utf-8")

    return output_path


def launch_viewer(
    source,
    output: Optional[str] = None,
    open_browser: bool = True,
    parser_name: Optional[str] = None,
) -> Path:
    """Lance le visualiseur de match dans le navigateur.

    Args:
        source: soit un chemin vers un PDF de feuille de match,
                soit un chemin vers un JSON de match parsé,
                soit un objet Match directement.
        output: chemin de sortie optionnel pour le HTML.
        open_browser: si True, ouvre automatiquement le navigateur.
        parser_name: nom du parser à utiliser (par défaut V5).

    Returns:
        Le chemin du fichier HTML généré.

    Raises:
        FileNotFoundError: si le fichier source n'existe pas.
        ValueError: si le parsing du PDF échoue.
    """
    from pyvolley.core.models import Match

    match = None

    if isinstance(source, Match):
        match = source
    else:
        source_path = Path(source)
        if not source_path.exists():
            raise FileNotFoundError(f"Fichier non trouvé : {source_path}")

        if source_path.suffix.lower() == ".pdf":
            # Parser le PDF
            from pyvolley.parsers import ParserFactory, get_parser

            parser = get_parser(parser_name) if parser_name else get_parser()
            result = parser.parse(source_path)
            if not result.success or not result.match:
                errors = "\n".join(result.errors) if result.errors else "Erreur inconnue"
                raise ValueError(
                    f"Échec du parsing de {source_path.name}:\n{errors}"
                )
            match = result.match

        elif source_path.suffix.lower() == ".json":
            # Charger depuis un JSON
            data = json.loads(source_path.read_text(encoding="utf-8"))
            # Support pour le format de test_parser_update.json (liste de résultats)
            if isinstance(data, list):
                if len(data) == 0:
                    raise ValueError("Le fichier JSON ne contient aucun match.")
                # Prendre le premier match
                entry = data[0]
                match_data = entry.get("match", entry)
            elif isinstance(data, dict):
                match_data = data.get("match", data)
            else:
                raise ValueError("Format JSON non reconnu.")

            # Convertir le format plat (formation_a, services_a...) en format
            # imbriqué (equipe_a.formation, equipe_a.services...) si nécessaire
            match_data = _convert_flat_sets_to_nested(match_data)
            match = Match.model_validate(match_data)
        else:
            raise ValueError(
                f"Format non supporté : {source_path.suffix}. "
                "Utilisez un fichier .pdf ou .json."
            )

    if match is None:
        raise ValueError("Impossible d'obtenir les données du match.")

    # Générer le HTML
    output_path = Path(output) if output else None
    html_path = generate_html(match, output_path)

    if open_browser:
        serve_and_open(html_path)

    return html_path


def serve_and_open(html_path: Path) -> None:
    """Démarre un serveur HTTP local et ouvre le navigateur.

    Le serveur tourne jusqu'à Ctrl+C ou interruption.
    """
    html_abs = Path(html_path).resolve()
    port = _find_free_port()
    handler = partial(_SingleFileHandler, html_path=html_abs)
    server = HTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}/"
    webbrowser.open(url)
    print(f"🏐 Visualiseur ouvert : {url}")
    print(f"📄 Fichier HTML : {html_path}")
    print("   (Ctrl+C pour arrêter le serveur)")
    try:
        thread.join()
    except KeyboardInterrupt:
        server.shutdown()
