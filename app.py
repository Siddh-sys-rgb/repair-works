"""Run the workshop on loopback; store local data independently of source code."""

import argparse
from pathlib import Path

from workshop import create_app


def main():
    parser = argparse.ArgumentParser(description="Repair Works — local Flask workshop demo")
    parser.add_argument("--port", type=int, default=8107)
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parent / "instance")
    parser.add_argument("--no-demo", action="store_true", help="Start without fictional seed tickets")
    arguments = parser.parse_args()
    if not 1 <= arguments.port <= 65535:
        parser.error("Port must be between 1 and 65535.")
    app = create_app({"DATA_DIR": arguments.data_dir, "SEED_DEMO": not arguments.no_demo})
    app.run(host="127.0.0.1", port=arguments.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
