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

Before installing or building `rmpp-pdf-enhancer`, ensure the following tools are installed:

- **Python**: Python $\ge 3.9$
- **Rust toolchain**: Rust $\ge 1.70$ (`cargo` and `rustc`) is required to compile the native PyO3 SIMD accelerator module.
  - Install via [rustup](https://rustup.rs):
    ```bash
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
    ```
- **uv**: Recommended fast Python package and tool manager.
  - Install via [astral.sh](https://docs.astral.sh/uv/):
    ```bash
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # Or on macOS via Homebrew:
    brew install uv
    ```

---

## Installation and execution

### Option A: Direct execution with `uvx`
Run directly from GitHub without manual installation (requires Rust to build the native extension on first run):
```bash
uvx --from git+https://github.com/nghiaagent/rmpp-pdf-enhancer.git rmpp-pdf-enhancer "Document.pdf"
```

### Option B: Install as a global CLI tool via `uv tool`
Install as a persistent system-wide CLI command:
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

The project uses [`maturin`](https://www.maturin.rs/) as its build backend to compile the native PyO3 Rust extension module (`rmpp_enhancer._accelerator`) alongside the Python orchestration code.

### 1. Clone the repository
```bash
git clone https://github.com/nghiaagent/rmpp-pdf-enhancer.git
cd rmpp-pdf-enhancer
```

### 2. Set up virtual environment
```bash
# Install dependencies and set up the local virtual environment:
uv sync
```

### 3. Build the native Rust accelerator in development mode
When developing or modifying Rust source code under `rust/src/`:
```bash
# Compile and install the extension in editable mode into the active virtual environment:
uv run maturin develop
```

To build optimized release wheels:
```bash
uv run maturin build --release
```

### 4. Run tests and code quality checks
```bash
# Run the automated pytest test suite:
uv run --with pytest pytest tests/

# Run Rust linter and formatter:
cargo clippy -- -D warnings
cargo fmt --check
```

---

## Quickstart

### 1. Optimize an existing PDF document
```bash
uv run rmpp-pdf-enhancer "Linear_Algebra_Textbook.pdf"
# If installed as an CLI
rmpp-pdf-enhancer "Linear_Algebra_Textbook.pdf"
```
Produces `Linear_Algebra_Textbook_PaperPro_Optimized.pdf`.
Running again in the same directory will skip already-generated files (override with `-f` / `--force`).

### 2. Optimize a comic archive (`.cbz` or `.zip`)
```bash
uv run rmpp-pdf-enhancer "OnePiece_Vol100.cbz"
# If installed as an CLI
rmpp-pdf-enhancer "OnePiece_Vol100.cbz"
```

### 3. Process a folder of images
```bash
uv run rmpp-pdf-enhancer ./scanned_pages/
# If installed as an CLI
rmpp-pdf-enhancer ./scanned_pages/
```

### 4. Batch process a directory
```bash
uv run rmpp-pdf-enhancer ./DocumentsFolder/ --batch
# If installed as an CLI
rmpp-pdf-enhancer ./DocumentsFolder/ --batch
```

---

## CLI options reference

```text
usage: rmpp-pdf-enhancer [-h] [-o OUTPUT] [-q QUALITY] [--subsampling {0,2}]
                         [-w WORKERS] [-f] [--no-lut] [--no-ink]
                         [--lut-file LUT_FILE] [--batch] [-v]
                         inputs [inputs ...]

reMarkable Paper Pro PDF enhancer

positional arguments:
  inputs                Input file(s): .pdf, .cbz, .zip, or directory of images/scans

options:
  -h, --help            Show this help message and exit
  -o, --output OUTPUT   Output PDF file path or destination directory (default: None)
  -q, --quality QUALITY JPEG quality (1-100, default 82)
  --subsampling {0,2}   Chroma subsampling: 0=4:4:4 (crisp text), 2=4:2:0 (smaller file) (default: 0)
  -w, --workers WORKERS Number of concurrent worker threads (default: CPU count)
  -f, --force           Force overwrite if output file already exists, and re-process already optimized files (default: False)
  --no-lut              Disable included LUT compensation (default: False)
  --no-ink              Disable bilateral edge-directed inking filter (default: False)
  --lut-file LUT_FILE   Custom .cube 3D LUT profile path (default: None)
  --batch               Treat directory contents as separate sub-documents/chapters (default: False)
  -v, --version         Show program's version number and exit
```

---

## Benchmarking and tablet screen comparisons

The repository includes scripts to generate comparison PDFs:

```bash
uv run python scripts/generate_illustration_comparisons.py
```

---

## Testing

Run the automated test suite with `uv`:

```bash
uv run --with pytest pytest tests/
# Or using the built-in unittest runner:
uv run python -m unittest discover tests
```

---

## License

MIT License.
