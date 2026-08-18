"""Tests for BOUT++ → GITR coupling adapter and driver script."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import numpy as np
import pytest

_ADAPTER_DIR = str(Path(__file__).resolve().parent.parent / "adapters")
if _ADAPTER_DIR not in sys.path:
    sys.path.insert(0, _ADAPTER_DIR)

_COUPLING_DIR = str(Path(__file__).resolve().parent.parent / "coupling")
if _COUPLING_DIR not in sys.path:
    sys.path.insert(0, _COUPLING_DIR)


class TestBoutToGitRAdapter:
    """Unit tests for the BoutToGitrAdapter class."""

    def test_synthetic_fallback_without_netcdf4(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When netCDF4 is unavailable synthetic data is used — no crash."""
        import importlib
        monkeypatch.setitem(sys.modules, "netCDF4", None)

        # Force re-import so the adapter sees the missing netCDF4.
        if "bout_to_gitr" in sys.modules:
            import bout_to_gitr
            importlib.reload(bout_to_gitr)

        from bout_to_gitr import BoutToGitrAdapter

        adapter = BoutToGitrAdapter("fake_dump.nc")
        adapter.load_bout_dump()

        assert adapter._density is not None
        assert adapter._temperature is not None
        assert adapter._density.shape == (4, 32, 32)

    def test_generate_particle_source_shape(self) -> None:
        """Generated particles dict has the expected variable keys and lengths."""
        from bout_to_gitr import BoutToGitrAdapter

        adapter = BoutToGitrAdapter("fake.nc")
        adapter.load_bout_dump()

        rng = np.random.default_rng(42)
        particles = adapter.generate_particle_source(n_particles=100, rng=rng)

        expected_keys = {"x", "y", "z", "vx", "vy", "vz", "energy_eV", "pitch_angle"}
        assert set(particles.keys()) == expected_keys
        for arr in particles.values():
            assert arr.size == 100

    def test_energy_is_positive(self) -> None:
        """All sampled energies are strictly positive (density > 0, T > 0)."""
        from bout_to_gitr import BoutToGitrAdapter

        adapter = BoutToGitrAdapter("fake.nc")
        adapter.load_bout_dump()

        particles = adapter.generate_particle_source(n_particles=200, rng=np.random.default_rng(7))
        assert np.all(particles["energy_eV"] > 0)


class TestRunBoutToGitRCli:
    """Integration-style tests for the CLI driver (mocked adapter)."""

    def test_help_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        """--help prints usage and exits cleanly."""
        from run_bout_to_gitr import _build_parser

        p = _build_parser()
        with pytest.raises(SystemExit) as exc:
            p.parse_args(["--help"])
        assert exc.value.code == 0

    @mock.patch("bout_to_gitr.BoutToGitrAdapter")
    def test_full_run_writes_netcdf(self, mock_adapter_cls: mock.MagicMock,
                                     tmp_path: Path) -> None:
        """End-to-end: simulate a run that writes a particle source file."""
        from run_bout_to_gitr import main

        mock_adapter = mock_adapter_cls.return_value
        mock_adapter.generate_particle_source.return_value = {
            "x": np.array([1.0, 2.0]),
            "y": np.array([0.5, 0.6]),
            "z": np.array([0.0, 0.0]),
            "vx": np.array([0.0, 0.0]),
            "vy": np.array([0.0, 0.0]),
            "vz": np.array([1e4, 1e4]),
            "energy_eV": np.array([10.0, 11.0]),
            "pitch_angle": np.array([0.0, 5.0]),
        }
        mock_adapter.write_netcdf.return_value = tmp_path / "particle_source.nc"

        # Create a dummy input file so the existence check passes.
        dummy_input = tmp_path / "plasma.nc"
        dummy_input.write_text("")

        main(["--bout-dump", str(dummy_input), "--n-particles", "2", "--output", str(tmp_path / "out.nc")])

        mock_adapter.load_bout_dump.assert_called_once()
        mock_adapter.generate_particle_source.assert_called_once()
        mock_adapter.write_netcdf.assert_called_once()
