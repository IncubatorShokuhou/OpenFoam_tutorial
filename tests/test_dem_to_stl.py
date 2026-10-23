import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
except ImportError:
    np = rasterio = from_origin = None


class DemToStlTest(unittest.TestCase):
    @unittest.skipIf(rasterio is None, "terrain extras are not installed")
    def test_projected_dem_produces_two_triangles(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            tif = directory / "dem.tif"
            stl = directory / "terrain.stl"
            with rasterio.open(
                tif, "w", driver="GTiff", height=2, width=2, count=1,
                dtype="float32", crs="EPSG:32650", transform=from_origin(500000, 4500000, 30, 30)
            ) as dataset:
                dataset.write(np.array([[10, 12], [11, 13]], dtype="float32"), 1)
            subprocess.run(
                [sys.executable, "tools/dem_to_stl.py", str(tif), str(stl)], check=True,
                cwd=Path(__file__).parents[1], capture_output=True, text=True
            )
            text = stl.read_text()
            self.assertEqual(text.count("facet normal"), 2)
            self.assertIn("vertex 0 30 10", text)


if __name__ == "__main__":
    unittest.main()
