import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from atmospheric_case import (  # noqa: E402
    load_heatflux,
    load_landcover,
    load_profiles,
    prepare_case,
    wind_components,
)
from csv_obs_to_boundary import (  # noqa: E402
    COLUMNS,
    CsvObsError,
    load_obs_rows,
    rows_from_obs,
    template_text,
)


HEADER = ",".join(COLUMNS)


def _row(**values):
    data = {name: "" for name in COLUMNS}
    data.update(values)
    return ",".join(str(data[name]) for name in COLUMNS)


def _table(*rows):
    return "\n".join(["# comment", HEADER, *rows]) + "\n"


class TemplateTest(unittest.TestCase):
    def test_template_lists_every_column_and_has_no_data(self):
        text = template_text()
        self.assertIn(",".join(COLUMNS), text)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "template.csv"
            path.write_text(text, encoding="utf-8")
            with self.assertRaises(CsvObsError) as caught:
                load_obs_rows(path)
        self.assertIn("no data rows", str(caught.exception))


class ConversionTest(unittest.TestCase):
    def _convert(self, text, solver_times=(0.0, 60.0), z0=0.1):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "obs.csv"
            path.write_text(text, encoding="utf-8")
            rows = load_obs_rows(path)
        return rows_from_obs(rows, 32650, 447435.0, 4419195.0, solver_times, z0)

    def test_speed_and_rh_become_uv_and_specific_humidity(self):
        # 270 degrees means the wind comes from the west, so u is positive.
        text = _table(
            _row(id="s", time="2025-01-15T00:00:00Z", lat=39.875, lon=116.375,
                 height_agl_m=2, pressure_hpa=1030, t_c=-10, wind_speed_ms=3, wind_dir_deg=270,
                 rh_percent=80, heat_flux_wm2=20),
            _row(id="s", time="2025-01-15T00:00:00Z", lat=39.875, lon=116.375,
                 height_agl_m=100, pressure_hpa=1000, t_c=-12, wind_speed_ms=5, wind_dir_deg=270,
                 rh_percent=70, heat_flux_wm2=20),
            _row(id="s", time="2025-01-15T01:00:00Z", lat=39.875, lon=116.375,
                 height_agl_m=2, pressure_hpa=1030, t_c=-9, wind_speed_ms=3, wind_dir_deg=270,
                 rh_percent=80, heat_flux_wm2=10),
            _row(id="s", time="2025-01-15T01:00:00Z", lat=39.875, lon=116.375,
                 height_agl_m=100, pressure_hpa=1000, t_c=-11, wind_speed_ms=5, wind_dir_deg=270,
                 rh_percent=70, heat_flux_wm2=10),
        )
        profiles, heat = self._convert(text)
        low = [row for row in profiles if row["time_s"] == 0.0 and row["z_m"] == 2.0][0]
        u_ms, v_ms = wind_components(3.0, 270.0)
        self.assertAlmostEqual(low["u_ms"], u_ms, places=6)
        self.assertAlmostEqual(low["v_ms"], v_ms, places=6)
        # 1030 hPa is above the 1000 hPa reference, so potential temperature is colder than t_c.
        self.assertLess(low["T_K"], -10.0 + 273.15)
        self.assertGreater(low["T_K"], 250.0)
        self.assertGreater(low["q_kgkg"], 0.0)
        self.assertEqual(low["w_ms"], 0.0)
        self.assertAlmostEqual(heat[1]["q_Wm2"], 10.0)
        self.assertIn("x_m", low)

    def test_pressure_coordinate_grows_upward_and_dewpoint_is_positive(self):
        text = _table(
            _row(id="s", time="2025-01-15T00:00:00Z", lat=39.92, lon=116.39,
                 pressure_hpa=1000, surface_pressure_hpa=1030, t_c=-5, u_ms=2, v_ms=0.2,
                 dewpoint_c=-8, heat_flux_wm2=5, z0_m=0.1),
            _row(id="s", time="2025-01-15T00:00:00Z", lat=39.92, lon=116.39,
                 pressure_hpa=900, surface_pressure_hpa=1030, t_c=-10, u_ms=4, v_ms=0.2,
                 dewpoint_c=-14, heat_flux_wm2=5, z0_m=0.1),
        )
        profiles, _heat = self._convert(text, solver_times=(0.0,), z0=None)
        self.assertGreater(profiles[1]["z_m"], profiles[0]["z_m"])
        self.assertGreater(profiles[0]["q_kgkg"], 0.0)
        self.assertGreater(profiles[1]["z_m"], 500.0)

    def test_asl_height_subtracts_the_surface(self):
        text = _table(
            _row(id="s", time="2025-01-15T00:00:00Z", lat=39.92, lon=116.39,
                 height_asl_m=52, surface_asl_m=50, pressure_hpa=1020, t_k=270,
                 u_ms=1, v_ms=0, q_kgkg=0.001, heat_flux_wm2=1, k_m2s2=0.2, epsilon_m2s3=0.01),
            _row(id="s", time="2025-01-15T00:00:00Z", lat=39.92, lon=116.39,
                 height_asl_m=150, surface_asl_m=50, pressure_hpa=1000, t_k=268,
                 u_ms=2, v_ms=0, q_kgkg=0.0008, heat_flux_wm2=1, k_m2s2=0.2, epsilon_m2s3=0.001),
        )
        profiles, _heat = self._convert(text, solver_times=(0.0,), z0=None)
        self.assertAlmostEqual(profiles[0]["z_m"], 2.0)
        self.assertAlmostEqual(profiles[0]["k_m2s2"], 0.2)

    def test_turbulence_intensity_is_a_fraction(self):
        text = _table(
            _row(id="s", time="2025-01-15T00:00:00Z", lat=39.92, lon=116.39,
                 height_agl_m=10, pressure_hpa=1010, theta_k=270, u_ms=4, v_ms=0,
                 q_kgkg=0.001, ti=0.1, heat_flux_wm2=1, z0_m=0.05),
            _row(id="s", time="2025-01-15T00:00:00Z", lat=39.92, lon=116.39,
                 height_agl_m=100, pressure_hpa=1000, theta_k=272, u_ms=4, v_ms=0,
                 q_kgkg=0.001, ti=0.1, heat_flux_wm2=1, z0_m=0.05),
        )
        profiles, _heat = self._convert(text, solver_times=(0.0,), z0=None)
        # k = 1.5 * (0.1 * 4)^2 = 0.24
        self.assertAlmostEqual(profiles[0]["k_m2s2"], 0.24, places=6)

    def test_missing_wind_names_the_line(self):
        text = _table(
            _row(id="s", time="2025-01-15T00:00:00Z", lat=39.92, lon=116.39,
                 height_agl_m=10, t_c=0, q_kgkg=0.001, heat_flux_wm2=1),
            _row(id="s", time="2025-01-15T00:00:00Z", lat=39.92, lon=116.39,
                 height_agl_m=50, t_c=-1, q_kgkg=0.001, heat_flux_wm2=1),
        )
        with self.assertRaises(CsvObsError) as caught:
            self._convert(text, solver_times=(0.0,))
        self.assertIn("line 3", str(caught.exception))
        self.assertIn("u_ms", str(caught.exception))

    def test_both_wind_forms_are_rejected(self):
        text = _table(
            _row(id="s", time="2025-01-15T00:00:00Z", lat=39.92, lon=116.39,
                 height_agl_m=10, t_c=0, u_ms=1, v_ms=0, wind_speed_ms=1, wind_dir_deg=0,
                 q_kgkg=0.001, heat_flux_wm2=1),
            _row(id="s", time="2025-01-15T00:00:00Z", lat=39.92, lon=116.39,
                 height_agl_m=50, t_c=-1, u_ms=1, v_ms=0, q_kgkg=0.001, heat_flux_wm2=1),
        )
        with self.assertRaises(CsvObsError) as caught:
            self._convert(text, solver_times=(0.0,))
        self.assertIn("not both", str(caught.exception))

    def test_unknown_column_and_nan_token(self):
        text = "# c\nid,time,lat,lon,height_agl_m,bonus\ns,2025-01-15T00:00:00Z,1,2,10,1\n"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "obs.csv"
            path.write_text(text, encoding="utf-8")
            with self.assertRaises(CsvObsError) as caught:
                load_obs_rows(path)
        self.assertIn("bonus", str(caught.exception))
        bad = _table(_row(id="s", time="2025-01-15T00:00:00Z", lat=1, lon=2, height_agl_m="nan"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "obs.csv"
            path.write_text(bad, encoding="utf-8")
            with self.assertRaises(CsvObsError) as caught:
                load_obs_rows(path)
        self.assertIn("nan", str(caught.exception).lower())

    def test_ti_at_or_above_one_is_rejected(self):
        text = _table(
            _row(id="s", time="2025-01-15T00:00:00Z", lat=39.92, lon=116.39,
                 height_agl_m=10, t_c=0, u_ms=1, v_ms=0, q_kgkg=0.001, ti=12, heat_flux_wm2=1),
            _row(id="s", time="2025-01-15T00:00:00Z", lat=39.92, lon=116.39,
                 height_agl_m=50, t_c=-1, u_ms=1, v_ms=0, q_kgkg=0.001, ti=12, heat_flux_wm2=1),
        )
        with self.assertRaises(CsvObsError) as caught:
            self._convert(text, solver_times=(0.0,))
        self.assertIn("fraction", str(caught.exception))

    def test_epsg_is_required(self):
        text = _table(
            _row(id="s", time="2025-01-15T00:00:00Z", lat=39.92, lon=116.39,
                 height_agl_m=10, t_c=0, u_ms=1, v_ms=0, q_kgkg=0.001, heat_flux_wm2=1),
            _row(id="s", time="2025-01-15T00:00:00Z", lat=39.92, lon=116.39,
                 height_agl_m=50, t_c=-1, u_ms=1, v_ms=0, q_kgkg=0.001, heat_flux_wm2=1),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "obs.csv"
            path.write_text(text, encoding="utf-8")
            rows = load_obs_rows(path)
        with self.assertRaises(CsvObsError):
            rows_from_obs(rows, None, 0.0, 0.0, (0.0,), 0.1)


class JingshanExampleTest(unittest.TestCase):
    def test_example_table_matches_the_icon_potential_temperature(self):
        path = ROOT / "examples" / "csv_obs" / "inputs" / "jingshan_obs_example.csv"
        profiles, heat = rows_from_obs(
            load_obs_rows(path), 32650, 447435.0, 4419195.0, (0.0, 60.0, 120.0), None,
        )
        south = [
            row for row in profiles
            if row["station"] == "south" and row["time_s"] == 0.0 and abs(row["z_m"] - 2.0) < 1e-6
        ][0]
        self.assertAlmostEqual(south["T_K"], 263.09617, places=4)
        self.assertAlmostEqual(south["y_m"], -5124.5138, places=3)
        self.assertAlmostEqual(heat[0]["q_Wm2"], 21.755059, places=4)
        self.assertEqual(len({row["station"] for row in profiles}), 2)


class PrepareKeepsExampleFilesTest(unittest.TestCase):
    def test_inputs_and_readme_survive_prepare(self):
        with tempfile.TemporaryDirectory() as directory:
            case = Path(directory)
            inputs = case / "inputs"
            inputs.mkdir()
            (inputs / "note.txt").write_text("keep", encoding="ascii")
            (case / "README.md").write_text("readme", encoding="ascii")
            (case / "120").mkdir()
            prepare_case(
                case,
                load_profiles(ROOT / "tutorial" / "data" / "beijing_boundary.csv"),
                load_landcover(ROOT / "tutorial" / "data" / "beijing_landcover_z0.csv"),
                load_heatflux(ROOT / "tutorial" / "data" / "beijing_heatflux.csv"),
                sample_hill=True,
                end_time=20, delta_t=1, write_interval=10,
                write_stl=False,
            )
            self.assertEqual((inputs / "note.txt").read_text(encoding="ascii"), "keep")
            self.assertEqual((case / "README.md").read_text(encoding="ascii"), "readme")
            self.assertFalse((case / "120").exists())
            text = (case / "system" / "controlDict").read_text(encoding="ascii")
            self.assertIn("endTime         20;", text)


if __name__ == "__main__":
    unittest.main()
