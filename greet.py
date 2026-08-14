#!/usr/bin/env python3
import sys


def main() -> None:
    if len(sys.argv) > 1:
        name = sys.argv[1]
    else:
        name = "World"
    print(f"Hello, {name}!")


if __name__ == "__main__":
    main()
