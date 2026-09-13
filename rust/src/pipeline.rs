//! Core image processing pipeline for reMarkable Paper Pro.

use image::{DynamicImage, Rgb, RgbImage};

use fast_image_resize as fir;
use jpeg_encoder::{ColorType, Encoder, PixelDensity, SamplingFactor};

use crate::inking::apply_edge_directed_inking;
use crate::lut::Lut3D;

#[derive(Clone, Debug)]
pub struct EnhancerConfig {
    pub quality: u8,            // Sweet-spot 82 for cloud sync
    pub subsampling: u8,        // 0 = 4:4:4, 2 = 4:2:0
    pub color_correction: bool, // OKLab v3 3D LUT
    pub edge_inking: bool,      // Bilateral edge-directed inking
    pub lut_path: Option<String>,
    pub target_width: u32,  // 1620
    pub target_height: u32, // 2160
    pub dpi: u16,           // 229
}

impl Default for EnhancerConfig {
    fn default() -> Self {
        Self {
            quality: 82,
            subsampling: 0,
            color_correction: true,
            edge_inking: true,
            lut_path: None,
            target_width: 1620,
            target_height: 2160,
            dpi: 229,
        }
    }
}

/// Ensures image is in RGB mode with alpha composited over pure white.
pub fn prepare_rgb(img: DynamicImage) -> RgbImage {
    match img {
        DynamicImage::ImageRgb8(rgb) => rgb,
        other => {
            let rgba = other.to_rgba8();
            let (w, h) = rgba.dimensions();
            let mut out = RgbImage::new(w, h);
            for (x, y, pixel) in rgba.enumerate_pixels() {
                let a = pixel[3] as f32 / 255.0;
                if a >= 1.0 {
                    out.put_pixel(x, y, Rgb([pixel[0], pixel[1], pixel[2]]));
                } else if a <= 0.0 {
                    out.put_pixel(x, y, Rgb([255, 255, 255]));
                } else {
                    let r = ((pixel[0] as f32 * a) + 255.0 * (1.0 - a)).round() as u8;
                    let g = ((pixel[1] as f32 * a) + 255.0 * (1.0 - a)).round() as u8;
                    let b = ((pixel[2] as f32 * a) + 255.0 * (1.0 - a)).round() as u8;
                    out.put_pixel(x, y, Rgb([r, g, b]));
                }
            }
            out
        }
    }
}

/// Computes Option A target dimensions for portrait or landscape orientation.
pub fn compute_target_geometry(w: u32, h: u32, config: &EnhancerConfig) -> (u32, u32) {
    let scale = if h >= w {
        // Portrait: fit within 1620 x 2160 (height target 2160)
        (config.target_width as f64 / w as f64).min(config.target_height as f64 / h as f64)
    } else {
        // Landscape spread: fit within 2160 x 1620
        (config.target_height as f64 / w as f64).min(config.target_width as f64 / h as f64)
    };

    let new_w = (w as f64 * scale).round().max(1.0) as u32;
    let new_h = (h as f64 * scale).round().max(1.0) as u32;
    (new_w, new_h)
}

/// Scales image proportionally to Option A screen geometry using SIMD Lanczos3.
pub fn scale_to_rmpp_geometry(img: &RgbImage, config: &EnhancerConfig) -> RgbImage {
    let (w, h) = img.dimensions();
    let (new_w, new_h) = compute_target_geometry(w, h, config);

    if (new_w, new_h) == (w, h) {
        return img.clone();
    }

    let src_view = fir::images::ImageRef::new(w, h, img.as_raw(), fir::PixelType::U8x3)
        .expect("Invalid source image buffer");
    let mut dst_image = fir::images::Image::new(new_w, new_h, fir::PixelType::U8x3);
    let mut resizer = fir::Resizer::new();
    let options = fir::ResizeOptions::new()
        .resize_alg(fir::ResizeAlg::Interpolation(fir::FilterType::Lanczos3));

    resizer
        .resize(&src_view, &mut dst_image, &options)
        .expect("Failed to resize image");

    RgbImage::from_raw(new_w, new_h, dst_image.into_vec())
        .expect("Failed to construct RgbImage from resized buffer")
}

/// Runs a single page through scaling, 3D LUT calibration, and edge-directed inking.
pub fn process_image(img: DynamicImage, config: &EnhancerConfig, lut: Option<&Lut3D>) -> RgbImage {
    let rgb = prepare_rgb(img);

    // 1. Scale to Option A Geometry (@ 229 PPI)
    let mut scaled = scale_to_rmpp_geometry(&rgb, config);

    // 2. 3D LUT Color Calibration
    if config.color_correction {
        if let Some(l) = lut {
            l.apply(&mut scaled);
        }
    }

    // 3. Bilateral Edge Inking Filter
    if config.edge_inking {
        apply_edge_directed_inking(&scaled)
    } else {
        scaled
    }
}

/// Encodes an RgbImage directly into JPEG bytes with tuned quality, chroma subsampling, and DPI.
pub fn encode_page_jpeg(img: &RgbImage, config: &EnhancerConfig) -> Result<Vec<u8>, String> {
    let mut buf = Vec::new();
    let mut encoder = Encoder::new(&mut buf, config.quality);
    let sampling = match config.subsampling {
        0 => SamplingFactor::R_4_4_4,
        2 => SamplingFactor::R_4_2_0,
        _ => SamplingFactor::R_4_4_4,
    };
    encoder.set_sampling_factor(sampling);
    encoder.set_density(PixelDensity::dpi(config.dpi));
    let (w, h) = img.dimensions();
    encoder
        .encode(img.as_raw(), w as u16, h as u16, ColorType::Rgb)
        .map_err(|e| format!("JPEG encoding error: {}", e))?;
    Ok(buf)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_option_a_scaling_portrait() {
        let config = EnhancerConfig::default();
        let (w, h) = compute_target_geometry(1080, 1920, &config);
        assert_eq!(h, 2160);
        assert_eq!(w, 1215);

        let img = RgbImage::new(1080, 1920);
        let scaled = scale_to_rmpp_geometry(&img, &config);
        assert_eq!(scaled.dimensions(), (1215, 2160));
    }

    #[test]
    fn test_option_a_scaling_landscape() {
        let config = EnhancerConfig::default();
        let (w, h) = compute_target_geometry(1920, 1080, &config);
        assert!(w <= 2160 && h <= 1620);
        assert_eq!(w, 2160);
        assert_eq!(h, 1215);

        let img = RgbImage::new(1920, 1080);
        let scaled = scale_to_rmpp_geometry(&img, &config);
        assert_eq!(scaled.dimensions(), (2160, 1215));
    }

    #[test]
    fn test_prepare_rgb_alpha() {
        let mut rgba = image::RgbaImage::new(10, 10);
        for pixel in rgba.pixels_mut() {
            *pixel = image::Rgba([255, 0, 0, 0]); // fully transparent
        }
        let rgb = prepare_rgb(DynamicImage::ImageRgba8(rgba));
        assert_eq!(rgb.get_pixel(5, 5), &Rgb([255, 255, 255]));
    }
}
