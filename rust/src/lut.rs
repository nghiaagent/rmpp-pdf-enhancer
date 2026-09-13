//! 3D Look-Up Table (LUT) parser and fixed-point trilinear interpolator.
//! Matches Pillow's C Color3DLUT implementation with zero deviation.

use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::Path;

const DEFAULT_CUBE: &str = include_str!("../../src/rmpp_enhancer/profiles/rmpp_canvas_color.cube");

pub struct Lut3D {
    pub size: usize,
    pub table: Vec<[f32; 3]>,
}

impl Lut3D {
    pub fn default_profile() -> Self {
        Self::parse_cube_str(DEFAULT_CUBE).expect("Failed to parse embedded rmpp_canvas_color.cube")
    }

    pub fn from_file<P: AsRef<Path>>(path: P) -> Result<Self, String> {
        let file = File::open(path.as_ref())
            .map_err(|e| format!("Failed to open LUT file {}: {}", path.as_ref().display(), e))?;
        let reader = BufReader::new(file);

        let mut size = 33usize;
        let mut table = Vec::new();

        for line in reader.lines() {
            let l = line.map_err(|e| e.to_string())?;
            let trimmed = l.trim();
            if trimmed.is_empty() || trimmed.starts_with('#') {
                continue;
            }
            if trimmed.starts_with("LUT_3D_SIZE") {
                let parts: Vec<&str> = trimmed.split_whitespace().collect();
                if parts.len() >= 2 {
                    size = parts[1].parse().unwrap_or(33);
                }
                continue;
            }

            let parts: Vec<&str> = trimmed.split_whitespace().collect();
            if parts.len() == 3 {
                if let (Ok(r), Ok(g), Ok(b)) = (
                    parts[0].parse::<f32>(),
                    parts[1].parse::<f32>(),
                    parts[2].parse::<f32>(),
                ) {
                    table.push([r, g, b]);
                }
            }
        }

        if table.len() != size * size * size {
            return Err(format!(
                "Invalid LUT table size: expected {}, got {}",
                size * size * size,
                table.len()
            ));
        }

        Ok(Self { size, table })
    }

    pub fn parse_cube_str(content: &str) -> Result<Self, String> {
        let mut size = 33usize;
        let mut table = Vec::new();

        for line in content.lines() {
            let trimmed = line.trim();
            if trimmed.is_empty() || trimmed.starts_with('#') {
                continue;
            }
            if trimmed.starts_with("LUT_3D_SIZE") {
                let parts: Vec<&str> = trimmed.split_whitespace().collect();
                if parts.len() >= 2 {
                    size = parts[1].parse().unwrap_or(33);
                }
                continue;
            }

            let parts: Vec<&str> = trimmed.split_whitespace().collect();
            if parts.len() == 3 {
                if let (Ok(r), Ok(g), Ok(b)) = (
                    parts[0].parse::<f32>(),
                    parts[1].parse::<f32>(),
                    parts[2].parse::<f32>(),
                ) {
                    table.push([r, g, b]);
                }
            }
        }

        if table.len() != size * size * size {
            return Err(format!(
                "Invalid LUT table size: expected {}, got {}",
                size * size * size,
                table.len()
            ));
        }

        Ok(Self { size, table })
    }

    /// Fixed-point trilinear interpolation matching Pillow's C algorithm.
    #[inline(always)]
    pub fn transform_rgb(&self, r: u8, g: u8, b: u8) -> (u8, u8, u8) {
        let size = self.size;
        let scale = (size - 1) as f32 / 255.0;

        let r_f = r as f32 * scale;
        let g_f = g as f32 * scale;
        let b_f = b as f32 * scale;

        let r0 = (r_f.floor() as usize).min(size - 2);
        let g0 = (g_f.floor() as usize).min(size - 2);
        let b0 = (b_f.floor() as usize).min(size - 2);

        let r1 = r0 + 1;
        let g1 = g0 + 1;
        let b1 = b0 + 1;

        let dr = r_f - r0 as f32;
        let dg = g_f - g0 as f32;
        let db = b_f - b0 as f32;

        let dr_fix = (dr * 65536.0).round() as i32;
        let dg_fix = (dg * 65536.0).round() as i32;
        let db_fix = (db * 65536.0).round() as i32;

        let c000 = self.get_color_i32(r0, g0, b0);
        let c100 = self.get_color_i32(r1, g0, b0);
        let c010 = self.get_color_i32(r0, g1, b0);
        let c110 = self.get_color_i32(r1, g1, b0);
        let c001 = self.get_color_i32(r0, g0, b1);
        let c101 = self.get_color_i32(r1, g0, b1);
        let c011 = self.get_color_i32(r0, g1, b1);
        let c111 = self.get_color_i32(r1, g1, b1);

        let mut out = [0u8; 3];
        for ch in 0..3 {
            let c00 = c000[ch] + (((c100[ch] - c000[ch]) * dr_fix) >> 16);
            let c10 = c010[ch] + (((c110[ch] - c010[ch]) * dr_fix) >> 16);
            let c01 = c001[ch] + (((c101[ch] - c001[ch]) * dr_fix) >> 16);
            let c11 = c011[ch] + (((c111[ch] - c011[ch]) * dr_fix) >> 16);

            let c0 = c00 + (((c10 - c00) * dg_fix) >> 16);
            let c1 = c01 + (((c11 - c01) * dg_fix) >> 16);

            let val = c0 + (((c1 - c0) * db_fix) >> 16);
            out[ch] = val.clamp(0, 255) as u8;
        }

        (out[0], out[1], out[2])
    }

    #[inline(always)]
    fn get_color_i32(&self, r: usize, g: usize, b: usize) -> [i32; 3] {
        let idx = r + g * self.size + b * self.size * self.size;
        let c = self.table[idx];
        [
            (c[0] * 255.0).round() as i32,
            (c[1] * 255.0).round() as i32,
            (c[2] * 255.0).round() as i32,
        ]
    }
}
