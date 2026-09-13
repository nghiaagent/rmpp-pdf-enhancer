//! Native PyO3 acceleration module for rmpp-pdf-enhancer.
//! Accelerates scaling, 3D LUT interpolation, inking, and JPEG encoding with zero GIL contention.

#![allow(clippy::useless_conversion)]

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use std::sync::OnceLock;

mod inking;
mod lut;
mod pipeline;

use lut::Lut3D;
use pipeline::{process_and_encode_to_file, ProcessConfig};

static DEFAULT_LUT: OnceLock<Lut3D> = OnceLock::new();

fn get_default_lut() -> &'static Lut3D {
    DEFAULT_LUT.get_or_init(Lut3D::default_profile)
}

/// Enhances a single page given raw RGB bytes, writes the resulting JPEG to `dst_path`.
/// Releases Python GIL during execution for full multi-core concurrency.
#[pyfunction]
#[allow(clippy::too_many_arguments, clippy::useless_conversion)]
#[pyo3(signature = (
    w,
    h,
    rgb_bytes,
    dst_path,
    quality = 82,
    subsampling = 0,
    color_correction = true,
    edge_inking = true,
    custom_lut_path = None,
    target_width = 1620,
    target_height = 2160,
    dpi = 229
))]
fn enhance_page_to_jpeg(
    py: Python<'_>,
    w: u32,
    h: u32,
    rgb_bytes: &[u8],
    dst_path: &str,
    quality: u8,
    subsampling: u8,
    color_correction: bool,
    edge_inking: bool,
    custom_lut_path: Option<&str>,
    target_width: u32,
    target_height: u32,
    dpi: u16,
) -> PyResult<()> {
    let config = ProcessConfig {
        quality,
        subsampling,
        color_correction,
        edge_inking,
        custom_lut_path,
        target_width,
        target_height,
        dpi,
    };

    let default_lut = get_default_lut();

    // Release GIL for the entire duration of resizing, LUT, inking, and JPEG encoding
    py.allow_threads(|| process_and_encode_to_file(w, h, rgb_bytes, dst_path, &config, default_lut))
        .map_err(PyValueError::new_err)
}

/// Returns True indicating the native compiled accelerator is active.
#[pyfunction]
fn is_available() -> bool {
    true
}

#[pymodule]
fn _accelerator(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(enhance_page_to_jpeg, m)?)?;
    m.add_function(wrap_pyfunction!(is_available, m)?)?;
    Ok(())
}
