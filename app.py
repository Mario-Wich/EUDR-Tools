from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components
import yaml
from pathlib import Path
import tempfile
import shutil
from typing import Optional, List, Dict, Set
from contextlib import contextmanager

from core.merge_geojson_lib import merge_geojson
from core.csv_to_geojson_lib import batch_csv_to_geojson
from core.extract_embedded_lib import extract_embedded


# -----------------------------------------------------------------------------
# App setup
# -----------------------------------------------------------------------------

st.set_page_config(
    page_title="EUDR GeoJSON Tools",
    page_icon="🌲",
    layout="wide",
)

APP_DIR = Path(__file__).resolve().parent
CFG_PATH = APP_DIR / "config.yaml"

DEFAULTS = {
    "defaults": {
        "input_folder": str(APP_DIR / "Input"),
        "output_folder": str(APP_DIR / "Output"),
        "default_country": "NZ",
    }
}


# -----------------------------------------------------------------------------
# Config handling
# -----------------------------------------------------------------------------

def load_config(path: Path, defaults: dict) -> dict:
    if not path.exists():
        return defaults
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return {**defaults, **data}
    except Exception:
        return defaults


CFG = load_config(CFG_PATH, DEFAULTS)


def cfg_get(tool: str, key: str, fallback: str) -> str:
    return (
        CFG.get(tool, {}).get(key)
        or CFG.get("defaults", {}).get(key)
        or fallback
    )


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def save_uploaded_files(uploaded_files, dest: Path) -> List[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    saved: List[Path] = []
    for upload in uploaded_files:
        target = dest / upload.name
        target.write_bytes(upload.read())
        saved.append(target)
    return saved


@contextmanager
def temp_dir(prefix: str = "eudr_"):
    p = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        yield p
    finally:
        shutil.rmtree(p, ignore_errors=True)


# -----------------------------------------------------------------------------
# Responsive helper (safe)
# -----------------------------------------------------------------------------

_WIDTH_JS = """
<script>
(function(){
  const param = '_sw';
  const w = window.innerWidth || document.documentElement.clientWidth;
  const url = new URL(window.location);
  if (url.searchParams.get(param) !== String(w)) {
    url.searchParams.set(param, String(w));
    window.location.replace(url.toString());
  }
})();
</script>
"""


def inject_width_tracker():
    components.html(_WIDTH_JS, height=0)


def get_client_width() -> Optional[int]:
    v = st.query_params.get("_sw")
    try:
        return int(v[0] if isinstance(v, list) else v)
    except Exception:
        return None


def quick_layout(width: Optional[int]) -> List[float]:
    # Always 3 columns — only ratios change
    if not width:
        return [1.2, 1.2, 1.6]
    if width < 1000:
        return [1.0, 1.0, 1.4]
    if width < 1400:
        return [1.4, 1.2, 2.0]
    return [1.8, 1.4, 2.6]


# -----------------------------------------------------------------------------
# Processor registry
# -----------------------------------------------------------------------------

PROCESSORS: Dict[str, Set[str]] = {
    "merge_geojson": {".geojson"},
    "csv_to_geojson": {".csv"},
    "extract_embedded": {".xlsx", ".zip"},
}


# -----------------------------------------------------------------------------
# UI
# -----------------------------------------------------------------------------

inject_width_tracker()
client_width = get_client_width()

st.title("EUDR Data Tools")
st.caption("Runs locally — no external sharing or uploads.")
st.subheader("Universal Quick Process")

out_root_default = Path(cfg_get("defaults", "output_folder", str(APP_DIR / "Output")))

left_col, mid_col, right_col = st.columns(
    quick_layout(client_width)
)


# -----------------------------------------------------------------------------
# Left column — Upload
# -----------------------------------------------------------------------------

with left_col:
    st.markdown("**Upload files**")
    quick_upload = st.file_uploader(
        "Drop files (.geojson, .csv, .xlsx, .zip)",
        accept_multiple_files=True,
        key="quick_uploader",
    )


# -----------------------------------------------------------------------------
# Middle column — Output
# -----------------------------------------------------------------------------

with mid_col:
    st.markdown("**Output**")
    quick_output_folder = st.text_input(
        "Output folder",
        str(out_root_default),
        key="quick_output_folder",
    )


# -----------------------------------------------------------------------------
# Right column — Detection, options, execution
# -----------------------------------------------------------------------------

with right_col:
    st.markdown("**Detected / Options**")

    detected_exts: Set[str] = set()

    if quick_upload:
        detected_exts = {
            Path(f.name).suffix.lower()
            for f in quick_upload
        }
        st.caption("Detected file types: " + ", ".join(sorted(detected_exts)))
    else:
        st.caption("No files uploaded — upload to enable quick run")

    opt_cols = st.columns(2)

    producer_country_geo = None
    producer_country_csv = None
    out_name_quick = "EUDR-Tool-Output"

    if ".geojson" in detected_exts:
        with opt_cols[0]:
            producer_country_geo = st.text_input(
                "ProducerCountry (Merge GeoJSON)",
                cfg_get(
                    "merge_geojson",
                    "default_country",
                    cfg_get("defaults", "default_country", "NZ"),
                ),
            )
        with opt_cols[0]:
            out_name_quick = st.text_input(
                "Output file name (Merge GeoJSON)",
                out_name_quick,
            )

    if ".csv" in detected_exts:
        with opt_cols[0]:
            producer_country_csv = st.text_input(
                "ProducerCountry (CSV → GeoJSON)",
                cfg_get(
                    "csv_to_geojson",
                    "default_country",
                    cfg_get("defaults", "default_country", "NZ"),
                ),
            )

    to_run: List[str] = []

    with st.form(key="quick_run_form", clear_on_submit=False):
        run_button = st.form_submit_button(
            "Run selected processors",
            type="primary",
        )

        if run_button:
            if not quick_upload:
                st.error("No files uploaded.")
            else:
                to_run = [
                    name for name, exts in PROCESSORS.items()
                    if detected_exts & exts
                ]

                if not to_run:
                    st.info("No supported file types found.")
                else:
                    st.info("Running: " + ", ".join(to_run))

                    try:
                        with temp_dir("eudr_quick_") as tmp_folder:
                            save_uploaded_files(quick_upload, tmp_folder)

                            if "merge_geojson" in to_run:
                                out_file = Path(quick_output_folder) / out_name_quick
                                final_path, summary = merge_geojson(
                                    input_folder=str(tmp_folder),
                                    output_file=str(out_file),
                                    producer_country=producer_country_geo
                                    or cfg_get("defaults", "default_country", "NZ"),
                                    add_bbox=False,
                                )
                                st.success(f"merge_geojson → {final_path}")
                                c1, c2 = st.columns(2)
                                c1.metric("Files scanned", summary["files_scanned"])
                                c2.metric("Unique features", summary["unique_features"])

                                if summary.get("errors"):
                                    with st.expander("Merge errors"):
                                        for p, msg in summary["errors"]:
                                            st.write(f"- {p}: {msg}")

                            if "csv_to_geojson" in to_run:
                                try:
                                    summary = batch_csv_to_geojson(
                                        str(tmp_folder),
                                        quick_output_folder,
                                        producer_country_csv
                                        or cfg_get("defaults", "default_country", "NZ"),
                                        None,
                                    )
                                    st.success(
                                        f"csv_to_geojson → "
                                        f"{summary['outputs']} of {summary['inputs']} files"
                                    )
                                    c1, c2 = st.columns(2)
                                    c1.metric("Inputs", summary["inputs"])
                                    c2.metric("Outputs", summary["outputs"])

                                    if summary.get("errors"):
                                        with st.expander("CSV conversion errors"):
                                            for name, msg in summary["errors"]:
                                                st.write(f"- {name}: {msg}")

                                except Exception as e:
                                    st.error(f"csv_to_geojson failed: {e}")

                            if "extract_embedded" in to_run:
                                s = extract_embedded(
                                    str(tmp_folder),
                                    quick_output_folder,
                                )
                                st.success("extract_embedded completed")
                                c1, c2, c3 = st.columns(3)
                                c1.metric(".xlsx", s["xlsx"])
                                c2.metric(".zip", s["zip"])
                                c3.metric("nested zips", s["nested_zips"])

                                if s.get("outputs"):
                                    with st.expander("Extraction outputs"):
                                        for src, outp in s["outputs"]:
                                            st.write(f"- {src} → {outp}")

                    except Exception as e:
                        st.error(f"Processing error: {e}")
