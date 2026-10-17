pub struct Item(pub usize);
pub trait Convert<T> { fn convert(&self, value: T) -> usize; }
impl Convert<&str> for Item {
    fn convert(&self, value: &str) -> usize { self.0 + value.len() }
}
impl Convert<String> for Item {
    fn convert(&self, value: String) -> usize { self.0 + value.len() }
}
impl Item {
    pub fn new(value: usize) -> Self { Self(value) }
    pub fn apply(&self, value: usize, f: impl Fn(usize, usize) -> usize) -> usize { f(self.0, value) }
}
pub fn entry() -> usize {
    /* outer /* nested */ still comment */
    let item = Item::new(2);
    item.apply(3, move |a, b| { a + b })
}
macro_rules! generated {
    ($name:ident) => { pub struct $name; impl $name { pub fn next() -> usize { 1 } } };
}
generated!(Generated);
pub fn macro_entry() -> usize { Generated::next() }
