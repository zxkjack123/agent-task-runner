#!/usr/bin/env python3
"""BOUT++ → GITR coupling driver.

Converts BOUT++ plasma dump NetCDF files into GITR particle source
NetCDF files suitable for impurity transport simulations.

Examples
--------
    python coupling/run_bout_to_gitr.py --bout-dump plasma_dump.nc --n-particles 10000
    python coupling/run_bout_to_gitr.py --bout-dump plasma_dump.nc --output my_source.nc --seed 42
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np

_BOUT_GITR_ADAPTER = Path(__file__).resolve().parent.parent / "adapters" / "bout_to_gitr.py"
if str(_BOUT_GITR_ADAPTER.parent) not in sys.path:
    sys.path.insert(0, str(_BOUT_GITR_ADAPTER.parent))


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Convert a BOUT++ dump file into a GITR particle source NetCDF file.",
    )
    p.add_argument(
        "--bout-dump",
        type=Path,
        required=True,
        metavar="PATH",
        help="Path to the BOUT++ dump NetCDF file.",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=Path("particle_source.nc"),
        metavar="PATH",
        help="Output path for the GITR particle source file (default: particle_source.nc).",
    )
    p.add_argument(
        "--n-particles",
        type=int,
        default=10000,
        metavar="N",
        help="Number of Monte Carlo particles to sample (default: 10000).",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=None,
        metavar="INT",
        help="Random seed for reproducible particle sampling.",
    )
    p.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging.",
    )
    return p


def main(argv: list[str] | None = None) -> None:
    from bout_to_gitr import BoutToGitrAdapter

    args = _build_parser().parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger("run_bout_to_gitr")

    if not args.bout_dump.exists():
        logger.error("BOUT++ dump file not found: %s", args.bout_dump)
        sys.exit(1)

    rng = np.random.default_rng(args.seed) if args.seed is not None else np.random.default_rng()

    logger.info("Loading BOUT++ dump from %s", args.bout_dump)
    adapter = BoutToGitrAdapter(args.bout_dump)
    adapter.load_bout_dump()

    logger.info("Sampling %d particles", args.n_particles)
    particles = adapter.generate_particle_source(args.n_particles, rng=rng)

    logger.info("Writing particle source to %s", args.output)
    out_path = adapter.write_netcdf(particles, args.output)

    logger.info("Done — written %s (%d particles)", out_path, args.n_particles)


if __name__ == "__main__":
    main()
