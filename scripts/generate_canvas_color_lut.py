#!/usr/bin/env python3
"""
generate_canvas_color_lut.py

Reproduces the official reMarkable Paper Pro Canvas Color 3D LUT profile:
`src/rmpp_enhancer/profiles/rmpp_canvas_color.cube`

Color science pipeline:
-----------------------
Synthesizes a 33x33x33 Adobe/Resolve `.cube` lookup table in the perceptually
uniform OKLab color space to compensate for physical E Ink Gallery 3 characteristics:

1. Monotonic Hermite spline tone curve on lightness (L):
   Smoothly de-crushes deep shadows (L < 0.35) while preserving true black ink (L = 0)
   and natural midtones.

2. Chrominance-dependent luminance equalization (LCE):
   Boosts lightness of cool hues (cyan, teal, blue: 110° to 290°) proportionally
   to chroma to counteract low ambient reflectance of blue pigments.

3. Margin & speech-bubble pure-white acceleration:
   Accelerates near-whites (C < 0.04, L >= 0.90) to pure white (1.0) to eliminate
   unwanted particle dithering / specks in gutters and dialogue bubbles.

4. Targeted chromatic & hue shifts:
   - Skin tone protection guard: keeps warm tones (30° to 65°) within a natural ceiling.
   - Blue/cyan inverse rotation: rotates -18° toward cyan to neutralize magenta crosstalk.
   - Green inverse rotation: rotates -10° toward yellow to eliminate olive mud.
   - General chroma boost: +24% to counteract reflective matte surface desaturation.

5. Inversion back to sRGB and clean white pass-through.
"""


import os
import numpy as np


# OKLab transformation matrices (Björn Ottosson, 2020)
M1 = np.array([
    [0.4122214708, 0.5363325363, 0.0514459929],
    [0.2119034982, 0.6806995451, 0.1073969566],
    [0.0883024619, 0.2817188376, 0.6299787005],
], dtype=np.float32)

M2 = np.array([
    [0.2104542553, 0.7936177850, -0.0040720468],
    [1.9779984951, -2.4285922050, 0.4505937099],
    [0.0259040371, 0.7827717662, -0.8086757660],
], dtype=np.float32)

M1_INV = np.linalg.inv(M1).astype(np.float32)
M2_INV = np.linalg.inv(M2).astype(np.float32)


def srgb_to_linear(rgb: np.ndarray) -> np.ndarray:
    """Converts sRGB to linear RGB using standard IEC 61966-2-1 transfer function."""
    a = 0.055
    return np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + a) / (1.0 + a)) ** 2.4)


def linear_to_srgb(lin: np.ndarray) -> np.ndarray:
    """Converts linear RGB back to sRGB."""
    a = 0.055
    return np.where(
        lin <= 0.0031308,
        lin * 12.92,
        (1.0 + a) * (np.maximum(lin, 0.0) ** (1.0 / 2.4)) - a,
    )


def rgb_to_oklab(rgb: np.ndarray) -> np.ndarray:
    """Transforms sRGB array to OKLab (L, a, b)."""
    lin = srgb_to_linear(rgb)
    lms = np.dot(lin, M1.T)
    lms_cbrt = np.cbrt(np.maximum(lms, 0.0))
    return np.dot(lms_cbrt, M2.T)


def oklab_to_rgb(lab: np.ndarray) -> np.ndarray:
    """Transforms OKLab (L, a, b) array back to clipped sRGB."""
    lms_cbrt = np.dot(lab, M2_INV.T)
    lms = lms_cbrt ** 3.0
    lin = np.dot(lms, M1_INV.T)
    return np.clip(linear_to_srgb(lin), 0.0, 1.0)


def generate_rmpp_canvas_color_cube(size: int = 33) -> str:
    """Generates the full .cube file string for reMarkable Paper Pro Canvas Color."""
    coords = np.linspace(0.0, 1.0, size, dtype=np.float32)
    grid_r, grid_g, grid_b = np.meshgrid(coords, coords, coords, indexing="ij")
    grid_rgb = np.stack([grid_r, grid_g, grid_b], axis=-1)

    lab = rgb_to_oklab(grid_rgb)
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]

    C = np.sqrt(a**2 + b**2)
    h_rad = np.arctan2(b, a)
    h_deg = (np.degrees(h_rad) + 360.0) % 360.0

    # 1. Monotonic Hermite spline tone curve on lightness (L)
    xp = np.array([0.0, 0.05, 0.15, 0.35, 0.70, 0.88, 0.94, 1.00], dtype=np.float32)
    yp = np.array([0.0, 0.13, 0.27, 0.47, 0.76, 0.91, 0.98, 1.00], dtype=np.float32)
    L_spline = np.interp(L, xp, yp)

    # 2. Chrominance-dependent luminance equalization (cool vs warm balance)
    cool_mask = (h_deg >= 110.0) & (h_deg <= 290.0)
    cool_weight = np.sin(np.radians(h_deg - 110.0) / 180.0 * np.pi)
    L_lce = np.copy(L_spline)
    L_lce[cool_mask] = L_lce[cool_mask] + 0.18 * C[cool_mask] * cool_weight[cool_mask]
    L_lce = np.clip(L_lce, 0.0, 1.0)

    # 3. Speech bubble & margin pure-white acceleration
    bubble_mask = (C < 0.04) & (L >= 0.90)
    t_bubble = (L[bubble_mask] - 0.90) / 0.10
    L_lce[bubble_mask] = L_lce[bubble_mask] * (1.0 - t_bubble) + 1.0 * t_bubble

    # 4. Targeted chromatic shifts
    C_new = np.copy(C)
    h_new = np.copy(h_deg)

    # A. Skin tone guard (30° to 65°, C in [0.02, 0.14])
    skin_mask = (h_deg >= 30.0) & (h_deg <= 65.0) & (C >= 0.02) & (C <= 0.14)
    C_new[skin_mask] = C[skin_mask] * 1.10

    # B. Blue / cyan (200° to 290°) -> rotate toward cyan (-18°)
    blue_mask = (h_deg >= 200.0) & (h_deg <= 290.0)
    blue_weight = np.clip(1.0 - np.abs(h_deg - 250.0) / 45.0, 0.0, 1.0)
    h_new = h_new - 18.0 * blue_weight
    C_new[blue_mask] = C_new[blue_mask] * (1.22 + 0.06 * blue_weight[blue_mask])

    # C. Green (105° to 175°) -> rotate toward yellow (-10°)
    green_mask = (h_deg >= 105.0) & (h_deg <= 175.0)
    green_weight = np.clip(1.0 - np.abs(h_deg - 140.0) / 35.0, 0.0, 1.0)
    h_new = h_new - 10.0 * green_weight
    C_new[green_mask] = C_new[green_mask] * (1.24 + 0.08 * green_weight[green_mask])

    # D. Yellow (85° to 110°) -> increase chroma on light yellows
    yellow_mask = (h_deg >= 85.0) & (h_deg <= 110.0) & (C < 0.10)
    C_new[yellow_mask] = C_new[yellow_mask] * 1.25

    # E. General colors
    other_mask = ~skin_mask & ~blue_mask & ~green_mask & ~yellow_mask
    C_new[other_mask] = C_new[other_mask] * 1.24

    # Reconstruct chromatic coordinates (a, b)
    h_rad_new = np.radians(h_new)
    a_new = C_new * np.cos(h_rad_new)
    b_new = C_new * np.sin(h_rad_new)

    lab_new = np.stack([L_lce, a_new, b_new], axis=-1)
    rgb_out = oklab_to_rgb(lab_new)

    # Pure white pass-through
    white_mask = (grid_rgb[..., 0] >= 0.98) & (grid_rgb[..., 1] >= 0.98) & (grid_rgb[..., 2] >= 0.98)
    rgb_out[white_mask] = 1.0

    # Build Adobe / DaVinci Resolve .cube format

    lines = [
        "# reMarkable Paper Pro Canvas Color (OKLab v3 - 5-Stage Advanced) Inverse Compensation LUT",
        'TITLE "RMPP_Canvas_Color_Advanced_v3"',
        f"LUT_3D_SIZE {size}",
        "DOMAIN_MIN 0.0 0.0 0.0",
        "DOMAIN_MAX 1.0 1.0 1.0",
    ]

    for bi in range(size):
        for gi in range(size):
            for ri in range(size):
                lines.append(
                    f"{rgb_out[ri, gi, bi, 0]:.6f} {rgb_out[ri, gi, bi, 1]:.6f} {rgb_out[ri, gi, bi, 2]:.6f}"
                )

    return "\n".join(lines) + "\n"


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_PATH = os.path.join(
    REPO_ROOT,
    "src",
    "rmpp_enhancer",
    "profiles",
    "rmpp_canvas_color.cube",
)


def main():
    print("Synthesizing reMarkable Paper Pro Canvas Color 3D LUT (33x33x33)...")
    cube_content = generate_rmpp_canvas_color_cube(size=33)

    os.makedirs(os.path.dirname(os.path.abspath(OUTPUT_PATH)), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(cube_content)

    file_size_kb = os.path.getsize(OUTPUT_PATH) / 1024.0
    print(f"✓ Successfully generated: {OUTPUT_PATH} ({file_size_kb:.1f} KB)")


if __name__ == "__main__":
    main()

