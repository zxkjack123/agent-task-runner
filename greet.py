#!/usr/bin/env python3
import sys


def main() -> None:
    try:
        name = sys.argv[1]
    except IndexError:
        name = "World"
    print(f"Hello, {name}!")


if __name__ == "__main__":
    main()
