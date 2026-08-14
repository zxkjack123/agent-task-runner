"""BOUT++ to GITR adapter — converts BOUT++ dump data into GITR particle source format."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from numpy.typing import NDArray

logger = logging.getLogger(__name__)


class BoutToGitrAdapter:
    """Converts BOUT++ field dump data to a GITR-compatible particle source.

    Reads BOUT++ NetCDF dumps (density, temperature, flow velocity) and
    generates Monte Carlo particle source data with positions, energies,
    and velocity direction angles written to a NetCDF file consumable
    by the GITR impurity transport code.
    """

    def __init__(self, bout_dump_path: str | Path) -> None:
        self._bout_path = Path(bout_dump_path)
        self._density: NDArray[np.floating] | None = None
        self._temperature: NDArray[np.floating] | None = None
        self._velocity_x: NDArray[np.floating] | None = None
        self._velocity_y: NDArray[np.floating] | None = None
        self._velocity_z: NDArray[np.floating] | None = None
        self._mesh_x: NDArray[np.floating] | None = None
        self._mesh_y: NDArray[np.floating] | None = None
        self._mesh_z: NDArray[np.floating] | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_bout_dump(self) -> None:
        """Read plasma field variables from the BOUT++ dump NetCDF file.

        Expected variables: n (density), T (temperature), vx/vy/vz (flow),
        and optional coordinate arrays (mx, my, mz).
        """
        try:
            import netCDF4
        except ImportError:
            logger.warning("netCDF4 not available — using synthetic data for testing")
            self._load_synthetic()
            return

        if not self._bout_path.exists():
            logger.warning("BOUT++ dump not found at %s — using synthetic data", self._bout_path)
            self._load_synthetic()
            return

        with netCDF4.Dataset(str(self._bout_path), "r") as ds:
            self._density = np.asarray(ds.variables["n"][:], dtype=np.float64)
            self._temperature = np.asarray(ds.variables["T"][:], dtype=np.float64)
            self._velocity_x = np.asarray(ds.variables.get("vx", ds.variables["n"]), dtype=np.float64)
            self._velocity_y = np.asarray(ds.variables.get("vy", ds.variables["n"]), dtype=np.float64)
            self._velocity_z = np.asarray(ds.variables.get("vz", ds.variables["n"]), dtype=np.float64)
            self._mesh_x = self._read_1d_coord(ds, "mx", self._density.shape[0])
            self._mesh_y = self._read_1d_coord(ds, "my", self._density.shape[1])
            self._mesh_z = self._read_1d_coord(ds, "mz", self._density.shape[2] if self._density.ndim > 2 else 1)

    def generate_particle_source(self, n_particles: int, rng: np.random.Generator | None = None) -> dict[str, NDArray[np.floating]]:
        """Sample *n_particles* from the loaded plasma fields.

        Returns a dict with keys: x, y, z, vx, vy, vz, energy_eV, pitch_angle.
        """
        if self._density is None:
            self.load_bout_dump()
        rng = rng or np.random.default_rng()

        assert self._density is not None
        assert self._temperature is not None

        flat_density = self._density.ravel().astype(np.float64)
        flat_density /= flat_density.sum()
        indices = rng.choice(flat_density.size, size=n_particles, p=flat_density)

        if self._density.ndim == 3:
            iz, iy, ix = np.unravel_index(indices, self._density.shape)
        elif self._density.ndim == 2:
            iz = np.zeros(n_particles, dtype=np.int64)
            iy, ix = np.unravel_index(indices, self._density.shape)
        else:
            iz = np.zeros(n_particles, dtype=np.int64)
            iy = np.zeros(n_particles, dtype=np.int64)
            ix = indices

        x = self._grid_coord(ix, 0)
        y = self._grid_coord(iy, 1)
        z = self._grid_coord(iz, 2)

        temperatures = self._temperature.flat[indices]
        energy_eV = temperatures * 1.5 * 8.617333262145e-5

        vx = self._sampled_velocity(iy, ix, iz, 0)
        vy = self._sampled_velocity(iy, ix, iz, 1)
        vz = self._sampled_velocity(iy, ix, iz, 2)

        speed = np.sqrt(np.asarray(vx, dtype=np.float64) ** 2
                        + np.asarray(vy, dtype=np.float64) ** 2
                        + np.asarray(vz, dtype=np.float64) ** 2)
        speed = np.where(speed == 0, 1.0, speed)
        pitch_angle = np.degrees(np.arccos(np.asarray(vz, dtype=np.float64) / speed))

        return {
            "x": np.asarray(x, dtype=np.float64),
            "y": np.asarray(y, dtype=np.float64),
            "z": np.asarray(z, dtype=np.float64),
            "vx": np.asarray(vx, dtype=np.float64),
            "vy": np.asarray(vy, dtype=np.float64),
            "vz": np.asarray(vz, dtype=np.float64),
            "energy_eV": np.asarray(energy_eV, dtype=np.float64),
            "pitch_angle": np.asarray(pitch_angle, dtype=np.float64),
        }

    def write_netcdf(self, particles: dict[str, NDArray[np.floating]], output_path: str | Path) -> Path:
        """Write particle source data to a GITR-compatible NetCDF file.

        Creates ``particle_source.nc`` with dimensions ``nP`` (number of
        particles) and variables: x, y, z, vx, vy, vz, energy_eV,
        pitch_angle.
        """
        import netCDF4

        out = Path(output_path)
        n = particles["x"].size

        with netCDF4.Dataset(str(out), "w", format="NETCDF4") as ds:
            ds.createDimension("nP", n)
            ds.description = "GITR particle source generated from BOUT++ dump"
            ds.source_file = str(self._bout_path)

            for vname in ("x", "y", "z", "vx", "vy", "vz", "energy_eV", "pitch_angle"):
                var = ds.createVariable(vname, "f8", ("nP",))
                var[:] = particles[vname]
                if vname in ("x", "y", "z"):
                    var.units = "m"
                elif vname in ("vx", "vy", "vz"):
                    var.units = "m/s"
                elif vname == "energy_eV":
                    var.units = "eV"
                elif vname == "pitch_angle":
                    var.units = "degrees"

        return out

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_synthetic(self) -> None:
        nz, ny, nx = 4, 32, 32
        self._density = np.ones((nz, ny, nx), dtype=np.float64) * 1e19
        self._temperature = np.ones((nz, ny, nx), dtype=np.float64) * 100.0
        self._velocity_x = np.zeros((nz, ny, nx), dtype=np.float64)
        self._velocity_y = np.zeros((nz, ny, nx), dtype=np.float64)
        self._velocity_z = np.ones((nz, ny, nx), dtype=np.float64) * 1e4
        self._mesh_x = np.linspace(0.0, 1.0, nx, dtype=np.float64)
        self._mesh_y = np.linspace(0.0, 1.0, ny, dtype=np.float64)
        self._mesh_z = np.linspace(0.0, 0.3, nz, dtype=np.float64)

    @staticmethod
    def _read_1d_coord(ds: object, name: str, default_size: int) -> NDArray[np.floating]:
        import netCDF4 as _nc

        if name in ds.variables:
            return np.asarray(ds.variables[name][:], dtype=np.float64)
        return np.linspace(0.0, 1.0, default_size, dtype=np.float64)

    def _grid_coord(self, indices: NDArray[np.integer], axis: int) -> NDArray[np.floating]:
        meshes = [self._mesh_x, self._mesh_y, self._mesh_z]
        mesh = meshes[axis]
        if mesh is not None and indices.max() < len(mesh):
            return mesh[indices]
        return indices.astype(np.float64)

    def _sampled_velocity(self, iy: NDArray[np.integer], ix: NDArray[np.integer],
                           iz: NDArray[np.integer], component: int) -> NDArray[np.floating]:
        fields = [self._velocity_x, self._velocity_y, self._velocity_z]
        field = fields[component]
        if field is not None:
            if field.ndim == 3:
                return field[iz, iy, ix]
            elif field.ndim == 2:
                return field[iy, ix]
            else:
                return field[ix]
        return np.zeros_like(ix, dtype=np.float64)
