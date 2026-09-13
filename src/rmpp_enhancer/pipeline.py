"""
Core image processing pipeline for reMarkable Paper Pro.

Features:
- Exact 1:1 pixel mapping for 11.8" Gallery 3 Canvas Color screen (2160 x 1620 @ 229 PPI).
- Calibrated 3D LUT inverse compensation (OKLab v3 color space).
- Bilateral edge-directed inking filter to deepen dialogue line-art and counteract pigment dithering.
- Tuned JPEG compression for fast cloud sync and minimal storage.
- Powered unconditionally by native PyO3 Rust SIMD accelerator (_accelerator).
"""

from dataclasses import dataclass
from typing import Optional
from PIL import Image

from rmpp_enhancer._accelerator import enhance_page_to_jpeg


@dataclass
class EnhancerConfig:
    quality: int = 82               # Tuned sweet-spot for fast reMarkable sync
    subsampling: int = 0            # 0 = 4:4:4 (full chroma), 2 = 4:2:0
    color_correction: bool = True   # Apply OKLab v3 3D LUT
    edge_inking: bool = True        # Apply bilateral edge-directed inking
    lut_path: Optional[str] = None  # Path to .cube LUT file (None = use bundled)
    target_width: int = 1620        # RMPP portrait width
    target_height: int = 2160       # RMPP portrait height
    dpi: int = 229                  # Native screen density


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


def process_and_save_page(img: Image.Image, dst_path: str, config: EnhancerConfig) -> str:
    """
    Enhances and encodes a single page image directly to JPEG.

    Delegates proportional resizing, 3D LUT evaluation, inking arithmetic, and
    JPEG encoding to the native Rust accelerator with GIL released for lock-free
    multi-core parallelism.
    """
    rgb = prepare_rgb(img)
    w, h = rgb.size
    enhance_page_to_jpeg(
        w,
        h,
        rgb.tobytes(),
        dst_path,
        quality=config.quality,
        subsampling=config.subsampling,
        color_correction=config.color_correction,
        edge_inking=config.edge_inking,
        custom_lut_path=config.lut_path,
        target_width=config.target_width,
        target_height=config.target_height,
        dpi=config.dpi,
    )
    return dst_path

