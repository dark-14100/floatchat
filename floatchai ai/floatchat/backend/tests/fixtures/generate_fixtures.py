"""
FloatChat Test Fixture Generator

Generates synthetic ARGO NetCDF files for testing the ingestion pipeline.
Uses netCDF4 directly to produce files that mimic real ARGO profile structure.

Fixtures generated:
    core_single_profile.nc   — 1 profile, 10 depth levels, core variables only
    bgc_multi_profile.nc     — 3 profiles, includes DOXY and CHLA
    malformed_missing_psal.nc — valid NetCDF but missing required PSAL variable

Run directly:
    python -m tests.fixtures.generate_fixtures
"""

import os
from pathlib import Path

import netCDF4 as nc
import numpy as np


FIXTURES_DIR = Path(__file__).parent


def _pad_string(s: str, length: int) -> list[str]:
    """Pad a string to fixed length as list of chars (ARGO convention)."""
    return list(s.ljust(length)[:length])


def generate_core_single_profile():
    """
    Generate a single-profile core ARGO NetCDF file.

    Contains:
    - 1 float (platform 1901234)
    - 1 profile (cycle 42)
    - 10 depth levels
    - Core variables: PRES, TEMP, PSAL + QC flags
    - JULD = 27154.5 (2024-05-15 12:00:00 UTC)
    - Position: lat=35.5, lon=-20.3
    """
    filepath = FIXTURES_DIR / "core_single_profile.nc"

    n_prof = 1
    n_levels = 10
    string_len = 8

    ds = nc.Dataset(str(filepath), "w", format="NETCDF4")

    try:
        # Dimensions
        ds.createDimension("N_PROF", n_prof)
        ds.createDimension("N_LEVELS", n_levels)
        ds.createDimension("STRING8", string_len)

        # Global attributes
        ds.title = "Argo float vertical profile (synthetic test fixture)"
        ds.institution = "FloatChat Test Suite"
        ds.source = "Argo float"
        ds.Conventions = "Argo-3.1 CF-1.6"

        # PLATFORM_NUMBER — char array (N_PROF, STRING8)
        platform = ds.createVariable("PLATFORM_NUMBER", "S1", ("N_PROF", "STRING8"))
        platform[0, :] = _pad_string("1901234", string_len)

        # CYCLE_NUMBER — int (N_PROF,)
        cycle = ds.createVariable("CYCLE_NUMBER", "i4", ("N_PROF",), fill_value=np.int32(99999))
        cycle[0] = 42

        # DIRECTION — char (N_PROF,)
        direction = ds.createVariable("DIRECTION", "S1", ("N_PROF",))
        direction[0] = "A"

        # DATA_MODE — char (N_PROF,)
        data_mode = ds.createVariable("DATA_MODE", "S1", ("N_PROF",))
        data_mode[0] = "R"

        # JULD — days since 1950-01-01 (N_PROF,)
        juld = ds.createVariable("JULD", "f8", ("N_PROF",), fill_value=99999.0)
        juld.units = "days since 1950-01-01 00:00:00 UTC"
        juld[0] = 27154.5  # 2024-05-15 12:00:00 UTC

        # LATITUDE (N_PROF,)
        lat = ds.createVariable("LATITUDE", "f8", ("N_PROF",), fill_value=99999.0)
        lat.valid_min = -90.0
        lat.valid_max = 90.0
        lat[0] = 35.5

        # LONGITUDE (N_PROF,)
        lon = ds.createVariable("LONGITUDE", "f8", ("N_PROF",), fill_value=99999.0)
        lon.valid_min = -180.0
        lon.valid_max = 180.0
        lon[0] = -20.3

        # PRES — pressure (N_PROF, N_LEVELS)
        pres = ds.createVariable("PRES", "f4", ("N_PROF", "N_LEVELS"), fill_value=np.float32(99999.0))
        pres.units = "decibar"
        pres[0, :] = np.array([5.0, 10.0, 25.0, 50.0, 100.0, 200.0, 500.0, 1000.0, 1500.0, 2000.0], dtype=np.float32)

        # PRES_QC (N_PROF, N_LEVELS) — byte flags
        pres_qc = ds.createVariable("PRES_QC", "S1", ("N_PROF", "N_LEVELS"))
        pres_qc[0, :] = list("1111111111")

        # TEMP — temperature (N_PROF, N_LEVELS)
        temp = ds.createVariable("TEMP", "f4", ("N_PROF", "N_LEVELS"), fill_value=np.float32(99999.0))
        temp.units = "degree_Celsius"
        temp[0, :] = np.array([18.5, 18.2, 17.1, 15.3, 12.8, 9.4, 5.2, 3.1, 2.5, 2.1], dtype=np.float32)

        # TEMP_QC (N_PROF, N_LEVELS)
        temp_qc = ds.createVariable("TEMP_QC", "S1", ("N_PROF", "N_LEVELS"))
        temp_qc[0, :] = list("1111111111")

        # PSAL — salinity (N_PROF, N_LEVELS)
        psal = ds.createVariable("PSAL", "f4", ("N_PROF", "N_LEVELS"), fill_value=np.float32(99999.0))
        psal.units = "psu"
        psal[0, :] = np.array([36.1, 36.0, 35.8, 35.5, 35.2, 35.0, 34.9, 34.8, 34.75, 34.7], dtype=np.float32)

        # PSAL_QC (N_PROF, N_LEVELS)
        psal_qc = ds.createVariable("PSAL_QC", "S1", ("N_PROF", "N_LEVELS"))
        psal_qc[0, :] = list("1111111111")

    finally:
        ds.close()

    print(f"  Created: {filepath}")
    return filepath


def generate_bgc_multi_profile():
    """
    Generate a multi-profile BGC ARGO NetCDF file.

    Contains:
    - 1 float (platform 5906789)
    - 3 profiles (cycles 10, 11, 12)
    - 8 depth levels each
    - Core + BGC variables: PRES, TEMP, PSAL, DOXY, CHLA
    - Positions in the North Atlantic
    - One measurement in profile 3 is an outlier (temp=45.0)
    """
    filepath = FIXTURES_DIR / "bgc_multi_profile.nc"

    n_prof = 3
    n_levels = 8
    string_len = 8

    ds = nc.Dataset(str(filepath), "w", format="NETCDF4")

    try:
        # Dimensions
        ds.createDimension("N_PROF", n_prof)
        ds.createDimension("N_LEVELS", n_levels)
        ds.createDimension("STRING8", string_len)

        # Global attributes
        ds.title = "Argo float vertical profile (synthetic BGC test fixture)"
        ds.institution = "FloatChat Test Suite"
        ds.source = "Argo float"
        ds.Conventions = "Argo-3.1 CF-1.6"

        # PLATFORM_NUMBER
        platform = ds.createVariable("PLATFORM_NUMBER", "S1", ("N_PROF", "STRING8"))
        for i in range(n_prof):
            platform[i, :] = _pad_string("5906789", string_len)

        # CYCLE_NUMBER
        cycle = ds.createVariable("CYCLE_NUMBER", "i4", ("N_PROF",), fill_value=np.int32(99999))
        cycle[:] = [10, 11, 12]

        # DIRECTION
        direction = ds.createVariable("DIRECTION", "S1", ("N_PROF",))
        direction[:] = ["A", "A", "A"]

        # DATA_MODE
        data_mode = ds.createVariable("DATA_MODE", "S1", ("N_PROF",))
        data_mode[:] = ["A", "A", "D"]

        # JULD — three timestamps ~10 days apart
        juld = ds.createVariable("JULD", "f8", ("N_PROF",), fill_value=99999.0)
        juld.units = "days since 1950-01-01 00:00:00 UTC"
        juld[:] = [27150.0, 27160.0, 27170.0]

        # LATITUDE
        lat = ds.createVariable("LATITUDE", "f8", ("N_PROF",), fill_value=99999.0)
        lat[:] = [45.2, 45.5, 45.8]

        # LONGITUDE
        lon = ds.createVariable("LONGITUDE", "f8", ("N_PROF",), fill_value=99999.0)
        lon[:] = [-30.1, -30.5, -30.9]

        # Pressure levels (same for all profiles)
        pressures = np.array([5.0, 10.0, 25.0, 50.0, 100.0, 200.0, 500.0, 1000.0], dtype=np.float32)

        # PRES
        pres = ds.createVariable("PRES", "f4", ("N_PROF", "N_LEVELS"), fill_value=np.float32(99999.0))
        pres.units = "decibar"
        for i in range(n_prof):
            pres[i, :] = pressures

        # PRES_QC
        pres_qc = ds.createVariable("PRES_QC", "S1", ("N_PROF", "N_LEVELS"))
        for i in range(n_prof):
            pres_qc[i, :] = list("11111111")

        # TEMP — Profile 3 has an outlier at level 0 (45.0°C)
        temp_data = [
            [16.5, 16.2, 14.8, 12.1, 9.5, 6.8, 4.2, 2.8],
            [16.8, 16.4, 15.0, 12.3, 9.7, 7.0, 4.3, 2.9],
            [45.0, 16.6, 15.2, 12.5, 9.9, 7.2, 4.4, 3.0],  # outlier at index 0
        ]
        temp = ds.createVariable("TEMP", "f4", ("N_PROF", "N_LEVELS"), fill_value=np.float32(99999.0))
        temp.units = "degree_Celsius"
        for i in range(n_prof):
            temp[i, :] = np.array(temp_data[i], dtype=np.float32)

        # TEMP_QC
        temp_qc = ds.createVariable("TEMP_QC", "S1", ("N_PROF", "N_LEVELS"))
        for i in range(n_prof):
            temp_qc[i, :] = list("11111111")

        # PSAL
        psal_data = [
            [35.8, 35.7, 35.5, 35.2, 35.0, 34.9, 34.85, 34.8],
            [35.9, 35.8, 35.6, 35.3, 35.1, 35.0, 34.9, 34.85],
            [35.7, 35.6, 35.4, 35.1, 34.9, 34.8, 34.75, 34.7],
        ]
        psal = ds.createVariable("PSAL", "f4", ("N_PROF", "N_LEVELS"), fill_value=np.float32(99999.0))
        psal.units = "psu"
        for i in range(n_prof):
            psal[i, :] = np.array(psal_data[i], dtype=np.float32)

        # PSAL_QC
        psal_qc = ds.createVariable("PSAL_QC", "S1", ("N_PROF", "N_LEVELS"))
        for i in range(n_prof):
            psal_qc[i, :] = list("11111111")

        # DOXY — dissolved oxygen (BGC variable)
        doxy_data = [
            [250.0, 248.0, 240.0, 220.0, 190.0, 160.0, 140.0, 135.0],
            [252.0, 250.0, 242.0, 222.0, 192.0, 162.0, 142.0, 137.0],
            [248.0, 246.0, 238.0, 218.0, 188.0, 158.0, 138.0, 133.0],
        ]
        doxy = ds.createVariable("DOXY", "f4", ("N_PROF", "N_LEVELS"), fill_value=np.float32(99999.0))
        doxy.units = "micromole/kg"
        for i in range(n_prof):
            doxy[i, :] = np.array(doxy_data[i], dtype=np.float32)

        # DOXY_QC
        doxy_qc = ds.createVariable("DOXY_QC", "S1", ("N_PROF", "N_LEVELS"))
        for i in range(n_prof):
            doxy_qc[i, :] = list("11111111")

        # CHLA — chlorophyll (BGC variable)
        chla_data = [
            [0.5, 0.6, 1.2, 0.8, 0.3, 0.1, 0.05, 0.02],
            [0.6, 0.7, 1.4, 0.9, 0.4, 0.15, 0.06, 0.03],
            [0.4, 0.5, 1.0, 0.7, 0.25, 0.08, 0.04, 0.01],
        ]
        chla = ds.createVariable("CHLA", "f4", ("N_PROF", "N_LEVELS"), fill_value=np.float32(99999.0))
        chla.units = "mg/m3"
        for i in range(n_prof):
            chla[i, :] = np.array(chla_data[i], dtype=np.float32)

        # CHLA_QC
        chla_qc = ds.createVariable("CHLA_QC", "S1", ("N_PROF", "N_LEVELS"))
        for i in range(n_prof):
            chla_qc[i, :] = list("11111111")

    finally:
        ds.close()

    print(f"  Created: {filepath}")
    return filepath


def generate_malformed_missing_psal():
    """
    Generate a malformed NetCDF file missing the required PSAL variable.

    This is a valid NetCDF file (can be opened by xarray) but fails
    ARGO validation because PSAL is absent.

    Contains: PRES, TEMP, JULD, LATITUDE, LONGITUDE, PLATFORM_NUMBER,
              CYCLE_NUMBER — but NO PSAL.
    """
    filepath = FIXTURES_DIR / "malformed_missing_psal.nc"

    n_prof = 1
    n_levels = 5
    string_len = 8

    ds = nc.Dataset(str(filepath), "w", format="NETCDF4")

    try:
        # Dimensions
        ds.createDimension("N_PROF", n_prof)
        ds.createDimension("N_LEVELS", n_levels)
        ds.createDimension("STRING8", string_len)

        # Global attributes
        ds.title = "Malformed ARGO file (missing PSAL)"
        ds.institution = "FloatChat Test Suite"

        # PLATFORM_NUMBER
        platform = ds.createVariable("PLATFORM_NUMBER", "S1", ("N_PROF", "STRING8"))
        platform[0, :] = _pad_string("9999999", string_len)

        # CYCLE_NUMBER
        cycle = ds.createVariable("CYCLE_NUMBER", "i4", ("N_PROF",), fill_value=np.int32(99999))
        cycle[0] = 1

        # JULD
        juld = ds.createVariable("JULD", "f8", ("N_PROF",), fill_value=99999.0)
        juld[0] = 27100.0

        # LATITUDE
        lat = ds.createVariable("LATITUDE", "f8", ("N_PROF",), fill_value=99999.0)
        lat[0] = 10.0

        # LONGITUDE
        lon = ds.createVariable("LONGITUDE", "f8", ("N_PROF",), fill_value=99999.0)
        lon[0] = -50.0

        # PRES
        pres = ds.createVariable("PRES", "f4", ("N_PROF", "N_LEVELS"), fill_value=np.float32(99999.0))
        pres[0, :] = np.array([5.0, 10.0, 25.0, 50.0, 100.0], dtype=np.float32)

        # TEMP (present)
        temp = ds.createVariable("TEMP", "f4", ("N_PROF", "N_LEVELS"), fill_value=np.float32(99999.0))
        temp[0, :] = np.array([20.0, 19.5, 18.0, 15.0, 12.0], dtype=np.float32)

        # NOTE: PSAL is intentionally missing!

    finally:
        ds.close()

    print(f"  Created: {filepath}")
    return filepath


def generate_all_fixtures():
    """Generate all test fixture files."""
    print("Generating test fixtures...")
    generate_core_single_profile()
    generate_bgc_multi_profile()
    generate_malformed_missing_psal()
    print("Done! All fixtures generated.")


if __name__ == "__main__":
    generate_all_fixtures()
