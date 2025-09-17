# helpers_knmi.py
"""
Compacte KNMI Open Data API helper voor 48h-forecast samenvatting.
- Probeert HARMONIE-AROME forecast te gebruiken (GRIB/NetCDF via Open Data API).
- Vereist KNMI_API_KEY in st.secrets of omgeving.
- Voor parsing van GRIB/NetCDF probeert hij xarray + cfgrib of netCDF4; bij ontbreken → return None.
- Output (als het lukt):
  {
    "temp_min": float,
    "temp_max": float,
    "pop_max": int,       # precipitation probability in %
    "rain_sum": float,    # mm
    "wind_max": float,    # m/s
    "first_desc": str     # optioneel
  }
De aanroeper kan bij None gewoon fallbacken naar OpenWeather.
"""

from __future__ import annotations
import os
import io
import math
import json
import time
import typing as t
from datetime import datetime, timedelta, timezone

import requests

# Dataset-namen wisselen soms; onderstaande zijn gangbare defaults
DATASET_CANDIDATES = [
    # (dataset, version)  # versienummers kunnen variëren; we pakken dynamisch de nieuwste als dit leeg loopt
    ("harmonie_arome_cy43_p1", "2"),
    ("harmonie_arome_cy43_p1", "1"),
]

def _get_secret(key: str) -> str | None:
    try:
        import streamlit as st  # alleen op runtime beschikbaar
        return st.secrets.get(key)
    except Exception:
        return os.environ.get(key)

def _auth_header() -> dict:
    key = _get_secret("KNMI_API_KEY")
    if not key:
        return {}
    return {"Authorization": key}

BASE = "https://api.dataplatform.knmi.nl/open-data/v1"

def _pick_latest_version(dataset: str) -> str | None:
    """Haal de lijst versies op en pak de laatste (string)."""
    try:
        r = requests.get(f"{BASE}/datasets/{dataset}/versions", headers=_auth_header(), timeout=10)
        if not r.ok:
            return None
        js = r.json()
        versions = js.get("versions") or js.get("data") or js  # defensief
        if isinstance(versions, list) and versions:
            # Neem max volgens semver-achtige strings; anders eerste
            return str(sorted(versions)[-1])
    except Exception:
        return None
    return None

def _list_instances(dataset: str, version: str) -> list[dict]:
    try:
        url = f"{BASE}/datasets/{dataset}/versions/{version}/instances"
        r = requests.get(url, headers=_auth_header(), timeout=15)
        if not r.ok:
            return []
        js = r.json()
        # Verwacht {"instances":[{...}]}
        inst = js.get("instances") or js.get("data") or []
        return inst if isinstance(inst, list) else []
    except Exception:
        return []

def _list_files(dataset: str, version: str, instance_id: str) -> list[dict]:
    try:
        url = f"{BASE}/datasets/{dataset}/versions/{version}/instances/{instance_id}/files"
        r = requests.get(url, headers=_auth_header(), timeout=15)
        if not r.ok:
            return []
        js = r.json()
        files = js.get("files") or js.get("data") or []
        return files if isinstance(files, list) else []
    except Exception:
        return []

def _get_file_url(dataset: str, version: str, instance_id: str, filename: str) -> str | None:
    """
    Haalt een tijdelijke pre-signed download URL op voor het bestand.
    """
    try:
        url = f"{BASE}/datasets/{dataset}/versions/{version}/instances/{instance_id}/files/{filename}/url"
        r = requests.get(url, headers=_auth_header(), timeout=15)
        if not r.ok:
            return None
        js = r.json()
        return js.get("temporaryDownloadUrl") or js.get("url")
    except Exception:
        return None

def _find_candidate_file(files: list[dict]) -> dict | None:
    """
    Kies een bruikbaar forecast-bestand.
    Heuristiek: geef voorkeur aan GRIB2 of NetCDF met 2m temp/precip/wind.
    Filenamen verschillen per release; we zoeken op hints.
    """
    if not files:
        return None
    # Probeer GRIB2 eerst
    for f in files:
        name = f.get("filename","").lower()
        if name.endswith(".grib2") or name.endswith(".grb2") or name.endswith(".grb"):
            return f
    # Dan NetCDF
    for f in files:
        name = f.get("filename","").lower()
        if name.endswith(".nc"):
            return f
    # Anders eerste
    return files[0]

def _try_parse_grib_or_netcdf_to_timeseries(content: bytes, lat: float, lon: float) -> dict | None:
    """
    Probeert met xarray + cfgrib (GRIB) of netCDF4/xarray (NetCDF) een 48h subset te lezen.
    Berekent temp_min/max, neerslagsom, wind_max, ruwe pop (benadering).
    Let op: vereist optionele libs; returnt None als parsing niet lukt.
    """
    try:
        import numpy as np
        import xarray as xr
    except Exception:
        return None

    # Heuristiek: eerst probeer GRIB via engine='cfgrib', anders standaard open_dataset (NC)
    ds = None
    bio = io.BytesIO(content)
    try:
        import cfgrib  # noqa
        try:
            ds = xr.open_dataset(bio, engine="cfgrib")
        except Exception:
            ds = None
    except Exception:
        ds = None

    if ds is None:
        # reset buffer en probeer netcdf
        bio.seek(0)
        try:
            ds = xr.open_dataset(bio)
        except Exception:
            return None

    # Vind dichtstbijzijnde gridpunt
    lat_name = None
    lon_name = None
    for a in ["latitude","lat","gridlat","y"]:
        if a in ds:
            lat_name = a; break
    for a in ["longitude","lon","gridlon","x"]:
        if a in ds:
            lon_name = a; break
    if lat_name is None or lon_name is None:
        # Mogelijk als coords onder ds.coords met andere namen staan
        for a in ["latitude","lat","y"]:
            if a in ds.coords:
                lat_name = a; break
        for a in ["longitude","lon","x"]:
            if a in ds.coords:
                lon_name = a; break
    if lat_name is None or lon_name is None:
        return None

    # Zoek index van dichtsbijzijnde coördinaat
    try:
        lat_vals = ds[lat_name].values
        lon_vals = ds[lon_name].values
        # Ondersteun 1D of 2D grids
        if lat_vals.ndim == 1 and lon_vals.ndim == 1:
            lat_idx = (np.abs(lat_vals - lat)).argmin()
            lon_idx = (np.abs(lon_vals - lon)).argmin()
            indexer = {lat_name: lat_idx, lon_name: lon_idx}
        else:
            # 2D grid: neem totale min afstand
            dist = (lat_vals - lat)**2 + (lon_vals - lon)**2
            pos = np.unravel_index(np.nanargmin(dist), dist.shape)
            indexer = {lat_name: pos[0], lon_name: pos[1]}
    except Exception:
        return None

    # Variabelen zoeken (namen verschillen per dataset)
    t2_candidates = ["t2m","t","2t","temperature","air_temperature_2m"]
    pr_candidates = ["tp","pr","precipitation","total_precipitation","apcp"]
    u10_candidates= ["u10","u","10u"]
    v10_candidates= ["v10","v","10v"]
    wspd_candidates = ["wind_speed","wspd","ws"]

    def _pick(name_list):
        for nm in name_list:
            if nm in ds:
                return nm
        # Extra poging: zoek in data_vars op substring
        for nm in ds.data_vars:
            for k in name_list:
                if k in nm.lower():
                    return nm
        return None

    t2 = _pick(t2_candidates)
    pr = _pick(pr_candidates)
    u10 = _pick(u10_candidates)
    v10 = _pick(v10_candidates)
    wspd = _pick(wspd_candidates)

    # Slice 48h venster vanaf "nu"
    try:
        tcoord = None
        for tcand in ["time","forecast_time","valid_time","t"]:
            if tcand in ds.coords:
                tcoord = tcand; break
        if tcoord is None:
            # soms in data_vars
            for tcand in ["time","forecast_time","valid_time","t"]:
                if tcand in ds:
                    tcoord = tcand; break
        if tcoord is None:
            return None

        # tijd index mask
        tvals = ds[tcoord].values
        now = np.datetime64(datetime.now(timezone.utc))
        horizon = now + np.timedelta64(48, "h")
        mask = (tvals >= now) & (tvals <= horizon)
        # fallback: als mask geen true bevat, neem eerste 16 stappen
        if not mask.any():
            sel = slice(0, min(16, tvals.shape[0]))
        else:
            sel = mask
    except Exception:
        sel = slice(0, 16)

    out = {}
    try:
        if t2:
            arr = ds[t2].isel(**indexer).sel({tcoord: sel}).values
            out["temp_min"] = float(np.nanmin(arr))
            out["temp_max"] = float(np.nanmax(arr))
    except Exception:
        pass
    try:
        if pr:
            arr = ds[pr].isel(**indexer).sel({tcoord: sel}).values
            # eenheden kunnen mm of m zijn — ruwe heuristiek:
            total = float(np.nansum(arr))
            if total < 1.0:  # mogelijk meters → naar mm
                total *= 1000.0
            out["rain_sum"] = total
            # crude POP: aandeel van stappen met >0.1mm
            pop = float((arr > 0.1).sum()) / max(1, arr.size) * 100.0
            out["pop_max"] = int(round(pop))
    except Exception:
        pass
    try:
        if wspd:
            arr = ds[wspd].isel(**indexer).sel({tcoord: sel}).values
            out["wind_max"] = float(np.nanmax(arr))
        elif u10 and v10:
            u = ds[u10].isel(**indexer).sel({tcoord: sel}).values
            v = ds[v10].isel(**indexer).sel({tcoord: sel}).values
            spd = (u**2 + v**2) ** 0.5
            out["wind_max"] = float(np.nanmax(spd))
    except Exception:
        pass

    if not out:
        return None
    # Zorg voor default keys
    out.setdefault("temp_min", None)
    out.setdefault("temp_max", None)
    out.setdefault("pop_max", 0)
    out.setdefault("rain_sum", 0.0)
    out.setdefault("wind_max", None)
    out.setdefault("first_desc", "")
    return out

def fetch_knmi_48h_summary(lat: float, lon: float) -> dict | None:
    """
    Hoofd-helper: probeert KNMI HARMONIE te lezen en vertaalt naar compacte summary.
    Retourneert None als het niet lukt (de app kan dan fallbacken naar OpenWeather).
    """
    headers = _auth_header()
    if not headers:
        return None

    # Vind dataset + versie + laatste instance
    dataset, version = None, None
    for ds_name, ver in DATASET_CANDIDATES:
        v = ver or _pick_latest_version(ds_name)
        if v is None:
            v = _pick_latest_version(ds_name)
        if v:
            instances = _list_instances(ds_name, v)
            if instances:
                dataset, version = ds_name, v
                break

    if not dataset or not version:
        return None

    instances = _list_instances(dataset, version)
    if not instances:
        return None
    # Neem laatste (meest recente)
    inst = instances[-1]
    instance_id = inst.get("instanceId") or inst.get("id") or inst.get("name")
    if not instance_id:
        return None

    files = _list_files(dataset, version, instance_id)
    if not files:
        return None
    f = _find_candidate_file(files)
    if not f:
        return None

    filename = f.get("filename")
    url = _get_file_url(dataset, version, instance_id, filename)
    if not url:
        return None

    # Download file in-memory (kan ~tientallen MB zijn)
    try:
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        content = resp.content
    except Exception:
        return None

    # Parse naar summary
    return _try_parse_grib_or_netcdf_to_timeseries(content, lat, lon)
