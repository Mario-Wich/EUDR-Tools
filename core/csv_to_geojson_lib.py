from __future__ import annotations
import json
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import pandas as pd
from shapely.geometry import Polygon, Point

COLUMN_ALIASES = {
    "polygon_id": ["Polygon #", "Polygon", "Plot ID", "ShapeID"],
    "longitude": ["Longitude", "Lon", "LONG", "X"],
    "latitude": ["Latitude", "Lat", "LAT", "Y"],

    "producer": ["Log Supplier", "Supplier", "ProducerName"],
    "forest": ["Forest Name", "Forest", "ProductionPlace"],
    "date_start": ["Harvest Start Date", "Start Date"],
    "date_end": ["Latest supplied Harvest Date", "End Date"],
    "percent_supply": ["% of Supply", "Percent Supply"],
    "under_4ha": ["Under 4Ha?", "Under4Ha"],
}

def resolve_columns(
    df: pd.DataFrame,
    aliases: Dict[str, List[str]],
) -> Dict[str, Optional[str]]:
    """
    Resolve actual CSV column names to canonical names.
    Returns dict of canonical_name -> matched_column_or_None
    """
    resolved: Dict[str, Optional[str]] = {}
    for canonical, options in aliases.items():
        match = next((c for c in options if c in df.columns), None)
        resolved[canonical] = match
    return resolved

def convert_csv_to_geojson(
    input_path: Path,
    output_path: Path,
    country: str,
    vertex_order_col: Optional[str] = None,
) -> Tuple[int, Optional[str]]:
    """Return (#features_written, error_message_if_any)."""

    try:
        df = pd.read_csv(input_path)
    except Exception as e:
        return 0, f"Failed to read {input_path.name}: {e}"

    cols = resolve_columns(df, COLUMN_ALIASES)

    # Required fields
    required = ["polygon_id", "longitude", "latitude"]
    missing = [r for r in required if cols[r] is None]
    if missing:
        return 0, f"Missing required column(s): {', '.join(missing)}"

    features: List[Dict[str, Any]] = []

    for poly_id, group in df.groupby(cols["polygon_id"]):
        if vertex_order_col and vertex_order_col in group.columns:
            group = group.sort_values(by=vertex_order_col)

        coords: List[Tuple[float, float]] = []
        for x, y in zip(group[cols["longitude"]], group[cols["latitude"]]):
            if pd.notnull(x) and pd.notnull(y):
                try:
                    coords.append((float(x), float(y)))
                except ValueError:
                    continue

        if not coords:
            continue

        if len(coords) >= 3:
            poly = Polygon(coords)
            geom = {
                "type": "Polygon",
                "coordinates": [list(map(list, poly.exterior.coords))],
            }
        else:
            pt = Point(coords[0])
            geom = {
                "type": "Point",
                "coordinates": [pt.x, pt.y],
            }

        first = group.iloc[0]

        props = {
            "Polygon #": poly_id,
            "ProducerName": first.get(cols["producer"]) if cols["producer"] else None,
            "ProductionPlace": first.get(cols["forest"]) if cols["forest"] else None,
            "date start": first.get(cols["date_start"]) if cols["date_start"] else None,
            "date end": first.get(cols["date_end"]) if cols["date_end"] else None,
            "% of Supply": first.get(cols["percent_supply"]) if cols["percent_supply"] else None,
            "Under 4Ha?": first.get(cols["under_4ha"]) if cols["under_4ha"] else None,
            "ProducerCountry": country,
        }

        features.append(
            {
                "type": "Feature",
                "geometry": geom,
                "properties": props,
            }
        )

    fc = {
        "type": "FeatureCollection",
        "features": features,
    }

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(fc, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return len(features), None
    except Exception as e:
        return 0, f"Failed to write {output_path.name}: {e}"

def batch_csv_to_geojson(
    input_folder: str,
    output_folder: str,
    country: str,
    vertex_order_col: Optional[str] = None,
):
    in_dir = Path(input_folder)
    out_dir = Path(output_folder)

    if not in_dir.is_dir():
        raise ValueError(f"Input folder does not exist: {input_folder}")

    csv_files = sorted(p for p in in_dir.iterdir() if p.suffix.lower() == ".csv")
    if not csv_files:
        raise FileNotFoundError("No CSV files found in the input folder.")

    outputs, errors = [], []

    for csv_path in csv_files:
        out_path = out_dir / f"{csv_path.stem}.geojson"
        n, err = convert_csv_to_geojson(
            csv_path,
            out_path,
            country,
            vertex_order_col,
        )
        if err:
            errors.append((csv_path.name, err))
        else:
            outputs.append((csv_path.name, out_path.name, n))

    return {
        "inputs": len(csv_files),
        "outputs": len(outputs),
        "country": country,
        "vertex_order_col": vertex_order_col,
        "written": outputs,
        "errors": errors,
    }
