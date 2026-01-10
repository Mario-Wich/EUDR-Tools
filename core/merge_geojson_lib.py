
# core/merge_geojson_lib.py
from __future__ import annotations
import os, json, glob, hashlib
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any
from datetime import datetime

def feature_hash(feature: Dict[str, Any]) -> str:
    geom = feature.get("geometry", {})
    props = {k: v for k, v in feature.get("properties", {}).items()
             if k not in ["ProductionPlace", "ProducerCountry"]}
    data = json.dumps({"geometry": geom, "properties": props}, sort_keys=True)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()

def to_features(obj: Dict[str, Any], source_name: Optional[str] = None, producer_country: str = "Unknown") -> List[Dict[str, Any]]:
    file_name = Path(source_name).stem if source_name else "Unknown"
    t = obj.get("type")
    features: List[Dict[str, Any]] = []

    def add_props(f: Dict[str, Any]):
        f.setdefault("properties", {})
        f["properties"]["ProductionPlace"] = file_name
        f["properties"]["ProducerCountry"] = producer_country

    if t == "FeatureCollection":
        for f in obj.get("features", []):
            if f.get("type") == "Feature":
                add_props(f); features.append(f)
            elif f.get("type") in {"Point","MultiPoint","LineString","MultiLineString","Polygon","MultiPolygon","GeometryCollection"}:
                features.append({"type":"Feature","geometry":f,"properties":{"ProductionPlace":file_name,"ProducerCountry":producer_country}})
    elif t == "Feature":
        add_props(obj); features.append(obj)
    elif t in {"Point","MultiPoint","LineString","MultiLineString","Polygon","MultiPolygon","GeometryCollection"}:
        features.append({"type":"Feature","geometry":obj,"properties":{"ProductionPlace":file_name,"ProducerCountry":producer_country}})
    return features

def compute_bbox(features: List[Dict[str, Any]]) -> Optional[List[float]]:
    def walk_coords(coords, acc):
        if isinstance(coords, (list, tuple)):
            if len(coords) >= 2 and all(isinstance(c, (int, float)) for c in coords[:2]):
                x, y = coords[:2]
                acc[0] = x if acc[0] is None else min(acc[0], x)
                acc[1] = y if acc[1] is None else min(acc[1], y)
                acc[2] = x if acc[2] is None else max(acc[2], x)
                acc[3] = y if acc[3] is None else max(acc[3], y)
            else:
                for item in coords:
                    walk_coords(item, acc)
    acc = [None, None, None, None]
    for f in features:
        geom = f.get("geometry")
        if not geom:
            continue
        coords = geom.get("coordinates")
        if coords is None and geom.get("type") == "GeometryCollection":
            for g in geom.get("geometries", []):
                walk_coords(g.get("coordinates"), acc)
        else:
            walk_coords(coords, acc)
    return acc if None not in acc else None

def merge_geojson(input_folder: str, output_file: str, producer_country: str, add_bbox: bool=False) -> Tuple[str, Dict[str, Any]]:
    in_dir = Path(input_folder)
    if not in_dir.is_dir():
        raise ValueError(f"Input is not a directory: {input_folder}")

    paths = sorted(glob.glob(str(in_dir / "**" / "*.geojson"), recursive=True))
    if not paths:
        raise FileNotFoundError(f"No .geojson files found in {input_folder}")

    all_features: List[Dict[str, Any]] = []
    seen = set()
    errors: List[Tuple[str, str]] = []

    for p in paths:
        try:
            data = json.loads(Path(p).read_text(encoding="utf-8"))
            for feat in to_features(data, source_name=p, producer_country=producer_country):
                h = feature_hash(feat)
                if h not in seen:
                    seen.add(h); all_features.append(feat)
        except Exception as e:
            errors.append((p, str(e)))

    if not all_features:
        raise RuntimeError("No features collected.")

    merged: Dict[str, Any] = {"type": "FeatureCollection", "features": all_features}
    if add_bbox:
        bbox = compute_bbox(all_features)
        if bbox:
            merged["bbox"] = bbox

    out_file = Path(output_file if output_file.lower().endswith(".geojson") else f"{output_file}.geojson")
    out_file.parent.mkdir(parents=True, exist_ok=True)

    final_out = out_file
    i = 1
    while final_out.exists():
        final_out = out_file.with_name(f"{out_file.stem}_{i}{out_file.suffix}")
        i += 1

    Path(final_out).write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "files_scanned": len(paths),
        "unique_features": len(all_features),
        "errors": errors,
        "producer_country": producer_country,
        "included_bbox": "bbox" in merged,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }
    return str(final_out), summary
