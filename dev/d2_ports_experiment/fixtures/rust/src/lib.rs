pub fn produce(seed: u32, enabled: bool) -> (u32, bool) {
    (seed, enabled)
}

pub fn transform(sample: u32, valid: bool) -> (u32, bool) {
    (sample.saturating_add(1), valid)
}

pub fn consume(sample: u32, valid: bool) -> (u32, bool) {
    (if valid { sample } else { 0 }, valid)
}

pub fn run(seed: u32, enabled: bool) -> (u32, bool) {
    let (sample, valid) = produce(seed, enabled);
    let (sample, valid) = transform(sample, valid);
    let (sample, valid) = transform(sample, valid);
    consume(sample, valid)
}

#[cfg(test)]
mod tests {
    #[test]
    fn pipeline_processes_enabled_sample() {
        assert_eq!(super::run(7, true), (9, true));
    }

    #[test]
    fn disabled_sample_is_zero() {
        assert_eq!(super::run(7, false), (0, false));
    }
}
