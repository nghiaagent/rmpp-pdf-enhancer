"""
Generate landscape side-by-side benchmark comparisons for reMarkable Paper Pro.
Dataset: MIT-Adobe FiveK benchmark dataset.
Resolution: 2160 x 1620 @ 229 PPI (Native Paper Pro Canvas Color landscape).
"""

import os
import sys
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
DPI = 229

# Fonts
FONT_HELVETICA = "/System/Library/Fonts/Helvetica.ttc"
FONT_ARIAL = "/Library/Fonts/Arial.ttf"
FONT_ARIAL_ALT = "/System/Library/Fonts/Supplemental/Arial.ttf"


def get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for fp in [FONT_HELVETICA, FONT_ARIAL, FONT_ARIAL_ALT]:
        if os.path.exists(fp):
            try:
                # Helvetica: 0 is Regular, 1 is Bold
                index = 1 if (bold and "Helvetica" in fp) else 0
                return ImageFont.truetype(fp, size, index=index)
            except Exception:
                continue
    return ImageFont.load_default()


def create_comparison_page(
    orig_img_path: str,
    scene_num: int,
    scene_title: str,
    scene_domain: str,
    test_description: str,
    config: EnhancerConfig,
) -> Image.Image:
    # 1. Load source image
    src_img = Image.open(orig_img_path).convert("RGB")
    src_w, src_h = src_img.size

    # Panel geometry
    # Canvas is 2160 x 1620.
    # Top banner: y = 0 to 140
    # Bottom banner: y = 1530 to 1620
    # Usable image area: height = 1370 px (from y=150 to y=1520)
    # Left panel: x = 30 to 1050 (width 1020)
    # Right panel: x = 1110 to 2130 (width 1020)
    # Center divider: x = 1079 to 1081 (vertical line)
    max_pw = 1020
    max_ph = 1370

    scale = min(max_pw / src_w, max_ph / src_h)
    new_w = int(round(src_w * scale))
    new_h = int(round(src_h * scale))

    # Scale original image
    orig_scaled = src_img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    # Apply enhancement pipeline to create compensated image
    # 1) 3D LUT
    pil_lut = load_3d_lut(config.lut_path)
    lut_applied = orig_scaled.filter(pil_lut) if pil_lut else orig_scaled
    # 2) Edge inking
    comp_scaled = apply_edge_directed_inking(lut_applied)

    # 2. Create blank canvas
    # Pure clean background: #F8F9FA (crisp paper)
    canvas = Image.new("RGB", (CANVAS_W, CANVAS_H), (248, 249, 250))
    draw = ImageDraw.Draw(canvas)

    # 3. Header styling
    # Top bar background
    draw.rectangle([0, 0, CANVAS_W, 130], fill=(238, 240, 243))
    draw.line([0, 130, CANVAS_W, 130], fill=(210, 214, 220), width=2)

    font_title = get_font(34, bold=True)
    font_meta = get_font(22, bold=False)
    font_badge = get_font(26, bold=True)
    font_badge_sub = get_font(18, bold=False)
    font_footer = get_font(20, bold=False)

    # Title & Metadata
    title_text = f"Scene {scene_num}: {scene_title}"
    meta_text = f"MIT-Adobe FiveK Dataset • {scene_domain} • Canvas Color Evaluation"
    draw.text((36, 26), title_text, fill=(20, 24, 33), font=font_title)
    draw.text((38, 76), meta_text, fill=(80, 88, 102), font=font_meta)

    # Target DPI badge at top right
    dpi_text = "reMarkable Paper Pro (2160 × 1620 @ 229 PPI)"
    draw.text((CANVAS_W - 560, 48), dpi_text, fill=(100, 108, 120), font=font_meta)

    # 4. Vertical divider line
    draw.line([1080, 130, 1080, 1530], fill=(210, 214, 220), width=2)

    # 5. Position image panels (vertically centered in y=140..1520)
    img_y = 145 + (1370 - new_h) // 2
    left_x = 30 + (1020 - new_w) // 2
    right_x = 1110 + (1020 - new_w) // 2

    # Draw panel borders
    draw.rectangle([left_x - 2, img_y - 2, left_x + new_w + 1, img_y + new_h + 1], outline=(200, 204, 210), width=1)
    draw.rectangle([right_x - 2, img_y - 2, right_x + new_w + 1, img_y + new_h + 1], outline=(200, 204, 210), width=1)

    canvas.paste(orig_scaled, (left_x, img_y))
    canvas.paste(comp_scaled, (right_x, img_y))

    # 6. Column badges (Left: Original sRGB / Right: Compensated RMPP)
    # Left badge (neutral gray/dark)
    badge_y = 145
    draw.rectangle([left_x + 12, img_y + 12, left_x + 280, img_y + 58], fill=(20, 24, 30, 220), outline=(255, 255, 255))
    draw.text((left_x + 24, img_y + 20), "Original sRGB", fill=(255, 255, 255), font=font_badge)

    # Right badge (accent/blue)
    draw.rectangle([right_x + 12, img_y + 12, right_x + 370, img_y + 58], fill=(16, 52, 112), outline=(255, 255, 255))
    draw.text((right_x + 24, img_y + 20), "Compensated RMPP", fill=(255, 255, 255), font=font_badge)

    # 7. Bottom footer
    draw.rectangle([0, 1530, CANVAS_W, CANVAS_H], fill=(238, 240, 243))
    draw.line([0, 1530, CANVAS_W, 1530], fill=(210, 214, 220), width=2)

    # Left note
    draw.text((left_x, 1555), "Direct sRGB input: subject to pigment desaturation and shadow crush on Canvas Color.", fill=(90, 95, 105), font=font_footer)
    # Right note
    draw.text((right_x, 1555), f"Pipeline calibrated: {test_description}", fill=(16, 52, 112), font=font_footer)

    return canvas


def main():
    config = EnhancerConfig(quality=82, subsampling=0)

    # Test cases: 5 diverse scenes from MIT FiveK
    scenes = [
        {
            "num": 1,
            "title": "Portrait and skin tones",
            "domain": "Canon EOS-1D Mark II • People / Indoor Portrait",
            "description": "Warm tone protection prevents unnatural red/orange shift on faces",
            "file": "/tmp/fivek_candidates/a4607.jpg",
            "id": "mit_scene_1_portrait",
        },
        {
            "num": 2,
            "title": "Deep shadow and low-light exposure",
            "domain": "Night Architecture • Low-Light Contrast",
            "description": "Monotonic Hermite de-crush recovers dark shadow details above Y=0.18 floor",
            "file": "/tmp/fivek_candidates/row_2.jpg",
            "id": "mit_scene_2_shadow",
        },
        {
            "num": 3,
            "title": "Cool landscape and blue sky",
            "domain": "Leica M8 • Sun & Sky Landscape",
            "description": "Cool-tone luminance lift brightens skies and water without hue clipping",
            "file": "/tmp/fivek_candidates/a1384.jpg",
            "id": "mit_scene_3_landscape",
        },
        {
            "num": 4,
            "title": "Vibrant flora and high-gamut pigments",
            "domain": "High-Saturation Macro • Floral Pigments",
            "description": "OKLab gamut mapping preserves high-saturation yellow, orange and magenta pigments without clipping",
            "file": "/tmp/fivek_candidates/row_11.jpg",
            "id": "mit_scene_4_vibrant",
        },
        {
            "num": 5,
            "title": "Fine nature texture and foliage",
            "domain": "Canon EOS-1D Mark II • Intricate Green Foliage & Animals",
            "description": "Bilateral edge-directed inking deepens lines and elevates micro-contrast",
            "file": "/tmp/fivek_candidates/a1629.jpg",
            "id": "mit_scene_5_foliage",
        },
    ]

    out_dir = "/Users/nghiaagent/Downloads/20260912-200000-converts"
    docs_img_dir = "/Users/nghiaagent/git-repos/rmpp-pdf-enhancer/docs/images"
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(docs_img_dir, exist_ok=True)

    page_jpegs = []
    chapters = []

    print(f"=======================================================")
    print(f"🎨 Generating 5 MIT FiveK Landscape Comparisons")
    print(f"   Canvas: {CANVAS_W}x{CANVAS_H} @ {DPI} PPI")
    print(f"=======================================================")

    for idx, sc in enumerate(scenes):
        print(f"\nProcessing Scene {sc['num']}: {sc['title']}...")
        page_img = create_comparison_page(
            orig_img_path=sc["file"],
            scene_num=sc["num"],
            scene_title=sc["title"],
            scene_domain=sc["domain"],
            test_description=sc["description"],
            config=config,
        )

        # Save individual high-res JPEG
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

        print(f"✓ Saved JPEG: {jpeg_filename} ({os.path.getsize(jpeg_out_path)/1024:.1f} KB)")
        page_jpegs.append(jpeg_out_path)
        chapters.append((f"Scene {sc['num']}: {sc['title']}", idx + 1))

    # Assemble into single multi-page PDF
    pdf_out_path = os.path.join(out_dir, "MIT_PaperPro_Comparison.pdf")
    docs_pdf_path = os.path.join(docs_img_dir, "MIT_PaperPro_Comparison.pdf")

    print(f"\n📦 Compiling PDF: {os.path.basename(pdf_out_path)}...")
    compile_pdf(page_jpegs, pdf_out_path, chapters=chapters)
    # Also copy to docs
    import shutil
    shutil.copyfile(pdf_out_path, docs_pdf_path)

    pdf_size_mb = os.path.getsize(pdf_out_path) / (1024 * 1024)
    print(f"🎉 Created {pdf_out_path} ({pdf_size_mb:.2f} MB, {len(page_jpegs)} pages)")
    print(f"   Also copied to {docs_pdf_path}")


if __name__ == "__main__":
    main()
