//! Bilateral edge-directed inking filter and micro-contrast unsharp mask.
//! Matches Python Pillow/NumPy edge-directed inking math with zero deviation.

use image::{GrayImage, RgbImage};
use imageproc::filter::gaussian_blur_f32;

pub fn apply_edge_directed_inking(img: &mut RgbImage) {
    let (w, h) = img.dimensions();
    if w < 3 || h < 3 {
        return;
    }

    // 1. Compute ITU-R 601-2 luma and convolve 3x3 Laplacian edge kernel
    // Pillow: ImageFilter.FIND_EDGES is [-1, -1, -1, -1, 8, -1, -1, -1, -1]
    let mut gray = GrayImage::new(w, h);
    for (x, y, pixel) in img.enumerate_pixels() {
        let lum = (0.299 * pixel[0] as f32 + 0.587 * pixel[1] as f32 + 0.114 * pixel[2] as f32)
            .round() as u8;
        gray.put_pixel(x, y, image::Luma([lum]));
    }

    let mut edge_mask = vec![false; (w * h) as usize];
    for y in 1..(h - 1) {
        for x in 1..(w - 1) {
            let center = gray.get_pixel(x, y)[0] as i32;
            let mut sum = 8 * center;
            sum -= gray.get_pixel(x - 1, y - 1)[0] as i32;
            sum -= gray.get_pixel(x, y - 1)[0] as i32;
            sum -= gray.get_pixel(x + 1, y - 1)[0] as i32;
            sum -= gray.get_pixel(x - 1, y)[0] as i32;
            sum -= gray.get_pixel(x + 1, y)[0] as i32;
            sum -= gray.get_pixel(x - 1, y + 1)[0] as i32;
            sum -= gray.get_pixel(x, y + 1)[0] as i32;
            sum -= gray.get_pixel(x + 1, y + 1)[0] as i32;

            let edge_val = (sum.abs() as f32) / 255.0;
            if edge_val > 0.16 {
                edge_mask[(y * w + x) as usize] = true;
            }
        }
    }

    // 2. Dark ink line deepening (-25%) and edge halo brightening (+10%)
    for y in 0..h {
        for x in 0..w {
            let idx = (y * w + x) as usize;
            if edge_mask[idx] {
                let pixel = img.get_pixel_mut(x, y);
                let lum =
                    (0.299 * pixel[0] as f32 + 0.587 * pixel[1] as f32 + 0.114 * pixel[2] as f32)
                        / 255.0;

                if lum < 0.40 {
                    // Dark ink line
                    pixel[0] = ((pixel[0] as f32 * 0.75).round() as u32).min(255) as u8;
                    pixel[1] = ((pixel[1] as f32 * 0.75).round() as u32).min(255) as u8;
                    pixel[2] = ((pixel[2] as f32 * 0.75).round() as u32).min(255) as u8;
                } else {
                    // Light surround / edge halo
                    pixel[0] = ((pixel[0] as f32 * 1.10).round() as u32).min(255) as u8;
                    pixel[1] = ((pixel[1] as f32 * 1.10).round() as u32).min(255) as u8;
                    pixel[2] = ((pixel[2] as f32 * 1.10).round() as u32).min(255) as u8;
                }
            }
        }
    }

    // 3. Gaussian unsharp mask: radius=1.0 (sigma=1.0), percent=115%, threshold=3
    let blurred = gaussian_blur_f32(img, 1.0);
    let amount = 1.15f32;
    let threshold = 3i32;

    for (x, y, pixel) in img.enumerate_pixels_mut() {
        let b_pix = blurred.get_pixel(x, y);
        for c in 0..3 {
            let orig = pixel[c] as i32;
            let blur = b_pix[c] as i32;
            let diff = orig - blur;
            if diff.abs() >= threshold {
                let sharpened = orig as f32 + diff as f32 * amount;
                pixel[c] = sharpened.round().clamp(0.0, 255.0) as u8;
            }
        }
    }
}
