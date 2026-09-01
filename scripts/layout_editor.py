#!/usr/bin/env python3
"""
Desktop PDF Parsing Layout Editor & Inspector (Dev Tool)

Application GUI de bureau (Tkinter / PyMuPDF / PIL) pour l'inspection visuelle,
le réglage interactif des zones géométriques hiérarchisées, le contrôle ultra-détaillé
du ZoneMatchSheetParser et la comparaison en direct avec le Legacy Parser (FastMatchSheetParser).

Utilisation:
    python scripts/layout_editor.py [chemin/vers/fichier.pdf]
"""

from __future__ import annotations

import sys
import os
import json
import logging
from pathlib import Path
from typing import Optional, Dict, List, Any, Tuple

# Ajouter src/ au sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk
import pymupdf

from pyvolley.parsers.layout_config import (
    ParserLayoutConfig, LayoutRegion, DEFAULT_FFVB_LAYOUT,
)
from pyvolley.parsers.fast_parser import FastMatchSheetParser
from pyvolley.parsers.parser import MatchSheetParser
from pyvolley.parsers.extractors.zone_extractor import extract_text_in_zone, extract_hierarchical_data
from pyvolley.parsers.base import ParseResult

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LayoutEditor")


class HoverTooltip:
    """Tooltip flottant pour l'affichage des informations sous le curseur."""

    def __init__(self, widget: tk.Widget):
        self.widget = widget
        self.tip_window: Optional[tk.Toplevel] = None

    def show(self, text: str, x: int, y: int):
        self.hide()
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            tw, text=text, justify=tk.LEFT,
            background="#1E293B", foreground="#F8FAFC",
            relief=tk.SOLID, borderwidth=1,
            font=("Consolas", 9, "normal"), padx=6, pady=4
        )
        label.pack(ipadx=1)

    def hide(self):
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None


class LayoutEditorApp:
    """Application principale du Layout Editor & Zone Parser Inspector (GUI)."""

    def __init__(self, root: tk.Tk, initial_pdf: Optional[Path] = None):
        self.root = root
        self.root.title("PyVolley — Layout Editor & Parser Inspector / Comparator (v4.0)")
        self.root.geometry("1620x980")
        self.root.minsize(1200, 750)

        # Style moderne dark/slate
        self.style = ttk.Style()
        self.style.theme_use("clam")
        self._configure_styles()

        # Modèles et parsers
        self.pdf_path: Optional[Path] = initial_pdf
        self.doc: Optional[pymupdf.Document] = None
        self.page: Optional[pymupdf.Page] = None
        self.layout_config: ParserLayoutConfig = ParserLayoutConfig.from_dict(
            DEFAULT_FFVB_LAYOUT.to_dict()
        )
        self.parser = FastMatchSheetParser()
        self.legacy_parser = MatchSheetParser()

        self.last_parse_result: Optional[ParseResult] = None
        self.last_legacy_result: Optional[ParseResult] = None

        self.words_data: List[dict] = []
        self.drawings_data: List[dict] = []
        self.image_info_list: List[dict] = []

        # Zoom et coordonnées PDF (A4 841.89 x 595.28 pt)
        self.zoom_factor: float = 1.2
        self.scale_x: float = 1.0  # Canvas pixel to PDF point scale
        self.scale_y: float = 1.0
        self.bg_photo: Optional[ImageTk.PhotoImage] = None
        self.bg_image_pil: Optional[Image.Image] = None

        # Interaction canvas
        self.selected_region_name: Optional[str] = "header/ville"
        self.dragging_region: Optional[str] = None
        self.drag_handle: Optional[str] = None  # 'nw', 'ne', 'se', 'sw', 'move'
        self.drag_start_pos: Tuple[float, float] = (0.0, 0.0)
        self.drag_orig_rect: Optional[Tuple[float, float, float, float]] = None

        self.highlight_box: Optional[Tuple[float, float, float, float]] = None
        self.compare_filter: str = "all"  # 'all', 'diffs', 'matches'

        # Tooltip
        self.tooltip = HoverTooltip(self.root)

        # Construction de l'interface
        self._create_menu()
        self._create_header_bar()
        self._create_main_layout()

        # Auto-load PDF si fourni ou si PDF par défaut existe
        if self.pdf_path and self.pdf_path.exists():
            self.load_pdf(self.pdf_path)
        else:
            self._find_and_load_default_pdf()

    def _configure_styles(self):
        """Configure les couleurs et styles ttk."""
        bg_dark = "#0F172A"
        panel_bg = "#1E293B"
        text_light = "#F8FAFC"
        accent = "#2563EB"

        self.root.configure(bg=bg_dark)
        self.style.configure(".", background=panel_bg, foreground=text_light, font=("Segoe UI", 9))
        self.style.configure("TFrame", background=panel_bg)
        self.style.configure("Header.TFrame", background="#090D16")
        self.style.configure("TLabel", background=panel_bg, foreground=text_light)
        self.style.configure("Header.TLabel", background="#090D16", foreground="#38BDF8", font=("Segoe UI", 10, "bold"))
        self.style.configure("Badge.TLabel", background="#090D16", foreground="#10B981", font=("Consolas", 10, "bold"))
        self.style.configure("TButton", font=("Segoe UI", 9, "bold"), background=accent, foreground="#FFFFFF")
        self.style.map("TButton", background=[("active", "#1D4ED8")])
        self.style.configure("Treeview", background="#0F172A", foreground=text_light, fieldbackground="#0F172A", rowheight=24)
        self.style.configure("Treeview.Heading", background="#1E293B", foreground="#38BDF8", font=("Segoe UI", 9, "bold"))
        self.style.configure("TNotebook", background="#1E293B")
        self.style.configure("TNotebook.Tab", background="#0F172A", foreground="#94A3B8", font=("Segoe UI", 9, "bold"), padding=[10, 5])
        self.style.map("TNotebook.Tab", background=[("selected", "#1E293B")], foreground=[("selected", "#38BDF8")])

    def _create_menu(self):
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Ouvrir un PDF...", command=self._on_open_pdf_dialog)
        file_menu.add_command(label="Charger un Preset JSON...", command=self._on_load_preset)
        file_menu.add_command(label="Sauvegarder le Preset JSON...", command=self._on_save_preset)
        file_menu.add_separator()
        file_menu.add_command(label="Réinitialiser Layout par Défaut", command=self._on_reset_layout)
        file_menu.add_separator()
        file_menu.add_command(label="Quitter", command=self.root.quit)
        menubar.add_cascade(label="Fichier", menu=file_menu)
        self.root.config(menu=menubar)

    def _create_header_bar(self):
        header_frame = ttk.Frame(self.root, style="Header.TFrame", padding=(12, 8))
        header_frame.pack(side=tk.TOP, fill=tk.X)

        title_lbl = ttk.Label(header_frame, text="🏐 PyVolley Layout Editor", style="Header.TLabel")
        title_lbl.pack(side=tk.LEFT, padx=(0, 10))

        # Badge Engine
        engine_lbl = ttk.Label(header_frame, text="⚡ ZoneMatchSheetParser v4.0 (100% Zone Engine)", style="Badge.TLabel")
        engine_lbl.pack(side=tk.LEFT, padx=(0, 15))

        # PDF Picker & Random PDF Buttons
        open_btn = tk.Button(
            header_frame, text="📁 Ouvrir PDF", command=self._on_open_pdf_dialog,
            bg="#2563EB", fg="white", font=("Segoe UI", 9, "bold"), relief=tk.FLAT, padx=8
        )
        open_btn.pack(side=tk.LEFT, padx=3)

        rand_btn = tk.Button(
            header_frame, text="🎲 PDF Aléatoire (2025-2026)", command=self._on_random_pdf,
            bg="#7C3AED", fg="white", font=("Segoe UI", 9, "bold"), relief=tk.FLAT, padx=8
        )
        rand_btn.pack(side=tk.LEFT, padx=3)

        self.lbl_pdf_info = ttk.Label(header_frame, text="Aucun PDF chargé", style="Header.TLabel", foreground="#94A3B8")
        self.lbl_pdf_info.pack(side=tk.LEFT, padx=12)

        # Parsing time & fields badges
        self.lbl_parse_time = ttk.Label(header_frame, text="⏱️ 0.0 ms", style="Header.TLabel", foreground="#10B981")
        self.lbl_parse_time.pack(side=tk.LEFT, padx=8)

        self.lbl_fields_extracted = ttk.Label(header_frame, text="Champs: 0/12", style="Header.TLabel", foreground="#38BDF8")
        self.lbl_fields_extracted.pack(side=tk.LEFT, padx=8)

        # Quick re-parse button
        parse_btn = tk.Button(
            header_frame, text="⚡ Re-Parse Live", command=self.reparse_pdf,
            bg="#059669", fg="white", font=("Segoe UI", 9, "bold"), relief=tk.FLAT, padx=10
        )
        parse_btn.pack(side=tk.RIGHT, padx=5)

        # Preset name label
        self.lbl_preset_info = ttk.Label(header_frame, text=f"Preset: {self.layout_config.name}", style="Header.TLabel", foreground="#F59E0B")
        self.lbl_preset_info.pack(side=tk.RIGHT, padx=12)

    def _create_main_layout(self):
        main_paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # Panel 1: Canvas Viewport (Left)
        left_frame = ttk.Frame(main_paned, padding=4)
        main_paned.add(left_frame, weight=3)
        self._build_viewport_panel(left_frame)

        # Panel 2: Region Controls & Inputs (Middle)
        mid_frame = ttk.Frame(main_paned, padding=4)
        main_paned.add(mid_frame, weight=1)
        self._build_controls_panel(mid_frame)

        # Panel 3: Multi-Tab Zone & Legacy Inspector (Right)
        right_frame = ttk.Frame(main_paned, padding=4)
        main_paned.add(right_frame, weight=2)
        self._build_inspector_panel(right_frame)

    def _build_viewport_panel(self, parent: ttk.Frame):
        toolbar = ttk.Frame(parent)
        toolbar.pack(side=tk.TOP, fill=tk.X, pady=(0, 4))

        ttk.Label(toolbar, text="Affichage:").pack(side=tk.LEFT, padx=(0, 8))

        self.var_show_regions = tk.BooleanVar(value=True)
        cb_reg = ttk.Checkbutton(toolbar, text="Zones (ROIs)", variable=self.var_show_regions, command=self.redraw_canvas)
        cb_reg.pack(side=tk.LEFT, padx=4)

        self.var_show_all_regions = tk.BooleanVar(value=False)
        cb_all = ttk.Checkbutton(toolbar, text="Tout Afficher", variable=self.var_show_all_regions, command=self.redraw_canvas)
        cb_all.pack(side=tk.LEFT, padx=4)

        self.var_show_words = tk.BooleanVar(value=True)
        cb_words = ttk.Checkbutton(toolbar, text="Mots Bboxes", variable=self.var_show_words, command=self.redraw_canvas)
        cb_words.pack(side=tk.LEFT, padx=4)

        self.var_show_handles = tk.BooleanVar(value=True)
        cb_handles = ttk.Checkbutton(toolbar, text="Poignées", variable=self.var_show_handles, command=self.redraw_canvas)
        cb_handles.pack(side=tk.LEFT, padx=4)

        # Zoom controls
        zoom_frame = ttk.Frame(toolbar)
        zoom_frame.pack(side=tk.RIGHT)
        ttk.Button(zoom_frame, text=" Zoom - ", command=lambda: self.change_zoom(-0.15), width=8).pack(side=tk.LEFT, padx=2)
        self.lbl_zoom = ttk.Label(zoom_frame, text="120%", width=6, anchor="center")
        self.lbl_zoom.pack(side=tk.LEFT)
        ttk.Button(zoom_frame, text=" Zoom + ", command=lambda: self.change_zoom(0.15), width=8).pack(side=tk.LEFT, padx=2)

        # Canvas with scrollbars
        canvas_container = ttk.Frame(parent)
        canvas_container.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(canvas_container, bg="#020617", highlightthickness=0)
        hbar = ttk.Scrollbar(canvas_container, orient=tk.HORIZONTAL, command=self.canvas.xview)
        vbar = ttk.Scrollbar(canvas_container, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=hbar.set, yscrollcommand=vbar.set)

        hbar.pack(side=tk.BOTTOM, fill=tk.X)
        vbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Binding Canvas Mouse Events
        self.canvas.bind("<ButtonPress-1>", self._on_canvas_mousedown)
        self.canvas.bind("<B1-Motion>", self._on_canvas_mousedrag)
        self.canvas.bind("<ButtonRelease-1>", self._on_canvas_mouseup)
        self.canvas.bind("<Motion>", self._on_canvas_mousemove)

    def _build_controls_panel(self, parent: ttk.Frame):
        ttk.Label(parent, text="📐 Arborescence des Zones", font=("Segoe UI", 10, "bold"), foreground="#38BDF8").pack(anchor="w", pady=(0, 6))

        # Treeview pour les zones hiérarchiques
        tree_zones_frame = ttk.Frame(parent)
        tree_zones_frame.pack(fill=tk.BOTH, expand=True, pady=4)

        self.tree_zones = ttk.Treeview(tree_zones_frame, show="tree", selectmode="browse")
        tree_zones_vbar = ttk.Scrollbar(tree_zones_frame, orient=tk.VERTICAL, command=self.tree_zones.yview)
        self.tree_zones.configure(yscrollcommand=tree_zones_vbar.set)
        tree_zones_vbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree_zones.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree_zones.bind("<<TreeviewSelect>>", self._on_zone_tree_selected)

        # Auto re-parse checkbox
        self.var_auto_reparse = tk.BooleanVar(value=True)
        cb_auto = ttk.Checkbutton(parent, text="⚡ Re-parse automatique", variable=self.var_auto_reparse)
        cb_auto.pack(anchor="w", pady=4)

        # Region description label
        self.lbl_region_desc = ttk.Label(parent, text="", font=("Segoe UI", 9, "italic"), foreground="#94A3B8", wraplength=220)
        self.lbl_region_desc.pack(anchor="w", pady=4)

    def _build_inspector_panel(self, parent: ttk.Frame):
        """Construit le panneau d'inspection complet à 5 onglets."""
        ttk.Label(parent, text="🔍 Zone Parser Live Inspector & Audit", font=("Segoe UI", 10, "bold"), foreground="#38BDF8").pack(anchor="w", pady=(0, 4))

        self.notebook = ttk.Notebook(parent)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # Tab 1: Zone Sélectionnée
        tab_zone = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(tab_zone, text="📝 Zone Sélectionnée")
        self._build_tab_selected_zone(tab_zone)

        # Tab 2: Objet Match Structuré (Modèle complet ZoneMatchSheetParser)
        tab_match = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(tab_match, text="🏐 Modèle Match")
        self._build_tab_match_model(tab_match)

        # Tab 3: Dictionnaire Hiérarchique BBoxes (ZoneExtractor)
        tab_hdict = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(tab_hdict, text="📐 Hierarchical Dict")
        self._build_tab_hdict(tab_hdict)

        # Tab 4: Table Récapitulative des Zones & Statuts
        tab_table = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(tab_table, text="📊 Table des Zones")
        self._build_tab_zones_table(tab_table)

        # Tab 5: Comparateur Legacy vs Zone Engine (NOUVEAU)
        tab_compare = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(tab_compare, text="⚖️ Compare Legacy/Zone")
        self._build_tab_compare(tab_compare)

    def _build_tab_selected_zone(self, parent: ttk.Frame):
        self.lbl_sel_zone_name = ttk.Label(parent, text="Zone: -", font=("Segoe UI", 9, "bold"), foreground="#F59E0B")
        self.lbl_sel_zone_name.pack(anchor="w", pady=(0, 4))

        # Box 1: Texte Brut Extrait
        sel_box = ttk.LabelFrame(parent, text="📝 Texte Brut Extrait (ZoneExtractor)", padding=6)
        sel_box.pack(fill=tk.X, pady=2)

        self.txt_sel_zone_value = tk.Text(
            sel_box, bg="#0F172A", fg="#10B981", font=("Consolas", 9, "bold"),
            height=3, relief=tk.FLAT, padx=6, pady=4
        )
        self.txt_sel_zone_value.pack(fill=tk.X, pady=2)

        # Box 2: Donnée Traitée dans le Modèle Match Structuré
        proc_box = ttk.LabelFrame(parent, text="⚙️ Donnée Traitée (Modèle Match ZoneParser)", padding=6)
        proc_box.pack(fill=tk.BOTH, expand=True, pady=4)

        proc_vbar = ttk.Scrollbar(proc_box)
        proc_vbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.txt_proc_zone_value = tk.Text(
            proc_box, bg="#0F172A", fg="#38BDF8", font=("Consolas", 9, "bold"),
            height=12, relief=tk.FLAT, padx=6, pady=4, yscrollcommand=proc_vbar.set
        )
        self.txt_proc_zone_value.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, pady=2)
        proc_vbar.config(command=self.txt_proc_zone_value.yview)

    def _build_tab_match_model(self, parent: ttk.Frame):
        ttk.Label(parent, text="Arborescence complète de l'objet Match généré par le ZoneMatchSheetParser:", font=("Segoe UI", 9, "italic"), foreground="#94A3B8").pack(anchor="w", pady=(0, 4))

        tree_frame = ttk.Frame(parent)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        self.tree_match_model = ttk.Treeview(tree_frame, columns=("valeur", "bbox_key"), show="tree headings", selectmode="browse")
        self.tree_match_model.heading("#0", text="Propriété / Élément du Match")
        self.tree_match_model.heading("valeur", text="Valeur Extrait")
        self.tree_match_model.heading("bbox_key", text="Zone BBox Clé")

        self.tree_match_model.column("#0", width=220)
        self.tree_match_model.column("valeur", width=200)
        self.tree_match_model.column("bbox_key", width=120)

        tree_vbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree_match_model.yview)
        self.tree_match_model.configure(yscrollcommand=tree_vbar.set)
        tree_vbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree_match_model.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.tree_match_model.bind("<<TreeviewSelect>>", self._on_tree_match_model_selected)

    def _build_tab_hdict(self, parent: ttk.Frame):
        tree_box = ttk.Frame(parent)
        tree_box.pack(fill=tk.BOTH, expand=True)

        self.tree_inspector = ttk.Treeview(tree_box, columns=("valeur",), show="tree headings")
        self.tree_inspector.heading("#0", text="Chemin Hiérarchique BBox")
        self.tree_inspector.heading("valeur", text="Valeur Brute Exacte")
        self.tree_inspector.column("#0", width=220)
        self.tree_inspector.column("valeur", width=220)

        tree_vbar = ttk.Scrollbar(tree_box, orient=tk.VERTICAL, command=self.tree_inspector.yview)
        self.tree_inspector.configure(yscrollcommand=tree_vbar.set)
        tree_vbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree_inspector.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.tree_inspector.bind("<<TreeviewSelect>>", self._on_tree_inspector_selected)

    def _build_tab_zones_table(self, parent: ttk.Frame):
        filter_frame = ttk.Frame(parent)
        filter_frame.pack(fill=tk.X, pady=(0, 4))

        ttk.Label(filter_frame, text="Rechercher:").pack(side=tk.LEFT, padx=(0, 4))
        self.entry_filter_zones = ttk.Entry(filter_frame)
        self.entry_filter_zones.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        self.entry_filter_zones.bind("<KeyRelease>", lambda e: self._update_zones_table())

        tbl_frame = ttk.Frame(parent)
        tbl_frame.pack(fill=tk.BOTH, expand=True)

        self.tree_zones_table = ttk.Treeview(
            tbl_frame,
            columns=("path", "bbox", "mots", "statut", "texte"),
            show="headings",
            selectmode="browse"
        )
        self.tree_zones_table.heading("path", text="Chemin Zone")
        self.tree_zones_table.heading("bbox", text="BBox (x0,y0,x1,y1)")
        self.tree_zones_table.heading("mots", text="Mots")
        self.tree_zones_table.heading("statut", text="Statut")
        self.tree_zones_table.heading("texte", text="Texte Extrait")

        self.tree_zones_table.column("path", width=160)
        self.tree_zones_table.column("bbox", width=140)
        self.tree_zones_table.column("mots", width=45, anchor="center")
        self.tree_zones_table.column("statut", width=60, anchor="center")
        self.tree_zones_table.column("texte", width=180)

        tbl_vbar = ttk.Scrollbar(tbl_frame, orient=tk.VERTICAL, command=self.tree_zones_table.yview)
        self.tree_zones_table.configure(yscrollcommand=tbl_vbar.set)
        tbl_vbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree_zones_table.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.tree_zones_table.bind("<<TreeviewSelect>>", self._on_zones_table_selected)

    def _build_tab_compare(self, parent: ttk.Frame):
        """Construit le tout nouvel onglet 5 de comparaison en direct entre Zone Parser et Legacy Parser."""
        # Top Metrics Bar
        metrics_frame = ttk.LabelFrame(parent, text="⚖️ Performance & Parité Globale", padding=6)
        metrics_frame.pack(fill=tk.X, pady=(0, 4))

        self.lbl_cmp_zone_time = ttk.Label(metrics_frame, text="Zone: 0.0 ms", font=("Consolas", 9, "bold"), foreground="#10B981")
        self.lbl_cmp_zone_time.pack(side=tk.LEFT, padx=8)

        self.lbl_cmp_legacy_time = ttk.Label(metrics_frame, text="Legacy: 0.0 ms", font=("Consolas", 9, "bold"), foreground="#F59E0B")
        self.lbl_cmp_legacy_time.pack(side=tk.LEFT, padx=8)

        self.lbl_cmp_speedup = ttk.Label(metrics_frame, text="Speedup: 1.0x", font=("Consolas", 9, "bold"), foreground="#38BDF8")
        self.lbl_cmp_speedup.pack(side=tk.LEFT, padx=8)

        self.lbl_cmp_parity = ttk.Label(metrics_frame, text="Parité: -", font=("Consolas", 9, "bold"), foreground="#EC4899")
        self.lbl_cmp_parity.pack(side=tk.RIGHT, padx=8)

        # Filter bar
        filter_bar = ttk.Frame(parent)
        filter_bar.pack(fill=tk.X, pady=2)

        ttk.Label(filter_bar, text="Filtrer l'affichage:").pack(side=tk.LEFT, padx=(0, 6))

        self.var_cmp_filter = tk.StringVar(value="all")
        rb_all = ttk.Radiobutton(filter_bar, text="Tous les champs", value="all", variable=self.var_cmp_filter, command=self._populate_compare_tree)
        rb_all.pack(side=tk.LEFT, padx=4)

        rb_diffs = ttk.Radiobutton(filter_bar, text="🔴 Écarts uniquement", value="diffs", variable=self.var_cmp_filter, command=self._populate_compare_tree)
        rb_diffs.pack(side=tk.LEFT, padx=4)

        rb_matches = ttk.Radiobutton(filter_bar, text="🟢 Concordances uniquement", value="matches", variable=self.var_cmp_filter, command=self._populate_compare_tree)
        rb_matches.pack(side=tk.LEFT, padx=4)

        # Treeview de comparaison côte-à-côte
        cmp_tree_frame = ttk.Frame(parent)
        cmp_tree_frame.pack(fill=tk.BOTH, expand=True, pady=4)

        self.tree_compare = ttk.Treeview(
            cmp_tree_frame,
            columns=("zone_val", "legacy_val", "status", "bbox_key"),
            show="tree headings",
            selectmode="browse"
        )
        self.tree_compare.heading("#0", text="Champ / Propriété du Match")
        self.tree_compare.heading("zone_val", text="Zone Parser v4.0")
        self.tree_compare.heading("legacy_val", text="Legacy Parser (Fast)")
        self.tree_compare.heading("status", text="Diagnostic Parité")
        self.tree_compare.heading("bbox_key", text="Zone Source")

        self.tree_compare.column("#0", width=220)
        self.tree_compare.column("zone_val", width=200)
        self.tree_compare.column("legacy_val", width=200)
        self.tree_compare.column("status", width=120, anchor="center")
        self.tree_compare.column("bbox_key", width=100)

        # Style de lignes colorées pour concordances (vert) et écarts (rouge)
        self.tree_compare.tag_configure("match", foreground="#10B981")
        self.tree_compare.tag_configure("diff", foreground="#EF4444", font=("Segoe UI", 9, "bold"))
        self.tree_compare.tag_configure("section", foreground="#38BDF8", font=("Segoe UI", 9, "bold"))

        cmp_vbar = ttk.Scrollbar(cmp_tree_frame, orient=tk.VERTICAL, command=self.tree_compare.yview)
        self.tree_compare.configure(yscrollcommand=cmp_vbar.set)
        cmp_vbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree_compare.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.tree_compare.bind("<<TreeviewSelect>>", self._on_tree_compare_selected)

    # -------------------------------------------------------------------------
    # Chargeur de PDF et Parser Engine
    # -------------------------------------------------------------------------
    def _find_and_load_default_pdf(self):
        """Recherche un PDF exemple dans data/data_sample/ ou data/pdfs/."""
        sample_dir = Path(__file__).resolve().parent.parent / "data" / "data_sample"
        if sample_dir.exists():
            pdfs = sorted(sample_dir.glob("*.pdf"))
            if pdfs:
                self.load_pdf(pdfs[0])
                return

        base_dir = Path(__file__).resolve().parent.parent / "data" / "pdfs"
        if base_dir.exists():
            pdfs = sorted(base_dir.rglob("*.pdf"))
            if pdfs:
                self.load_pdf(pdfs[0])

    def load_pdf(self, pdf_path: Path):
        """Charge un fichier PDF et initialise le canvas."""
        try:
            self.pdf_path = Path(pdf_path)
            self.doc = pymupdf.open(str(self.pdf_path))
            if not len(self.doc):
                messagebox.showerror("Erreur", "Le fichier PDF est vide.")
                return

            self.page = self.doc[0]
            page_rect = self.page.rect
            self.layout_config.page_width = page_rect.width
            self.layout_config.page_height = page_rect.height

            # Mots bruts et dessins PyMuPDF
            raw_words = self.page.get_text("words")
            self.words_data = [
                {"x0": w[0], "y0": w[1], "x1": w[2], "y1": w[3], "text": w[4]}
                for w in raw_words
            ]
            self.drawings_data = self.page.get_drawings()
            self.image_info_list = self.page.get_image_info(hashes=True)

            self.lbl_pdf_info.config(text=f"{self.pdf_path.name} ({int(page_rect.width)}x{int(page_rect.height)} pt)")
            self._update_zone_tree()
            self.render_pdf_page()
            self.reparse_pdf()

        except Exception as e:
            logger.error("Erreur lors du chargement du PDF", exc_info=True)
            messagebox.showerror("Erreur", f"Impossible de charger le PDF:\n{e}")

    def render_pdf_page(self):
        """Rend la page PDF en image PIL et l'affiche sur le Canvas."""
        if not self.page:
            return

        dpi = int(150 * self.zoom_factor)
        pix = self.page.get_pixmap(dpi=dpi)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        self.bg_image_pil = img
        self.bg_photo = ImageTk.PhotoImage(img)

        self.scale_x = pix.width / self.page.rect.width
        self.scale_y = pix.height / self.page.rect.height

        self.canvas.config(scrollregion=(0, 0, pix.width, pix.height))
        self.redraw_canvas()

    def reparse_pdf(self):
        """Exécute simultanément le ZoneMatchSheetParser et le FastMatchSheetParser (Legacy)."""
        if not self.pdf_path or not self.pdf_path.exists():
            return

        try:
            # 1. Fast Parser
            parser = FastMatchSheetParser(layout_config=self.layout_config)
            self.last_parse_result = parser.parse(self.pdf_path)
            if self.last_parse_result:
                self.lbl_parse_time.config(text=f"⏱️ {self.last_parse_result.parse_time_ms:.1f} ms")
                self.lbl_fields_extracted.config(text=f"Champs: {self.last_parse_result.fields_extracted}/{self.last_parse_result.fields_total}")

            # 2. Legacy Parser (FastMatchSheetParser)
            try:
                self.last_legacy_result = self.legacy_parser.parse(self.pdf_path)
            except Exception as leg_err:
                logger.warning(f"FastMatchSheetParser error: {leg_err}")
                self.last_legacy_result = None

            # 3. Remplissage des arbres d'inspection et de comparaison
            self._populate_inspector_tree()
            self._populate_match_model_tree()
            self._populate_compare_tree()
            self._update_zones_table()
            self._update_live_zone_inspector()

        except Exception as e:
            logger.error("Erreur de re-parsing", exc_info=True)

    def _on_random_pdf(self):
        """Sélectionne et charge aléatoirement un PDF de l'année 2025-2026."""
        import random
        base_dir = Path(__file__).resolve().parent.parent / "data" / "pdfs" / "2025-2026"
        if not base_dir.exists() or not list(base_dir.rglob("*.pdf")):
            base_dir = Path(__file__).resolve().parent.parent / "data" / "pdfs"
            if not base_dir.exists() or not list(base_dir.rglob("*.pdf")):
                base_dir = Path(__file__).resolve().parent.parent / "data" / "data_sample"

        pdfs = list(base_dir.rglob("*.pdf"))
        if pdfs:
            chosen = random.choice(pdfs)
            self.load_pdf(chosen)

    # -------------------------------------------------------------------------
    # Canvas Rendering & Bounding Boxes Overlay
    # -------------------------------------------------------------------------
    def redraw_canvas(self):
        """Redessine le canvas avec le fond PDF, les zones ROIs et les mots."""
        self.canvas.delete("all")

        if self.bg_photo:
            self.canvas.create_image(0, 0, image=self.bg_photo, anchor="nw")

        # 1. Tracé des Mots Extraits
        if self.var_show_words.get():
            for w in self.words_data:
                cx0 = w["x0"] * self.scale_x
                cy0 = w["y0"] * self.scale_y
                cx1 = w["x1"] * self.scale_x
                cy1 = w["y1"] * self.scale_y

                word_color = "#334155"
                for r_name, reg in self.layout_config.bboxes.items():
                    if reg.x0 <= w["x0"] <= reg.x1 and reg.y0 <= w["y0"] <= reg.y1:
                        word_color = reg.color
                        break

                self.canvas.create_rectangle(cx0, cy0, cx1, cy1, outline=word_color, width=1, tags="word_box")

        # 2. Tracé des Zones ROIs
        if self.var_show_regions.get():
            selected_path = self.selected_region_name or ""
            show_all = self.var_show_all_regions.get()

            for name, reg in self.layout_config.bboxes.items():
                if not show_all and selected_path:
                    is_exact = (name == selected_path)
                    is_child = name.startswith(selected_path + "/")
                    is_parent = selected_path.startswith(name + "/")
                    if not (is_exact or is_child or is_parent):
                        continue

                cx0 = reg.x0 * self.scale_x
                cy0 = reg.y0 * self.scale_y
                cx1 = reg.x1 * self.scale_x
                cy1 = reg.y1 * self.scale_y

                is_selected = (name == self.selected_region_name)
                color = "#F59E0B" if is_selected else reg.color
                width = 3 if is_selected else 1

                self.canvas.create_rectangle(
                    cx0, cy0, cx1, cy1,
                    outline=color, width=width,
                    tags=("region_box", name)
                )

                # Nom de la zone sur le canvas
                short_name = name.split("/")[-1].upper()
                self.canvas.create_text(
                    cx0 + 3, cy0 + 10, text=short_name,
                    fill=color, font=("Segoe UI", 8, "bold"), anchor="w",
                    tags=("region_label", name)
                )

                # Poignées de redimensionnement aux 4 coins
                if is_selected and self.var_show_handles.get():
                    hs = 5
                    corners = {
                        "nw": (cx0, cy0),
                        "ne": (cx1, cy0),
                        "se": (cx1, cy1),
                        "sw": (cx0, cy1),
                    }
                    for handle_key, (hx, hy) in corners.items():
                        self.canvas.create_rectangle(
                            hx - hs, hy - hs, hx + hs, hy + hs,
                            fill="#FFFFFF", outline="#F59E0B", width=2,
                            tags=("handle", name, handle_key)
                        )

        # 3. Highlight d'un élément sélectionné dans l'inspecteur
        if self.highlight_box:
            hx0, hy0, hx1, hy1 = self.highlight_box
            cx0 = hx0 * self.scale_x
            cy0 = hy0 * self.scale_y
            cx1 = hx1 * self.scale_x
            cy1 = hy1 * self.scale_y

            self.canvas.create_rectangle(
                cx0 - 3, cy0 - 3, cx1 + 3, cy1 + 3,
                outline="#00FFFF", width=4, tags="highlight_box"
            )

    # -------------------------------------------------------------------------
    # Canvas Mouse Interaction
    # -------------------------------------------------------------------------
    def _on_canvas_mousedown(self, event: tk.Event):
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)

        pdf_x = canvas_x / self.scale_x
        pdf_y = canvas_y / self.scale_y

        if self.selected_region_name and self.selected_region_name in self.layout_config.bboxes:
            reg = self.layout_config.bboxes[self.selected_region_name]
            cx0, cy0, cx1, cy1 = reg.x0 * self.scale_x, reg.y0 * self.scale_y, reg.x1 * self.scale_x, reg.y1 * self.scale_y
            hs = 8

            corners = {"nw": (cx0, cy0), "ne": (cx1, cy0), "se": (cx1, cy1), "sw": (cx0, cy1)}
            for handle_key, (hx, hy) in corners.items():
                if abs(canvas_x - hx) <= hs and abs(canvas_y - hy) <= hs:
                    self.dragging_region = self.selected_region_name
                    self.drag_handle = handle_key
                    self.drag_start_pos = (pdf_x, pdf_y)
                    self.drag_orig_rect = (reg.x0, reg.y0, reg.x1, reg.y1)
                    return

        # Clic sur une zone ROI
        for name, reg in reversed(list(self.layout_config.bboxes.items())):
            if reg.x0 <= pdf_x <= reg.x1 and reg.y0 <= pdf_y <= reg.y1:
                self.selected_region_name = name
                self._select_zone_in_tree(name)
                self.dragging_region = name
                self.drag_handle = "move"
                self.drag_start_pos = (pdf_x, pdf_y)
                self.drag_orig_rect = (reg.x0, reg.y0, reg.x1, reg.y1)
                self._update_spinbox_values()
                self.redraw_canvas()
                return

    def _on_canvas_mousedrag(self, event: tk.Event):
        if not self.dragging_region or not self.drag_orig_rect:
            return

        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)

        pdf_x = canvas_x / self.scale_x
        pdf_y = canvas_y / self.scale_y

        dx = pdf_x - self.drag_start_pos[0]
        dy = pdf_y - self.drag_start_pos[1]

        ox0, oy0, ox1, oy1 = self.drag_orig_rect
        reg = self.layout_config.bboxes[self.dragging_region]

        if self.drag_handle == "move":
            reg.x0 = round(max(0.0, ox0 + dx), 1)
            reg.y0 = round(max(0.0, oy0 + dy), 1)
            reg.x1 = round(ox1 + dx, 1)
            reg.y1 = round(oy1 + dy, 1)

        elif self.drag_handle == "nw":
            reg.x0 = round(min(ox1 - 5.0, ox0 + dx), 1)
            reg.y0 = round(min(oy1 - 5.0, oy0 + dy), 1)

        elif self.drag_handle == "ne":
            reg.x1 = round(max(ox0 + 5.0, ox1 + dx), 1)
            reg.y0 = round(min(oy1 - 5.0, oy0 + dy), 1)

        elif self.drag_handle == "se":
            reg.x1 = round(max(ox0 + 5.0, ox1 + dx), 1)
            reg.y1 = round(max(oy0 + 5.0, oy1 + dy), 1)

        elif self.drag_handle == "sw":
            reg.x0 = round(min(ox1 - 5.0, ox0 + dx), 1)
            reg.y1 = round(max(oy0 + 5.0, oy1 + dy), 1)

        self._update_spinbox_values()
        self.redraw_canvas()

    def _on_canvas_mouseup(self, event: tk.Event):
        if self.dragging_region:
            self.dragging_region = None
            self.drag_handle = None
            if self.var_auto_reparse.get():
                self.reparse_pdf()

    def _on_canvas_mousemove(self, event: tk.Event):
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        pdf_x = canvas_x / self.scale_x
        pdf_y = canvas_y / self.scale_y

        for w in self.words_data:
            if w["x0"] <= pdf_x <= w["x1"] and w["y0"] <= pdf_y <= w["y1"]:
                tip_text = f"Mot: '{w['text']}'\nBbox: ({w['x0']:.1f}, {w['y0']:.1f}, {w['x1']:.1f}, {w['y1']:.1f})"
                self.tooltip.show(tip_text, event.x_root + 15, event.y_root + 10)
                return

        self.tooltip.hide()

    # -------------------------------------------------------------------------
    # Synchronisation des Contrôles & Presets
    # -------------------------------------------------------------------------
    def _update_zone_tree(self):
        """Reconstruit l'arborescence des zones dans le Treeview des contrôles."""
        self.tree_zones.delete(*self.tree_zones.get_children())

        excluded = {"roster_a", "roster_b", "liberos_a", "liberos_b", "officiels_a", "officiels_b", "teams_header"}

        nodes: Dict[str, str] = {}
        for path in sorted(self.layout_config.bboxes.keys()):
            if path in excluded:
                continue

            parts = [p for p in path.split("/") if p]
            parent_id = ""
            curr_path = ""
            for i, part in enumerate(parts):
                curr_path = f"{curr_path}/{part}" if curr_path else part
                if curr_path not in nodes:
                    item_text = part
                    node_id = self.tree_zones.insert(parent_id, "end", text=item_text, values=(curr_path,), open=True)
                    nodes[curr_path] = node_id
                parent_id = nodes[curr_path]

        if self.selected_region_name in nodes:
            self.tree_zones.selection_set(nodes[self.selected_region_name])
            self.tree_zones.see(nodes[self.selected_region_name])

    def _select_zone_in_tree(self, path: str):
        """Sélectionne un noeud dans le Treeview des zones."""
        for item in self.tree_zones.get_children():
            self._search_and_select_tree_item(item, path)

    def _search_and_select_tree_item(self, item: str, target_path: str) -> bool:
        vals = self.tree_zones.item(item, "values")
        if vals and vals[0] == target_path:
            self.tree_zones.selection_set(item)
            self.tree_zones.see(item)
            return True
        for child in self.tree_zones.get_children(item):
            if self._search_and_select_tree_item(child, target_path):
                return True
        return False

    def _on_zone_tree_selected(self, event):
        selected = self.tree_zones.selection()
        if not selected:
            return
        vals = self.tree_zones.item(selected[0], "values")
        if vals and vals[0] in self.layout_config.bboxes:
            self.selected_region_name = vals[0]
            self._update_spinbox_values()
            self.redraw_canvas()

    def _update_spinbox_values(self):
        if not self.selected_region_name or self.selected_region_name not in self.layout_config.bboxes:
            return

        reg = self.layout_config.bboxes[self.selected_region_name]
        self.lbl_region_desc.config(text=reg.description or "")
        self._update_live_zone_inspector()

    def _update_live_zone_inspector(self):
        """Met à jour l'inspecteur en direct avec les texte brut et les données traitées de la zone."""
        if not hasattr(self, "txt_sel_zone_value"):
            return

        self.txt_sel_zone_value.delete("1.0", tk.END)
        if hasattr(self, "txt_proc_zone_value"):
            self.txt_proc_zone_value.delete("1.0", tk.END)

        if not self.selected_region_name or self.selected_region_name not in self.layout_config.bboxes:
            self.lbl_sel_zone_name.config(text="Zone: (Aucune zone sélectionnée)")
            return

        reg = self.layout_config.bboxes[self.selected_region_name]
        self.lbl_sel_zone_name.config(text=f"Zone: {self.selected_region_name} | BBox: ({reg.x0:.1f}, {reg.y0:.1f}, {reg.x1:.1f}, {reg.y1:.1f})")

        val = extract_text_in_zone(self.words_data, reg)
        if val:
            self.txt_sel_zone_value.insert(tk.END, val)
        else:
            self.txt_sel_zone_value.insert(tk.END, "(Vide / Non détecté)")

        if hasattr(self, "txt_proc_zone_value"):
            proc_val = self._get_processed_data_for_region(self.selected_region_name)
            self.txt_proc_zone_value.insert(tk.END, proc_val)

    def _get_processed_data_for_region(self, region_name: str) -> str:
        """Retourne de manière 100% exhaustive la donnée traitée issue du Match model pour n'importe quelle zone."""
        if not self.last_parse_result or not self.last_parse_result.match:
            return "(Aucune donnée traitée disponible)"

        m = self.last_parse_result.match
        path = region_name.strip("/")

        # En-tête
        if path == "header/match_code":
            return f"Code Match: {m.code_match}"
        elif path == "header/date":
            return f"Date: {m.date}\nHeure: {m.heure}"
        elif path == "header/ville":
            return f"Lieu / Ville: {m.lieu}"
        elif path == "header/salle":
            return f"Salle: {m.salle}"
        elif path == "header/competition":
            return f"Compétition: {m.competition}\nNiveau: {m.niveau}"
        elif path == "header/organisateur":
            return f"Organisateur: {m.organisateur}"
        elif path == "header/journee":
            return f"Journée: {m.journee}"
        elif path == "header/division_categorie":
            return f"Genre: {m.genre}\nCatégorie: {m.categorie}"
        elif path == "header/equipes/gauche":
            eq = m.equipe_a
            return f"Côté Gauche (Feuille): Équipe A ({eq.nom})\nCapitaine: N° {eq.capitaine or '-'}\nJoueurs: {len(eq.joueurs)} | Libéros: {len(eq.liberos)} | Officiels: {len(eq.officiels)}"
        elif path == "header/equipes/droite":
            eq = m.equipe_b
            return f"Côté Droit (Feuille): Équipe B ({eq.nom})\nCapitaine: N° {eq.capitaine or '-'}\nJoueurs: {len(eq.joueurs)} | Libéros: {len(eq.liberos)} | Officiels: {len(eq.officiels)}"

        # Effectifs / Rosters
        elif path.endswith("/joueurs") or path in ("roster_a", "roster_b"):
            side = "A" if "gauche" in path or "a" in path else "B"
            eq = m.equipe_a if side == "A" else m.equipe_b
            lines = [f"Effectif Équipe {side} ({eq.nom}):"]
            for j in eq.joueurs:
                cap_str = " (C)" if j.est_capitaine else ""
                lib_str = " (L)" if j.est_libero else ""
                lines.append(f"  N° {j.numero:>2}: {j.nom} {j.prenom} (Licence: {j.licence}){cap_str}{lib_str}")
            return "\n".join(lines) if len(lines) > 1 else "(Aucun joueur)"
        elif path.endswith("/liberos") or path in ("liberos_a", "liberos_b"):
            side = "A" if "gauche" in path or "a" in path else "B"
            eq = m.equipe_a if side == "A" else m.equipe_b
            lines = [f"Libéros Équipe {side}:"]
            for j in eq.liberos:
                lines.append(f"  N° {j.numero:>2}: {j.nom} {j.prenom} (Licence: {j.licence})")
            return "\n".join(lines) if len(lines) > 1 else "(Aucun libéro)"
        elif path.endswith("/officiels") or path in ("officiels_a", "officiels_b"):
            side = "A" if "gauche" in path or "a" in path else "B"
            eq = m.equipe_a if side == "A" else m.equipe_b
            lines = [f"Officiels Équipe {side}:"]
            for o in eq.officiels:
                lines.append(f"  [{o.role}]: {o.nom} {o.prenom or ''} (Licence: {o.licence or '-'})")
            return "\n".join(lines) if len(lines) > 1 else "(Aucun officiel)"

        # Arbitres
        elif path == "arbitres":
            lines = ["Corps Arbitral:"]
            for arb in m.arbitres:
                lines.append(f"  [{arb.role.value if hasattr(arb.role, 'value') else str(arb.role)}]: {arb.nom} {arb.prenom or ''} (Ligue: {arb.ligue or '-'}, Lic: {arb.licence or '-'})")
            return "\n".join(lines) if len(lines) > 1 else "(Aucun arbitre)"

        # Résultats & Remarques
        elif path == "resultats":
            return f"Vainqueur: {m.vainqueur_nom or '-'}\nScore final: {m.score_final or '-'}\nSets: {m.sets_a}-{m.sets_b}\nMatch Joué: {m.match_joue}"
        elif path == "remarques":
            return f"Remarques: {m.remarques or '(Aucune remarque)'}"

        # Sub-zones précises des Sets 1 à 5
        elif path.startswith("sets/set"):
            parts = path.split("/")
            try:
                s_num = int(parts[1].replace("set", ""))
                target_set = next((s for s in m.sets if s.numero == s_num), None)
                if not target_set:
                    return f"Set {s_num}: (Set non joué / Pas de données)"

                if len(parts) == 3:
                    sub = parts[2]
                    if sub == "debut":
                        return f"Set {s_num} Heure de Début: {target_set.debut or '-'}"
                    elif sub == "fin":
                        return f"Set {s_num} Heure de Fin: {target_set.fin or '-'}"

                if len(parts) >= 4:
                    team_key = parts[2]  # equipe_a ou equipe_b
                    eq_target = target_set.equipe_a if team_key == "equipe_a" else target_set.equipe_b
                    team_name = m.equipe_a.nom if team_key == "equipe_a" else m.equipe_b.nom
                    sub_feat = parts[3]  # pos1..pos6, services, timeouts

                    if not eq_target:
                        return f"Set {s_num} Équipe {team_key[-1].upper()} ({team_name}): Non disponible"

                    if sub_feat.startswith("pos"):
                        pos_num_idx = int(sub_feat.replace("pos", ""))
                        pos_val = getattr(eq_target.formation, f"position_{pos_num_idx}", None) if eq_target.formation else None
                        return f"Set {s_num} Équipe {team_key[-1].upper()} ({team_name}) — Position {pos_num_idx}:\nJoueur Maillot N°: {pos_val or '-'}"

                    elif sub_feat == "timeouts":
                        if eq_target.timeouts:
                            to_strs = [f"({t.score_a}:{t.score_b})" for t in eq_target.timeouts]
                            return f"Set {s_num} Équipe {team_key[-1].upper()} ({team_name}) — Temps Morts:\n{', '.join(to_strs)}"
                        return f"Set {s_num} Équipe {team_key[-1].upper()} ({team_name}) — Temps Morts: Aucun"

                    elif sub_feat == "services":
                        if eq_target.services:
                            srv_strs = [f"P{p}:{sc}" for p, sc in sorted(eq_target.services.items())]
                            return f"Set {s_num} Équipe {team_key[-1].upper()} ({team_name}) — Services:\n" + "\n".join(srv_strs)
                        return f"Set {s_num} Équipe {team_key[-1].upper()} ({team_name}) — Services: Aucun"

                # Vue générale du Set
                res_lines = [
                    f"═══ SET {s_num} : {target_set.score_str} ═══",
                    f"• Durée: {target_set.duree_minutes or '-'} min (Début: {target_set.debut or '-'} | Fin: {target_set.fin or '-'})",
                    f"• Service Initial: Équipe {target_set.service_initial or '-'}",
                ]
                return "\n".join(res_lines)

            except Exception:
                pass

        return f"Champ BBox: {path}"

    def change_zoom(self, delta: float):
        new_zoom = max(0.5, min(3.0, self.zoom_factor + delta))
        if new_zoom != self.zoom_factor:
            self.zoom_factor = new_zoom
            self.lbl_zoom.config(text=f"{int(self.zoom_factor * 100)}%")
            self.render_pdf_page()

    # -------------------------------------------------------------------------
    # Inspecteurs et Remplissage des Trees
    # -------------------------------------------------------------------------
    def _populate_inspector_tree(self):
        """Remplit le Treeview du dictionnaire hiérarchique BBox."""
        self.tree_inspector.delete(*self.tree_inspector.get_children())

        drawings = getattr(self, "drawings_data", None)
        images = getattr(self, "image_info_list", None)
        h_data = extract_hierarchical_data(self.words_data, self.layout_config, drawings=drawings, image_blocks=images)

        def add_dict_nodes(parent_id: str, data_dict: dict, current_path: str = ""):
            for k, v in data_dict.items():
                node_path = f"{current_path}/{k}" if current_path else k
                if isinstance(v, dict):
                    node_id = self.tree_inspector.insert(parent_id, "end", text=k, values=("", node_path), open=True)
                    add_dict_nodes(node_id, v, node_path)
                else:
                    self.tree_inspector.insert(parent_id, "end", text=k, values=(str(v), node_path))

        add_dict_nodes("", h_data)

    def _populate_match_model_tree(self):
        """Remplit l'arborescence interactive complète de l'objet Match structuré (Modèle ZoneParser)."""
        self.tree_match_model.delete(*self.tree_match_model.get_children())

        if not self.last_parse_result or not self.last_parse_result.match:
            return

        m = self.last_parse_result.match

        # Racine Match
        root_id = self.tree_match_model.insert("", "end", text=f"Match [{m.code_match}]", values=(f"Score: {m.score_final or m.sets_score_str}", ""), open=True)

        # En-Tête
        hdr_id = self.tree_match_model.insert(root_id, "end", text="📌 En-Tête Match", values=("", "header"), open=True)
        self.tree_match_model.insert(hdr_id, "end", text="Code Match", values=(str(m.code_match), "header/match_code"))
        self.tree_match_model.insert(hdr_id, "end", text="Date", values=(str(m.date or "-"), "header/date"))
        self.tree_match_model.insert(hdr_id, "end", text="Heure", values=(str(m.heure or "-"), "header/date"))
        self.tree_match_model.insert(hdr_id, "end", text="Lieu / Ville", values=(str(m.lieu or "-"), "header/ville"))
        self.tree_match_model.insert(hdr_id, "end", text="Salle", values=(str(m.salle or "-"), "header/salle"))
        self.tree_match_model.insert(hdr_id, "end", text="Compétition", values=(str(m.competition or "-"), "header/competition"))
        self.tree_match_model.insert(hdr_id, "end", text="Journée", values=(str(m.journee or "-"), "header/journee"))
        self.tree_match_model.insert(hdr_id, "end", text="Organisateur", values=(str(m.organisateur or "-"), "header/organisateur"))
        self.tree_match_model.insert(hdr_id, "end", text="Genre", values=(str(m.genre or "-"), "header/division_categorie"))
        self.tree_match_model.insert(hdr_id, "end", text="Catégorie", values=(str(m.categorie or "-"), "header/division_categorie"))
        self.tree_match_model.insert(hdr_id, "end", text="Niveau", values=(str(m.niveau or "-"), "header/competition"))
        self.tree_match_model.insert(hdr_id, "end", text="Score Final", values=(str(m.score_final or "-"), "resultats"))
        self.tree_match_model.insert(hdr_id, "end", text="Durée Totale", values=(str(m.duree_totale or "-"), "resultats"))
        self.tree_match_model.insert(hdr_id, "end", text="Vainqueur", values=(str(m.vainqueur_nom or "-"), "resultats"))
        self.tree_match_model.insert(hdr_id, "end", text="Match Joué", values=(str(m.match_joue), "resultats"))

        # Équipes A & B
        for side, eq, key_suffix in [("Équipe A", m.equipe_a, "gauche"), ("Équipe B", m.equipe_b, "droite")]:
            eq_id = self.tree_match_model.insert(root_id, "end", text=f"🔵 {side} ({eq.nom})", values=(f"Capitaine: N°{eq.capitaine or '-'}", f"header/equipes/{key_suffix}"), open=True)

            j_id = self.tree_match_model.insert(eq_id, "end", text=f"Joueurs ({len(eq.joueurs)})", values=("", f"header/equipes/{key_suffix}/joueurs"), open=True)
            for j in eq.joueurs:
                cap_str = " (C)" if j.est_capitaine else ""
                lib_str = " (L)" if j.est_libero else ""
                self.tree_match_model.insert(j_id, "end", text=f"N° {j.numero:>2}", values=(f"{j.nom} {j.prenom} [{j.licence}]{cap_str}{lib_str}", f"header/equipes/{key_suffix}/joueurs"))

            lib_id = self.tree_match_model.insert(eq_id, "end", text=f"Libéros ({len(eq.liberos)})", values=("", f"header/equipes/{key_suffix}/liberos"), open=True)
            for j in eq.liberos:
                self.tree_match_model.insert(lib_id, "end", text=f"N° {j.numero:>2}", values=(f"{j.nom} {j.prenom} [{j.licence}]", f"header/equipes/{key_suffix}/liberos"))

            off_id = self.tree_match_model.insert(eq_id, "end", text=f"Officiels ({len(eq.officiels)})", values=("", f"header/equipes/{key_suffix}/officiels"), open=True)
            for o in eq.officiels:
                self.tree_match_model.insert(off_id, "end", text=f"[{o.role}]", values=(f"{o.nom} {o.prenom or ''} [{o.licence or '-'}]", f"header/equipes/{key_suffix}/officiels"))

        # Arbitres
        arb_id = self.tree_match_model.insert(root_id, "end", text=f"🏁 Corps Arbitral ({len(m.arbitres)})", values=("", "arbitres"), open=True)
        for arb in m.arbitres:
            role_str = arb.role.value if hasattr(arb.role, 'value') else str(arb.role)
            self.tree_match_model.insert(arb_id, "end", text=f"[{role_str}]", values=(f"{arb.nom} {arb.prenom or ''} (Ligue: {arb.ligue or '-'}, Lic: {arb.licence or '-'})", "arbitres"))

        # Sets 1 à 5
        sets_root_id = self.tree_match_model.insert(root_id, "end", text=f"📊 Sets ({len(m.sets)})", values=(f"Sets Score: {m.sets_a}-{m.sets_b}", "resultats"), open=True)
        for s in m.sets:
            s_num = s.numero
            set_id = self.tree_match_model.insert(sets_root_id, "end", text=f"Set {s_num} [{s.score_str}]", values=(f"Durée: {s.duree_minutes or '-'} min", f"sets/set{s_num}"), open=True)

            self.tree_match_model.insert(set_id, "end", text="Début", values=(str(s.debut or "-"), f"sets/set{s_num}/debut"))
            self.tree_match_model.insert(set_id, "end", text="Fin", values=(str(s.fin or "-"), f"sets/set{s_num}/fin"))
            self.tree_match_model.insert(set_id, "end", text="Service Initial", values=(f"Équipe {s.service_initial or '-'}", f"sets/set{s_num}"))

            for side_name, set_team, t_key in [("Équipe A", s.equipe_a, "equipe_a"), ("Équipe B", s.equipe_b, "equipe_b")]:
                st_id = self.tree_match_model.insert(set_id, "end", text=side_name, values=("", f"sets/set{s_num}/{t_key}"))
                if set_team:
                    if set_team.formation:
                        f_id = self.tree_match_model.insert(st_id, "end", text="Formation Initiale", values=("", f"sets/set{s_num}/{t_key}/pos1"))
                        for pos_idx in range(1, 7):
                            pos_val = getattr(set_team.formation, f"position_{pos_idx}", None)
                            self.tree_match_model.insert(f_id, "end", text=f"Position {pos_idx}", values=(f"N° {pos_val or '-'}", f"sets/set{s_num}/{t_key}/pos{pos_idx}"))
                    if set_team.timeouts:
                        to_strs = [f"({t.score_a}:{t.score_b})" for t in set_team.timeouts]
                        self.tree_match_model.insert(st_id, "end", text="Temps Morts", values=(", ".join(to_strs), f"sets/set{s_num}/{t_key}/timeouts"))
                    if set_team.changements:
                        chg_strs = [f"N°{c.joueur_sortant}➔N°{c.joueur_entrant} ({c.score_a}:{c.score_b})" for c in set_team.changements]
                        self.tree_match_model.insert(st_id, "end", text="Changements", values=(", ".join(chg_strs), f"sets/set{s_num}/{t_key}"))
                    if set_team.services:
                        srv_strs = [f"P{p}:{sc}" for p, sc in sorted(set_team.services.items())]
                        self.tree_match_model.insert(st_id, "end", text="Services", values=("; ".join(srv_strs), f"sets/set{s_num}/{t_key}/services"))

        # Remarques
        self.tree_match_model.insert(root_id, "end", text="📝 Remarques", values=(str(m.remarques or "(Aucune remarque)"), "remarques"))

    def _populate_compare_tree(self):
        """Remplit le Treeview de comparaison côte-à-côte entre Zone Parser et Legacy Parser."""
        if not hasattr(self, "tree_compare"):
            return

        self.tree_compare.delete(*self.tree_compare.get_children())

        res_z = self.last_parse_result
        res_l = self.last_legacy_result

        z_time = res_z.parse_time_ms if res_z else 0.0
        l_time = res_l.parse_time_ms if res_l else 0.0

        self.lbl_cmp_zone_time.config(text=f"Zone: {z_time:.1f} ms")
        self.lbl_cmp_legacy_time.config(text=f"Legacy: {l_time:.1f} ms")

        if z_time > 0 and l_time > 0:
            speedup = l_time / z_time
            self.lbl_cmp_speedup.config(text=f"Speedup: {speedup:.1f}x")
        else:
            self.lbl_cmp_speedup.config(text="Speedup: -")

        mz = res_z.match if res_z else None
        ml = res_l.match if res_l else None

        if not mz or not ml:
            self.lbl_cmp_parity.config(text="Parité: Indisponible")
            return

        filt = self.var_cmp_filter.get() if hasattr(self, "var_cmp_filter") else "all"

        match_count = 0
        diff_count = 0

        def add_cmp_item(parent_id: str, prop_label: str, z_val: Any, l_val: Any, bbox_key: str = ""):
            nonlocal match_count, diff_count
            z_str = str(z_val) if z_val is not None else "-"
            l_str = str(l_val) if l_val is not None else "-"

            is_match = (z_str == l_str)
            if is_match:
                match_count += 1
                status_str = "🟢 Concordant"
                tag_name = "match"
            else:
                diff_count += 1
                status_str = "🔴 Écart"
                tag_name = "diff"

            if filt == "diffs" and is_match:
                return
            if filt == "matches" and not is_match:
                return

            self.tree_compare.insert(
                parent_id, "end", text=prop_label,
                values=(z_str, l_str, status_str, bbox_key),
                tags=(tag_name,)
            )

        # 1. En-Tête Match
        hdr_id = self.tree_compare.insert("", "end", text="📌 En-Tête Match", values=("", "", "", "header"), tags=("section",), open=True)
        add_cmp_item(hdr_id, "Code Match", mz.code_match, ml.code_match, "header/match_code")
        add_cmp_item(hdr_id, "Date", str(mz.date or "-"), str(ml.date or "-"), "header/date")
        add_cmp_item(hdr_id, "Heure", str(mz.heure or "-"), str(ml.heure or "-"), "header/date")
        add_cmp_item(hdr_id, "Lieu / Ville", mz.lieu, ml.lieu, "header/ville")
        add_cmp_item(hdr_id, "Salle", mz.salle, ml.salle, "header/salle")
        add_cmp_item(hdr_id, "Compétition", mz.competition, ml.competition, "header/competition")
        add_cmp_item(hdr_id, "Journée", mz.journee, ml.journee, "header/journee")
        add_cmp_item(hdr_id, "Organisateur", mz.organisateur, ml.organisateur, "header/organisateur")
        add_cmp_item(hdr_id, "Genre", str(mz.genre or "-"), str(ml.genre or "-"), "header/division_categorie")
        add_cmp_item(hdr_id, "Catégorie", str(mz.categorie or "-"), str(ml.categorie or "-"), "header/division_categorie")
        add_cmp_item(hdr_id, "Score Final", mz.score_final, ml.score_final, "resultats")
        add_cmp_item(hdr_id, "Durée Totale", mz.duree_totale, ml.duree_totale, "resultats")

        # 2. Équipes A & B
        for side, eq_z, eq_l, k_suf in [("Équipe A", mz.equipe_a, ml.equipe_a, "gauche"), ("Équipe B", mz.equipe_b, ml.equipe_b, "droite")]:
            eq_id = self.tree_compare.insert("", "end", text=f"🔵 {side}", values=("", "", "", f"header/equipes/{k_suf}"), tags=("section",), open=True)
            add_cmp_item(eq_id, "Nom Équipe", eq_z.nom if eq_z else "-", eq_l.nom if eq_l else "-", f"header/equipes/{k_suf}")
            add_cmp_item(eq_id, "Capitaine (N°)", eq_z.capitaine if eq_z else "-", eq_l.capitaine if eq_l else "-", f"header/equipes/{k_suf}")

            j_z = len(eq_z.joueurs) if eq_z else 0
            j_l = len(eq_l.joueurs) if eq_l else 0
            add_cmp_item(eq_id, "Nombre Joueurs", f"{j_z} joueur(s)", f"{j_l} joueur(s)", f"header/equipes/{k_suf}/joueurs")

            lib_z = len(eq_z.liberos) if eq_z else 0
            lib_l = len(eq_l.liberos) if eq_l else 0
            add_cmp_item(eq_id, "Nombre Libéros", f"{lib_z} libéro(s)", f"{lib_l} libéro(s)", f"header/equipes/{k_suf}/liberos")

            off_z = len(eq_z.officiels) if eq_z else 0
            off_l = len(eq_l.officiels) if eq_l else 0
            add_cmp_item(eq_id, "Nombre Officiels", f"{off_z} officiel(s)", f"{off_l} officiel(s)", f"header/equipes/{k_suf}/officiels")

        # 3. Arbitres
        arb_id = self.tree_compare.insert("", "end", text="🏁 Corps Arbitral", values=("", "", "", "arbitres"), tags=("section",), open=True)
        add_cmp_item(arb_id, "Nombre Arbitres", f"{len(mz.arbitres)} arbitre(s)", f"{len(ml.arbitres)} arbitre(s)", "arbitres")

        # 4. Sets 1 à 5
        sets_root_id = self.tree_compare.insert("", "end", text="📊 Sets 1 à 5", values=("", "", "", "resultats"), tags=("section",), open=True)

        sets_z = {s.numero: s for s in mz.sets}
        sets_l = {s.numero: s for s in ml.sets}

        for s_num in range(1, 6):
            sz = sets_z.get(s_num)
            sl = sets_l.get(s_num)
            if not sz and not sl:
                continue

            set_id = self.tree_compare.insert(sets_root_id, "end", text=f"Set {s_num}", values=("", "", "", f"sets/set{s_num}"), tags=("section",), open=True)
            add_cmp_item(set_id, "Score", sz.score_str if sz else "-", sl.score_str if sl else "-", f"sets/set{s_num}")
            add_cmp_item(set_id, "Début", str(sz.debut) if sz and sz.debut else "-", str(sl.debut) if sl and sl.debut else "-", f"sets/set{s_num}/debut")
            add_cmp_item(set_id, "Fin", str(sz.fin) if sz and sz.fin else "-", str(sl.fin) if sl and sl.fin else "-", f"sets/set{s_num}/fin")
            add_cmp_item(set_id, "Durée (min)", sz.duree_minutes if sz else "-", sl.duree_minutes if sl else "-", f"sets/set{s_num}")
            add_cmp_item(set_id, "Service Initial", sz.service_initial if sz else "-", sl.service_initial if sl else "-", f"sets/set{s_num}")

            # Formations A & B
            for team_label, eq_sz, eq_sl, t_key in [("Equipe A", sz.equipe_a if sz else None, sl.equipe_a if sl else None, "equipe_a"),
                                                    ("Equipe B", sz.equipe_b if sz else None, sl.equipe_b if sl else None, "equipe_b")]:
                f_z = str(eq_sz.formation) if eq_sz and eq_sz.formation else "-"
                f_l = str(eq_sl.formation) if eq_sl and eq_sl.formation else "-"
                add_cmp_item(set_id, f"Formation {team_label[-1]}", f_z, f_l, f"sets/set{s_num}/{t_key}/pos1")

                chg_z = [(c.joueur_sortant, c.joueur_entrant, f"({c.score_a}:{c.score_b})") for c in (eq_sz.changements if eq_sz else [])]
                chg_l = [(c.joueur_sortant, c.joueur_entrant, f"({c.score_a}:{c.score_b})") for c in (eq_sl.changements if eq_sl else [])]
                add_cmp_item(set_id, f"Changements {team_label[-1]}", str(chg_z) if chg_z else "Aucun", str(chg_l) if chg_l else "Aucun", f"sets/set{s_num}/{t_key}")

                to_z = [(t.score_a, t.score_b) for t in (eq_sz.timeouts if eq_sz else [])]
                to_l = [(t.score_a, t.score_b) for t in (eq_sl.timeouts if eq_sl else [])]
                add_cmp_item(set_id, f"Timeouts {team_label[-1]}", str(to_z) if to_z else "Aucun", str(to_l) if to_l else "Aucun", f"sets/set{s_num}/{t_key}/timeouts")

                srv_z = str(eq_sz.services) if eq_sz and eq_sz.services else "-"
                srv_l = str(eq_sl.services) if eq_sl and eq_sl.services else "-"
                add_cmp_item(set_id, f"Services {team_label[-1]}", srv_z, srv_l, f"sets/set{s_num}/{t_key}/services")

        total_tested = match_count + diff_count
        self.lbl_cmp_parity.config(text=f"Parité: {match_count}/{total_tested} (🟢 {match_count} | 🔴 {diff_count})")

    def _update_zones_table(self):
        """Met à jour le tableau récapitulatif des zones et de leurs statuts d'extraction."""
        if not hasattr(self, "tree_zones_table"):
            return

        self.tree_zones_table.delete(*self.tree_zones_table.get_children())
        filter_query = self.entry_filter_zones.get().strip().lower() if hasattr(self, "entry_filter_zones") else ""

        for path, reg in sorted(self.layout_config.bboxes.items()):
            if filter_query and filter_query not in path.lower() and filter_query not in (reg.description or "").lower():
                continue

            # Comptage des mots et texte dans la zone
            words_in_reg = [w for w in self.words_data if reg.x0 <= w["x0"] <= reg.x1 and reg.y0 <= w["y0"] <= reg.y1]
            raw_text = extract_text_in_zone(self.words_data, reg)
            status = "OK" if raw_text else "Vide"
            bbox_str = f"({reg.x0:.1f}, {reg.y0:.1f}, {reg.x1:.1f}, {reg.y1:.1f})"

            self.tree_zones_table.insert(
                "", "end",
                values=(path, bbox_str, len(words_in_reg), status, raw_text or "-")
            )

    def _on_tree_inspector_selected(self, event):
        selected = self.tree_inspector.selection()
        if not selected:
            return

        vals = self.tree_inspector.item(selected[0], "values")
        if len(vals) > 1 and vals[1]:
            target_path = vals[1]
            if target_path in self.layout_config.bboxes:
                reg = self.layout_config.bboxes[target_path]
                self.highlight_box = (reg.x0, reg.y0, reg.x1, reg.y1)
                self.selected_region_name = target_path
                self._select_zone_in_tree(target_path)
                self._update_spinbox_values()
            else:
                self.highlight_box = None
            self.redraw_canvas()

    def _on_tree_match_model_selected(self, event):
        selected = self.tree_match_model.selection()
        if not selected:
            return

        vals = self.tree_match_model.item(selected[0], "values")
        if len(vals) > 1 and vals[1]:
            target_path = vals[1]
            if target_path in self.layout_config.bboxes:
                reg = self.layout_config.bboxes[target_path]
                self.highlight_box = (reg.x0, reg.y0, reg.x1, reg.y1)
                self.selected_region_name = target_path
                self._select_zone_in_tree(target_path)
                self._update_spinbox_values()
            else:
                self.highlight_box = None
            self.redraw_canvas()

    def _on_tree_compare_selected(self, event):
        selected = self.tree_compare.selection()
        if not selected:
            return

        vals = self.tree_compare.item(selected[0], "values")
        if len(vals) > 3 and vals[3]:
            target_path = vals[3]
            if target_path in self.layout_config.bboxes:
                reg = self.layout_config.bboxes[target_path]
                self.highlight_box = (reg.x0, reg.y0, reg.x1, reg.y1)
                self.selected_region_name = target_path
                self._select_zone_in_tree(target_path)
                self._update_spinbox_values()
            else:
                self.highlight_box = None
            self.redraw_canvas()

    def _on_zones_table_selected(self, event):
        selected = self.tree_zones_table.selection()
        if not selected:
            return

        vals = self.tree_zones_table.item(selected[0], "values")
        if vals and vals[0] in self.layout_config.bboxes:
            target_path = vals[0]
            reg = self.layout_config.bboxes[target_path]
            self.highlight_box = (reg.x0, reg.y0, reg.x1, reg.y1)
            self.selected_region_name = target_path
            self._select_zone_in_tree(target_path)
            self._update_spinbox_values()
            self.redraw_canvas()

    # -------------------------------------------------------------------------
    # Event Handlers Menus & Dialogs
    # -------------------------------------------------------------------------
    def _on_open_pdf_dialog(self):
        file_path = filedialog.askopenfilename(
            title="Sélectionner une feuille de match PDF",
            filetypes=[("Fichiers PDF", "*.pdf"), ("Tous les fichiers", "*.*")]
        )
        if file_path:
            self.load_pdf(Path(file_path))

    def _on_load_preset(self):
        file_path = filedialog.askopenfilename(
            title="Charger un preset de layout JSON",
            filetypes=[("Fichiers JSON", "*.json")]
        )
        if file_path:
            try:
                self.layout_config = ParserLayoutConfig.load_preset(file_path)
                self.lbl_preset_info.config(text=f"Preset: {self.layout_config.name}")
                self._update_zone_tree()
                self.redraw_canvas()
                self.reparse_pdf()
                messagebox.showinfo("Succès", f"Preset '{self.layout_config.name}' chargé avec succès !")
            except Exception as e:
                messagebox.showerror("Erreur", f"Échec du chargement du preset:\n{e}")

    def _on_save_preset(self):
        file_path = filedialog.asksaveasfilename(
            title="Sauvegarder le preset de layout JSON",
            defaultextension=".json",
            filetypes=[("Fichiers JSON", "*.json")]
        )
        if file_path:
            try:
                self.layout_config.save_preset(file_path)
                messagebox.showinfo("Succès", f"Preset sauvegardé dans :\n{file_path}")
            except Exception as e:
                messagebox.showerror("Erreur", f"Échec de la sauvegarde :\n{e}")

    def _on_reset_layout(self):
        self.layout_config = ParserLayoutConfig.from_dict(DEFAULT_FFVB_LAYOUT.to_dict())
        self._update_zone_tree()
        self.redraw_canvas()
        self.reparse_pdf()


def main():
    pdf_file = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    root = tk.Tk()
    app = LayoutEditorApp(root, initial_pdf=pdf_file)
    root.mainloop()


if __name__ == "__main__":
    main()
