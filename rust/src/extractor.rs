//! Input document and archive extractor.
//!
//! Supports:
//! - Image directories (flat or multi-chapter subfolders)
//! - Comic archives (.cbz, .zip)
//! - Scanned PDF documents (extracts embedded image streams)
//! - Single image files (.png, .jpg, .jpeg, .webp, .bmp, .tiff)
//! - Natural alphanumeric sorting for page ordering

use std::cmp::Ordering;
use std::fs::File;
use std::io::{BufReader, Read};

use image::DynamicImage;
use std::path::{Path, PathBuf};
use zip::ZipArchive;

pub const IMAGE_EXTENSIONS: &[&str] = &["png", "jpg", "jpeg", "webp", "bmp", "tiff", "tif"];

pub fn is_image_ext(ext: &str) -> bool {
    IMAGE_EXTENSIONS.contains(&ext.to_ascii_lowercase().as_str())
}

#[derive(Debug, PartialEq, Eq)]
enum Token<'a> {
    Num(u64),
    Str(&'a str),
}

/// Tokenizes a string into alternating text and numeric segments for natural sorting.
fn tokenize(s: &str) -> Vec<Token<'_>> {
    let mut tokens = Vec::new();
    let mut chars = s.char_indices().peekable();

    while let Some(&(start, ch)) = chars.peek() {
        if ch.is_ascii_digit() {
            let mut end = start;
            while let Some(&(idx, d)) = chars.peek() {
                if d.is_ascii_digit() {
                    end = idx + d.len_utf8();
                    chars.next();
                } else {
                    break;
                }
            }
            if let Ok(num) = s[start..end].parse::<u64>() {
                tokens.push(Token::Num(num));
            } else {
                tokens.push(Token::Str(&s[start..end]));
            }
        } else {
            let mut end = start;
            while let Some(&(idx, non_d)) = chars.peek() {
                if !non_d.is_ascii_digit() {
                    end = idx + non_d.len_utf8();
                    chars.next();
                } else {
                    break;
                }
            }
            tokens.push(Token::Str(&s[start..end]));
        }
    }

    tokens
}

/// Compares two strings in natural human alphanumeric order (e.g. 1, 2, 10).
pub fn natural_compare(a: &str, b: &str) -> Ordering {
    let tok_a = tokenize(a);
    let tok_b = tokenize(b);

    for (t_a, t_b) in tok_a.iter().zip(tok_b.iter()) {
        match (t_a, t_b) {
            (Token::Num(n_a), Token::Num(n_b)) => {
                let ord = n_a.cmp(n_b);
                if ord != Ordering::Equal {
                    return ord;
                }
            }
            (Token::Str(s_a), Token::Str(s_b)) => {
                let ord = s_a.to_lowercase().cmp(&s_b.to_lowercase());
                if ord != Ordering::Equal {
                    return ord;
                }
            }
            (Token::Num(_), Token::Str(_)) => return Ordering::Less,
            (Token::Str(_), Token::Num(_)) => return Ordering::Greater,
        }
    }

    tok_a.len().cmp(&tok_b.len())
}

pub struct PageItem {
    pub page_number: usize,
    pub chapter_name: Option<String>,
    pub loader: Box<dyn Fn() -> Result<DynamicImage, String> + Send + Sync>,
}

pub struct ExtractedDocument {
    pub title: String,
    pub pages: Vec<PageItem>,
    pub chapters: Vec<(String, usize)>,
}

fn load_image_file<P: AsRef<Path>>(path: P) -> Result<DynamicImage, String> {
    image::open(path.as_ref())
        .map_err(|e| format!("Failed to load image {}: {}", path.as_ref().display(), e))
}

fn load_image_zip(archive_path: PathBuf, member_name: String) -> Result<DynamicImage, String> {
    let file = File::open(&archive_path)
        .map_err(|e| format!("Failed to open zip {}: {}", archive_path.display(), e))?;
    let mut archive = ZipArchive::new(BufReader::new(file))
        .map_err(|e| format!("Failed to parse zip archive: {}", e))?;
    let mut member = archive
        .by_name(&member_name)
        .map_err(|e| format!("Failed to locate {} in zip: {}", member_name, e))?;
    let mut buf = Vec::with_capacity(member.size() as usize);
    member
        .read_to_end(&mut buf)
        .map_err(|e| format!("Failed to read zip member {}: {}", member_name, e))?;
    image::load_from_memory(&buf)
        .map_err(|e| format!("Failed to decode image {}: {}", member_name, e))
}

pub fn extract_from_directory<P: AsRef<Path>>(dir: P) -> Result<ExtractedDocument, String> {
    let path = dir.as_ref();
    let title = path
        .file_name()
        .and_then(|s| s.to_str())
        .unwrap_or("document")
        .to_string();

    let mut subdirs = Vec::new();
    let mut root_files = Vec::new();

    let entries = std::fs::read_dir(path)
        .map_err(|e| format!("Failed to read directory {}: {}", path.display(), e))?;

    for entry_res in entries {
        let entry = entry_res.map_err(|e| format!("Error reading directory entry: {}", e))?;
        let entry_path = entry.path();
        if entry_path.is_dir() {
            subdirs.push(entry_path);
        } else if entry_path.is_file() {
            if let Some(ext) = entry_path.extension().and_then(|s| s.to_str()) {
                if is_image_ext(ext) {
                    root_files.push(entry_path);
                }
            }
        }
    }

    subdirs.sort_by(|a, b| {
        let a_str = a.file_name().unwrap().to_str().unwrap();
        let b_str = b.file_name().unwrap().to_str().unwrap();
        natural_compare(a_str, b_str)
    });

    root_files.sort_by(|a, b| {
        let a_str = a.file_name().unwrap().to_str().unwrap();
        let b_str = b.file_name().unwrap().to_str().unwrap();
        natural_compare(a_str, b_str)
    });

    let mut pages = Vec::new();
    let mut chapters = Vec::new();
    let mut page_num = 1;

    // Subdirectories as chapters
    for sdir in subdirs {
        let ch_name = sdir
            .file_name()
            .and_then(|s| s.to_str())
            .unwrap_or("Chapter")
            .to_string();
        let mut chapter_files = Vec::new();

        if let Ok(entries) = std::fs::read_dir(&sdir) {
            for entry_res in entries.flatten() {
                let p = entry_res.path();
                if p.is_file() {
                    if let Some(ext) = p.extension().and_then(|s| s.to_str()) {
                        if is_image_ext(ext) {
                            chapter_files.push(p);
                        }
                    }
                }
            }
        }

        chapter_files.sort_by(|a, b| {
            let a_str = a.file_name().unwrap().to_str().unwrap();
            let b_str = b.file_name().unwrap().to_str().unwrap();
            natural_compare(a_str, b_str)
        });

        if !chapter_files.is_empty() {
            chapters.push((ch_name.clone(), page_num));
            for fpath in chapter_files {
                let captured_path = fpath.clone();
                pages.push(PageItem {
                    page_number: page_num,
                    chapter_name: Some(ch_name.clone()),
                    loader: Box::new(move || load_image_file(&captured_path)),
                });
                page_num += 1;
            }
        }
    }

    // Root files
    if !root_files.is_empty() {
        let root_ch = if chapters.is_empty() {
            None
        } else {
            chapters.push((title.clone(), page_num));
            Some(title.clone())
        };

        for fpath in root_files {
            let captured_path = fpath.clone();
            let ch_name = root_ch.clone();
            pages.push(PageItem {
                page_number: page_num,
                chapter_name: ch_name,
                loader: Box::new(move || load_image_file(&captured_path)),
            });
            page_num += 1;
        }
    }

    Ok(ExtractedDocument {
        title,
        pages,
        chapters,
    })
}

pub fn extract_from_zip<P: AsRef<Path>>(archive_path: P) -> Result<ExtractedDocument, String> {
    let path = archive_path.as_ref();
    let title = path
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("archive")
        .to_string();

    let file = File::open(path)
        .map_err(|e| format!("Failed to open zip archive {}: {}", path.display(), e))?;
    let mut archive = ZipArchive::new(BufReader::new(file))
        .map_err(|e| format!("Failed to parse zip archive: {}", e))?;

    let mut members: Vec<String> = Vec::new();
    for i in 0..archive.len() {
        if let Ok(m) = archive.by_index(i) {
            let name = m.name();
            if !m.is_dir() {
                if let Some(ext) = Path::new(name).extension().and_then(|s| s.to_str()) {
                    if is_image_ext(ext) {
                        members.push(name.to_string());
                    }
                }
            }
        }
    }

    members.sort_by(|a, b| natural_compare(a, b));

    let mut pages = Vec::new();
    let mut chapters = Vec::new();
    let mut current_ch: Option<String> = None;
    let arch_buf = path.to_path_buf();

    for (idx, member_name) in members.into_iter().enumerate() {
        let page_num = idx + 1;
        let parts: Vec<&str> = member_name.split('/').collect();
        let ch_name = if parts.len() > 1 && !parts[0].is_empty() {
            Some(parts[0].to_string())
        } else {
            None
        };

        if let Some(ref ch) = ch_name {
            if current_ch.as_ref() != Some(ch) {
                current_ch = Some(ch.clone());
                chapters.push((ch.clone(), page_num));
            }
        }

        let arch_clone = arch_buf.clone();
        let mem_clone = member_name.clone();
        pages.push(PageItem {
            page_number: page_num,
            chapter_name: ch_name,
            loader: Box::new(move || load_image_zip(arch_clone.clone(), mem_clone.clone())),
        });
    }

    Ok(ExtractedDocument {
        title,
        pages,
        chapters,
    })
}

pub fn extract_from_pdf<P: AsRef<Path>>(pdf_path: P) -> Result<ExtractedDocument, String> {
    let path = pdf_path.as_ref();
    let title = path
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("document")
        .to_string();

    let doc = lopdf::Document::load(path)
        .map_err(|e| format!("Failed to parse PDF {}: {}", path.display(), e))?;

    let pages_dict = doc.get_pages();
    let total_pages = pages_dict.len();

    // Extract outline bookmarks if available
    let mut chapters = Vec::new();
    if let Ok(catalog) = doc.catalog() {
        if let Ok(outlines_id) = catalog.get(b"Outlines").and_then(|o| o.as_reference()) {
            if let Ok(outlines_obj) = doc.get_object(outlines_id) {
                if let Ok(outlines_dict) = outlines_obj.as_dict() {
                    let mut curr_item_ref = outlines_dict
                        .get(b"First")
                        .and_then(|o| o.as_reference())
                        .ok();
                    while let Some(item_id) = curr_item_ref {
                        if let Ok(item_obj) = doc.get_object(item_id) {
                            if let Ok(item_dict) = item_obj.as_dict() {
                                let title_str = item_dict
                                    .get(b"Title")
                                    .and_then(|t| t.as_str())
                                    .map(|bytes| String::from_utf8_lossy(bytes).into_owned())
                                    .unwrap_or_else(|_| "Chapter".to_string());
                                chapters.push((title_str, chapters.len() + 1));
                                curr_item_ref =
                                    item_dict.get(b"Next").and_then(|o| o.as_reference()).ok();
                            } else {
                                break;
                            }
                        } else {
                            break;
                        }
                    }
                }
            }
        }
    }

    let mut pages = Vec::with_capacity(total_pages);
    let path_buf = path.to_path_buf();

    for (page_num, (_p_num, page_obj_id)) in pages_dict.into_iter().enumerate() {
        let p_num_1indexed = page_num + 1;
        let p_path = path_buf.clone();
        pages.push(PageItem {
            page_number: p_num_1indexed,
            chapter_name: None,
            loader: Box::new(move || {
                let doc = lopdf::Document::load(&p_path)
                    .map_err(|e| format!("Failed to reload PDF: {}", e))?;
                let page_obj = doc
                    .get_object(page_obj_id)
                    .map_err(|e| format!("Failed to get page object: {}", e))?;
                let page_dict = page_obj
                    .as_dict()
                    .map_err(|e| format!("Page object is not dict: {}", e))?;

                // Search for /Resources /XObject /Subtype /Image
                if let Ok(resources) = page_dict.get(b"Resources").and_then(|r| doc.dereference(r))
                {
                    if let Ok(r_dict) = resources.1.as_dict() {
                        if let Ok(xobjects) =
                            r_dict.get(b"XObject").and_then(|x| doc.dereference(x))
                        {
                            if let Ok(x_dict) = xobjects.1.as_dict() {
                                for (_key, val) in x_dict.iter() {
                                    if let Ok(xobj) = doc.dereference(val) {
                                        if let Ok(stream) = xobj.1.as_stream() {
                                            if let Ok(subtype) = stream
                                                .dict
                                                .get(b"Subtype")
                                                .and_then(|s| s.as_name())
                                            {
                                                if subtype == b"Image" {
                                                    // Check if JPEG (DCTDecode)
                                                    let is_dct = stream
                                                        .dict
                                                        .get(b"Filter")
                                                        .and_then(|f| f.as_name())
                                                        .map(|n| n == b"DCTDecode")
                                                        .unwrap_or(false);

                                                    if is_dct {
                                                        if let Ok(img) =
                                                            image::load_from_memory(&stream.content)
                                                        {
                                                            return Ok(img);
                                                        }
                                                    }

                                                    // Try decoding decompressed stream
                                                    if let Ok(decompressed) =
                                                        stream.decompressed_content()
                                                    {
                                                        if let Ok(img) =
                                                            image::load_from_memory(&decompressed)
                                                        {
                                                            return Ok(img);
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                Err(format!(
                    "Could not extract image from page {}",
                    p_num_1indexed
                ))
            }),
        });
    }

    Ok(ExtractedDocument {
        title,
        pages,
        chapters,
    })
}

pub fn extract_document<P: AsRef<Path>>(input_path: P) -> Result<ExtractedDocument, String> {
    let path = input_path.as_ref();
    if !path.exists() {
        return Err(format!("Input path does not exist: {}", path.display()));
    }

    if path.is_dir() {
        return extract_from_directory(path);
    }

    let ext = path
        .extension()
        .and_then(|s| s.to_str())
        .unwrap_or("")
        .to_ascii_lowercase();

    match ext.as_str() {
        "cbz" | "zip" => extract_from_zip(path),
        "pdf" => extract_from_pdf(path),
        e if is_image_ext(e) => {
            let title = path
                .file_stem()
                .and_then(|s| s.to_str())
                .unwrap_or("image")
                .to_string();
            let captured = path.to_path_buf();
            let pages = vec![PageItem {
                page_number: 1,
                chapter_name: None,
                loader: Box::new(move || load_image_file(&captured)),
            }];
            Ok(ExtractedDocument {
                title,
                pages,
                chapters: Vec::new(),
            })
        }
        other => Err(format!(
            "Unsupported file format: .{} (supported: .cbz, .zip, .pdf, image folders)",
            other
        )),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_natural_compare() {
        let mut list = vec!["page10.png", "page1.png", "page2.png", "page20.png"];
        list.sort_by(|a, b| natural_compare(a, b));
        assert_eq!(
            list,
            vec!["page1.png", "page2.png", "page10.png", "page20.png"]
        );
    }
}
