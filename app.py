# app.py
from __future__ import annotations
import streamlit as st
import yaml
from pathlib import Path
import tempfile
import shutil
from typing import Optional, List
from io import BytesIO

from core.merge_geojson_lib import merge_geojson
from core.csv_to_geojson_lib import batch_csv_to_geojson
from core.extract_embedded_lib import extract_embedded

st.set_page_config(page_title="EUDR GeoJSON Tools", page_icon="🌲", layout="wide")

# ----- Load config RELATIVE TO THIS FILE (fix) -----
APP_DIR = Path(__file__).resolve().parent
CFG_PATH = APP_DIR / "config.yaml"

DEFAULTS = {
    "defaults": {
        "input_folder": str(APP_DIR / "Input"),
        "output_folder": str(APP_DIR / "Output"),
        "default_country": "NZ",
    }
}
if CFG_PATH.exists():
    try:
        loaded = yaml.safe_load(CFG_PATH.read_text(encoding="utf-8")) or {}
        # shallow-merge with defaults
        for k, v in DEFAULTS.items():
            if k not in loaded:
                loaded[k] = v
        CFG = loaded
    except Exception:
        CFG = DEFAULTS
else:
    CFG = DEFAULTS

def cfg_get(tool: str, key: str, fallback: str):
    try:
        return CFG.get(tool, {}).get(key, CFG.get("defaults", {}).get(key, fallback))
    except Exception:
        return fallback

st.title("EUDR Data Tools")
st.caption("Runs locally. No external sharing or uploads.")

# ---------------- Helper utilities for uploaded files ----------------

def save_uploaded_files(uploaded_files, dest: Path) -> List[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    saved: List[Path] = []
    for upload in uploaded_files:
        target = dest / upload.name
        # uploaded_file in Streamlit has getbuffer() on bytes-like
        try:
            data = upload.getbuffer()
            target.write_bytes(data)
        except Exception:
            # fallback to read()
            target.write_bytes(upload.read())
        saved.append(target)
    return saved

def mk_temp_dir(prefix: str = "eudr_") -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))

def cleanup_temp_dir(p: Path):
    try:
        shutil.rmtree(p)
    except Exception:
        pass

# ------------- Universal quick uploader (auto-detect & auto-pick) -------------
st.subheader("Universal Quick Process")

quick_upload = st.file_uploader(
    ".geojson, .csv, .xlsx, .zip files will be saved to a temporary folder and processed",
    accept_multiple_files=True
)

# Always-visible quick output controls
out_root_default = Path(cfg_get("defaults", "output_folder", str(APP_DIR / "Output")))
quick_output_folder = st.text_input("Output Folder", str(out_root_default), key="quick_output_folder")
out_name_quick = st.text_input("Output File Name", "quick_merged_geojson", key="quick_output_name")

if quick_upload:
    tmp = mk_temp_dir("eudr_upload_")
    saved = save_uploaded_files(quick_upload, tmp)
    exts = {p.suffix.lower() for p in saved}
    st.write("Detected file types:", ", ".join(sorted(exts)))

    # Reveal additional options depending on detected file types
    st.markdown("**Quick options (customize before running)**")

    producer_country_quick_geo = None
    producer_country_quick_csv = None
    order_col_quick = None
    bbox_quick = False

    if ".geojson" in exts:
        producer_country_quick_geo = st.text_input(
            "ProducerCountry (for merge)",
            cfg_get("merge_geojson", "default_country", cfg_get("defaults", "default_country", "Unknown")),
            key="quick_merge_producer_country",
        )
        bbox_quick = st.checkbox("Include bbox (for merge)", value=False, key="quick_merge_include_bbox")

    if ".csv" in exts:
        producer_country_quick_csv = st.text_input(
            "ProducerCountry (for CSV → GeoJSON)",
            cfg_get("csv_to_geojson", "default_country", cfg_get("defaults", "default_country", "NZ")),
            key="quick_csv_producer_country",
        )

    # determine processors
    to_run = []
    if any(e == ".geojson" for e in exts):
        to_run.append("merge_geojson")
    if any(e == ".csv" for e in exts):
        to_run.append("csv_to_geojson")
    if any(e in (".xlsx", ".zip") for e in exts):
        to_run.append("extract_embedded")

    if to_run:
        st.write("Auto-picked processors:", ", ".join(to_run))
        if st.button("Run selected processors", key="quick_run"):
            # Run each selected processor and show results
            try:
                if "merge_geojson" in to_run:
                    # ensure output path is sensible
                    out_file = Path(quick_output_folder) / out_name_quick
                    final_path, summary = merge_geojson(
                        input_folder=str(tmp),
                        output_file=str(out_file),
                        producer_country=producer_country_quick_geo or cfg_get("defaults", "default_country", "NZ"),
                        add_bbox=bbox_quick,
                    )
                    st.success(f"merge_geojson: Done → {final_path}")
                    st.metric("Files scanned", summary["files_scanned"]); st.metric("Unique features", summary["unique_features"])
                    if summary.get("errors"):
                        with st.expander("Merge errors"):
                            for p, msg in summary["errors"]:
                                st.write(f"- {p}: {msg}")
                if "csv_to_geojson" in to_run:
                    summary = batch_csv_to_geojson(
                        str(tmp),
                        str(Path(quick_output_folder)),
                        producer_country_quick_csv or cfg_get("defaults", "default_country", "NZ"),
                        order_col_quick or None,
                    )
                    st.success(f"csv_to_geojson: Written {summary['outputs']} files (of {summary['inputs']})")
                    if summary.get("errors"):
                        with st.expander("CSV errors"):
                            for name, msg in summary["errors"]:
                                st.write(f"- {name}: {msg}")
                if "extract_embedded" in to_run:
                    s = extract_embedded(str(tmp), str(Path(quick_output_folder)))
                    st.success("extract_embedded: Extraction completed")
                    st.metric(".xlsx extracted", s["xlsx"]); st.metric(".zip extracted", s["zip"]); st.metric("nested zips", s["nested_zips"])
                    if s.get("outputs"):
                        with st.expander("Output files"):
                            for src, outp in s["outputs"]:
                                st.write(f"- {src} → {outp}")
            except Exception as e:
                st.error(f"Error during processing: {e}")
            finally:
                cleanup_temp_dir(tmp)
    else:
        st.info("No known processors matched the uploaded file types. Supported: .geojson, .csv, .xlsx, .zip")
        if st.button("Remove uploaded temp files", key="quick_cleanup"):
            cleanup_temp_dir(tmp)
            st.info("Temporary files removed")


# -----------------------------------------------------------------------------
with st.expander("Manual processor choice"):
    tab1, tab2, tab3 = st.tabs(["Merge GeoJSON", "CSV → GeoJSON", "Extract Embedded"])

# -------------------- TAB 1: MERGE GEOJSON --------------------
with tab1:
    st.subheader("Merge all .geojson files in a folder")
    in1 = st.text_input(
        "Input folder (recursive)",
        cfg_get("merge_geojson", "input_folder", ""),
        key="merge_input_folder",
    )
    out_dir1 = st.text_input(
        "Output folder",
        cfg_get("merge_geojson", "output_folder", ""),
        key="merge_output_folder",
    )
    country1 = st.text_input(
        "ProducerCountry",
        cfg_get("merge_geojson", "default_country", "Unknown"),
        key="merge_producer_country",
    )
    out_name1 = st.text_input(
        "Output file name",
        "merged_geojson",
        key="merge_output_name",
    )
    bbox1 = st.checkbox("Include bbox", value=False, key="merge_include_bbox")

    colA, colB = st.columns(2)
    if colA.button("Preview count", key="merge_preview_count"):
        count = len(list(Path(in1).rglob("*.geojson"))) if Path(in1).is_dir() else 0
        st.info(f"Found {count} .geojson file(s)" if count else "No .geojson files found")
        pass

    if colB.button("Run merge", type="primary", key="merge_run"):
        try:
            final_path, summary = merge_geojson(
                input_folder=in1,
                output_file=str(Path(out_dir1) / out_name1),
                producer_country=country1,
                add_bbox=bbox1,
            )
            st.success(f"Done → {final_path}")
            m1, m2, m3 = st.columns(3)
            m1.metric("Files scanned", summary["files_scanned"])
            m2.metric("Unique features", summary["unique_features"])
            m3.metric("Included bbox", "Yes" if summary["included_bbox"] else "No")
            if summary["errors"]:
                with st.expander("Show errors"):
                    for p, msg in summary["errors"]:
                        st.write(f"- {p}: {msg}")
        except Exception as e:
            st.error(f"Error: {e}")
        pass

# -------------------- TAB 2: CSV → GEOJSON (NZ) --------------------

with tab2:
    st.subheader("Batch convert CSV files to GeoJSON")
    in2 = st.text_input(
        "CSV input folder",
        cfg_get("csv_to_geojson", "input_folder", ""),
        key="csv_input_folder",
    )
    out2 = st.text_input(
        "GeoJSON output folder",
        cfg_get("csv_to_geojson", "output_folder", ""),
        key="csv_output_folder",
    )
    country2 = st.text_input(
        "ProducerCountry",
        cfg_get("csv_to_geojson", "default_country", "NZ"),
        key="csv_producer_country",
    )
    c21, c22 = st.columns(2)
    if c21.button("Preview CSVs", key="csv_preview"):
        count = len(list(Path(in2).glob("*.csv"))) if Path(in2).is_dir() else 0
        st.info(f"Found {count} CSV file(s)" if count else "No CSV files found")
        pass

    if c22.button("Run conversion", type="primary", key="csv_run"):
        try:
            summary = batch_csv_to_geojson(in2, out2, country2, order_col or None)
            st.success(f"Written {summary['outputs']} files (of {summary['inputs']})")
            m1, m2 = st.columns(2)
            m1.metric("Inputs", summary["inputs"]); m2.metric("Outputs", summary["outputs"])
            st.write(f"ProducerCountry: `{summary['country']}`")
            if summary["written"]:
                with st.expander("Written files"):
                    for src, dst, n in summary["written"]:
                        st.write(f"- {src} → {dst} ({n} features)")
            if summary["errors"]:
                with st.expander("Errors"):
                    for name, msg in summary["errors"]:
                        st.write(f"- {name}: {msg}")
        except Exception as e:
            st.error(f"Error: {e}")
        pass

# -------------------- TAB 3: EXTRACT EMBEDDED --------------------

with tab3:
    st.subheader("Extract embedded content from .xlsx/.zip (BIN, nested zips)")
    in3 = st.text_input(
        "Input folder",
        cfg_get("extract_embedded", "input_folder", ""),
        key="extract_input_folder",
    )
    out3 = st.text_input(
        "Output folder",
        cfg_get("extract_embedded", "output_folder", ""),
        key="extract_output_folder",
    )
    c31, c32 = st.columns(2)
    if c31.button("Preview inputs", key="extract_preview"):
        x = len(list(Path(in3).glob("*.xlsx"))) if Path(in3).is_dir() else 0
        z = len(list(Path(in3).glob("*.zip"))) if Path(in3).is_dir() else 0
        st.info(f"Found {x} .xlsx and {z} .zip file(s)")
        pass
    if c32.button("Run extraction", type="primary", key="extract_run"):
        try:
            s = extract_embedded(in3, out3)
            st.success("Extraction completed")
            m1, m2, m3 = st.columns(3)
            m1.metric(".xlsx extracted", s["xlsx"]); m2.metric(".zip extracted", s["zip"]); m3.metric("nested zips", s["nested_zips"])
            m4, m5, m6 = st.columns(3)
            m4.metric("BIN processed", s["bin_processed"]); m5.metric("BIN zips extracted", s["zip_bins_extracted"]); m6.metric("JSON cleaned", s["json_cleaned"])
            st.metric("Errors", s["errors"])
            st.write("Outputs root:", s["outputs_root"])
            if s["outputs"]:
                with st.expander("Output files"):
                    for src, outp in s["outputs"]:
                        st.write(f"- {src} → {outp}")
        except Exception as e:
            st.error(f"Error: {e}")
        pass