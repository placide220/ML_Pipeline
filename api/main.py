"""Run:  uvicorn api.main:app --reload --port 8000   ->  docs at http://localhost:8000/docs"""
from fastapi import FastAPI
from .routers import sql_readings, mongo_readings

app = FastAPI(
    title="Household Power Time-Series API",
    description="CRUD and time-series endpoints over the same dataset stored in MySQL and MongoDB.",
    version="1.0.0",
)
app.include_router(sql_readings.router)
app.include_router(mongo_readings.router)


@app.get("/", tags=["Health"])
def health():
    return {"status": "ok", "endpoints": ["/sql/readings", "/mongo/readings"], "docs": "/docs"}
