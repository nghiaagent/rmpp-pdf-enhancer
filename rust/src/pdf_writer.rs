//! Zero-transcode JPEG PDF compilation and Table of Contents (TOC) builder using pdf-writer.

use pdf_writer::{Content, Filter, Finish, Name, Pdf, Rect, Ref, TextStr};
use std::fs::File;
use std::io::{BufWriter, Write};
use std::path::Path;

const DPI: f32 = 229.0;
const PT_PER_INCH: f32 = 72.0;

/// Represents a chapter bookmark: (title, 1-indexed start page number).
pub type Chapter = (String, usize);

pub struct ImagePage {
    pub width: u32,
    pub height: u32,
    pub jpeg_bytes: Vec<u8>,
}

/// Reads JPEG dimensions from its header (SOF markers) without decoding pixels.
pub fn get_jpeg_dimensions(data: &[u8]) -> Result<(u32, u32), String> {
    let mut i = 0;
    if data.len() < 4 || data[0] != 0xFF || data[1] != 0xD8 {
        return Err("Not a valid JPEG file".to_string());
    }
    i += 2;
    while i < data.len() {
        if data[i] != 0xFF {
            i += 1;
            continue;
        }
        let marker = data[i + 1];
        i += 2;
        // SOF0, SOF1, SOF2 markers contain image height and width
        if matches!(marker, 0xC0..=0xC3 | 0xC5..=0xC7 | 0xC9..=0xCB | 0xCD..=0xCF) {
            if i + 7 > data.len() {
                return Err("Truncated JPEG SOF marker".to_string());
            }
            let h = ((data[i + 3] as u32) << 8) | (data[i + 4] as u32);
            let w = ((data[i + 5] as u32) << 8) | (data[i + 6] as u32);
            return Ok((w, h));
        }
        // Skip marker segment
        if i + 2 > data.len() {
            break;
        }
        let len = ((data[i] as usize) << 8) | (data[i + 1] as usize);
        i += len;
    }
    Err("Could not find SOF marker in JPEG data".to_string())
}

/// Compiles JPEG image files into a single PDF with 229 DPI MediaBox and optional TOC outlines.
pub fn compile_pdf<P: AsRef<Path>>(
    jpeg_paths: &[P],
    output_pdf_path: P,
    chapters: &[Chapter],
) -> Result<(), String> {
    let mut pages = Vec::with_capacity(jpeg_paths.len());
    for p in jpeg_paths {
        let path = p.as_ref();
        let bytes = std::fs::read(path)
            .map_err(|e| format!("Failed to read JPEG {}: {}", path.display(), e))?;
        let (w, h) = get_jpeg_dimensions(&bytes)?;
        pages.push(ImagePage {
            width: w,
            height: h,
            jpeg_bytes: bytes,
        });
    }
    compile_pdf_from_pages(&pages, output_pdf_path, chapters)
}

/// Compiles in-memory JPEG pages into a single PDF with 229 DPI MediaBox and optional TOC outlines.
pub fn compile_pdf_from_pages<P: AsRef<Path>>(
    pages: &[ImagePage],
    output_pdf_path: P,
    chapters: &[Chapter],
) -> Result<(), String> {
    if pages.is_empty() {
        return Err("No pages provided to compile_pdf".to_string());
    }

    let mut pdf = Pdf::new();
    let mut ref_alloc = 1;
    let mut alloc_ref = || {
        let r = Ref::new(ref_alloc);
        ref_alloc += 1;
        r
    };

    let catalog_id = alloc_ref();
    let page_tree_id = alloc_ref();

    let num_pages = pages.len();
    let mut page_ids = Vec::with_capacity(num_pages);
    let mut image_ids = Vec::with_capacity(num_pages);
    let mut content_ids = Vec::with_capacity(num_pages);

    for _ in 0..num_pages {
        page_ids.push(alloc_ref());
        image_ids.push(alloc_ref());
        content_ids.push(alloc_ref());
    }

    // Allocate outline IDs if chapters are provided
    let outline_id = if !chapters.is_empty() {
        Some(alloc_ref())
    } else {
        None
    };

    let mut outline_item_ids = Vec::new();
    if outline_id.is_some() {
        for _ in 0..chapters.len() {
            outline_item_ids.push(alloc_ref());
        }
    }

    // 1. Catalog
    let mut catalog = pdf.catalog(catalog_id);
    catalog.pages(page_tree_id);
    if let Some(oid) = outline_id {
        catalog.outlines(oid);
    }
    catalog.finish();

    // 2. Page Tree
    pdf.pages(page_tree_id)
        .kids(page_ids.iter().copied())
        .count(num_pages as i32);

    let image_name = Name(b"Im1");

    // 3. Pages & Content
    for i in 0..num_pages {
        let page = &pages[i];
        let p_id = page_ids[i];
        let img_id = image_ids[i];
        let c_id = content_ids[i];

        // 229 DPI point dimensions matching img2pdf
        let w_pt = (page.width as f32) * PT_PER_INCH / DPI;
        let h_pt = (page.height as f32) * PT_PER_INCH / DPI;
        let rect = Rect::new(0.0, 0.0, w_pt, h_pt);

        let mut page_obj = pdf.page(p_id);
        page_obj.media_box(rect);
        page_obj.parent(page_tree_id);
        page_obj.contents(c_id);
        page_obj.resources().x_objects().pair(image_name, img_id);
        page_obj.finish();

        // JPEG XObject stream (lossless DCTDecode)
        let mut img_obj = pdf.image_xobject(img_id, &page.jpeg_bytes);
        img_obj.filter(Filter::DctDecode);
        img_obj.width(page.width as i32);
        img_obj.height(page.height as i32);
        img_obj.color_space().device_rgb();
        img_obj.bits_per_component(8);
        img_obj.finish();

        // Content stream: scale image to fit entire page rect
        let mut content = Content::new();
        content.save_state();
        content.transform([w_pt, 0.0, 0.0, h_pt, 0.0, 0.0]);
        content.x_object(image_name);
        content.restore_state();
        pdf.stream(c_id, &content.finish());
    }

    // 4. Outlines (Table of Contents)
    if let Some(oid) = outline_id {
        let n_items = chapters.len();
        let first_item = outline_item_ids[0];
        let last_item = outline_item_ids[n_items - 1];

        let mut outline = pdf.outline(oid);
        outline.first(first_item);
        outline.last(last_item);
        outline.count(n_items as i32);
        outline.finish();

        for (idx, (title, target_page_1indexed)) in chapters.iter().enumerate() {
            let item_id = outline_item_ids[idx];
            let clamped_page_idx = target_page_1indexed.saturating_sub(1).min(num_pages - 1);
            let target_page_ref = page_ids[clamped_page_idx];

            let mut item = pdf.outline_item(item_id);
            item.title(TextStr(title));
            item.parent(oid);

            if idx > 0 {
                item.prev(outline_item_ids[idx - 1]);
            }
            if idx + 1 < n_items {
                item.next(outline_item_ids[idx + 1]);
            }

            item.dest().page(target_page_ref).fit();
            item.finish();
        }
    }

    // Write final PDF
    let out_path = output_pdf_path.as_ref();
    if let Some(parent) = out_path.parent() {
        if !parent.as_os_str().is_empty() {
            std::fs::create_dir_all(parent)
                .map_err(|e| format!("Failed to create directory {}: {}", parent.display(), e))?;
        }
    }

    let file = File::create(out_path)
        .map_err(|e| format!("Failed to create output file {}: {}", out_path.display(), e))?;
    let mut writer = BufWriter::new(file);
    writer
        .write_all(&pdf.finish())
        .map_err(|e| format!("Failed to write PDF {}: {}", out_path.display(), e))?;

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use jpeg_encoder::{ColorType, Encoder, PixelDensity, SamplingFactor};

    fn make_test_jpeg(w: u32, h: u32) -> Vec<u8> {
        let mut buf = Vec::new();
        let mut encoder = Encoder::new(&mut buf, 82);
        encoder.set_sampling_factor(SamplingFactor::R_4_4_4);
        encoder.set_density(PixelDensity::dpi(229));
        let data = vec![128u8; (w * h * 3) as usize];
        encoder
            .encode(&data, w as u16, h as u16, ColorType::Rgb)
            .unwrap();
        buf
    }

    #[test]
    fn test_jpeg_dimensions() {
        let jpg = make_test_jpeg(120, 80);
        let (w, h) = get_jpeg_dimensions(&jpg).unwrap();
        assert_eq!(w, 120);
        assert_eq!(h, 80);
    }

    #[test]
    fn test_compile_pdf_with_chapters() {
        let jpg1 = make_test_jpeg(1620, 2160);
        let jpg2 = make_test_jpeg(2160, 1620);
        let pages = vec![
            ImagePage {
                width: 1620,
                height: 2160,
                jpeg_bytes: jpg1,
            },
            ImagePage {
                width: 2160,
                height: 1620,
                jpeg_bytes: jpg2,
            },
        ];

        let out_file = "/tmp/test_pdf_writer_output.pdf";
        let chapters = vec![
            ("Chapter 1: Portrait".to_string(), 1),
            ("Chapter 2: Landscape".to_string(), 2),
        ];

        compile_pdf_from_pages(&pages, out_file, &chapters).unwrap();
        assert!(std::path::Path::new(out_file).exists());
        let _ = std::fs::remove_file(out_file);
    }
}
