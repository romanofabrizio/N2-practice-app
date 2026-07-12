from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from n2_generator import router as n2_router

app = FastAPI(title="N2 Question Generator")

app.include_router(n2_router)

app.add_middleware(
    CORSMiddleware,
    # Replace YOURNAME with your GitHub username (https, no trailing slash, no repo path)
    allow_origins=["https://romanofabrizio.github.io"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {"status": "ok", "docs": "/docs"}
