"""
The committed generated artifacts still correspond to the code that makes them.

Deliberately numeric rather than byte-for-byte. The .cube is written at six
decimals, so last-ulp floating point differences between platforms flip the
final digit on about half its lines; the rendered images differ by roughly one
LSB between libjpeg and matplotlib versions. A byte comparison therefore fails
on any machine but the one that generated them, which says nothing about
whether the code is correct.

Images are not compared at all, not even with a tolerance: a genuine pipeline
change (the inking filter moving from truncation to rounding) shifted the
benchmark comparisons by a mean of 0.49 per channel, which is the same
magnitude as cross-platform JPEG encoding noise. Any threshold loose enough to
survive CI would be too loose to catch the regression. The pipeline's behaviour
is covered directly by the behaviour suite instead.
"""

import os
import sys

import numpy as np
import pytest

from rmpp_enhancer.pipeline import load_3d_lut
from rmpp_enhancer.profiles import DEFAULT_LUT_PATH

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

# Six decimals of precision, so a same-platform run is exact and a different
# one differs by ~1e-6. Any real change to the colour science is far larger.
LUT_TOLERANCE = 1e-4


def parse_cube(text):
    values = []
    size = None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("LUT_3D_SIZE"):
            size = int(line.split()[1])
            continue
        if line.startswith(("TITLE", "DOMAIN")):
            continue
        parts = line.split()
        if len(parts) == 3:
            values.extend(float(x) for x in parts)
    return size, np.array(values, dtype=np.float64)


@pytest.fixture(scope="module")
def shipped():
    with open(DEFAULT_LUT_PATH, encoding="utf-8") as f:
        return parse_cube(f.read())


@pytest.fixture(scope="module")
def regenerated():
    from generate_canvas_color_lut import generate_rmpp_canvas_color_cube

    return parse_cube(generate_rmpp_canvas_color_cube(size=33))


class TestShippedProfile:

    def test_matches_its_generator(self, shipped, regenerated):
        """Catches a generator edited without regenerating the profile."""
        assert shipped[0] == regenerated[0] == 33
        assert shipped[1].shape == regenerated[1].shape
        worst = np.abs(shipped[1] - regenerated[1]).max()
        assert worst < LUT_TOLERANCE, (
            f"shipped profile is {worst:.2e} away from what the generator "
            f"produces; regenerate it with scripts/generate_canvas_color_lut.py"
        )

    def test_has_the_expected_shape(self, shipped):
        size, values = shipped
        assert values.size == size**3 * 3

    def test_values_stay_in_range(self, shipped):
        _, values = shipped
        assert values.min() >= 0.0
        assert values.max() <= 1.0

    def test_pure_white_passes_through(self, shipped):
        """The white accelerator must not tint the page background."""
        size, values = shipped
        table = values.reshape(size, size, size, 3)
        assert np.allclose(table[-1, -1, -1], 1.0, atol=1e-6)

    def test_black_stays_black(self, shipped):
        size, values = shipped
        table = values.reshape(size, size, size, 3)
        assert np.allclose(table[0, 0, 0], 0.0, atol=0.02)

    def test_loads_through_the_public_api(self):
        lut = load_3d_lut()
        assert lut.size == (33, 33, 33)
        assert len(lut.table) == 33**3 * 3


class TestGeneratorsRun:
    """The documented scripts must execute and produce output."""

    def test_lut_generator_is_self_consistent(self):
        from generate_canvas_color_lut import generate_rmpp_canvas_color_cube

        once = generate_rmpp_canvas_color_cube(size=9)
        twice = generate_rmpp_canvas_color_cube(size=9)
        assert once == twice, "the generator must be deterministic within a run"

    def test_comparison_page_builds_at_panel_size(self, tmp_path):
        from PIL import Image

        from generate_illustration_comparisons import CANVAS_H, CANVAS_W, create_comparison_page
        from rmpp_enhancer.pipeline import EnhancerConfig

        src = str(tmp_path / "p.png")
        Image.new("RGB", (300, 420), (180, 140, 90)).save(src)
        spec = {"num": 1, "title": "t", "file": src, "fit_mode": "cover", "id": "t"}
        page = create_comparison_page(spec, EnhancerConfig(), load_3d_lut())
        assert page.size == (CANVAS_W, CANVAS_H) == (2160, 1620)
