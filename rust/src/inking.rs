//! Edge-directed inking filter matching Pillow pipeline.

use image::{GrayImage, RgbImage};

use imageproc::filter::gaussian_blur_f32;
use rayon::prelude::*;

/// Computes 8-bit grayscale luminance using ITU-R 601-2 luma transform.
#[inline(always)]
fn rgb_to_luma(r: u8, g: u8, b: u8) -> u8 {
    ((299 * (r as u32) + 587 * (g as u32) + 114 * (b as u32) + 500) / 1000) as u8
}

/// Applies 3x3 FIND_EDGES Laplacian convolution matching Pillow.
/// Kernel: [[-1, -1, -1], [-1, 8, -1], [-1, -1, -1]]
/// Preserves 1-pixel outer border identical to Pillow.
fn find_edges(gray: &GrayImage) -> GrayImage {
    let (width, height) = gray.dimensions();
    let mut edges = gray.clone();

    if width < 3 || height < 3 {
        return edges;
    }

    let w = width as usize;
    let gray_raw = gray.as_raw();
    let edges_raw = edges.as_mut();

    // Process interior rows
    edges_raw
        .par_chunks_exact_mut(w)
        .enumerate()
        .skip(1)
        .take((height - 2) as usize)
        .for_each(|(y, row)| {
            let prev_row = &gray_raw[(y - 1) * w..y * w];
            let curr_row = &gray_raw[y * w..(y + 1) * w];
            let next_row = &gray_raw[(y + 1) * w..(y + 2) * w];

            for x in 1..(w - 1) {
                let center = curr_row[x] as i32;
                let sum_neighbors = (prev_row[x - 1] as i32)
                    + (prev_row[x] as i32)
                    + (prev_row[x + 1] as i32)
                    + (curr_row[x - 1] as i32)
                    + (curr_row[x + 1] as i32)
                    + (next_row[x - 1] as i32)
                    + (next_row[x] as i32)
                    + (next_row[x + 1] as i32);

                let val = 8 * center - sum_neighbors;
                row[x] = val.clamp(0, 255) as u8;
            }
        });

    edges
}

/// Applies bilateral edge-directed inking and micro-contrast unsharp mask.
pub fn apply_edge_directed_inking(img: &RgbImage) -> RgbImage {
    let (width, height) = img.dimensions();

    // 1. Create Grayscale image
    let mut gray = GrayImage::new(width, height);
    for (x, y, pixel) in img.enumerate_pixels() {
        gray.put_pixel(
            x,
            y,
            image::Luma([rgb_to_luma(pixel[0], pixel[1], pixel[2])]),
        );
    }

    // 2. FIND_EDGES Laplacian convolution
    let edges = find_edges(&gray);
    let edges_raw = edges.as_raw();

    // 3. Darken ink lines and brighten edge halos
    let mut pre_usm = img.clone();
    let raw = pre_usm.as_mut();

    raw.par_chunks_exact_mut(3)
        .enumerate()
        .for_each(|(i, pixel)| {
            let edge_val = edges_raw[i];
            // Threshold > 0.16 * 255.0 = 40.8 => edge_val >= 41
            if edge_val >= 41 {
                let r = pixel[0] as f32;
                let g = pixel[1] as f32;
                let b = pixel[2] as f32;
                let lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0;

                if lum < 0.40 {
                    // Dark ink: multiply by 0.75
                    pixel[0] = (r * 0.75).clamp(0.0, 255.0) as u8;
                    pixel[1] = (g * 0.75).clamp(0.0, 255.0) as u8;
                    pixel[2] = (b * 0.75).clamp(0.0, 255.0) as u8;
                } else {
                    // Light surround: multiply by 1.10
                    pixel[0] = (r * 1.10).clamp(0.0, 255.0) as u8;
                    pixel[1] = (g * 1.10).clamp(0.0, 255.0) as u8;
                    pixel[2] = (b * 1.10).clamp(0.0, 255.0) as u8;
                }
            }
        });

    // 4. Unsharp mask (radius=1.0, percent=115, threshold=3)
    let blurred = gaussian_blur_f32(&pre_usm, 1.0);
    let blurred_raw = blurred.as_raw();
    let pre_usm_raw = pre_usm.as_raw();

    let mut output = RgbImage::new(width, height);
    let out_raw = output.as_mut();

    out_raw
        .par_chunks_exact_mut(3)
        .enumerate()
        .for_each(|(i, out_pixel)| {
            let idx = i * 3;
            for c in 0..3 {
                let orig = pre_usm_raw[idx + c] as i32;
                let blur = blurred_raw[idx + c] as i32;
                let diff = orig - blur;
                if diff.abs() > 3 {
                    out_pixel[c] = (orig + diff * 115 / 100).clamp(0, 255) as u8;
                } else {
                    out_pixel[c] = orig as u8;
                }
            }
        });

    output
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_inking_dimensions() {
        let img = RgbImage::new(100, 100);
        let res = apply_edge_directed_inking(&img);
        assert_eq!(res.dimensions(), (100, 100));
    }
}
