"""
Script d'inspection exhaustive du contenu d'une page PDF avec PyMuPDF.

Extrait et dump dans un fichier JSON et un résumé lisible :
- Métadonnées de la page (dimensions, rotation)
- Tous les mots (texte, coordonnées 2D, bloc, ligne, mot)
- Blocs et lignes de texte (avec polices, tailles, couleurs)
- Dessins et graphiques vectoriels (lignes, rects, béziers, couleurs de tracé/remplissage)
- Images et leurs bboxes sur la page (images matricielles, dimensions, formats)
- Formulaires, annotations et liens
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pymupdf as fitz


def dump_pdf_page_content(pdf_path: str | Path, output_json_path: str | Path | None = None) -> dict[str, Any]:
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"Fichier PDF non trouvé : {pdf_path}")

    doc = fitz.open(str(pdf_path))
    if len(doc) == 0:
        raise ValueError(f"Le fichier PDF est vide : {pdf_path}")

    page = doc[0]  # Première page

    page_width = page.rect.width
    page_height = page.rect.height

    # 1. Métadonnées de la page
    data: dict[str, Any] = {
        "file_info": {
            "filename": pdf_path.name,
            "filepath": str(pdf_path.resolve()),
            "total_pages": len(doc),
            "page_number": 1,
            "page_width": page_width,
            "page_height": page_height,
            "rotation": page.rotation,
        },
        "words": [],
        "text_blocks": [],
        "drawings": [],
        "images": [],
        "annotations": [],
    }

    # 2. Extraction des Mots bruts PyMuPDF
    raw_words = page.get_text("words")
    for idx, w in enumerate(raw_words):
        data["words"].append({
            "id": idx + 1,
            "x0": round(w[0], 2),
            "y0": round(w[1], 2),
            "x1": round(w[2], 2),
            "y1": round(w[3], 2),
            "width": round(w[2] - w[0], 2),
            "height": round(w[3] - w[1], 2),
            "text": w[4],
            "block_no": w[5],
            "line_no": w[6],
            "word_no": w[7],
        })

    # 3. Extraction de la structure hiérarchique détaillée (rawdict)
    rawdict = page.get_text("rawdict")
    for b_idx, block in enumerate(rawdict.get("blocks", [])):
        b_type = block.get("type", 0)  # 0 = texte, 1 = image
        bbox = [round(v, 2) for v in block.get("bbox", [0, 0, 0, 0])]

        if b_type == 0:  # Bloc Texte
            lines_data = []
            for l_idx, line in enumerate(block.get("lines", [])):
                spans_data = []
                for s_idx, span in enumerate(line.get("spans", [])):
                    spans_data.append({
                        "text": span.get("text", ""),
                        "font": span.get("font", ""),
                        "size": round(span.get("size", 0), 2),
                        "color": hex(span.get("color", 0)),
                        "bbox": [round(v, 2) for v in span.get("bbox", [0, 0, 0, 0])],
                    })
                lines_data.append({
                    "line_no": l_idx,
                    "bbox": [round(v, 2) for v in line.get("bbox", [0, 0, 0, 0])],
                    "dir": line.get("dir", (1, 0)),
                    "spans": spans_data,
                })
            data["text_blocks"].append({
                "block_no": b_idx,
                "type": "text",
                "bbox": bbox,
                "lines": lines_data,
            })
        elif b_type == 1:  # Bloc Image
            data["text_blocks"].append({
                "block_no": b_idx,
                "type": "image",
                "bbox": bbox,
                "width": round(bbox[2] - bbox[0], 2),
                "height": round(bbox[3] - bbox[1], 2),
                "ext": block.get("ext", ""),
            })

    # 4. Extraction des graphiques vectoriels (Drawings / Vector Paths)
    raw_drawings = page.get_drawings()
    for d_idx, draw in enumerate(raw_drawings):
        rect = draw.get("rect")
        bbox = [round(rect.x0, 2), round(rect.y0, 2), round(rect.x1, 2), round(rect.y1, 2)] if rect else [0, 0, 0, 0]
        
        items_summary = []
        for item in draw.get("items", []):
            item_type = item[0]
            if item_type == "l":  # Ligne
                items_summary.append({
                    "type": "line",
                    "p1": [round(item[1].x, 2), round(item[1].y, 2)],
                    "p2": [round(item[2].x, 2), round(item[2].y, 2)],
                })
            elif item_type == "re":  # Rectangle
                r = item[1]
                items_summary.append({
                    "type": "rect",
                    "bbox": [round(r.x0, 2), round(r.y0, 2), round(r.x1, 2), round(r.y1, 2)],
                })
            elif item_type == "c":  # Courbe Bézier
                items_summary.append({
                    "type": "curve",
                    "p1": [round(item[1].x, 2), round(item[1].y, 2)],
                    "p2": [round(item[2].x, 2), round(item[2].y, 2)],
                    "p3": [round(item[3].x, 2), round(item[3].y, 2)],
                    "p4": [round(item[4].x, 2), round(item[4].y, 2)],
                })

        data["drawings"].append({
            "drawing_id": d_idx + 1,
            "bbox": bbox,
            "width": round(bbox[2] - bbox[0], 2),
            "height": round(bbox[3] - bbox[1], 2),
            "color": draw.get("color"),
            "fill": draw.get("fill"),
            "line_width": draw.get("width", 1.0),
            "closePath": draw.get("closePath", False),
            "items_count": len(draw.get("items", [])),
            "items": items_summary,
        })

    # 5. Extraction détaillée et catégorisation des Images
    try:
        # Cross-reference with page.get_images() for XREF and format details
        page_imgs_raw = page.get_images(full=True)
        xref_info_map = {}
        for img_tuple in page_imgs_raw:
            xref = img_tuple[0]
            xref_info_map[xref] = {
                "xref": xref,
                "smask": img_tuple[1],
                "pix_width": img_tuple[2],
                "pix_height": img_tuple[3],
                "bpc": img_tuple[4],
                "colorspace": img_tuple[5],
                "filter": img_tuple[8],
            }

        image_info_list = page.get_image_info(hashes=True)
        for img_idx, img in enumerate(image_info_list):
            bbox = [round(v, 2) for v in img.get("bbox", [0, 0, 0, 0])]
            w = round(bbox[2] - bbox[0], 2)
            h = round(bbox[3] - bbox[1], 2)
            y0 = bbox[1]
            x0 = bbox[0]
            xref = img.get("xref", 0)

            raw_extra = xref_info_map.get(xref, {})
            digest_hex = img.get("digest").hex() if isinstance(img.get("digest"), bytes) else str(img.get("digest", ""))

            # Catégorisation automatique de l'image
            category = "Autre"
            if x0 < 100 and y0 < 60 and w > 40:
                category = "Logo Organisateur (ex: FFVB / Ligue)"
            elif 550 <= x0 <= 835 and 270 <= y0 <= 420 and 5 <= w <= 25 and 5 <= h <= 25:
                category = "Cercle Capitaine (Maillot)"
            elif 400 <= x0 <= 450 and 50 <= y0 <= 80 and 8 <= w <= 20:
                category = "Icône Équipe A/B"
            elif 5 <= w <= 15 and 5 <= h <= 15:
                category = "Puce / Puce de tableau / Case"
            elif y0 > 450 and w > 30:
                category = "Signature / Tampon"

            data["images"].append({
                "image_id": img_idx + 1,
                "xref": xref,
                "category": category,
                "bbox": bbox,
                "page_width": w,
                "page_height": h,
                "pixel_width": img.get("width", raw_extra.get("pix_width")),
                "pixel_height": img.get("height", raw_extra.get("pix_height")),
                "colorspace": raw_extra.get("colorspace", "Inconnu"),
                "filter": raw_extra.get("filter", "Inconnu"),
                "md5_hash": digest_hex,
                "xres": img.get("xres"),
                "yres": img.get("yres"),
            })
    except Exception as e:
        pass

    # 6. Extraction des Annotations / Widgets
    annots = page.annots()
    if annots:
        for a_idx, annot in enumerate(annots):
            r = annot.rect
            data["annotations"].append({
                "annot_id": a_idx + 1,
                "type": annot.type[1],
                "bbox": [round(r.x0, 2), round(r.y0, 2), round(r.x1, 2), round(r.y1, 2)],
                "info": annot.info,
            })

    doc.close()

    # Sauvegarde au format JSON si demandé
    if output_json_path:
        out_path = Path(output_json_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"Dump JSON complet enregistré dans : {out_path.resolve()}")

    return data


def print_summary(data: dict[str, Any]) -> None:
    f_info = data["file_info"]
    print("\n=======================================================")
    print(f" DUMP CONTENU PDF: {f_info['filename']}")
    print("=======================================================")
    print(f"Dimensions page : {f_info['page_width']} x {f_info['page_height']} pt (A4 Paysage)")
    print(f"Nombre de mots  : {len(data['words'])}")
    print(f"Blocs de texte  : {len(data['text_blocks'])}")
    print(f"Graphiques/Lignes: {len(data['drawings'])}")
    print(f"Images d'objets : {len(data['images'])}")
    print(f"Annotations     : {len(data['annotations'])}")
    print("-------------------------------------------------------")

    # Échantillon des 10 premiers mots
    print("\n--- Échantillon des 10 premiers mots ---")
    for w in data["words"][:10]:
        print(f"  Word #{w['id']:3d} | '{w['text']:15s}' | Box: [{w['x0']:6.1f}, {w['y0']:6.1f}, {w['x1']:6.1f}, {w['y1']:6.1f}]")

    # Échantillon des 5 premiers dessins
    print("\n--- Échantillon des 5 premiers dessins/vecteurs ---")
    for d in data["drawings"][:5]:
        print(f"  Drawing #{d['drawing_id']:2d} | Box: {d['bbox']} | Stroke: {d['color']} | Fill: {d['fill']} | Items: {d['items_count']}")

    # Échantillon des images groupées par catégorie
    if data["images"]:
        print("\n--- Analyse détaillée et différenciation des Images ---")
        categories: dict[str, list[dict]] = {}
        for img in data["images"]:
            cat = img["category"]
            categories.setdefault(cat, []).append(img)

        for cat, img_list in categories.items():
            print(f"\n  -> Catégorie : {cat} ({len(img_list)} trouvée(s))")
            for img in img_list[:6]:  # Afficher jusqu'à 6 exemples par catégorie
                print(
                    f"     - Image #{img['image_id']:2d} | XREF: {img['xref']:4d} | "
                    f"Pos: [{img['bbox'][0]:6.1f}, {img['bbox'][1]:6.1f}] | "
                    f"Taille Page: {img['page_width']}x{img['page_height']} pt | "
                    f"Pixels: {img['pixel_width']}x{img['pixel_height']} | "
                    f"MD5: {img['md5_hash'][:8]}..."
                )
            if len(img_list) > 6:
                print(f"     ... et {len(img_list) - 6} autre(s) image(s) similaire(s)")


def main():
    if len(sys.argv) > 1:
        pdf_path = sys.argv[1]
    else:
        # Fichier PDF par défaut si aucun n'est fourni en argument
        pdf_path = "data/pdfs/2025-2026/PTCE28/18M/18M021.pdf"
        if not Path(pdf_path).exists():
            # Chercher le premier PDF dans data/
            found = list(Path("data").glob("**/*.pdf"))
            if found:
                pdf_path = str(found[0])

    output_json = Path(pdf_path).stem + "_dump.json"
    print(f"Analyse du fichier : {pdf_path}")

    data = dump_pdf_page_content(pdf_path, output_json_path=output_json)
    print_summary(data)


if __name__ == "__main__":
    main()
