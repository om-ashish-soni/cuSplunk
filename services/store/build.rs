fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Point prost-build at the vendored protoc binary so the build works
    // without a system protoc installation.
    let protoc = protoc_bin_vendored::protoc_bin_path()?;
    std::env::set_var("PROTOC", &protoc);

    // Compile the shared store.proto into Rust code (prost + tonic).
    // The generated code lands in $OUT_DIR/store.rs and is included via
    // the proto module.
    tonic_build::configure()
        .build_server(true)
        .build_client(true)
        // Emit serde derives so proto types can be serialized in tests.
        .type_attribute(".", "#[derive(serde::Serialize, serde::Deserialize)]")
        .compile(
            &["../../libs/proto/store.proto"],
            &["../../libs/proto"],
        )?;

    Ok(())
}
