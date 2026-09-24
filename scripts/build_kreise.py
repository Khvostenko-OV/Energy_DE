import sys

import geopandas as gpd
import pandas as pd

SOURCE = "data/geo/DE_VG250.gpkg"
LAYER = "vg250_krs"
TARGET = "data/boundaries/germany_districts.gpkg"


def main() -> int:
    gdf = gpd.read_file(SOURCE, layer=LAYER)
    src_crs = gdf.crs
    out = gdf[["GEN", "AGS", "geometry", "BEZ"]].rename(
        columns={"GEN": "name", "AGS": "ags"}
    )
    out["iso"] = "DEU"
    # Append 'Stadt' to kreisfreie Stadt names.  VG250 labels these two ways
    # depending on the state: 'Kreisfreie Stadt' (most states) and
    # 'Stadtkreis' (Baden-Württemberg) — both must get the suffix, or the
    # Stadtkreis duplicates its surrounding Landkreis name (Karlsruhe,
    # Heilbronn, ...).
    mask = out["BEZ"].isin(["Kreisfreie Stadt", "Stadtkreis"])
    out.loc[mask, "name"] = out.loc[mask, "name"] + " (Stadt)"
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
    assert out["name"].is_unique, "duplicate district names after (Stadt) rename"
    out = out.to_crs("EPSG:4326")
    out.to_file(TARGET, driver="GPKG")
    print(f"wrote {len(out)} kreise to {TARGET} (crs={out.crs})")
    return 0


if __name__ == "__main__":
    sys.exit(main())