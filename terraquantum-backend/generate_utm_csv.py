import pyproj
import csv

lat = -22.28
lon = -68.89

# UTM zone 19S -> EPSG:32719
transformer = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32719", always_xy=True)
easting, northing = transformer.transform(lon, lat)

points = []
for i in range(12):
    row = i // 4
    col = i % 4
    points.append({
        "station_id": f"S{i:03d}",
        "x_m": round(easting + col * 500, 2),
        "y_m": round(northing + row * 500, 2),
        "z_m": 0.0,
        "g": round(0.10 + i * 0.01, 2),
        "unit": "mGal"
    })

with open("test_r23_qa.csv", "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=["station_id", "x_m", "y_m", "z_m", "g", "unit"])
    writer.writeheader()
    writer.writerows(points)

print(f"Generated test_r23_qa.csv with {len(points)} points. Range: X ~ {easting:.2f}, Y ~ {northing:.2f}")
