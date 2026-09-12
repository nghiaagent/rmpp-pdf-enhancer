#!/usr/bin/env python3
"""
generate_lut_viz.py

Generates a publication-quality 4-panel visualization of the reMarkable Paper Pro 3D LUT profile:
1. Input sRGB identity lattice (neutral 3D scatter)
2. Compensated RMPP output lattice (warped 3D scatter)
3. Luminance transfer response curves by color family (2D curves)
4. Mid-blue constant plane color slice comparison (2D side-by-side swatch)
"""

import os
import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
from PIL import Image, ImageFilter

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LUT_PATH = os.path.join(REPO_ROOT, "src", "rmpp_enhancer", "profiles", "rmpp_canvas_color.cube")
OUT_PATH = os.path.join(REPO_ROOT, "docs", "images", "cube_lut_visualization.png")


def main():
    lut = []
    with open(LUT_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("TITLE") or line.startswith("LUT") or line.startswith("DOMAIN"):
                continue
            parts = [float(x) for x in line.split()]
            if len(parts) == 3:
                lut.extend(parts)

    lut_arr = np.array(lut, dtype=np.float32).reshape((33, 33, 33, 3))

    plt.style.use("default")
    fig = plt.figure(figsize=(15, 11), dpi=200)
    fig.patch.set_facecolor("#0F141C")

    # Title in sentence case
    fig.suptitle(
        "reMarkable Paper Pro Canvas Color — 3D LUT inverse compensation profile",
        fontsize=16,
        fontweight="bold",
        color="#FFFFFF",
        y=0.96,
    )

    # 1. 3D Input sRGB Identity Lattice
    ax1 = fig.add_subplot(2, 2, 1, projection="3d")
    ax1.set_facecolor("#0F141C")

    step = 4
    sub_indices = np.arange(0, 33, step)
    grid_r, grid_g, grid_b = np.meshgrid(sub_indices / 32.0, sub_indices / 32.0, sub_indices / 32.0, indexing="ij")
    flat_r, flat_g, flat_b = grid_r.flatten(), grid_g.flatten(), grid_b.flatten()
    colors_in = np.column_stack([flat_r, flat_g, flat_b])

    ax1.scatter(flat_r, flat_g, flat_b, c=colors_in, s=28, alpha=0.9, edgecolors="none")
    ax1.set_title("Input sRGB identity cube (neutral)", color="#E2E8F0", fontsize=12, pad=12)
    ax1.set_xlabel("Red", color="#A0AEC0", fontsize=9)
    ax1.set_ylabel("Green", color="#A0AEC0", fontsize=9)
    ax1.set_zlabel("Blue", color="#A0AEC0", fontsize=9)
    ax1.tick_params(colors="#718096", labelsize=8)
    ax1.view_init(elev=22, azim=-55)
    for axis in [ax1.xaxis, ax1.yaxis, ax1.zaxis]:
        axis.pane.set_facecolor("#1A202C")
        axis.pane.set_edgecolor("#2D3748")

    # 2. 3D Compensated RMPP Output Lattice
    ax2 = fig.add_subplot(2, 2, 2, projection="3d")
    ax2.set_facecolor("#0F141C")

    out_points = []
    out_colors = []
    for r_idx in sub_indices:
        for g_idx in sub_indices:
            for b_idx in sub_indices:
                pt = lut_arr[b_idx, g_idx, r_idx]
                out_points.append(pt)
                out_colors.append(np.clip(pt, 0.0, 1.0))
    out_points = np.array(out_points)
    out_colors = np.array(out_colors)

    ax2.scatter(out_points[:, 0], out_points[:, 1], out_points[:, 2], c=out_colors, s=28, alpha=0.9, edgecolors="none")
    ax2.set_title("Compensated RMPP output cube (warped)", color="#E2E8F0", fontsize=12, pad=12)
    ax2.set_xlabel("Red", color="#A0AEC0", fontsize=9)
    ax2.set_ylabel("Green", color="#A0AEC0", fontsize=9)
    ax2.set_zlabel("Blue", color="#A0AEC0", fontsize=9)
    ax2.tick_params(colors="#718096", labelsize=8)
    ax2.view_init(elev=22, azim=-55)
    for axis in [ax2.xaxis, ax2.yaxis, ax2.zaxis]:
        axis.pane.set_facecolor("#1A202C")
        axis.pane.set_edgecolor("#2D3748")

    # 3. Transfer Response Curves
    ax3 = fig.add_subplot(2, 2, 3)
    ax3.set_facecolor("#141A23")
    ax3.grid(True, linestyle="--", alpha=0.2, color="#718096")

    gray_levels = np.linspace(0, 1, 33)
    neutral_out = [lut_arr[i, i, i, 0] for i in range(33)]
    cyan_out = [lut_arr[i, i, 0, 1] for i in range(33)]

    skin_out = []
    for i in range(33):
        r_idx = i
        g_idx = int(round(i * 0.75))
        b_idx = int(round(i * 0.60))
        pt = lut_arr[b_idx, g_idx, r_idx]
        skin_out.append(0.299 * pt[0] + 0.587 * pt[1] + 0.114 * pt[2])

    ax3.plot(gray_levels, gray_levels, linestyle="--", label="Linear baseline (1:1)", color="#4A5568", linewidth=1.5)
    ax3.plot(gray_levels, neutral_out, label="Grayscale (Hermite shadow lift + white snap)", color="#ED8936", linewidth=2.5)
    ax3.plot(gray_levels, cyan_out, label="Cool tone (Cyan/teal luminance boost)", color="#38B2AC", linewidth=2.2)
    ax3.plot(gray_levels, skin_out, label="Warm tone (Skin-tone soft ceiling guard)", color="#F687B3", linewidth=2.0)

    ax3.axvspan(0.0, 0.35, color="#ECC94B", alpha=0.08, label="Shadow de-crush zone (L < 0.35)")
    ax3.axvspan(0.95, 1.0, color="#63B3ED", alpha=0.08, label="Pure white snap zone (> 0.95)")

    ax3.set_title("Luminance transfer functions by color family", color="#E2E8F0", fontsize=12, pad=10)
    ax3.set_xlabel("Input sRGB value", color="#A0AEC0", fontsize=10)
    ax3.set_ylabel("Compensated output value", color="#A0AEC0", fontsize=10)
    ax3.tick_params(colors="#718096", labelsize=9)
    ax3.legend(facecolor="#1A202C", edgecolor="#2D3748", labelcolor="#E2E8F0", fontsize=8.5, loc="upper left")
    for spine in ax3.spines.values():
        spine.set_color("#2D3748")

    # 4. 2D Color Slice Comparison
    ax4 = fig.add_subplot(2, 2, 4)
    ax4.set_facecolor("#141A23")

    res = 200
    r_coords = np.linspace(0, 1, res)
    g_coords = np.linspace(1, 0, res)
    rg_r, rg_g = np.meshgrid(r_coords, g_coords)
    orig_slice = np.stack([rg_r, rg_g, np.full_like(rg_r, 0.5)], axis=-1)

    pil_lut = ImageFilter.Color3DLUT(33, lut)
    orig_pil = Image.fromarray((orig_slice * 255).astype(np.uint8))
    comp_pil = orig_pil.filter(pil_lut)
    comp_slice = np.array(comp_pil, dtype=np.float32) / 255.0

    split_slice = np.copy(orig_slice)
    split_slice[:, res//2:, :] = comp_slice[:, res//2:, :]

    ax4.imshow(split_slice)
    ax4.axvline(x=res//2, color="#FFFFFF", linestyle="--", linewidth=1.5)
    ax4.text(res*0.25, res*0.08, "Original sRGB", color="#FFFFFF", fontsize=11, fontweight="bold", ha="center",
             bbox=dict(boxstyle="round,pad=0.3", facecolor="#000000", alpha=0.6, edgecolor="none"))
    ax4.text(res*0.75, res*0.08, "Compensated RMPP", color="#FFFFFF", fontsize=11, fontweight="bold", ha="center",
             bbox=dict(boxstyle="round,pad=0.3", facecolor="#000000", alpha=0.6, edgecolor="none"))

    ax4.set_title("Mid-blue slice comparison (B = 0.50 plane)", color="#E2E8F0", fontsize=12, pad=10)
    ax4.set_xlabel("Red axis (0 -> 1)", color="#A0AEC0", fontsize=9)
    ax4.set_ylabel("Green axis (1 -> 0)", color="#A0AEC0", fontsize=9)
    ax4.tick_params(colors="#718096", labelsize=8)
    for spine in ax4.spines.values():
        spine.set_color("#2D3748")

    plt.tight_layout(rect=[0, 0.03, 1, 0.94])
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    plt.savefig(OUT_PATH, facecolor=fig.get_facecolor(), edgecolor="none")
    print(f"Generated visualization: {OUT_PATH}")


if __name__ == "__main__":
    main()
