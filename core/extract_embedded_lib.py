
# core/extract_embedded_lib.py
from __future__ import annotations
import os, stat, shutil, zipfile
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

def remove_readonly(func, path, exc_info):
    try:
        os.chmod(path, stat.S_IWRITE)
    except Exception:
        pass
    try:
        func(path)
    except Exception:
        pass

def safe_extract_zip(zip_path: Path, dest: Path) -> bool:
    try:
        with zipfile.ZipFile(zip_path, 'r') as z:
            z.extractall(dest)
        return True
    except zipfile.BadZipFile:
        return False
    except Exception:
        return False

def clean_json_from_bin(bin_path: Path) -> Optional[str]:
    try:
        text = bin_path.read_bytes().decode('utf-8', errors='ignore')
    except Exception:
        return None
    start = text.find('{"type":')
    end_marker = '"type":"Polygon"}}]}'
    end_idx = text.rfind(end_marker)
    if start >= 0 and end_idx >= 0:
        return text[start:end_idx + len(end_marker)]
    first = text.find('{'); last = text.rfind('}')
    if first >= 0 and last > first and '"type"' in text[first:last]:
        return text[first:last + 1]
    return None

def unique_dir(base: Path) -> Path:
    if not base.exists():
        return base
    idx = 1
    while True:
        candidate = base.with_name(f"{base.name}_{idx}")
        if not candidate.exists():
            return candidate
        idx += 1

def extract_embedded(src_folder: str, out_folder: str):
    SRC = Path(src_folder); OUT = Path(out_folder); TEMP = OUT / "temp"
    OUT.mkdir(parents=True, exist_ok=True); TEMP.mkdir(parents=True, exist_ok=True)

    n_xlsx = n_zip = n_nested_zips = n_bin_processed = n_json_cleaned = n_zip_bins_extracted = errors = 0
    files_found = list(SRC.glob("*.xlsx")) + list(SRC.glob("*.zip"))
    if not files_found:
        return {
            "xlsx": 0, "zip": 0, "nested_zips": 0, "bin_processed": 0,
            "zip_bins_extracted": 0, "json_cleaned": 0, "errors": 0,
            "outputs_root": str(OUT.resolve()), "outputs": []
        }

    outputs: List[Tuple[str, str]] = []

    for file in files_found:
        temp_dir = TEMP / file.stem; temp_dir.mkdir(parents=True, exist_ok=True)
        final_dir = unique_dir(OUT / file.stem); final_dir.mkdir(parents=True, exist_ok=True)

        ok = safe_extract_zip(file, temp_dir)
        if ok:
            if file.suffix.lower() == ".xlsx": n_xlsx += 1
            else: n_zip += 1
        else:
            errors += 1
            continue

        for zip_path in temp_dir.rglob("*.zip"):
            inner_dest = zip_path.with_name(zip_path.stem + "_inner")
            inner_dest.mkdir(exist_ok=True)
            if safe_extract_zip(zip_path, inner_dest):
                n_nested_zips += 1

        bin_files = [f for f in temp_dir.rglob("*.bin") if not f.name.startswith("printerSettings")]
        for bin_file in bin_files:
            n_bin_processed += 1
            if safe_extract_zip(bin_file, final_dir):
                n_zip_bins_extracted += 1
                continue
            cleaned = clean_json_from_bin(bin_file)
            if cleaned:
                out_file = final_dir / f"{bin_file.stem}.geojson"
                i = 1
                while out_file.exists():
                    out_file = final_dir / f"{bin_file.stem}_{i}.geojson"
                    i += 1
                out_file.write_text(cleaned, encoding='utf-8')
                n_json_cleaned += 1
                outputs.append((file.name, str(out_file)))
            else:
                errors += 1

        shutil.rmtree(temp_dir, onerror=remove_readonly)

    shutil.rmtree(TEMP, onerror=remove_readonly)

    return {
        "xlsx": n_xlsx, "zip": n_zip, "nested_zips": n_nested_zips,
        "bin_processed": n_bin_processed, "zip_bins_extracted": n_zip_bins_extracted,
        "json_cleaned": n_json_cleaned, "errors": errors,
        "outputs_root": str(OUT.resolve()), "outputs": outputs
    }
