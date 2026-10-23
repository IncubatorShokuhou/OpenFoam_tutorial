import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from atmospheric_case import (  # noqa: E402
    interpolate_profile_at,
    prepare_case,
    project_wgs84_to_local,
    build_sample_heatflux,
    build_sample_landcover,
    build_sample_profiles,
)
from fetch_era5_boundary import decode_era5_pair, write_sample_era5  # noqa: E402
from fetch_gfs_boundary import parse_gfs_index, select_messages, LEVEL_NAMES  # noqa: E402
from wrfout_to_boundary import destagger, rows_from_wrf, write_sample_wrfout  # noqa: E402


class ClockRewriteTest(unittest.TestCase):
    def test_end_time_delta_t_and_write_interval_move_together(self):
        from atmospheric_case import rewrite_control_times
        with tempfile.TemporaryDirectory() as directory:
            case = Path(directory)
            system = case / "system"
            system.mkdir()
            (system / "controlDict").write_text(
                "endTime         360;\ndeltaT          2;\nwriteInterval   120;\n",
                encoding="ascii",
            )
            rewrite_control_times(case, 120, 2, 60)
            text = (system / "controlDict").read_text(encoding="ascii")
        self.assertIn("endTime         120;", text)
        self.assertIn("deltaT          2;", text)
        self.assertIn("writeInterval   60;", text)


class ProjectTest(unittest.TestCase):
    def test_epsg_is_required(self):
        with self.assertRaises(ValueError):
            project_wgs84_to_local(116.39, 39.92, None, 0.0, 0.0)

    def test_jingshan_corner_lands_near_the_dem_origin(self):
        # Southwest of the committed clip. The number is checked against
        # EPSG:32650, which the caller has to pass.
        x_m, y_m = project_wgs84_to_local(116.3847, 39.9211, 32650, 447435.0, 4419195.0)
        self.assertLess(abs(x_m), 80.0)
        self.assertLess(abs(y_m), 80.0)


class Era5SampleTest(unittest.TestCase):
    def test_sample_is_labeled_and_theta_increases(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            pressure, single = write_sample_era5(
                folder / "era5_pressure_sample.nc",
                folder / "era5_single_sample.nc",
            )
            import netCDF4
            with netCDF4.Dataset(pressure) as dataset:
                self.assertIn("synthetic", dataset.tutorial_sample)
            rows, heat_rows, flag = decode_era5_pair(
                pressure, single,
                [(39.75, 116.25), (40.00, 116.25)],
                [-1000.0, 8000.0],
                0.1,
                solver_times=(0.0, 60.0, 120.0),
            )
        self.assertIn("synthetic", flag)
        self.assertEqual(sorted({row["time_s"] for row in rows}), [0.0, 60.0, 120.0])
        south = sorted(
            (row for row in rows if row["station"] == "era5_0" and row["time_s"] == 0.0),
            key=lambda row: row["z_m"],
        )
        self.assertGreater(south[-1]["T_K"], south[0]["T_K"])
        self.assertGreater(south[-1]["z_m"], 100.0)
        self.assertEqual(len(heat_rows), 3)
        self.assertGreater(heat_rows[0]["q_Wm2"], 0.0)
        self.assertNotAlmostEqual(rows[0]["w_ms"], 0.0, places=4)


class GfsIndexTest(unittest.TestCase):
    def test_parse_and_select(self):
        text = "\n".join([
            "1:0:d=2025011500:UGRD:1000 mb:anl:",
            "2:1000:d=2025011500:VGRD:1000 mb:anl:",
            "3:2500:d=2025011500:TMP:2 m above ground:anl:",
            "4:4000:d=2025011500:REFC:entire atmosphere:anl:",
        ])
        records = parse_gfs_index(text)
        self.assertEqual(records[0]["length"], 1000)
        self.assertIsNone(records[-1]["length"])
        chosen = select_messages(records, LEVEL_NAMES)
        names = {(item["name"], item["level"]) for item in chosen}
        self.assertIn(("UGRD", "1000 mb"), names)
        self.assertIn(("TMP", "2 m above ground"), names)
        self.assertNotIn(("REFC", "entire atmosphere"), names)


class WrfSampleTest(unittest.TestCase):
    def test_destagger_averages_faces(self):
        values = np.array([0.0, 2.0, 4.0])
        np.testing.assert_allclose(destagger(values, 0), [1.0, 3.0])

    def test_sample_round_trip_uses_passed_epsg(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wrfout_d01_synthetic.nc"
            write_sample_wrfout(path, 447435.0, 4419195.0, 32650)
            import netCDF4
            with netCDF4.Dataset(path) as dataset:
                self.assertIn("synthetic", dataset.tutorial_sample)
                self.assertEqual(dataset.dimensions["west_east_stag"].size,
                                 dataset.dimensions["west_east"].size + 1)
            rows, heat_rows, flag = rows_from_wrf(
                path, 32650, 447435.0, 4419195.0, 0.1, (0.0, 60.0),
            )
        self.assertIn("synthetic", flag)
        xs = sorted({round(row["x_m"], 3) for row in rows})
        self.assertAlmostEqual(xs[0], 0.0, delta=1.0)
        self.assertAlmostEqual(xs[1], 150.0, delta=1.0)
        self.assertGreater(heat_rows[0]["q_Wm2"], 0.0)
        column = sorted(
            (row for row in rows if row["station"] == "wrf_0_0" and row["time_s"] == 0.0),
            key=lambda row: row["z_m"],
        )
        self.assertGreater(column[-1]["T_K"], column[0]["T_K"])
        self.assertLess(column[0]["T_K"], 300.0)


class HorizontalTableTest(unittest.TestCase):
    def test_x_changes_the_sample(self):
        rows = []
        for x_m, u_value in ((0.0, 1.0), (100.0, 5.0)):
            for z_m, extra in ((0.0, 0.0), (100.0, 1.0)):
                rows.append({
                    "station": f"s{x_m}", "time_s": 0.0, "x_m": x_m, "y_m": 0.0, "z_m": z_m,
                    "u_ms": u_value + extra, "v_ms": 0.0, "w_ms": 0.0, "T_K": 270.0,
                    "q_kgkg": 0.001, "p_Pa": 1.0e5, "k_m2s2": 0.1, "epsilon_m2s3": 0.01,
                })
        west = interpolate_profile_at(rows, 0.0, 0.0, 0.0, 0.0)
        east = interpolate_profile_at(rows, 0.0, 100.0, 0.0, 0.0)
        self.assertAlmostEqual(west["u_ms"], 1.0, places=6)
        self.assertAlmostEqual(east["u_ms"], 5.0, places=6)

    def test_two_sites_off_a_rectangle_still_interpolate(self):
        rows = []
        for x_m, y_m, u_value in ((-800.0, -5000.0, 1.0), (-700.0, 8000.0, 5.0)):
            for z_m in (2.0, 100.0):
                rows.append({
                    "station": f"s{y_m}", "time_s": 0.0, "x_m": x_m, "y_m": y_m, "z_m": z_m,
                    "u_ms": u_value, "v_ms": 0.0, "w_ms": 0.0, "T_K": 270.0,
                    "q_kgkg": 0.001, "p_Pa": 1.0e5, "k_m2s2": 0.1, "epsilon_m2s3": 0.01,
                })
        mid = interpolate_profile_at(rows, 0.0, -750.0, 0.0, 10.0)
        self.assertGreater(mid["u_ms"], 1.0)
        self.assertLess(mid["u_ms"], 5.0)


class SideBoundaryTest(unittest.TestCase):
    def test_front_and_back_clouds_are_written(self):
        with tempfile.TemporaryDirectory() as directory:
            case = Path(directory) / "atmospheric"
            prepare_case(
                case, build_sample_profiles(), build_sample_landcover(), build_sample_heatflux(),
                sample_hill=True, nz=4, write_stl=False,
            )
            velocity = (case / "0" / "U").read_text(encoding="ascii")
            self.assertEqual(velocity.count("timeVaryingMappedFixedValue"), 3)
            self.assertTrue((case / "constant" / "boundaryData" / "front" / "0" / "U").exists())
            self.assertTrue((case / "constant" / "boundaryData" / "back" / "0" / "T").exists())
            self.assertTrue((case / "constant" / "boundaryData" / "outlet" / "0" / "p_rgh").exists())


if __name__ == "__main__":
    unittest.main()
