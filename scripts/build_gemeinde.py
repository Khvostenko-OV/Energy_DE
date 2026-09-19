import sys

import geopandas as gpd
import pandas as pd

SOURCE = "data/boundaries/DE_VG250.gpkg"
LAYER = "vg250_gem"
TARGET = "data/boundaries/germany_municipalities.gpkg"


def main() -> int:
    gdf = gpd.read_file(SOURCE, layer=LAYER)
    src_crs = gdf.crs
    out = gdf[["GEN", "AGS", "geometry"]].rename(
        columns={"GEN": "name", "AGS": "ags"}
    )
    out["iso"] = "DEU"
    out = out[["name", "iso", "ags", "geometry"]]
    out = out[~out.geometry.is_empty & out.geometry.is_valid]
    out = (
        out.groupby(["ags", "name", "iso"], sort=False)["geometry"]
        .agg(lambda geoms: geoms.union_all() if len(geoms) > 1 else geoms.iloc[0])
        .reset_index()
    )
    out = gpd.GeoDataFrame(out, geometry="geometry", crs=src_crs)
    out = out[["name", "iso", "ags", "geometry"]]
    out = out.sort_values("ags").reset_index(drop=True)
    out = out.to_crs("EPSG:4326")
    out.to_file(TARGET, driver="GPKG")
    print(f"wrote {len(out)} municipalities to {TARGET} (crs={out.crs})")
    return 0


if __name__ == "__main__":
    sys.exit(main())