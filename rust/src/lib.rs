//! rmpp-pdf-enhancer library
//! Universal color-calibrated PDF, document, textbook, and comic optimizer engineered for reMarkable Paper Pro.

pub mod extractor;
pub mod inking;
pub mod lut;
pub mod pdf_writer;
pub mod pipeline;

use rayon::prelude::*;
use std::path::{Path, PathBuf};
use std::time::Instant;

pub use extractor::{extract_document, ExtractedDocument};
pub use inking::apply_edge_directed_inking;
pub use lut::Lut3D;
pub use pdf_writer::{compile_pdf_from_pages, Chapter, ImagePage};
pub use pipeline::{encode_page_jpeg, process_image, scale_to_rmpp_geometry, EnhancerConfig};

/// Enhances a single document or archive into an RMPP-optimized PDF.
pub fn enhance_document<P1: AsRef<Path>, P2: AsRef<Path>>(
    input_path: P1,
    output_path: Option<P2>,
    config: &EnhancerConfig,
    workers: usize,
    force: bool,
) -> Result<PathBuf, String> {
    let start_time = Instant::now();
    let inp = input_path.as_ref();
    let inp_canon = inp.canonicalize().unwrap_or_else(|_| inp.to_path_buf());
    let inp_filename = inp
        .file_name()
        .and_then(|s| s.to_str())
        .unwrap_or("document");

    let out_path: PathBuf = match output_path {
        Some(p) => p.as_ref().to_path_buf(),
        None => {
            let stem = inp
                .file_stem()
                .and_then(|s| s.to_str())
                .unwrap_or("document");
            let parent_dir = if inp.is_dir() {
                inp_canon
                    .parent()
                    .unwrap_or_else(|| Path::new("."))
                    .to_path_buf()
            } else {
                inp.parent().unwrap_or_else(|| Path::new(".")).to_path_buf()
            };
            parent_dir.join(format!("{}_PaperPro_Optimized.pdf", stem))
        }
    };

    let out_filename = out_path
        .file_name()
        .and_then(|s| s.to_str())
        .unwrap_or("document.pdf");

    if out_path.exists() && !force {
        println!("\n⏭️  Skipping: {}", inp_filename);
        println!(
            "   Output '{}' already exists. Use --force to re-process.",
            out_filename
        );
        return Ok(out_path);
    }

    println!("\n=======================================================");
    println!("📖 Reading: {}", inp_filename);
    println!("=======================================================");

    let doc = extract_document(inp)?;
    let total_pages = doc.pages.len();
    println!(
        "Detected: {} pages | Chapters: {}",
        total_pages,
        doc.chapters.len()
    );

    if total_pages == 0 {
        println!("Warning: No pages found to process.");
        return Ok(out_path);
    }

    // Configure Rayon threadpool worker count
    if workers > 0 {
        let _ = rayon::ThreadPoolBuilder::new()
            .num_threads(workers)
            .build_global();
    }

    // Load LUT
    let lut = if config.color_correction {
        let loaded = if let Some(ref path) = config.lut_path {
            Lut3D::from_file(path)?
        } else {
            Lut3D::default_lut()
        };
        Some(loaded)
    } else {
        None
    };

    println!(
        "⚡ Processing {} pages with {} workers...",
        total_pages, workers
    );
    println!(
        "   Settings: Quality Q{}, Subsampling={}",
        config.quality,
        if config.subsampling == 0 {
            "4:4:4"
        } else {
            "4:2:0"
        }
    );
    println!(
        "   LUT Correction: {} | Edge Inking: {}",
        if config.color_correction { "ON" } else { "OFF" },
        if config.edge_inking { "ON" } else { "OFF" }
    );

    let t0 = Instant::now();

    // Process all pages in parallel
    let processed_pages: Result<Vec<ImagePage>, String> = doc
        .pages
        .into_par_iter()
        .map(|page_item| {
            let dyn_img = (page_item.loader)()
                .map_err(|e| format!("Page {}: {}", page_item.page_number, e))?;
            let enhanced = process_image(dyn_img, config, lut.as_ref());
            let (w, h) = enhanced.dimensions();
            let jpeg_bytes = encode_page_jpeg(&enhanced, config)?;
            Ok(ImagePage {
                width: w,
                height: h,
                jpeg_bytes,
            })
        })
        .collect();

    let pages = processed_pages?;
    let proc_duration = t0.elapsed().as_secs_f64();
    println!(
        "✓ Processed {} output pages in {:.2}s ({:.3}s/page)",
        pages.len(),
        proc_duration,
        proc_duration / pages.len() as f64
    );

    println!("📦 Assembling PDF: {}...", out_filename);
    compile_pdf_from_pages(&pages, &out_path, &doc.chapters)?;

    let total_duration = start_time.elapsed().as_secs_f64();
    let file_size_mb = std::fs::metadata(&out_path)
        .map(|m| m.len() as f64 / (1024.0 * 1024.0))
        .unwrap_or(0.0);

    println!(
        "🎉 Generated {} ({:.2} MB) in {:.2}s",
        out_filename, file_size_mb, total_duration
    );
    let full_path = out_path.canonicalize().unwrap_or_else(|_| out_path.clone());
    println!("   Full Path: {}", full_path.display());

    Ok(out_path)
}
