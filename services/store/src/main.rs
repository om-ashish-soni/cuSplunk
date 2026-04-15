use std::net::SocketAddr;
use std::sync::Arc;

use tonic::transport::Server;
use tracing::info;

use cusplunk_store::{
    config::Config,
    proto::store_server::StoreServer,
    retention::RetentionEngine,
    server::StoreService,
};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info")),
        )
        .init();

    let config_path = std::env::args()
        .skip_while(|a| a != "--config")
        .nth(1)
        .unwrap_or_else(|| "config.yaml".to_string());

    let config = Config::from_file(&config_path).unwrap_or_else(|e| {
        tracing::warn!(error = %e, path = %config_path, "Using default config");
        Config::default()
    });

    let addr: SocketAddr = config.grpc_addr().parse()?;
    let service = StoreService::new(config.clone())?;

    // Spawn the retention engine as a background task.
    let retention = RetentionEngine::new(
        service.warm_tier(),
        service.catalog(),
        config.retention.clone(),
    );
    tokio::spawn(async move {
        retention.run_loop().await;
    });

    info!(addr = %addr, "cuSplunk Store gRPC server starting");

    Server::builder()
        .add_service(StoreServer::new(service))
        .serve(addr)
        .await?;

    Ok(())
}
