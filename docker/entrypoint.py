#!/venv/bin/python
"""Shared container entrypoint (pipeline + viz services, issues #13/#28/#34).

The runtime images are distroless — no shell, no pip — so this Python script
is the behavior-identical twin of the old `docker/entrypoint.sh`:

- the CLI reads `DATABASE_URL` from its environment (`etl/config.py`); the viz
  app reads `VIZ_DATABASE_URL` (`viz/data.py`).  On a seeded stack those
  settings live in the detached data volume (`/app/data/docker.env`), not baked
  into the images or compose config.
- when `DATA_ENV_FILE` is set, that file exists, and neither URL is already
  supplied (an operator-supplied URL always wins — and suppresses the file
  entirely, exactly like the shell's `[ -z "$DATABASE_URL" ] && [ -z
  "$VIZ_DATABASE_URL" ]` test), the file is loaded via python-dotenv.
- then the container command (`CMD` / the compose `command`) is `execvp`'d as
  PID 1, so `docker stop`'s SIGINT reaches the real process.

No pipeline or app code changes are made.
"""

import os
import sys


def _both_urls_unset() -> bool:
    return not os.environ.get("DATABASE_URL") and not os.environ.get("VIZ_DATABASE_URL")


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv if argv is None else argv)
    if len(argv) < 2:
        sys.exit("etl-entrypoint: no container command given (empty CMD)")
    command = argv[1:]

    data_env_file = os.environ.get("DATA_ENV_FILE")
    if _both_urls_unset() and data_env_file and os.path.isfile(data_env_file):
        from dotenv import load_dotenv

        load_dotenv(data_env_file)

    os.execvp(command[0], command)


if __name__ == "__main__":
    main()