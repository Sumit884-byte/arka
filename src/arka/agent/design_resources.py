"""Default design-resource reference used by Arka's design workflows."""
from __future__ import annotations

import argparse

RESOURCE_URL = "https://github.com/bradtraversy/design-resources-for-developers"
LICENSE_NOTE = "The catalog is reported as MIT-licensed; linked resources may have separate licenses."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka design-resources")
    parser.add_argument("command", choices=("show", "prompt"), nargs="?", default="show")
    args = parser.parse_args(argv)
    if args.command == "prompt":
        print(f"Use {RESOURCE_URL} as a discovery catalog; verify individual licenses before use.")
    else:
        print(f"catalog\t{RESOURCE_URL}\nlicense\t{LICENSE_NOTE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
