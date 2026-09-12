"""
Generate landscape side-by-side benchmark comparisons for reMarkable Paper Pro.
Dataset: Curated illustrations (Genshin, Boshik, Yuvalkirstain anime) and standard color card.
Resolution: 2160 x 1620 @ 229 PPI (Native Paper Pro Canvas Color landscape).

Layout:
- Canvas: 2160 x 1620 px
- Left half: Original sRGB (1080 x 1620 px)
- Right half: Compensated RMPP (1080 x 1620 px)
- Subtle 2px divider at x=1080 and minimal corner badges for clean tablet photography.
"""

import os
import shutil
import sys
from typing import Dict, List, Tuple
from PIL import Image, ImageDraw, ImageFont
import numpy as np

# Ensure src is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from rmpp_enhancer.pipeline import (
    EnhancerConfig,
    load_3d_lut,
    apply_edge_directed_inking,
)
from rmpp_enhancer.pdf_builder import compile_pdf


CANVAS_W = 2160
CANVAS_H = 1620
PANEL_W = 1080
PANEL_H = 1620
DPI = 229

# System fonts
FONT_HELVETICA = "/System/Library/Fonts/Helvetica.ttc"
FONT_ARIAL = "/Library/Fonts/Arial.ttf"
FONT_ARIAL_ALT = "/System/Library/Fonts/Supplemental/Arial.ttf"


def get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Load system font with graceful fallback."""
    for fp in [FONT_HELVETICA, FONT_ARIAL, FONT_ARIAL_ALT]:
        if os.path.exists(fp):
            try:
                index = 1 if (bold and "Helvetica" in fp) else 0
                return ImageFont.truetype(fp, size, index=index)
            except Exception:
                continue
    return ImageFont.load_default()


def prepare_original_panel(
    img_path: str,
    fit_mode: str = "cover",
) -> Image.Image:
    """
    Prepare a 1080 x 1620 original image panel.

    fit_mode:
        - "cover": Aspect-fill and center crop to fill the entire 1080 x 1620 area.
        - "fit_white": Aspect-fit inside 1040 x 1560 and center on pure white (255, 255, 255).
        - "character_alpha": Crop to non-transparent bounding box and center on pure white.
    """
    raw_img = Image.open(img_path)

    if fit_mode == "character_alpha":
        rgba = raw_img.convert("RGBA")
        alpha = np.array(rgba)[:, :, 3]
        cols = np.where(alpha.max(axis=0) > 10)[0]
        rows = np.where(alpha.max(axis=1) > 10)[0]
        if len(cols) > 0 and len(rows) > 0:
            cropped = rgba.crop((cols[0], rows[0], cols[-1] + 1, rows[-1] + 1))
        else:
            cropped = rgba

        # Scale character to fit nicely inside 1020 x 1540
        max_w, max_h = 1020, 1540
        scale = min(max_w / cropped.width, max_h / cropped.height)
        new_w = int(round(cropped.width * scale))
        new_h = int(round(cropped.height * scale))
        scaled = cropped.resize((new_w, new_h), Image.Resampling.LANCZOS)

        panel = Image.new("RGB", (PANEL_W, PANEL_H), (255, 255, 255))
        px = (PANEL_W - new_w) // 2
        py = (PANEL_H - new_h) // 2
        panel.paste(scaled, (px, py), scaled)
        return panel

    elif fit_mode == "fit_white":
        rgb = raw_img.convert("RGB")
        max_w, max_h = 1040, 1560
        scale = min(max_w / rgb.width, max_h / rgb.height)
        new_w = int(round(rgb.width * scale))
        new_h = int(round(rgb.height * scale))
        scaled = rgb.resize((new_w, new_h), Image.Resampling.LANCZOS)

        panel = Image.new("RGB", (PANEL_W, PANEL_H), (255, 255, 255))
        px = (PANEL_W - new_w) // 2
        py = (PANEL_H - new_h) // 2
        panel.paste(scaled, (px, py))
        return panel

    else:  # "cover"
        rgb = raw_img.convert("RGB")
        scale = max(PANEL_W / rgb.width, PANEL_H / rgb.height)
        new_w = int(round(rgb.width * scale))
        new_h = int(round(rgb.height * scale))
        scaled = rgb.resize((new_w, new_h), Image.Resampling.LANCZOS)

        crop_x = (new_w - PANEL_W) // 2
        crop_y = (new_h - PANEL_H) // 2
        panel = scaled.crop((crop_x, crop_y, crop_x + PANEL_W, crop_y + PANEL_H))
        return panel


def create_comparison_page(
    spec: Dict,
    config: EnhancerConfig,
    pil_lut,
) -> Image.Image:
    """Create a 2160 x 1620 side-by-side comparison page."""
    # 1. Prepare original left panel (1080 x 1620)
    orig_panel = prepare_original_panel(spec["file"], fit_mode=spec["fit_mode"])

    # 2. Process right panel (1080 x 1620) with 3D LUT + edge inking
    lut_applied = orig_panel.filter(pil_lut) if pil_lut else orig_panel
    comp_panel = apply_edge_directed_inking(lut_applied)

    # 3. Create full canvas (2160 x 1620)
    canvas = Image.new("RGB", (CANVAS_W, CANVAS_H), (255, 255, 255))
    canvas.paste(orig_panel, (0, 0))
    canvas.paste(comp_panel, (PANEL_W, 0))

    draw = ImageDraw.Draw(canvas)

    # 4. Subtle center divider line at x = 1080
    draw.line([(PANEL_W - 1, 0), (PANEL_W - 1, CANVAS_H)], fill=(200, 204, 210), width=2)

    # 5. Minimal corner badges for clean tablet photography
    font_badge = get_font(22, bold=True)

    # Left badge: Original sRGB (bottom-left)
    draw.rounded_rectangle([24, 1560, 24 + 172, 1560 + 38], radius=6, fill=(24, 28, 36))
    draw.text((36, 1568), "Original sRGB", fill=(255, 255, 255), font=font_badge)

    # Right badge: Compensated RMPP (bottom-right)
    draw.rounded_rectangle(
        [CANVAS_W - 24 - 232, 1560, CANVAS_W - 24, 1560 + 38],
        radius=6,
        fill=(16, 52, 112),
    )
    draw.text(
        (CANVAS_W - 24 - 220, 1568),
        "Compensated RMPP",
        fill=(255, 255, 255),
        font=font_badge,
    )

    return canvas


def main():
    config = EnhancerConfig(quality=82, subsampling=0)
    pil_lut = load_3d_lut(config.lut_path)

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    asset_dir = os.path.join(repo_root, "assets", "benchmark_illustrations")

    # 7 diverse benchmark targets
    scenes = [
        {
            "num": 1,
            "title": "Color card calibration target",
            "file": os.path.join(asset_dir, "01_colorcard_target.png"),
            "fit_mode": "fit_white",
            "id": "illust_scene_1_colorcard",
        },
        {
            "num": 2,
            "title": "Genshin Impact: Navia (warm gold and amber)",
            "file": os.path.join(asset_dir, "02_genshin_navia_gold.png"),
            "fit_mode": "character_alpha",
            "id": "illust_scene_2_navia_gold",
        },
        {
            "num": 3,
            "title": "Genshin Impact: Neuvillette (midnight navy and hydro cyan)",
            "file": os.path.join(asset_dir, "03_genshin_neuvillette_navy.png"),
            "fit_mode": "character_alpha",
            "id": "illust_scene_3_neuvillette_navy",
        },
        {
            "num": 4,
            "title": "Anime landscape: Shinto shrine valley (daylight scenery)",
            "file": os.path.join(asset_dir, "04_anime_shrine_valley.png"),
            "fit_mode": "cover",
            "id": "illust_scene_4_anime_shrine_valley",
        },
        {
            "num": 5,
            "title": "Anime landscape: Winter railway station (night snow)",
            "file": os.path.join(asset_dir, "05_anime_winter_railway.png"),
            "fit_mode": "cover",
            "id": "illust_scene_5_anime_winter_railway",
        },
        {
            "num": 6,
            "title": "Graphic pop art: Summer figure (high gamut yellow and coral pink)",
            "file": os.path.join(asset_dir, "06_boshik_summer_popart.jpg"),
            "fit_mode": "cover",
            "id": "illust_scene_6_boshik_summer_popart",
        },
        {
            "num": 7,
            "title": "Graphic illustration: Palm foliage (vibrant modern palette)",
            "file": os.path.join(asset_dir, "07_boshik_tropical_foliage.jpg"),
            "fit_mode": "cover",
            "id": "illust_scene_7_boshik_tropical_foliage",
        },
    ]

    out_dir = "/Users/nghiaagent/Downloads/20260912-200000-converts"
    docs_img_dir = os.path.join(repo_root, "docs", "images")
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(docs_img_dir, exist_ok=True)

    page_jpegs = []
    chapters = []

    print("=======================================================")
    print("🎨 Generating 7 Illustration Landscape Comparisons")
    print(f"   Canvas: {CANVAS_W}x{CANVAS_H} @ {DPI} PPI")
    print(f"   Panels: Left {PANEL_W}x{PANEL_H} (Original) | Right {PANEL_W}x{PANEL_H} (Compensated)")
    print("=======================================================")

    for idx, sc in enumerate(scenes):
        print(f"\nProcessing Page {sc['num']}: {sc['title']}...")
        if not os.path.exists(sc["file"]):
            raise FileNotFoundError(f"Missing asset file: {sc['file']}")

        page_img = create_comparison_page(
            spec=sc,
            config=config,
            pil_lut=pil_lut,
        )

        jpeg_filename = f"{sc['id']}_comparison.jpg"
        jpeg_out_path = os.path.join(out_dir, jpeg_filename)
        docs_out_path = os.path.join(docs_img_dir, jpeg_filename)

        page_img.save(
            jpeg_out_path,
            "JPEG",
            quality=config.quality,
            subsampling=config.subsampling,
            dpi=(DPI, DPI),
            optimize=True,
        )
        page_img.save(
            docs_out_path,
            "JPEG",
            quality=config.quality,
            subsampling=config.subsampling,
            dpi=(DPI, DPI),
            optimize=True,
        )

        size_kb = os.path.getsize(jpeg_out_path) / 1024
        print(f"✓ Saved JPEG: {jpeg_filename} ({size_kb:.1f} KB)")
        page_jpegs.append(jpeg_out_path)
        chapters.append((f"Page {sc['num']}: {sc['title']}", idx + 1))

    # Assemble into single multi-page PDF
    pdf_out_path = os.path.join(out_dir, "Illustration_PaperPro_Comparison.pdf")
    docs_pdf_path = os.path.join(docs_img_dir, "Illustration_PaperPro_Comparison.pdf")

    print(f"\n📦 Compiling PDF: {os.path.basename(pdf_out_path)}...")
    compile_pdf(page_jpegs, pdf_out_path, chapters=chapters)
    shutil.copyfile(pdf_out_path, docs_pdf_path)

    pdf_size_mb = os.path.getsize(pdf_out_path) / (1024 * 1024)
    print(f"🎉 Created {pdf_out_path} ({pdf_size_mb:.2f} MB, {len(page_jpegs)} pages)")
    print(f"   Also copied to {docs_pdf_path}")


if __name__ == "__main__":
    main()
