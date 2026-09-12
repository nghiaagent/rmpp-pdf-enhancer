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
[2] Scaling (1:1 pixel mapping to RMPP at 2160px height @ 229 PPI Lanczos)
  │
  ▼
[3] Calibrated 3D LUT (OKLab Canvas Color compensation)
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
[5] Tuned fast-sync JPEG compression (Q82, 4:4:4 chroma, 229 DPI)
  │
  ▼
[6] Direct PDF injection (zero-transcode img2pdf + PyMuPDF outline TOC)
```

For full mathematical formulas, color science curves, and particle physics, see the [Architecture and color science guide](docs/architecture.md).

---

## 3D LUT visualization

![reMarkable Paper Pro Canvas Color — 3D LUT inverse compensation profile](docs/images/cube_lut_visualization.png)

---

## Installation and execution

### Option A: Direct execution with `uvx`
Run directly from GitHub without cloning or managing environments:
```bash
uvx --from git+https://github.com/nghiaagent/rmpp-pdf-enhancer.git rmpp-pdf-enhancer "Document.pdf"
```

### Option B: Install globally via `uv tool`
Install as an isolated, persistent system-wide CLI command:
```bash
# Directly from GitHub:
uv tool install git+https://github.com/nghiaagent/rmpp-pdf-enhancer.git

# Or from local clone:
uv tool install .
```
Now `rmpp-pdf-enhancer` is permanently in your `$PATH`.

---

## Quickstart

### 1. Optimize an existing PDF document
```bash
uv run rmpp-pdf-enhancer "Linear_Algebra_Textbook.pdf"
```
Produces `Linear_Algebra_Textbook_PaperPro_Optimized.pdf` with enhanced charts, clean margins, and sharp formulas.
Running again in the same directory safely skips already-generated files without re-processing them (override with `-f` / `--force`).

### 2. Optimize a comic archive (`.cbz` or `.zip`)
```bash
uv run rmpp-pdf-enhancer "OnePiece_Vol100.cbz"
```

### 3. Process a folder of images
```bash
uv run rmpp-pdf-enhancer ./scanned_pages/ -o "MeetingNotes_Enhanced.pdf"
```

### 4. Batch process a directory
```bash
uv run rmpp-pdf-enhancer ./DocumentsFolder/ --batch -o ./RMPP_Ready/
```

---

## CLI options reference

```text
usage: rmpp-pdf-enhancer [-h] [-o OUTPUT] [-q QUALITY] [--subsampling {0,2}]
                         [-w WORKERS] [-f] [--no-lut] [--no-ink]
                         [--lut-file LUT_FILE] [--batch] [-v]
                         inputs [inputs ...]

reMarkable Paper Pro Canvas Color universal PDF, document, textbook and manga enhancer

positional arguments:
  inputs                Input file(s): .pdf, .cbz, .zip, or directory of images/scans

options:
  -h, --help            Show this help message and exit
  -o, --output OUTPUT   Output PDF file path or destination directory (default: None)
  -q, --quality QUALITY JPEG quality (1-100), tuned to 82 for fast cloud sync (default: 82)
  --subsampling {0,2}   Chroma subsampling: 0=4:4:4 (crisp text), 2=4:2:0 (smaller file) (default: 0)
  -w, --workers WORKERS Number of concurrent worker threads (default: CPU count)
  -f, --force           Force overwrite if output file already exists, and re-process already optimized files (default: False)
  --no-lut              Disable 3D LUT Canvas Color compensation (default: False)
  --no-ink              Disable bilateral edge-directed inking filter (default: False)
  --lut-file LUT_FILE   Custom .cube 3D LUT profile path (default: None)
  --batch               Treat directory contents as separate sub-documents/chapters (default: False)
  -v, --version         Show program's version number and exit
```

---

## Benchmarking and tablet screen comparisons

The repository includes scripts to generate native $2160 \times 1620$ side-by-side landscape comparison PDFs ($1080 \times 1620$ original sRGB on the left, $1080 \times 1620$ compensated RMPP on the right) formatted specifically for photographing directly on the reMarkable Paper Pro screen:

- **Illustration benchmark & calibration target**:
  ```bash
  uv run python scripts/generate_illustration_comparisons.py
  ```
  Generates `Illustration_PaperPro_Comparison.pdf` containing side-by-side comparisons of standard calibration targets (CMYK, RGB, Grayscale ramps, SWOP colors, and resolution line tests), digital character illustrations (Genshin Impact), anime landscapes (Yuvalkirstain anime dataset), and high-gamut pop-art illustrations (Boshik dataset).

---

## Testing

Run the automated test suite with `uv`:

```bash
uv run python -m unittest discover tests
```

---

## License

MIT License.
