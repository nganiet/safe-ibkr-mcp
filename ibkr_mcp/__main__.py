"""Console entrypoint: `ibkr-mcp` / `python -m ibkr_mcp`."""

from ibkr_mcp.core.connection import IBKRConnection
from ibkr_mcp.mcp.config import Config
from ibkr_mcp.mcp.server import build_server


def main() -> None:
    config = Config.from_env()
    conn = IBKRConnection(
        config.host, config.port, config.client_id, readonly=config.read_only
    )
    app = build_server(conn)
    try:
        app.run()  # stdio transport by default
    finally:
        conn.disconnect()


if __name__ == "__main__":
    main()
