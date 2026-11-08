fn main() {
    // Expose the target triple so the packaged sidecar name matches Tauri's
    // externalBin convention on every platform (e.g. aarch64-apple-darwin,
    // x86_64-unknown-linux-gnu).
    println!(
        "cargo:rustc-env=STEM_STUDIO_TARGET_TRIPLE={}",
        std::env::var("TARGET").expect("Cargo always sets TARGET for build scripts")
    );
    tauri_build::build()
}
