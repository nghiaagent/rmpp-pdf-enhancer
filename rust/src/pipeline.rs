//! Image processing pipeline and direct-to-file JPEG encoding.

use std::fs::File;
use std::io::BufWriter;
use std::path::Path;

use fast_image_resize as fir;
use image::RgbImage;
use jpeg_encoder::{ColorType, Density, Encoder, SamplingFactor};

use crate::inking::apply_edge_directed_inking;
use crate::lut::Lut3D;

pub struct ProcessConfig<'a> {
    pub quality: u8,
    pub subsampling: u8,
    pub color_correction: bool,
    pub edge_inking: bool,
    pub custom_lut_path: Option<&'a str>,
    pub target_width: u32,  // 1620
    pub target_height: u32, // 2160
    pub dpi: u16,           // 229
}

impl<'a> Default for ProcessConfig<'a> {
    fn default() -> Self {
        Self {
            quality: 82,
            subsampling: 0,
            color_correction: true,
            edge_inking: true,
            custom_lut_path: None,
            target_width: 1620,
            target_height: 2160,
            dpi: 229,
        }
    }
}

/// Computes Option A target dimensions for portrait or landscape orientation.
#[inline]
pub fn compute_target_geometry(w: u32, h: u32, target_w: u32, target_h: u32) -> (u32, u32) {
    let scale = if h >= w {
        // Portrait: fit within 1620 x 2160 (height target 2160)
        (target_w as f64 / w as f64).min(target_h as f64 / h as f64)
    } else {
        // Landscape spread: fit within 2160 x 1620
        (target_h as f64 / w as f64).min(target_w as f64 / h as f64)
    };

    let new_w = (w as f64 * scale).round().max(1.0) as u32;
    let new_h = (h as f64 * scale).round().max(1.0) as u32;
    (new_w, new_h)
}

/// Scales image proportionally to Option A screen geometry using SIMD Lanczos3.
pub fn scale_to_rmpp_geometry(img: &RgbImage, target_w: u32, target_h: u32) -> RgbImage {
    let (w, h) = img.dimensions();
    let (new_w, new_h) = compute_target_geometry(w, h, target_w, target_h);

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

/// Processes raw RGB image bytes and writes the enhanced JPEG directly to `dst_path`.
pub fn process_and_encode_to_file<P: AsRef<Path>>(
    w: u32,
    h: u32,
    rgb_bytes: &[u8],
    dst_path: P,
    config: &ProcessConfig,
    cached_default_lut: &Lut3D,
) -> Result<(), String> {
    if (w * h * 3) as usize != rgb_bytes.len() {
        return Err(format!(
            "Buffer size mismatch: expected {} bytes ({}x{}x3), got {}",
            w * h * 3,
            w,
            h,
            rgb_bytes.len()
        ));
    }

    let raw_img = RgbImage::from_raw(w, h, rgb_bytes.to_vec())
        .ok_or_else(|| "Failed to create RgbImage from buffer".to_string())?;

    // 1. Scale to Option A Geometry
    let mut scaled = scale_to_rmpp_geometry(&raw_img, config.target_width, config.target_height);

    // 2. 3D LUT Color Calibration
    if config.color_correction {
        let custom_lut;
        let lut_ref = if let Some(path) = config.custom_lut_path {
            custom_lut = Lut3D::from_file(path)?;
            &custom_lut
        } else {
            cached_default_lut
        };

        for pixel in scaled.pixels_mut() {
            let (r, g, b) = lut_ref.transform_rgb(pixel[0], pixel[1], pixel[2]);
            pixel[0] = r;
            pixel[1] = g;
            pixel[2] = b;
        }
    }

    // 3. Bilateral Edge Inking Filter
    if config.edge_inking {
        apply_edge_directed_inking(&mut scaled);
    }

    // 4. Encode to JPEG with 229 DPI header
    let (final_w, final_h) = scaled.dimensions();
    let out_file = File::create(dst_path.as_ref())
        .map_err(|e| format!("Failed to create destination file: {}", e))?;
    let writer = BufWriter::new(out_file);

    let mut encoder = Encoder::new(writer, config.quality);
    encoder.set_density(Density::Inch {
        x: config.dpi,
        y: config.dpi,
    });

    let sampling = if config.subsampling == 2 {
        SamplingFactor::R_4_2_0
    } else {
        SamplingFactor::R_4_4_4
    };
    encoder.set_sampling_factor(sampling);

    encoder
        .encode(
            scaled.as_raw(),
            final_w as u16,
            final_h as u16,
            ColorType::Rgb,
        )
        .map_err(|e| format!("JPEG encoding failed: {}", e))?;

    Ok(())
}
