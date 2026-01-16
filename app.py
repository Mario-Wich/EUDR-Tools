# app.py
from __future__ import annotations
import streamlit as st
import streamlit.components.v1 as components
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

# ----- Load config RELATIVE TO THIS FILE -----
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
        try:
            # first try buffer (works for UploadedFile)
            data = upload.getbuffer()
            target.write_bytes(data)
        except Exception:
            # fallback to read()
            target.write_bytes(upload.read())
        saved.append(target)
    return saved

def mk_temp_dir(prefix: str = "eudr_") -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))

def cleanup_temp_dir(p: Optional[Path]):
    if not p:
        return
    try:
        shutil.rmtree(p)
    except Exception:
        pass

# ---------------- Responsive helper (detect client width via URL param) ----------------
# This injects a tiny JS snippet that ensures the URL includes a `_sw` query param
# with the window width. It will reload once if needed. On resize it will debounce
# and update the param + reload (so layout adjusts). Reloads are limited by checking
# whether the param already matches the current width.
_components_html = """
<script>
(function(){
  const param = '_sw';
  const w = window.innerWidth || document.documentElement.clientWidth;
  const url = new URL(window.location);
  const cur = url.searchParams.get(param);
  // Only reload if the value actually differs to avoid loops
  if (cur !== String(w)) {
    url.searchParams.set(param, String(w));
    // Use replace to avoid creating browsing history entries
    window.location.replace(url.toString());
  }
  // Also listen for resize and debounce update (500ms)
  let t = null;
  window.addEventListener('resize', function(){
    clearTimeout(t);
    t = setTimeout(function(){
      const newWidth = window.innerWidth || document.documentElement.clientWidth;
      const u = new URL(window.location);
      if (u.searchParams.get(param) !== String(newWidth)) {
        u.searchParams.set(param, String(newWidth));
        window.location.replace(u.toString());
      }
    }, 500);
  });
})();
</script>
"""
# height=0 sometimes isn't enough; set small height to avoid vertical gap
components.html(_components_html, height=10, scrolling=False)

def get_client_width() -> Optional[int]:
    # Use st.query_params (replacement for experimental_get_query_params)
    params = st.query_params
    w = None
    if isinstance(params, dict):
        v = params.get("_sw")
        if isinstance(v, list):
            w = v[0] if v else None
        else:
            w = v
    try:
        return int(w) if w else None
    except Exception:
        return None

client_width = get_client_width()

# Decide column ratios based on width
def choose_cols_ratio(width: Optional[int], purpose: str = "quick") -> List[float]:
    # purpose may be 'quick' or 'tab'
    if width is None:
        # fallback defaults
        return [1.4, 2.6] if purpose == "quick" else [1.6, 2.4]
    if width < 700:
        return [1.0]  # single column
    if width < 1000:
        # narrow screen: two columns but right wider
        return [1.0, 1.6] if purpose == "quick" else [1.1, 1.9]
    if width < 1400:
        return [1.4, 2.6] if purpose == "quick" else [1.4, 2.6]
    if width < 2000:
        return [1.8, 2.2] if purpose == "quick" else [1.6, 2.4]
    # very wide monitors: give more space to right pane
    return [2.0, 3.0] if purpose == "quick" else [1.8, 2.8]

# -----------------------------------------------------------------------------
# Compact "Universal Quick Process" area (uses responsive columns)
st.subheader("Universal Quick Process")

# Always-visible quick output controls (left column)
out_root_default = Path(cfg_get("defaults", "output_folder", str(APP_DIR / "Output")))

ratios_quick = choose_cols_ratio(client_width, purpose="quick")
if len(ratios_quick) == 1:
    left_col = st.container()
    right_col = left_col
else:
    cols = st.columns(ratios_quick)
    left_col, right_col = cols[0], cols[1]

# LEft column: Upload files
with left_col:
    st.markdown("**Upload files**")
    quick_upload = st.file_uploader(
        "Drop files (.geojson, .csv, .xlsx, .zip)",
        accept_multiple_files=True,
        key="quick_uploader"
    )

# Right column: Output options, detected types, per-type options and results
with right_col:
    st.markdown("**Output**")
    quick_output_folder = st.text_input("Quick output folder", str(out_root_default), key="quick_output_folder")
    out_name_quick = st.text_input("Quick output file name (merged)", "quick_merged_geojson", key="quick_output_name")
    st.markdown("---")
    st.markdown("**Detected / Options**")
    detected_exts = set()
    tmp_folder: Optional[Path] = None
    if quick_upload:
        tmp_folder = mk_temp_dir("eudr_quick_")
        saved = save_uploaded_files(quick_upload, tmp_folder)
        detected_exts = {p.suffix.lower() for p in saved}
        st.caption("Detected file types: " + ", ".join(sorted(detected_exts)))
    else:
        st.caption("No files uploaded — set output and upload to enable Quick Run")

    # compact options area (use two narrow columns for option fields when wide enough)
    if len(ratios_quick) == 1:
        opt_cols = [st.container(), st.container()]
    else:
        opt_cols = st.columns(2)

    producer_country_quick_geo = None
    producer_country_quick_csv = None
    order_col_quick = None
    bbox_quick = False

    if ".geojson" in detected_exts:
        with opt_cols[0]:
            producer_country_quick_geo = st.text_input(
                "ProducerCountry (merge)",
                cfg_get("merge_geojson", "default_country", cfg_get("defaults", "default_country", "Unknown")),
                key="quick_merge_producer_country"
            )
        with opt_cols[1]:
            bbox_quick = st.checkbox("Include bbox (merge)", value=False, key="quick_merge_include_bbox")

    if ".csv" in detected_exts:
        with opt_cols[0]:
            producer_country_quick_csv = st.text_input(
                "ProducerCountry (CSV → GeoJSON)",
                cfg_get("csv_to_geojson", "default_country", cfg_get("defaults", "default_country", "NZ")),
                key="quick_csv_producer_country"
            )
        with opt_cols[1]:
            order_col_quick = st.text_input(
                "Vertex order column (optional, CSV)",
                str(cfg_get("csv_to_geojson", "vertex_order_col", "")) or "",
                key="quick_csv_vertex_order_col"
            )

    # compact run UI: group into a single form so options + run are tidy
    with st.form(key="quick_run_form", clear_on_submit=False):
        run_button = st.form_submit_button("Run selected processors", type="primary")
        if run_button:
            if not quick_upload:
                st.error("No files uploaded. Upload files before running the quick processor.")
            else:
                to_run = []
                if any(e == ".geojson" for e in detected_exts):
                    to_run.append("merge_geojson")
                if any(e == ".csv" for e in detected_exts):
                    to_run.append("csv_to_geojson")
                if any(e in (".xlsx", ".zip") for e in detected_exts):
                    to_run.append("extract_embedded")

                if not to_run:
                    st.info("No supported file types found in uploads.")
                else:
                    try:
                        results_container = st.container()
                        with results_container:
                            st.info("Running: " + ", ".join(to_run))
                            # run merge
                            if "merge_geojson" in to_run:
                                out_file = Path(quick_output_folder) / out_name_quick
                                final_path, summary = merge_geojson(
                                    input_folder=str(tmp_folder),
                                    output_file=str(out_file),
                                    producer_country=producer_country_quick_geo or cfg_get("defaults", "default_country", "NZ"),
                                    add_bbox=bbox_quick,
                                )
                                st.success(f"merge_geojson: Done → {final_path}")
                                r1, r2 = st.columns(2)
                                r1.metric("Files scanned", summary["files_scanned"])
                                r2.metric("Unique features", summary["unique_features"])
                                if summary.get("errors"):
                                    with st.expander("Merge errors (click to expand)"):
                                        for p, msg in summary["errors"]:
                                            st.write(f"- {p}: {msg}")

                            # run CSV conversion
                            if "csv_to_geojson" in to_run:
                                summary = batch_csv_to_geojson(
                                    str(tmp_folder),
                                    str(Path(quick_output_folder)),
                                    producer_country_quick_csv or cfg_get("defaults", "default_country", "NZ"),
                                    order_col_quick or None,
                                )
                                st.success(f"csv_to_geojson: Written {summary['outputs']} files (of {summary['inputs']})")
                                r1, r2 = st.columns(2)
                                r1.metric("Inputs", summary["inputs"]); r2.metric("Outputs", summary["outputs"])
                                if summary.get("errors"):
                                    with st.expander("CSV errors"):
                                        for name, msg in summary["errors"]:
                                            st.write(f"- {name}: {msg}")

                            # run extract embedded
                            if "extract_embedded" in to_run:
                                s = extract_embedded(str(tmp_folder), str(Path(quick_output_folder)))
                                st.success("extract_embedded: Extraction completed")
                                c1, c2, c3 = st.columns(3)
                                c1.metric(".xlsx", s["xlsx"]); c2.metric(".zip", s["zip"]); c3.metric("nested zips", s["nested_zips"])
                                if s.get("outputs"):
                                    with st.expander("Extraction outputs"):
                                        for src, outp in s["outputs"]:
                                            st.write(f"- {src} → {outp}")
                    except Exception as e:
                        st.error(f"Processing error: {e}")
                    finally:
                        cleanup_temp_dir(tmp_folder)

# -----------------------------------------------------------------------------
# Manual processor choice — use responsive column layout too
ratios_tab = choose_cols_ratio(client_width, purpose="tab")
with st.expander("Manual processor choice"):
    tab1, tab2, tab3 = st.tabs(["Merge GeoJSON", "CSV → GeoJSON", "Extract Embedded"])

# -------------------- TAB 1: MERGE GEOJSON --------------------
with tab1:
    if len(ratios_tab) == 1:
        left = st.container(); right = left
    else:
        left, right = st.columns(ratios_tab)
    with left:
        st.markdown("### Inputs / Options")
        in1 = st.text_input("Input folder (recursive)", cfg_get("merge_geojson", "input_folder", ""), key="merge_input_folder")
        out_dir1 = st.text_input("Output folder", cfg_get("merge_geojson", "output_folder", ""), key="merge_output_folder")
        country1 = st.text_input("ProducerCountry", cfg_get("merge_geojson", "default_country", "Unknown"), key="merge_producer_country")
        out_name1 = st.text_input("Output file name", "merged_geojson", key="merge_output_name")
        bbox1 = st.checkbox("Include bbox", value=False, key="merge_include_bbox")
    with right:
        st.markdown("### Actions / Results")
        with st.form(key="merge_form"):
            preview = st.form_submit_button("Preview count")
            run_merge = st.form_submit_button("Run merge")
            if preview:
                count = len(list(Path(in1).rglob("*.geojson"))) if Path(in1).is_dir() else 0
                st.info(f"Found {count} .geojson file(s)" if count else "No .geojson files found")
            if run_merge:
                try:
                    final_path, summary = merge_geojson(
                        input_folder=in1,
                        output_file=str(Path(out_dir1) / out_name1),
                        producer_country=country1,
                        add_bbox=bbox1,
                    )
                    st.success(f"Done → {final_path}")
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Files scanned", summary["files_scanned"])
                    c2.metric("Unique features", summary["unique_features"])
                    c3.metric("Included bbox", "Yes" if summary["included_bbox"] else "No")
                    if summary["errors"]:
                        with st.expander("Show errors"):
                            for p, msg in summary["errors"]:
                                st.write(f"- {p}: {msg}")
                except Exception as e:
                    st.error(f"Error: {e}")

# -------------------- TAB 2: CSV → GEOJSON --------------------
with tab2:
    if len(ratios_tab) == 1:
        left = st.container(); right = left
    else:
        left, right = st.columns(ratios_tab)
    with left:
        st.markdown("### Inputs / Options")
        in2 = st.text_input("CSV input folder", cfg_get("csv_to_geojson", "input_folder", ""), key="csv_input_folder")
        out2 = st.text_input("GeoJSON output folder", cfg_get("csv_to_geojson", "output_folder", ""), key="csv_output_folder")
        country2 = st.text_input("ProducerCountry", cfg_get("csv_to_geojson", "default_country", "NZ"), key="csv_producer_country")
        order_col = st.text_input("Vertex order column (optional)", str(cfg_get("csv_to_geojson", "vertex_order_col", "")) or "", key="csv_vertex_order_col")
    with right:
        st.markdown("### Actions / Results")
        with st.form(key="csv_form"):
            preview_csv = st.form_submit_button("Preview CSVs")
            run_csv = st.form_submit_button("Run conversion")
            if preview_csv:
                count = len(list(Path(in2).glob("*.csv"))) if Path(in2).is_dir() else 0
                st.info(f"Found {count} CSV file(s)" if count else "No CSV files found")
            if run_csv:
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

# -------------------- TAB 3: EXTRACT EMBEDDED --------------------
with tab3:
    if len(ratios_tab) == 1:
        left = st.container(); right = left
    else:
        left, right = st.columns(ratios_tab)
    with left:
        st.markdown("### Inputs / Options")
        in3 = st.text_input("Input folder", cfg_get("extract_embedded", "input_folder", ""), key="extract_input_folder")
        out3 = st.text_input("Output folder", cfg_get("extract_embedded", "output_folder", ""), key="extract_output_folder")
    with right:
        st.markdown("### Actions / Results")
        with st.form(key="extract_form"):
            preview_extract = st.form_submit_button("Preview inputs")
            run_extract = st.form_submit_button("Run extraction")
            if preview_extract:
                x = len(list(Path(in3).glob("*.xlsx"))) if Path(in3).is_dir() else 0
                z = len(list(Path(in3).glob("*.zip"))) if Path(in3).is_dir() else 0
                st.info(f"Found {x} .xlsx and {z} .zip file(s)")
            if run_extract:
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