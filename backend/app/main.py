from fastapi import FastAPI

app = FastAPI(title="Expense Sharing API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
