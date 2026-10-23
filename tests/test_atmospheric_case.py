import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))


def _rasterio_available():
    try:
        import rasterio  # noqa: F401
    except ImportError:
        return False
    return True


from atmospheric_case import (  # noqa: E402
    DEFAULT_HEATFLUX,
    DEFAULT_LANDCOVER,
    DEFAULT_PROFILES,
    P_REF,
    PRGH_LIMIT,
    RHO0,
    GRAVITY,
    build_hex_mesh,
    build_sample_heatflux,
    build_sample_landcover,
    build_sample_profiles,
    bulk_sensible_heat,
    cell_centers,
    cell_count,
    deaccumulate,
    diagnose_k_epsilon,
    dynamic_pressure,
    ground_ks,
    interpolate_profile,
    load_heatflux,
    load_landcover,
    load_profiles,
    omega_to_w,
    plane_sample_points,
    potential_temperature,
    prepare_case,
    read_dem,
    specific_humidity,
    wind_components,
    write_profile_csv,
    write_sample_dem,
    z0_at,
)


class AtmosphericTableTest(unittest.TestCase):
    def test_sample_generator_round_trip(self):
        self.assertEqual(_rounded_profiles(build_sample_profiles()), _rounded_profiles(build_sample_profiles()))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.csv"
            write_profile_csv(path, build_sample_profiles())
            self.assertEqual(load_profiles(path), _rounded_profiles(build_sample_profiles()))

    def test_tutorial_tables_are_the_beijing_case(self):
        header = DEFAULT_PROFILES.read_text(encoding="ascii")
        self.assertIn("icon_global", header)
        self.assertIn("2025-01-15", header)
        self.assertIn("ZBAA", header)
        self.assertIn("historical-forecast-api.open-meteo.com", header)
        self.assertIn("Jingshan", header)
        rows = load_profiles(DEFAULT_PROFILES)
        self.assertNotEqual(rows, _rounded_profiles(build_sample_profiles()))
        self.assertEqual(sorted({row["station"] for row in rows}), ["north_icon", "south_icon"])
        self.assertEqual(sorted({row["time_s"] for row in rows}), [0.0, 180.0, 360.0])
        south = sorted(
            (row for row in rows if row["station"] == "south_icon" and row["time_s"] == 0.0),
            key=lambda row: row["z_m"],
        )
        self.assertGreater(south[-1]["T_K"], south[0]["T_K"])
        north_top = max(
            (row for row in rows if row["station"] == "north_icon" and row["time_s"] == 0.0),
            key=lambda row: row["z_m"],
        )
        south_top = max(
            (row for row in rows if row["station"] == "south_icon" and row["time_s"] == 0.0),
            key=lambda row: row["z_m"],
        )
        self.assertNotAlmostEqual(north_top["u_ms"], south_top["u_ms"], places=3)
        cover = DEFAULT_LANDCOVER.read_text(encoding="ascii")
        self.assertIn("WorldCover", cover)
        self.assertIn("built", cover)
        self.assertIn("tree", cover)
        heat = DEFAULT_HEATFLUX.read_text(encoding="ascii")
        self.assertIn("era5", heat)
        self.assertEqual(len(load_heatflux(DEFAULT_HEATFLUX)), 3)
        iem = (DEFAULT_PROFILES.parent / "beijing_iem_zbaa.csv").read_text(encoding="ascii")
        self.assertIn("ZBAA,2025-01-15 00:00", iem)
        self.assertIn("mesonet.agron.iastate.edu", iem)

    def test_met_conversions(self):
        east, north = wind_components(10.0, 90.0)
        self.assertAlmostEqual(east, -10.0, places=8)
        self.assertAlmostEqual(north, 0.0, places=8)
        self.assertAlmostEqual(potential_temperature(0.0, 1.0e5), 273.15, places=8)
        humidity = specific_humidity(50.0, 20.0, 101325.0)
        self.assertGreater(humidity, 0.0)
        self.assertLess(humidity, 0.02)
        heat = bulk_sensible_heat(1.88, -2.3, -7.1)
        self.assertAlmostEqual(heat, 1.2 * 1004.5 * 0.002 * 1.88 * 4.8, places=6)

    def test_sample_covers_two_stations_and_three_times(self):
        rows = build_sample_profiles()
        self.assertGreaterEqual(len({row["station"] for row in rows}), 2)
        self.assertEqual(sorted({row["time_s"] for row in rows}), [0.0, 10.0, 20.0])
        required = {"u_ms", "v_ms", "w_ms", "T_K", "q_kgkg", "p_Pa", "k_m2s2", "epsilon_m2s3"}
        self.assertTrue(required <= set(rows[0]))

    def test_station_value_round_trip(self):
        rows = build_sample_profiles()
        target = next(row for row in rows if row["station"] == "south_mast" and row["time_s"] == 10 and row["z_m"] == 50)
        got = interpolate_profile(rows, 10.0, target["y_m"], target["z_m"])
        for key in ("u_ms", "v_ms", "w_ms", "T_K", "q_kgkg", "p_Pa", "k_m2s2", "epsilon_m2s3"):
            self.assertAlmostEqual(got[key], target[key], places=6)

    def test_north_station_is_slower_and_more_crosswind(self):
        rows = build_sample_profiles()
        south = interpolate_profile(rows, 0.0, 40.0, 20.0)
        north = interpolate_profile(rows, 0.0, 260.0, 20.0)
        self.assertLess(north["u_ms"], south["u_ms"])
        self.assertGreater(abs(north["v_ms"]), abs(south["v_ms"]))

    def test_heights_may_differ_between_times(self):
        rows = []
        for time_s, z_top in ((0.0, 200.0), (10.0, 240.0)):
            for station, y_m in (("south", 0.0), ("north", 100.0)):
                for z_m, speed in ((0.0, 1.0), (z_top, 5.0)):
                    rows.append({
                        "station": station, "time_s": time_s, "y_m": y_m, "z_m": z_m,
                        "u_ms": speed, "v_ms": 0.0, "w_ms": 0.0, "T_K": 280.0 + z_m / 100.0,
                        "q_kgkg": 0.001, "p_Pa": 100000.0 - z_m, "k_m2s2": 0.1,
                        "epsilon_m2s3": 0.01,
                    })
        got = interpolate_profile(rows, 0.0, 0.0, 100.0)
        self.assertAlmostEqual(got["u_ms"], 3.0, places=6)
        got = interpolate_profile(rows, 10.0, 0.0, 120.0)
        self.assertAlmostEqual(got["u_ms"], 3.0, places=6)

    def test_potential_temperature_increases_with_height(self):
        rows = build_sample_profiles()
        low = interpolate_profile(rows, 0.0, 40.0, 5.0)
        high = interpolate_profile(rows, 0.0, 40.0, 160.0)
        self.assertGreater(high["T_K"], low["T_K"])

    def test_dynamic_pressure_drops_hydrostatic_and_mean(self):
        height = np.array([0.0, 100.0, 200.0])
        residual = np.array([1.0, -0.5, 0.2])
        pressure = P_REF - RHO0 * GRAVITY * height + 80.0 + residual
        anomaly, clamped = dynamic_pressure(pressure, height)
        self.assertFalse(clamped)
        self.assertAlmostEqual(float(np.mean(anomaly)), 0.0, places=8)
        self.assertAlmostEqual(float(np.max(anomaly) - np.min(anomaly)), float(residual.max() - residual.min()), places=8)

    def test_dynamic_pressure_clamps_large_era5_mismatch(self):
        height = np.linspace(0.0, 200.0, 5)
        pressure = P_REF - 1.0 * GRAVITY * height
        anomaly, clamped = dynamic_pressure(pressure, height)
        self.assertTrue(clamped)
        self.assertLessEqual(float(np.max(np.abs(anomaly))), PRGH_LIMIT + 1e-8)

    def test_landcover_classes(self):
        rows = build_sample_landcover()
        self.assertAlmostEqual(z0_at(rows, 300.0, 150.0), 0.15)
        self.assertAlmostEqual(z0_at(rows, 10.0, 10.0), 0.01)
        self.assertAlmostEqual(z0_at(rows, 100.0, 100.0), 0.03)

    def test_omega_and_accumulated_flux(self):
        # 1 Pa/s at 290 K and 1e5 Pa is a downward speed of about 0.0086 m/s.
        w_ms = omega_to_w(1.0, 290.0, 1.0e5)
        self.assertLess(float(w_ms), 0.0)
        self.assertAlmostEqual(float(w_ms), -1.0 / ((1.0e5 / (287.05 * 290.0)) * 9.81), places=8)
        watts = deaccumulate(np.array([0.0, 3600.0, 1800.0]), 3600.0)
        self.assertTrue(np.allclose(watts, [0.0, 1.0, -0.5]))

    def test_diagnosed_turbulence_is_positive(self):
        k_value, epsilon = diagnose_k_epsilon([4.0, 6.0], [0.2, 0.3], [10.0, 50.0], 0.05)
        self.assertTrue(np.all(k_value > 0))
        self.assertTrue(np.all(epsilon > 0))
        self.assertGreater(epsilon[0], epsilon[1])


class MeshTest(unittest.TestCase):
    def test_face_normals_point_owner_to_neighbour(self):
        x = np.linspace(0.0, 40.0, 3)
        y = np.linspace(0.0, 30.0, 3)
        ground = np.zeros((3, 3))
        ground[:, :] = np.array([0.0, 4.0, 2.0])[:, None]
        mesh = build_hex_mesh(x, y, ground, h_air=20.0, nz=2, growth=1.0)
        self.assertEqual(cell_count(mesh), 8)
        n_internal = (2 - 1) * 2 * 2 + 2 * (2 - 1) * 2 + 2 * 2 * (2 - 1)
        self.assertEqual(mesh["n_internal"], n_internal)
        self.assertEqual(mesh["patches"]["ground"]["count"], 4)
        centers = cell_centers(mesh)
        points = mesh["points"]
        for face, own, nei in zip(
            mesh["faces"][: mesh["n_internal"]],
            mesh["owner"][: mesh["n_internal"]],
            mesh["neighbour"],
        ):
            verts = points[list(face)]
            normal = np.cross(verts[1] - verts[0], verts[2] - verts[0])
            self.assertGreater(float(np.dot(normal, centers[nei] - centers[own])), 0.0)
        for face, own in zip(mesh["faces"][mesh["n_internal"]:], mesh["owner"][mesh["n_internal"]:]):
            verts = points[list(face)]
            normal = np.cross(verts[1] - verts[0], verts[2] - verts[0])
            self.assertGreater(float(np.dot(normal, verts.mean(axis=0) - centers[own])), 0.0)

    def test_mapped_plane_is_not_a_line(self):
        points = plane_sample_points(0.0, np.linspace(0.0, 100.0, 4), 1.0, 40.0, n_y=4, n_z=3)
        edge_a = points[1] - points[0]
        edge_b = points[2] - points[0]
        self.assertGreater(float(np.linalg.norm(np.cross(edge_a, edge_b))), 0.0)

    def test_ground_roughness_follows_the_map(self):
        x = np.linspace(0.0, 500.0, 11)
        y = np.linspace(0.0, 300.0, 7)
        xx, yy = np.meshgrid(x, y)
        ground = np.zeros_like(xx)
        mesh = build_hex_mesh(x, y, ground, h_air=30.0, nz=2, growth=1.0)
        ks, centers = ground_ks(mesh, build_sample_landcover())
        self.assertEqual(len(ks), mesh["patches"]["ground"]["count"])
        self.assertGreater(float(ks.max()), float(ks.min()))
        woodland = [value for value, (x_m, y_m, _z0) in zip(ks, centers) if 250 <= x_m <= 350 and 100 <= y_m <= 200]
        grass = [value for value, (x_m, y_m, _z0) in zip(ks, centers) if 70 <= x_m <= 130 and 70 <= y_m <= 130]
        self.assertGreater(min(woodland), max(grass))


class PrepareTest(unittest.TestCase):
    @unittest.skipUnless(_rasterio_available(), "terrain extras are not installed")
    def test_prepare_round_trips_sample_dem_and_writes_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            case = Path(directory) / "atmospheric"
            profiles = build_sample_profiles()
            prepare_case(
                case, profiles, build_sample_landcover(), build_sample_heatflux(),
                nz=4, h_air=80.0, growth=1.05, sample_hill=True,
            )
            dem = read_dem(case / "dem_utm.tif")
            self.assertIn("32650", dem["crs"])
            self.assertEqual(dem["height"].shape, (13, 21))
            self.assertGreater(float(dem["height"].max()), 20.0)
            self.assertLess(float(dem["height"][0, 0]), 1.0)
            inlet_u = (case / "constant" / "boundaryData" / "inlet" / "0" / "U").read_text()
            inlet_points = (case / "constant" / "boundaryData" / "inlet" / "points").read_text()
            self.assertEqual(inlet_u.split()[0], inlet_points.split()[0])
            self.assertIn("timeVaryingMappedFixedValue", (case / "0" / "U").read_text())
            self.assertIn("externalTemperature", (case / "0" / "T").read_text())
            self.assertIn("timeVaryingMappedFixedValue", (case / "0" / "q").read_text())
            self.assertIn("timeVaryingMappedFixedValue", (case / "0" / "p_rgh").read_text())
            nut = (case / "0" / "nut").read_text()
            self.assertIn("nutkRoughWallFunction", nut)
            self.assertIn("type wall;", (case / "constant" / "polyMesh" / "boundary").read_text())
            self.assertIn("nonuniform", nut)
            self.assertRegex((case / "0" / "T").read_text(), r"externalTemperature")
            prgh = np.loadtxt(
                case / "constant" / "boundaryData" / "outlet" / "0" / "p_rgh",
                skiprows=2, max_rows=int(inlet_points.split()[0]),
            )
            # The list may include a closing parenthesis on the last row; loadtxt stops.
            self.assertLess(float(np.nanmax(np.abs(prgh))), PRGH_LIMIT + 1e-6)
            self.assertGreater(float(np.nanstd(prgh)), 0.05)
            self.assertTrue((case / "constant" / "triSurface" / "terrain.stl").exists())
            # Rewriting the profile CSV is stable.
            target = Path(directory) / "profiles.csv"
            write_profile_csv(target, profiles)
            self.assertEqual(load_profiles(target), _rounded_profiles(profiles))


def _rounded_profiles(rows):
    # Match the decimal text written to the CSV.
    loaded_path = None
    import tempfile
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "p.csv"
        write_profile_csv(path, rows)
        loaded_path = load_profiles(path)
    return loaded_path


def _rounded_landcover(rows):
    from atmospheric_case import write_landcover_csv
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "land.csv"
        write_landcover_csv(path, rows)
        return load_landcover(path)


def _rounded_heat(rows):
    from atmospheric_case import write_heatflux_csv
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "heat.csv"
        write_heatflux_csv(path, rows)
        return load_heatflux(path)


class PointsReaderTest(unittest.TestCase):
    def test_parenthesised_vectors(self):
        from plot_atmospheric import read_points

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "points"
            path.write_text(
                "FoamFile\n{\n    format ascii;\n    class vectorField;\n"
                "    object points;\n}\n2\n(\n(0 1 2.5)\n(3 4 5)\n)\n",
                encoding="ascii",
            )
            points = read_points(path)
        self.assertEqual(points.shape, (2, 3))
        np.testing.assert_allclose(points[0], [0.0, 1.0, 2.5])
        np.testing.assert_allclose(points[1], [3.0, 4.0, 5.0])


if __name__ == "__main__":
    unittest.main()
