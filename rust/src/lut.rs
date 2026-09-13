//! 3D LUT parser and evaluation matching Pillow's Color3DLUT.

use image::RgbImage;
use rayon::prelude::*;
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::Path;

const DEFAULT_CUBE_STR: &str =
    include_str!("../../src/rmpp_enhancer/profiles/rmpp_canvas_color.cube");

const PRECISION_BITS: u32 = 6;
const SCALE_BITS: u32 = 18;
const SHIFT_BITS: u32 = 15;
const SCALE_MASK: u32 = (1 << SCALE_BITS) - 1;
const PRECISION_ROUNDING: i32 = 1 << (PRECISION_BITS - 1);

#[derive(Clone, Debug)]
pub struct Lut3D {
    pub size: usize,
    pub table: Vec<i32>,
    scale: u32,
}

impl Lut3D {
    pub fn default_lut() -> Self {
        Self::from_cube_str(DEFAULT_CUBE_STR).expect("Failed to parse embedded default LUT")
    }

    pub fn from_file<P: AsRef<Path>>(path: P) -> Result<Self, String> {
        let file = File::open(path.as_ref())
            .map_err(|e| format!("Failed to open LUT file {}: {}", path.as_ref().display(), e))?;
        let reader = BufReader::new(file);
        Self::from_reader(reader)
    }

    pub fn from_cube_str(s: &str) -> Result<Self, String> {
        Self::from_reader(s.as_bytes())
    }

    pub fn from_reader<R: BufRead>(reader: R) -> Result<Self, String> {
        let mut size = 33usize;
        let mut raw_table: Vec<f32> = Vec::new();

        for line_res in reader.lines() {
            let line = line_res.map_err(|e| format!("Error reading line: {}", e))?;
            let trimmed = line.trim();
            if trimmed.is_empty() || trimmed.starts_with('#') {
                continue;
            }
            if trimmed.starts_with("LUT_3D_SIZE") {
                let parts: Vec<&str> = trimmed.split_whitespace().collect();
                if parts.len() >= 2 {
                    size = parts[1]
                        .parse::<usize>()
                        .map_err(|e| format!("Invalid LUT_3D_SIZE: {}", e))?;
                }
                continue;
            }
            if trimmed.starts_with("TITLE") || trimmed.starts_with("DOMAIN") {
                continue;
            }
            let nums: Vec<f32> = trimmed
                .split_whitespace()
                .filter_map(|s| s.parse::<f32>().ok())
                .collect();
            if nums.len() == 3 {
                raw_table.extend_from_slice(&nums);
            }
        }

        let expected_len = size * size * size * 3;
        if raw_table.len() != expected_len {
            return Err(format!(
                "Invalid LUT table size: expected {} values, got {}",
                expected_len,
                raw_table.len()
            ));
        }

        let scale = ((size - 1) as f32 / 255.0 * ((1 << SCALE_BITS) as f32)) as u32;

        let mut prep_table = Vec::with_capacity(expected_len);
        let factor = (255 << PRECISION_BITS) as f32;
        for &item in &raw_table {
            let val = item * factor;
            let prep = if val >= 0.0 {
                (val + 0.5) as i32
            } else {
                (val - 0.5) as i32
            };
            prep_table.push(prep);
        }

        Ok(Self {
            size,
            table: prep_table,
            scale,
        })
    }

    #[inline(always)]
    pub fn transform_pixel(&self, r: u8, g: u8, b: u8) -> [u8; 3] {
        let idx1 = (r as u32) * self.scale;
        let idx2 = (g as u32) * self.scale;
        let idx3 = (b as u32) * self.scale;

        let s1 = ((SCALE_MASK & idx1) >> (SCALE_BITS - SHIFT_BITS)) as i32;
        let s2 = ((SCALE_MASK & idx2) >> (SCALE_BITS - SHIFT_BITS)) as i32;
        let s3 = ((SCALE_MASK & idx3) >> (SCALE_BITS - SHIFT_BITS)) as i32;

        let i1 = (idx1 >> SCALE_BITS) as usize;
        let i2 = (idx2 >> SCALE_BITS) as usize;
        let i3 = (idx3 >> SCALE_BITS) as usize;

        let size = self.size;
        let base_idx = 3 * (i1 + i2 * size + i3 * size * size);
        let inv_s1 = (1 << SHIFT_BITS) - s1;
        let inv_s2 = (1 << SHIFT_BITS) - s2;
        let inv_s3 = (1 << SHIFT_BITS) - s3;

        let interp3 = |a_off: usize, b_off: usize| -> [i32; 3] {
            [
                (self.table[a_off] * inv_s1 + self.table[b_off] * s1) >> SHIFT_BITS,
                (self.table[a_off + 1] * inv_s1 + self.table[b_off + 1] * s1) >> SHIFT_BITS,
                (self.table[a_off + 2] * inv_s1 + self.table[b_off + 2] * s1) >> SHIFT_BITS,
            ]
        };

        let interp_vec2 = |a: [i32; 3], b: [i32; 3]| -> [i32; 3] {
            [
                (a[0] * inv_s2 + b[0] * s2) >> SHIFT_BITS,
                (a[1] * inv_s2 + b[1] * s2) >> SHIFT_BITS,
                (a[2] * inv_s2 + b[2] * s2) >> SHIFT_BITS,
            ]
        };

        let interp_vec3 = |a: [i32; 3], b: [i32; 3]| -> [i32; 3] {
            [
                (a[0] * inv_s3 + b[0] * s3) >> SHIFT_BITS,
                (a[1] * inv_s3 + b[1] * s3) >> SHIFT_BITS,
                (a[2] * inv_s3 + b[2] * s3) >> SHIFT_BITS,
            ]
        };

        let ll = interp3(base_idx, base_idx + 3);
        let lr = interp3(base_idx + size * 3, base_idx + size * 3 + 3);
        let l = interp_vec2(ll, lr);

        let rl = interp3(base_idx + size * size * 3, base_idx + size * size * 3 + 3);
        let rr = interp3(
            base_idx + size * size * 3 + size * 3,
            base_idx + size * size * 3 + size * 3 + 3,
        );
        let r = interp_vec2(rl, rr);

        let res = interp_vec3(l, r);

        [
            (((res[0] + PRECISION_ROUNDING) >> PRECISION_BITS).clamp(0, 255)) as u8,
            (((res[1] + PRECISION_ROUNDING) >> PRECISION_BITS).clamp(0, 255)) as u8,
            (((res[2] + PRECISION_ROUNDING) >> PRECISION_BITS).clamp(0, 255)) as u8,
        ]
    }

    pub fn apply(&self, img: &mut RgbImage) {
        let raw = img.as_mut();
        raw.par_chunks_exact_mut(3).for_each(|pixel| {
            let out = self.transform_pixel(pixel[0], pixel[1], pixel[2]);
            pixel[0] = out[0];
            pixel[1] = out[1];
            pixel[2] = out[2];
        });
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_load_default_lut() {
        let lut = Lut3D::default_lut();
        assert_eq!(lut.size, 33);
        assert_eq!(lut.table.len(), 33 * 33 * 33 * 3);

        // Test known points verified against Pillow
        assert_eq!(lut.transform_pixel(0, 0, 0), [0, 0, 0]);
        assert_eq!(lut.transform_pixel(255, 255, 255), [255, 255, 255]);
        assert_eq!(lut.transform_pixel(64, 128, 192), [0, 162, 225]);
        assert_eq!(lut.transform_pixel(200, 50, 10), [249, 50, 0]);
        assert_eq!(lut.transform_pixel(128, 128, 128), [151, 151, 151]);
        assert_eq!(lut.transform_pixel(42, 87, 199), [0, 122, 254]);
    }
}
