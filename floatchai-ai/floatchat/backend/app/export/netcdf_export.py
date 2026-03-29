"""Feature 8 NetCDF export generator."""

from __future__ import annotations

import math
import os
import tempfile
from datetime import datetime, timezone
from typing import Any

import numpy as np
import xarray as xr

ARGO_EPOCH = datetime(1950, 1, 1, tzinfo=timezone.utc)
_DIMENSION_NAME = "N_LEVELS"

ARGO_NAME_MAP: dict[str, str] = {
    "pressure": "PRES",
    "temperature": "TEMP",
    "salinity": "PSAL",
    "dissolved_oxygen": "DOXY",
    "chlorophyll": "CHLA",
    "nitrate": "NITRATE",
    "ph": "PH_IN_SITU_TOTAL",
}

QC_NAME_MAP: dict[str, str] = {
    "temp_qc": "TEMP_QC",
    "psal_qc": "PSAL_QC",
    "doxy_qc": "DOXY_QC",
    "chla_qc": "CHLA_QC",
    "nitrate_qc": "NITRATE_QC",
    "ph_qc": "PH_IN_SITU_TOTAL_QC",
}

ARGO_VARIABLE_ATTRS: dict[str, dict[str, Any]] = {
    "PRES": {
        "long_name": "Sea water pressure",
        "units": "decibar",
        "_FillValue": 99999.0,
        "valid_min": 0.0,
        "valid_max": 12000.0,
    },
    "TEMP": {
        "long_name": "Sea water temperature",
        "units": "degree_Celsius",
        "_FillValue": 99999.0,
        "valid_min": -3.0,
        "valid_max": 50.0,
    },
    "PSAL": {
        "long_name": "Sea water salinity",
        "units": "psu",
        "_FillValue": 99999.0,
        "valid_min": 0.0,
        "valid_max": 50.0,
    },
    "DOXY": {
        "long_name": "Dissolved oxygen",
        "units": "micromole/kg",
        "_FillValue": 99999.0,
        "valid_min": 0.0,
        "valid_max": 800.0,
    },
    "CHLA": {
        "long_name": "Chlorophyll-a concentration",
        "units": "mg m-3",
        "_FillValue": 99999.0,
        "valid_min": 0.0,
        "valid_max": 100.0,
    },
    "NITRATE": {
        "long_name": "Nitrate concentration",
        "units": "micromole/kg",
        "_FillValue": 99999.0,
        "valid_min": 0.0,
        "valid_max": 100.0,
    },
    "PH_IN_SITU_TOTAL": {
        "long_name": "In-situ pH on total scale",
        "units": "1",
        "_FillValue": 99999.0,
        "valid_min": 6.5,
        "valid_max": 9.5,
    },
    "LATITUDE": {
        "long_name": "Latitude",
        "units": "degrees_north",
        "_FillValue": 99999.0,
        "valid_min": -90.0,
        "valid_max": 90.0,
    },
    "LONGITUDE": {
        "long_name": "Longitude",
        "units": "degrees_east",
        "_FillValue": 99999.0,
        "valid_min": -180.0,
        "valid_max": 180.0,
    },
    "JULD": {
        "long_name": "Julian day",
        "units": "days since 1950-01-01 00:00:00 UTC",
        "_FillValue": 99999.0,
    },
}

_COORD_ALIASES: set[str] = {
    "latitude",
    "LATITUDE",
    "longitude",
    "LONGITUDE",
    "juld_timestamp",
    "JULD",
    "pressure",
    "PRES",
}


def _iso_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None

    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        text = text.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc)


def _to_juld_days(value: Any) -> float:
    dt = _parse_datetime(value)
    if dt is None:
        return 99999.0
    return (dt - ARGO_EPOCH).total_seconds() / 86400.0


def _to_float(value: Any, fill_value: float = 99999.0) -> float:
    if value is None:
        return fill_value

    try:
        number = float(value)
    except (TypeError, ValueError):
        return fill_value

    if math.isnan(number) or math.isinf(number):
        return fill_value

    return number


def _to_qc(value: Any, fill_value: int = 99) -> np.int8:
    if value is None:
        return np.int8(fill_value)

    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return np.int8(fill_value)

    if number < 0 or number > 127:
        return np.int8(fill_value)

    return np.int8(number)


def _iter_present_columns(rows: list[dict[str, Any]], columns: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for column in columns:
        seen[column] = None
    for row in rows:
        for key in row.keys():
            seen[key] = None
    return list(seen.keys())


def _column_values(rows: list[dict[str, Any]], aliases: list[str]) -> list[Any]:
    values: list[Any] = []
    for row in rows:
        value = None
        for alias in aliases:
            if alias in row:
                value = row.get(alias)
                break
        values.append(value)
    return values


def _map_variable_name(column: str) -> str:
    if column in ARGO_NAME_MAP:
        return ARGO_NAME_MAP[column]
    if column in QC_NAME_MAP:
        return QC_NAME_MAP[column]
    return column


def _is_qc_column(column: str) -> bool:
    return column in QC_NAME_MAP or column.endswith("_QC")


def generate_netcdf(
    rows: list[dict[str, Any]],
    columns: list[str],
    nl_query: str,
    exported_at: datetime | None = None,
) -> bytes:
    """Generate ARGO-oriented NetCDF bytes per Feature 8 FR-08."""
    export_time = exported_at or datetime.now(timezone.utc)
    export_iso = _iso_utc(export_time)

    present_columns = _iter_present_columns(rows, columns)

    coords: dict[str, tuple[str, np.ndarray, dict[str, Any]]] = {}

    if any(alias in present_columns for alias in ["latitude", "LATITUDE"]):
        lat_values = _column_values(rows, ["latitude", "LATITUDE"])
        lat_array = np.array([_to_float(v) for v in lat_values], dtype=np.float64)
        coords["LATITUDE"] = (_DIMENSION_NAME, lat_array, ARGO_VARIABLE_ATTRS["LATITUDE"])

    if any(alias in present_columns for alias in ["longitude", "LONGITUDE"]):
        lon_values = _column_values(rows, ["longitude", "LONGITUDE"])
        lon_array = np.array([_to_float(v) for v in lon_values], dtype=np.float64)
        coords["LONGITUDE"] = (_DIMENSION_NAME, lon_array, ARGO_VARIABLE_ATTRS["LONGITUDE"])

    if any(alias in present_columns for alias in ["juld_timestamp", "JULD"]):
        juld_values = _column_values(rows, ["juld_timestamp", "JULD"])
        juld_array = np.array([_to_juld_days(v) for v in juld_values], dtype=np.float64)
        coords["JULD"] = (_DIMENSION_NAME, juld_array, ARGO_VARIABLE_ATTRS["JULD"])

    if any(alias in present_columns for alias in ["pressure", "PRES"]):
        pres_values = _column_values(rows, ["pressure", "PRES"])
        pres_array = np.array([_to_float(v) for v in pres_values], dtype=np.float64)
        coords["PRES"] = (_DIMENSION_NAME, pres_array, ARGO_VARIABLE_ATTRS["PRES"])

    data_vars: dict[str, tuple[str, np.ndarray, dict[str, Any]]] = {}

    for column in present_columns:
        if column in _COORD_ALIASES:
            continue

        variable_name = _map_variable_name(column)
        if variable_name in coords or variable_name in data_vars:
            continue

        values = _column_values(rows, [column])

        if _is_qc_column(column):
            qc_array = np.array([_to_qc(v) for v in values], dtype=np.int8)
            attrs = {
                "long_name": f"Quality control flag for {variable_name.replace('_QC', '')}",
                "units": "1",
                "_FillValue": np.int8(99),
            }
            data_vars[variable_name] = (_DIMENSION_NAME, qc_array, attrs)
            continue

        numeric_array = np.array([_to_float(v) for v in values], dtype=np.float64)
        attrs = ARGO_VARIABLE_ATTRS.get(variable_name, {"long_name": column})
        data_vars[variable_name] = (_DIMENSION_NAME, numeric_array, attrs)

    dataset = xr.Dataset(
        data_vars={
            name: xr.Variable(dims=[dims], data=data, attrs=attrs)
            for name, (dims, data, attrs) in data_vars.items()
        },
        coords={
            name: xr.Variable(dims=[dims], data=data, attrs=attrs)
            for name, (dims, data, attrs) in coords.items()
        },
        attrs={
            "title": "FloatChat ARGO Data Export",
            "institution": "FloatChat",
            "source": "Argo float",
            "history": f"Exported {export_iso} from FloatChat query: {nl_query}",
            "Conventions": "Argo-3.1 CF-1.6",
            "floatchat_query": nl_query,
            "floatchat_export_timestamp": export_iso,
        },
    )

    encoding = {
        variable_name: {"zlib": True, "complevel": 4}
        for variable_name in dataset.variables
    }

    temp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".nc", delete=False) as temp_file:
            temp_path = temp_file.name

        dataset.to_netcdf(
            temp_path,
            engine="netcdf4",
            format="NETCDF4_CLASSIC",
            encoding=encoding,
        )

        with open(temp_path, "rb") as handle:
            return handle.read()
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
