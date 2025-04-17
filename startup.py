import uvicorn

from server.api import app
from configs import API_SERVER


if __name__ == "__main__":
    host = API_SERVER["host"]
    port = API_SERVER["port"]

    uvicorn.run(app, host=host, port=port, loop="asyncio")