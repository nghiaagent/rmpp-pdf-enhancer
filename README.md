# rmpp-pdf-enhancer

> [!NOTE]
> ### Re: Who made this
> I implemented none of this pipeline, outside from:
> 
> 1. Buying a reMarkable Paper Pro (and got 2 warranty replacements).
> 2. Complaining that colors and documents looked dark and muddy on its Canvas Color screen.
> 3. Handing over sample files and saying: *"Make the CLI as described. Tune the JPEG quality, syncing is very slow. And don't say that this is only for comics. PDFs in general will benefit as well."*
> 4. Micromanaging a LLM re: colorspace and LUT implementation. 
> 
> Everything in this codebase: OKLab colorspace inverse compensation profile, monotonic Hermite spline shadow de-crusher, bilateral edge-directed inking filter, Lanczos scaler, the `uv` packaging, and this documentation was done by Antigravity.

---

## Methods: 6-stage pipeline

```
Input PDF / archive / scans (.pdf, .cbz, .zip, folder)
  │
  ▼
[1] Universal extractor (extracts image streams / renders vector pages + TOC)
  │
  ▼
[2] Sheet layout and geometry scaling
    ├── Row width matched to the sheet aspect (auto or fixed N per row)
    ├── Double-page spreads claim a whole row, never cut in half
    ├── Reading order from ComicInfo.xml (right-to-left by default)
    └── 1:1 pixel mapping to 2160 x 1620 @ 229 PPI via 8-tap Lanczos
  │
  ▼
[3] Calibrated 3D LUT 
    ├── Monotonic Hermite spline shadow lift (L < 0.35)
    ├── Cool-tone (cyan/teal/blue) luminance equalization
    ├── Warm skin-tone / highlight soft protection ceiling
    └── Background pure-white accelerator (> 248 -> 255)
  │
  ▼
[4] Bilateral edge-directed inking filter
    ├── Detects high-contrast line-art and typography contours
    ├── Deepens dark ink lines (lum < 0.40) by -25%
    ├── Brightens surrounding edge halos (lum >= 0.40) by +10%
    └── Micro-contrast unsharp mask (r=1.0, 115%)
  │
  ▼
[5] Customised JPEG compression (Q82, 4:4:4 chroma, 229 DPI)
  │
  ▼
[6] PDF injection (zero-transcode img2pdf + PyMuPDF outline TOC)
```

For more rationale, see [Architecture and color science guide](docs/architecture.md).

---

## 3D LUT visualization

![reMarkable Paper Pro Canvas Color — 3D LUT inverse compensation profile](docs/images/cube_lut_visualization.png)

---

## Prerequisites

You need [`uv`](https://docs.astral.sh/uv/) to install, run, or build this app.

To install `uv`, follow the [official installation guide](https://docs.astral.sh/uv/getting-started/installation/).

---

## Installation and execution

### Option A: Run directly with `uvx` (no install required)
Execute directly from GitHub:
```bash
uvx --from git+https://github.com/nghiaagent/rmpp-pdf-enhancer.git rmpp-pdf-enhancer "Document.pdf"
```

### Option B: Install as a global CLI command with `uv tool`
Install `rmpp-pdf-enhancer` into an isolated global environment:
```bash
# Directly from GitHub:
uv tool install git+https://github.com/nghiaagent/rmpp-pdf-enhancer.git

# Or from a local clone:
git clone https://github.com/nghiaagent/rmpp-pdf-enhancer.git
cd rmpp-pdf-enhancer
uv tool install --force .
```

---

## Building from source and development

The project is packaged as a pure-Python application using [`hatchling`](https://hatch.pypa.io/latest/) as its build backend.

### 1. Clone the repository
```bash
git clone https://github.com/nghiaagent/rmpp-pdf-enhancer.git
cd rmpp-pdf-enhancer
```

### 2. Set up the development environment
Install dependencies and sync the virtual environment automatically:
```bash
uv sync
```

### 3. Run the CLI in development
```bash
uv run rmpp-pdf-enhancer "Document.pdf"
```

---

## Quickstart

### 1. Optimize an existing PDF document
```bash
rmpp-pdf-enhancer "Linear_Algebra_Textbook.pdf"
```
Produces `Linear_Algebra_Textbook_PaperPro_Optimized.pdf`.
Running again in the same directory will skip already-generated files (override with `-f` / `--force`).

### 2. Optimize a comic archive (`.cbz` or `.zip`)
```bash
rmpp-pdf-enhancer "OnePiece_Vol100.cbz"
```
Chapter folders inside the archive become PDF bookmarks, and `ComicInfo.xml` is
read for reading direction if the archive carries one.

### 3. Process a folder of images
```bash
rmpp-pdf-enhancer ./scanned_pages/
```
Pages are ordered naturally (`1, 2, 10`, not `1, 10, 2`). Subfolders become chapters.

### 4. Batch process a directory
```bash
rmpp-pdf-enhancer ./DocumentsFolder/ --batch
```
Each archive or subfolder is optimized into its own PDF, rather than being merged into one.

---

## Multi-page sheets

By default one source page becomes one output page. `--per-row` puts several
source pages side by side on a single sheet instead — two manga pages across a
landscape sheet, or three tall strips across a portrait one.

```bash
# Two pages per landscape sheet, the classic manga spread view
rmpp-pdf-enhancer "Volume01.cbz" --per-row 2 --orientation landscape

# Let the packer choose the row width that wastes least
rmpp-pdf-enhancer "Volume01.cbz" --per-row auto --orientation landscape

# Crop to fill the panel instead of letterboxing
rmpp-pdf-enhancer "Scans/" --per-row 2 --fit fill
```

### Choosing the row width

`--per-row auto` picks the row whose combined aspect best matches the sheet,
which is the row that wastes least. For a page of aspect `r` on a sheet of
aspect `R` that is `N ≈ R/r`:

| source page | portrait sheet (3:4) | landscape sheet (4:3) |
| --- | --- | --- |
| manga 1500x2100 | 1 per row (4.8% waste) | 2 per row (6.7% waste) |
| tall strip 1:4 | 3 per row (0.0% waste) | 5 per row (6.2% waste) |
| wide panorama 4:1 | 1 per row | 1 per row |

Layouts are always a single row, never a grid. Waste is scale-invariant across
grids — 1×1, 2×2 and 3×3 all waste exactly the same — so "minimise waste" cannot
choose between them. Restricted to one row the minimum is unique and `auto` is
well defined.

`--per-row 1` with no `--orientation` is the default and leaves every page at its
own size, which is the behaviour from before this option existed.

### Fitting pages into cells

`--fit` decides what to give up when a page and its cell disagree on aspect:

| mode | gives up | typical cost |
| --- | --- | --- |
| `fit` (default) | screen space, as white margins | ~7% of the sheet blank |
| `fill` | image, cropped from the long edge | ~6% of each page cut |

Neither is free, and which edge gets trimmed matters more than the percentage.
On a landscape sheet `fill` trims the **sides** of a portrait page, which is
where gutter art and panel edges live; on a portrait sheet it trims top and
bottom, usually only headers and page numbers.

### Double-page spreads

A spread is one artwork across two facing pages. Split across a sheet boundary
it reads as two broken halves, so any page detected as a spread claims two
adjacent cells and can never be cut. Detection uses, strongest signal first:

1. **`ComicInfo.xml`** — the metadata file inside most `.cbz` archives marks
   spreads with `DoublePage="true"`. Authoritative when present.
2. **Aspect ratio** — an image wider than it is tall. This is the whole of
   Mihon's detector (`isWideImage` is `outWidth > outHeight`) and TachiyomiJ2K's.
3. **Filename** — `012-013.jpg` names both pages it covers.

Because the rule is "wider than tall", it also catches landscape cover art,
credit banners and bonus illustrations, and those are given the full row too.
That is intentional: art should use as much of the screen as it can, and a wide
image squeezed into a half-width cell wastes the panel. Pass `--no-keep-spreads`
to turn the whole behaviour off and pack purely by count.

Re-pairing a spread that was *split into two separate files* is deliberately not
attempted — no mainstream reader does it, because pairing parity cannot be
recovered reliably. Mihon and TachiyomiJ2K instead expose a manual shift, and so
does this tool: if a volume's spreads land on the wrong parity, pass
`--shift-pages` to offset the pairing by one page.

### Reading direction

`--reading-direction auto` (the default) resolves in this order:

1. An explicit `--reading-direction ltr|rtl` always wins.
2. Whatever `ComicInfo.xml` declares, so a volume marked `<Manga>No</Manga>` is
   laid out left-to-right even under the default.
3. **Right-to-left**, because an archive carrying no metadata at all is far more
   likely to be manga than not.

Under `rtl` the first page of a row sits on the right, and a part-filled row
leaves its blank cells on the left. Direction only affects sheets holding more
than one page; at `--per-row 1` there is nothing to order.

---

## CLI options reference

```text
usage: rmpp-pdf-enhancer [-h] [-o OUTPUT] [-q QUALITY] [--subsampling {0,2}]
                         [-w WORKERS] [-f] [--no-lut] [--no-ink]
                         [--lut-file LUT_FILE] [--per-row N|auto]
                         [--orientation {portrait,landscape,vertical,horizontal,auto}]
                         [--fit {fit,fill}]
                         [--reading-direction {ltr,rtl,auto}]
                         [--keep-spreads | --no-keep-spreads] [--shift-pages]
                         [--batch] [-v]
                         inputs [inputs ...]

reMarkable Paper Pro PDF enhancer

positional arguments:
  inputs                Input file(s): .pdf, .cbz, .zip, or directory of images/scans

options:
  -h, --help            Show this help message and exit
  -o, --output OUTPUT   Output PDF file path or destination directory (default: None)
  -q, --quality QUALITY JPEG quality (1-100, default 82)
  --subsampling {0,2}   Chroma subsampling: 0=4:4:4 (crisp text), 2=4:2:0 (smaller file) (default: 0)
  -w, --workers WORKERS Number of concurrent worker threads (default: 8, or CPU count if lower)
  -f, --force           Force overwrite if output file already exists, and re-process already optimized files (default: False)
  --no-lut              Disable included LUT compensation (default: False)
  --no-ink              Disable bilateral edge-directed inking filter (default: False)
  --lut-file LUT_FILE   Custom .cube 3D LUT profile path (default: None)
  --batch               Treat directory contents as separate sub-documents/chapters (default: False)
  -v, --version         Show program's version number and exit

sheet layout:
  --per-row N|auto      Source pages side by side on each output sheet, or 'auto' to pick
                        the row width that wastes least (default: 1)
  --orientation {portrait,landscape,vertical,horizontal,auto}
                        Output sheet orientation ('vertical'/'horizontal' are accepted as
                        aliases for portrait/landscape) (default: auto)
  --fit {fit,fill}      fit letterboxes the whole page; fill crops it to cover the cell (default: fit)
  --reading-direction {ltr,rtl,auto}
                        Page order within a row; auto reads ComicInfo.xml and falls back to rtl (default: auto)
  --keep-spreads, --no-keep-spreads
                        Keep double-page spreads whole on one sheet (default: True)
  --shift-pages         Offset pairing by one page, for volumes whose spreads land on the
                        wrong parity (default: False)
```

See [Multi-page sheets](#multi-page-sheets) for what the layout options do and
when each one is worth reaching for.

---

## Benchmarking and tablet screen comparisons

The repository includes scripts to regenerate the committed artifacts. Each one
writes into the repository by default — pass `--out-dir` to send output elsewhere.

```bash
# Side-by-side comparison JPEGs + PDF -> docs/images/
uv run python scripts/generate_illustration_comparisons.py

# The bundled .cube colour profile -> src/rmpp_enhancer/profiles/
uv run python scripts/generate_canvas_color_lut.py

# The 4-panel LUT visualization -> docs/images/ (needs matplotlib)
uv run --with matplotlib python scripts/generate_lut_viz.py
```

All three are deterministic: re-running them on an unmodified checkout
reproduces the committed files byte-for-byte.

---

## Testing

Run the automated test suite with `uv`:

```bash
uv run pytest
```

`pytest` is declared in the `dev` dependency group, so `uv run` installs it automatically.

The suite is split by what it protects:

| file | covers |
| --- | --- |
| `test_behaviour_formats.py` | every documented input format, end to end, plus bookmarks |
| `test_behaviour_invariants.py` | properties that hold for *all* 24 layout combinations |
| `test_behaviour_options.py` | each option having a visible effect |
| `test_behaviour_cli.py` | the command lines a user actually types |
| `test_behaviour_errors.py` | bad input failing loudly instead of writing a wrong PDF |
| `test_layout.py`, `test_extractor.py`, `test_pipeline.py`, … | unit-level detail |

### Continuous integration

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs on every push and
pull request:

- **lint** — `ruff` with a correctness-only rule set, and `uv lock --check`.
- **test** — the full suite on Python 3.9 through 3.13, plus macOS on 3.13.
- **artifacts** — regenerates the `.cube` profile, the LUT visualization and the
  benchmark comparisons, then fails if any committed file changed. The pipeline
  is deterministic, so a diff here means an unintended change in output.
- **package** — builds the wheel, installs it into a clean environment and
  converts a real page with the installed command.

---

## License

MIT License.
