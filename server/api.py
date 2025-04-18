import uvicorn

from server.start import start, fake_start

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def create_app():
    app = FastAPI(
        title="API Server",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=['*'],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # app.get("/start")(start)

    app.get("/start")(fake_start)

    return app

app = create_app()