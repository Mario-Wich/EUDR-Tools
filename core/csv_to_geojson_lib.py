
# core/csv_to_geojson_lib.py
from __future__ import annotations
import os, json
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import pandas as pd
from shapely.geometry import Polygon, Point

def convert_csv_to_geojson(input_path: Path, output_path: Path, country: str, vertex_order_col: Optional[str]=None) -> Tuple[int, Optional[str]]:
    """Return (#features_written, error_message_if_any)."""
    try:
        df = pd.read_csv(input_path)
    except Exception as e:
        return 0, f"Failed to read {input_path.name}: {e}"

    required = ["Polygon #", "Longitude", "Latitude"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        return 0, f"Missing required column(s): {', '.join(missing)}"

    features: List[Dict[str, Any]] = []

    for poly_id, group in df.groupby("Polygon #"):
        if vertex_order_col and vertex_order_col in group.columns:
            group = group.sort_values(by=vertex_order_col)

        coords: List[Tuple[float, float]] = []
        for x, y in zip(group["Longitude"], group["Latitude"]):
            if pd.notnull(x) and pd.notnull(y):
                try:
                    coords.append((float(x), float(y)))
                except ValueError:
                    continue

        if not coords:
            continue

        if len(coords) >= 3:
            poly = Polygon(coords)
            geom = {"type": "Polygon", "coordinates": [list(map(list, poly.exterior.coords))]}
        else:
            pt = Point(coords[0])
            geom = {"type": "Point", "coordinates": [pt.x, pt.y]}

        first = group.iloc[0]
        props = {
            "Polygon #": poly_id,
            "ProducerName": first.get("Log Supplier"),
            "ProductionPlace": first.get("Forest Name"),
            "date start": first.get("Harvest Start Date"),
            "date end": first.get("Latest supplied Harvest Date"),
            "% of Supply": first.get("% of Supply"),
            "Under 4Ha?": first.get("Under 4Ha?"),
            "ProducerCountry": country,
        }

        features.append({"type": "Feature", "geometry": geom, "properties": props})

    fc = {"type": "FeatureCollection", "features": features}
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(fc, indent=2, ensure_ascii=False), encoding="utf-8")
        return len(features), None
    except Exception as e:
        return 0, f"Failed to write {output_path.name}: {e}"

def batch_csv_to_geojson(input_folder: str, output_folder: str, country: str, vertex_order_col: Optional[str]=None):
    in_dir = Path(input_folder); out_dir = Path(output_folder)
    if not in_dir.is_dir():
        raise ValueError(f"Input folder does not exist: {input_folder}")

    csv_files = sorted([p for p in in_dir.iterdir() if p.suffix.lower()==".csv"])
    if not csv_files:
        raise FileNotFoundError("No CSV files found in the input folder.")

    outputs, errors = [], []
    for csv_path in csv_files:
        out_path = out_dir / (csv_path.stem + ".geojson")
        n, err = convert_csv_to_geojson(csv_path, out_path, country, vertex_order_col)
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
