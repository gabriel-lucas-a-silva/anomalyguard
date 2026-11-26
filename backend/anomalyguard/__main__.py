import uvicorn

uvicorn.run("anomalyguard.main:build_app", factory=True, host="0.0.0.0", port=8000, log_level="info")
