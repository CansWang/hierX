//! Fixture crate for the LSP frontend (rust-analyzer).
pub mod dma;
pub mod hal;

use dma::{DmaChan, Desc};

/// Entry point used by the tests.
pub fn app_run(data: &[u8], n: usize) -> Result<usize, dma::DmaError> {
    let mut ch = DmaChan::new(0x4000_0000);
    ch.set_callback(on_done);
    let rc = dma::dma_start(&mut ch, &data[..n.min(data.len())])?;
    while dma::dma_poll(&mut ch) == dma::Status::Busy {}
    Ok(rc)
}

fn on_done(_ctx: &Desc, status: i32) {
    let _ = status;
}
