"""
Core image processing pipeline for reMarkable Paper Pro.

Features:
- Exact 1:1 pixel mapping for 11.8" Gallery 3 Canvas Color screen (2160 x 1620 @ 229 PPI).
- Calibrated 3D LUT inverse compensation (OKLab v3 color space).
- Bilateral edge-directed inking filter to deepen dialogue line-art and counteract pigment dithering.
- Dual-page spread auto-detection and splitting (RTL manga / LTR western).
- Tuned JPEG compression for fast cloud sync and minimal storage.
"""

import os
from dataclasses import dataclass
from typing import List, Optional, Tuple
from PIL import Image, ImageFilter
import numpy as np

from rmpp_enhancer.profiles import DEFAULT_LUT_PATH


@dataclass
class EnhancerConfig:
    quality: int = 82               # Tuned sweet-spot for fast reMarkable sync
    subsampling: int = 0            # 0 = 4:4:4 (full chroma), 2 = 4:2:0
    color_correction: bool = True   # Apply OKLab v3 3D LUT
    edge_inking: bool = True        # Apply bilateral edge-directed inking
    split_spreads: bool = False     # Split wide double spreads into 2 portrait pages
    spread_direction: str = "rtl"   # "rtl" (manga: right first) or "ltr" (western: left first)
    lut_path: Optional[str] = None  # Path to .cube LUT file (None = use bundled)
    target_width: int = 1620        # RMPP portrait width
    target_height: int = 2160       # RMPP portrait height
    dpi: int = 229                  # Native screen density


# Global cache for the parsed Pillow 3D LUT
_CACHED_LUT: Optional[ImageFilter.Color3DLUT] = None
_CACHED_LUT_PATH: Optional[str] = None


def load_3d_lut(cube_path: Optional[str] = None) -> ImageFilter.Color3DLUT:
    """Loads and caches a .cube 3D LUT into Pillow's Color3DLUT format."""
    global _CACHED_LUT, _CACHED_LUT_PATH
    actual_path = cube_path or DEFAULT_LUT_PATH

    if _CACHED_LUT is not None and _CACHED_LUT_PATH == actual_path:
        return _CACHED_LUT

    if not os.path.exists(actual_path):
        raise FileNotFoundError(f"3D LUT profile not found at {actual_path}")

    lut_table = []
    size = 33
    with open(actual_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("LUT_3D_SIZE"):
                size = int(line.split()[1])
                continue
            if line.startswith("TITLE") or line.startswith("DOMAIN"):
                continue
            parts = [float(x) for x in line.split()]
            if len(parts) == 3:
                lut_table.extend(parts)

    expected_len = size * size * size * 3
    if len(lut_table) != expected_len:
        raise ValueError(f"Invalid LUT data in {actual_path}: expected {expected_len} values, got {len(lut_table)}")

    _CACHED_LUT = ImageFilter.Color3DLUT(size, lut_table)
    _CACHED_LUT_PATH = actual_path
    return _CACHED_LUT


def prepare_rgb(img: Image.Image) -> Image.Image:
    """Ensures image is in RGB mode with alpha composited over pure white."""
    if img.mode == "RGB":
        return img
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        rgba = img.convert("RGBA")
        bg.paste(rgba, mask=rgba.split()[3])
        return bg
    return img.convert("RGB")


def scale_to_rmpp_geometry(img: Image.Image, config: EnhancerConfig) -> Image.Image:
    """Scales image proportionally to reMarkable Paper Pro Option A screen dimensions."""
    w, h = img.size
    if h >= w:
        # Portrait: fit within 1620 x 2160 (height target 2160)
        scale = min(config.target_width / w, config.target_height / h)
    else:
        # Landscape spread: fit within 2160 x 1620
        scale = min(config.target_height / w, config.target_width / h)

    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))

    if (new_w, new_h) != (w, h):
        return img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    return img


def apply_edge_directed_inking(img: Image.Image) -> Image.Image:
    """
    Applies bilateral edge-directed inking filter:
    1. Detects high-contrast edge gradients.
    2. Deepens dark ink lines (lum < 0.40) to counteract pigment diffusion.
    3. Brightens edge halos (lum >= 0.40) for crisp line separation.
    4. Applies micro-contrast unsharp mask.
    """
    gray = img.convert("L")
    edges = gray.filter(ImageFilter.FIND_EDGES)
    edges_arr = np.array(edges, dtype=np.float32) / 255.0
    edge_mask = edges_arr > 0.16

    arr = np.array(img, dtype=np.float32) / 255.0
    lum = 0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2]

    dark_ink = edge_mask & (lum < 0.40)
    light_surround = edge_mask & (lum >= 0.40)

    for c in range(3):
        arr[..., c][dark_ink] = np.clip(arr[..., c][dark_ink] * 0.75, 0.0, 1.0)
        arr[..., c][light_surround] = np.clip(arr[..., c][light_surround] * 1.10, 0.0, 1.0)

    res = Image.fromarray((arr * 255).astype(np.uint8))
    return res.filter(ImageFilter.UnsharpMask(radius=1.0, percent=115, threshold=3))


def process_image(img: Image.Image, config: EnhancerConfig) -> List[Image.Image]:
    """
    Runs an image through the full RMPP processing pipeline.
    May return 1 or 2 images (if wide spread auto-splitting is active).
    """
    rgb = prepare_rgb(img)

    # Check for wide double-page spread splitting
    images_to_process: List[Image.Image] = []
    w, h = rgb.size
    is_wide_spread = config.split_spreads and (w > 1.25 * h)

    if is_wide_spread:
        half_w = w // 2
        left_half = rgb.crop((0, 0, half_w, h))
        right_half = rgb.crop((half_w, 0, w, h))

        if config.spread_direction.lower() == "rtl":
            # Manga / Japanese comic: read right page then left page
            images_to_process = [right_half, left_half]
        else:
            # Western comic: read left page then right page
            images_to_process = [left_half, right_half]
    else:
        images_to_process = [rgb]

    results: List[Image.Image] = []
    pil_lut = load_3d_lut(config.lut_path) if config.color_correction else None

    for im in images_to_process:
        # 1. Scale to Option A Geometry (@ 229 PPI)
        scaled = scale_to_rmpp_geometry(im, config)

        # 2. 3D LUT Color Calibration
        if config.color_correction and pil_lut is not None:
            corrected = scaled.filter(pil_lut)
        else:
            corrected = scaled

        # 3. Bilateral Edge Inking Filter
        if config.edge_inking:
            final_img = apply_edge_directed_inking(corrected)
        else:
            final_img = corrected

        results.append(final_img)

    return results


def save_page_jpeg(img: Image.Image, dst_path: str, config: EnhancerConfig) -> str:
    """Saves enhanced image to JPEG with specified quality, chroma subsampling, and DPI."""
    img.save(
        dst_path,
        "JPEG",
        quality=config.quality,
        subsampling=config.subsampling,
        optimize=True,
        dpi=(config.dpi, config.dpi),
    )
    return dst_path
