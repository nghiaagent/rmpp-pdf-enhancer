//! Command-line interface for rmpp-pdf-enhancer.

use clap::Parser;
use std::path::PathBuf;

use rmpp_enhancer::{enhance_document, EnhancerConfig};

fn default_workers() -> usize {
    std::thread::available_parallelism()
        .map(|n| n.get().min(8))
        .unwrap_or(4)
}

#[derive(Parser, Debug)]
#[command(
    name = "rmpp-pdf-enhancer",
    version = env!("CARGO_PKG_VERSION"),
    about = "reMarkable Paper Pro PDF enhancer"
)]
struct Cli {
    /// Input file(s): .pdf, .cbz, .zip, or directory of images/scans
    #[arg(required = true)]
    inputs: Vec<PathBuf>,

    /// Output PDF file path (or destination directory if multiple inputs)
    #[arg(short = 'o', long = "output")]
    output: Option<PathBuf>,

    /// JPEG quality (1-100, default 82)
    #[arg(short = 'q', long = "quality", default_value_t = 82)]
    quality: u8,

    /// Chroma subsampling: 0=4:4:4 (crisp text), 2=4:2:0 (smaller file)
    #[arg(long = "subsampling", default_value_t = 0)]
    subsampling: u8,

    /// Number of concurrent worker threads
    #[arg(short = 'w', long = "workers", default_value_t = default_workers())]
    workers: usize,

    /// Force overwrite if output file already exists, and re-process already optimized files
    #[arg(short = 'f', long = "force")]
    force: bool,

    /// Disable included LUT compensation
    #[arg(long = "no-lut")]
    no_lut: bool,

    /// Disable bilateral edge-directed inking filter
    #[arg(long = "no-ink")]
    no_ink: bool,

    /// Custom .cube 3D LUT profile path
    #[arg(long = "lut-file")]
    lut_file: Option<PathBuf>,

    /// Treat directory contents as separate sub-documents/chapters
    #[arg(long = "batch")]
    batch: bool,
}

fn main() {
    let args = Cli::parse();

    let config = EnhancerConfig {
        quality: args.quality,
        subsampling: args.subsampling,
        color_correction: !args.no_lut,
        edge_inking: !args.no_ink,
        lut_path: args.lut_file.map(|p| p.to_string_lossy().to_string()),
        ..Default::default()
    };

    let mut raw_targets = Vec::new();
    for inp in &args.inputs {
        if args.batch && inp.is_dir() {
            if let Ok(entries) = std::fs::read_dir(inp) {
                let mut sorted_entries: Vec<PathBuf> =
                    entries.flatten().map(|e| e.path()).collect();
                sorted_entries.sort();
                for entry in sorted_entries {
                    let is_archive = entry
                        .extension()
                        .and_then(|s| s.to_str())
                        .map(|ext| {
                            matches!(ext.to_ascii_lowercase().as_str(), "cbz" | "zip" | "pdf")
                        })
                        .unwrap_or(false);
                    if entry.is_dir() || is_archive {
                        raw_targets.push(entry);
                    }
                }
            }
        } else {
            raw_targets.push(inp.clone());
        }
    }

    let mut targets = Vec::new();
    for t in raw_targets {
        let basename = t.file_name().and_then(|s| s.to_str()).unwrap_or("");
        if !args.force && basename.contains("_PaperPro_Optimized") {
            println!("⏭️  Skipping already optimized file: {}", basename);
            continue;
        }
        targets.push(t);
    }

    if targets.is_empty() {
        println!("No valid input files found to process.");
        std::process::exit(0);
    }

    println!(
        "rmpp-pdf-enhancer v{} - reMarkable Paper Pro Universal Optimizer",
        env!("CARGO_PKG_VERSION")
    );
    println!("Total targets to process: {}", targets.len());

    let multiple_targets = targets.len() > 1;

    for target in targets {
        let out_target = match &args.output {
            Some(out) => {
                if out.is_dir() || multiple_targets {
                    let _ = std::fs::create_dir_all(out);
                    let stem = target
                        .file_stem()
                        .and_then(|s| s.to_str())
                        .unwrap_or("document");
                    Some(out.join(format!("{}_PaperPro_Optimized.pdf", stem)))
                } else {
                    Some(out.clone())
                }
            }
            None => None,
        };

        if let Err(e) = enhance_document(
            &target,
            out_target.as_ref(),
            &config,
            args.workers,
            args.force,
        ) {
            eprintln!("Error processing {}: {}", target.display(), e);
        }
    }
}
