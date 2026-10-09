use crate::hal;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Status {
    Idle,
    Busy,
    Done,
    Err,
}

#[derive(Debug)]
pub struct DmaError(pub i32);

#[derive(Debug, Default, Clone, Copy)]
pub struct Desc {
    pub src: u32,
    pub dst: u32,
    pub len: u16,
    pub flags: u8,
}

pub type Callback = fn(&Desc, i32);

pub struct DmaChan {
    pub base: usize,
    pub desc: Desc,
    pub cb: Option<Callback>,
    pub busy: bool,
}

static mut G_DMA_ACTIVE: u32 = 0;

impl DmaChan {
    pub fn new(base: usize) -> Self {
        DmaChan { base, desc: Desc::default(), cb: None, busy: false }
    }

    pub fn set_callback(&mut self, cb: Callback) {
        self.cb = Some(cb);
    }
}

fn prog_desc(ch: &mut DmaChan, buf: &[u8]) -> usize {
    ch.desc.src = buf.as_ptr() as u32;
    ch.desc.len = buf.len() as u16;
    hal::write32(ch.base, ch.desc.src);
    hal::write32(ch.base + 4, ch.desc.len as u32);
    buf.len()
}

pub fn dma_start(ch: &mut DmaChan, buf: &[u8]) -> Result<usize, DmaError> {
    if buf.is_empty() {
        return Err(DmaError(-1));
    }
    let n = prog_desc(ch, buf);
    unsafe { G_DMA_ACTIVE += 1 };
    ch.busy = true;
    hal::write32(ch.base + 8, 1);
    if let Some(cb) = ch.cb {
        cb(&ch.desc, n as i32);
    }
    Ok(n)
}

pub fn dma_poll(ch: &mut DmaChan) -> Status {
    let s = hal::read32(ch.base + 12);
    if s & 1 != 0 {
        ch.busy = false;
        unsafe { G_DMA_ACTIVE -= 1 };
        return Status::Done;
    }
    Status::Busy
}
