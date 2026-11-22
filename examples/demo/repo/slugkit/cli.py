import argparse

from slugkit.slug import slugify, truncate


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="slugkit")
    parser.add_argument("text")
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    if args.verbose:
        print(f"input: {args.text!r}")
    print(slugify(truncate(args.text, args.limit)))
