"""Uso: uv run python -m bfa  (sobe o BFA em http://127.0.0.1:8000)"""
import logging

import uvicorn

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    uvicorn.run("bfa.api:app", host="127.0.0.1", port=8000)
