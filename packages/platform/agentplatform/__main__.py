"""Entry point: python -m agentplatform."""

import uvicorn

from agentplatform.server import create_app


def main() -> None:
    app = create_app()
    uvicorn.run(app, host="0.0.0.0", port=8420)


if __name__ == "__main__":
    main()
