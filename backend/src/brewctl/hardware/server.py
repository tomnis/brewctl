from fastapi import FastAPI

app = FastAPI(title="BrewCTL Hardware API")

@app.get("/")
async def root():
    return {"message": "Hello World from BrewCTL Hardware"}

@app.get("/health")
async def health():
    return {"status": "healthy", "mode": "hardware"}
