"""
FloatChat NetCDF Parser

Parses ARGO float profile files using xarray to extract oceanographic measurements.
Supports Core Argo and BGC Argo profiles (not trajectory files).

Extracted Data:
- Float metadata: WMO ID, cycle number, direction
- Positions: lat/lon/timestamp for each profile
- Measurements: temperature, salinity, and BGC parameters (if present)
"""

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import structlog
import xarray as xr

logger = structlog.get_logger(__name__)

# BGC parameters to extract (in addition to core T/S)
BGC_VARIABLES = {
    "DOXY": "oxygen",
    "CHLA": "chlorophyll_a",
    "NITRATE": "nitrate",
    "PH_IN_SITU_TOTAL": "ph",
}

# Core Argo variables
CORE_VARIABLES = {
    "TEMP": "temperature",
    "PSAL": "salinity",
}

# All measurement variables
ALL_VARIABLES = {**CORE_VARIABLES, **BGC_VARIABLES}


@dataclass
class FloatInfo:
    """Extracted float metadata."""
    wmo_id: str
    float_type: str  # 'core' or 'bgc'


@dataclass
class ProfileInfo:
    """Extracted profile metadata."""
    cycle_number: int
    direction: str  # 'A' (ascending) or 'D' (descending)
    latitude: float
    longitude: float
    timestamp: datetime
    n_levels: int


@dataclass
class MeasurementRecord:
    """Single measurement at a depth level."""
    pressure: float
    temperature: Optional[float] = None
    salinity: Optional[float] = None
    oxygen: Optional[float] = None
    chlorophyll_a: Optional[float] = None
    nitrate: Optional[float] = None
    ph: Optional[float] = None


@dataclass
class ParseResult:
    """Complete result from parsing a NetCDF file."""
    success: bool
    error_message: Optional[str] = None
    file_hash: Optional[str] = None
    float_info: Optional[FloatInfo] = None
    profile_info: Optional[ProfileInfo] = None
    measurements: list[MeasurementRecord] = field(default_factory=list)
    
    @property
    def extracted_rows_count(self) -> int:
        """Number of measurement rows extracted."""
        return len(self.measurements)


def validate_file(file_path: str) -> tuple[bool, Optional[str]]:
    """
    Validate that a file is a proper ARGO-compliant NetCDF.
    
    Checks:
    1. File can be opened by xarray
    2. Required ARGO variables are present
    
    Args:
        file_path: Path to the NetCDF file
    
    Returns:
        (True, None) if valid
        (False, error_message) if invalid
    """
    required_variables = [
        "PRES", "TEMP", "PSAL", "JULD",
        "LATITUDE", "LONGITUDE", "PLATFORM_NUMBER", "CYCLE_NUMBER",
    ]
    
    try:
        ds = xr.open_dataset(file_path, decode_cf=False, mask_and_scale=False)
    except (ValueError, OSError) as e:
        return False, f"Cannot open NetCDF file: {str(e)}"
    except Exception as e:
        return False, f"Unexpected error opening file: {str(e)}"
    
    try:
        # Check for required variables
        for var in required_variables:
            if var not in ds.data_vars and var not in ds.coords:
                return False, f"Missing required ARGO variable: {var}"
        
        # Check if it's a trajectory file (unsupported)
        if _is_trajectory_file(ds, file_path):
            return False, "Trajectory files are not supported. Please upload profile files only."
        
        return True, None
    finally:
        ds.close()


def compute_file_hash(file_path: str) -> str:
    """Compute SHA-256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def _safe_scalar(value: Any) -> Any:
    """Convert numpy scalar to Python native type."""
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, np.ndarray) and value.ndim == 0:
        return value.item()
    return value


def _extract_string(ds: xr.Dataset, var_name: str, index: int = 0) -> Optional[str]:
    """Extract string value from a dataset variable."""
    if var_name not in ds:
        return None
    
    val = ds[var_name].values
    if val.ndim == 0:
        return str(val).strip()
    if val.ndim >= 1 and len(val) > index:
        result = val[index]
        # Handle character arrays (common in ARGO files)
        if isinstance(result, np.ndarray):
            return "".join(c.decode() if isinstance(c, bytes) else str(c) for c in result).strip()
        if isinstance(result, bytes):
            return result.decode().strip()
        return str(result).strip()
    return None


def _is_trajectory_file(ds: xr.Dataset, file_path: str) -> bool:
    """Check if this is a trajectory file (not supported)."""
    filename = Path(file_path).name.lower()
    
    # Check filename patterns that indicate trajectory
    if "traj" in filename:
        return True
    
    # Check for trajectory-specific dimensions
    trajectory_dims = {"N_CYCLE", "N_MEASUREMENT"}
    if any(dim in ds.dims for dim in trajectory_dims):
        return True
    
    return False


def _determine_float_type(ds: xr.Dataset) -> str:
    """
    Determine if float is 'core' or 'bgc' based on available variables.
    
    G-14 resolution: float_type inferred from BGC variable presence.
    """
    for bgc_var in BGC_VARIABLES.keys():
        if bgc_var in ds.data_vars:
            return "bgc"
    return "core"


def _extract_float_info(ds: xr.Dataset) -> FloatInfo:
    """Extract float metadata from dataset."""
    # WMO ID = platform_number (G-15 resolution)
    wmo_id = _extract_string(ds, "PLATFORM_NUMBER")
    if not wmo_id:
        # Fallback to DATA_CENTRE + FLOAT_SERIAL_NO if available
        wmo_id = "UNKNOWN"
    
    float_type = _determine_float_type(ds)
    
    return FloatInfo(wmo_id=wmo_id, float_type=float_type)


def _extract_datetime(ds: xr.Dataset, index: int = 0) -> Optional[datetime]:
    """Extract datetime from JULD (Julian day) or reference_date + offset.
    
    Handles two cases:
    1. xarray decoded JULD to datetime64 (default open_dataset behaviour)
    2. JULD is raw float (days since 1950-01-01), e.g. when decode_cf=False
    """
    if "JULD" not in ds:
        return None
    
    juld = ds["JULD"].values
    if juld.ndim >= 1 and len(juld) > index:
        val = juld[index]
    else:
        val = juld
    
    # --- Case 1: xarray already decoded to datetime64 ---
    if isinstance(val, np.datetime64):
        if np.isnat(val):
            return None
        # Convert to Python datetime (UTC)
        ts = (val - np.datetime64("1970-01-01T00:00:00")) / np.timedelta64(1, "s")
        return datetime.fromtimestamp(float(ts), tz=timezone.utc)
    
    # --- Case 2: raw float (days since 1950-01-01) ---
    try:
        fval = float(val)
    except (TypeError, ValueError):
        return None
    
    if np.isnan(fval) or fval == 99999.0:
        return None
    
    # ARGO uses days since 1950-01-01
    reference_date = datetime(1950, 1, 1, tzinfo=timezone.utc)
    
    try:
        from datetime import timedelta
        result = reference_date + timedelta(seconds=fval * 86400)
        return result
    except (ValueError, OverflowError):
        return None


def _extract_profile_info(ds: xr.Dataset, profile_idx: int = 0) -> ProfileInfo:
    """Extract profile metadata for a specific profile index."""
    # Cycle number
    cycle = 0
    if "CYCLE_NUMBER" in ds:
        cycles = ds["CYCLE_NUMBER"].values
        if cycles.ndim >= 1 and len(cycles) > profile_idx:
            cycle = int(_safe_scalar(cycles[profile_idx]))
        else:
            cycle = int(_safe_scalar(cycles))
    
    # Direction
    direction = "A"  # Default to ascending
    if "DIRECTION" in ds:
        dirs = ds["DIRECTION"].values
        if dirs.ndim >= 1 and len(dirs) > profile_idx:
            d = dirs[profile_idx]
            direction = d.decode() if isinstance(d, bytes) else str(d)
        else:
            direction = dirs.decode() if isinstance(dirs, bytes) else str(dirs)
    
    # Position
    lat, lon = 0.0, 0.0
    if "LATITUDE" in ds:
        lats = ds["LATITUDE"].values
        lat = float(_safe_scalar(lats[profile_idx]) if lats.ndim >= 1 else lats)
    if "LONGITUDE" in ds:
        lons = ds["LONGITUDE"].values
        lon = float(_safe_scalar(lons[profile_idx]) if lons.ndim >= 1 else lons)
    
    # Timestamp
    timestamp = _extract_datetime(ds, profile_idx)
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    
    # Number of depth levels
    n_levels = 0
    if "N_LEVELS" in ds.dims:
        n_levels = ds.sizes["N_LEVELS"]
    elif "PRES" in ds:
        pres = ds["PRES"].values
        if pres.ndim == 2:
            n_levels = pres.shape[1]
        elif pres.ndim == 1:
            n_levels = len(pres)
    
    return ProfileInfo(
        cycle_number=cycle,
        direction=direction,
        latitude=lat,
        longitude=lon,
        timestamp=timestamp,
        n_levels=n_levels,
    )


def _extract_measurements(
    ds: xr.Dataset,
    profile_idx: int = 0,
) -> list[MeasurementRecord]:
    """Extract all measurements for a profile."""
    measurements = []
    
    # Get pressure array
    if "PRES" not in ds:
        logger.warning("no_pressure_variable")
        return measurements
    
    pres_var = ds["PRES"].values
    
    # Handle 2D array (N_PROF x N_LEVELS)
    if pres_var.ndim == 2:
        pressures = pres_var[profile_idx]
    else:
        pressures = pres_var
    
    # Build a dict of available variable data
    var_data: dict[str, np.ndarray] = {}
    for nc_name, our_name in ALL_VARIABLES.items():
        if nc_name in ds:
            data = ds[nc_name].values
            if data.ndim == 2:
                var_data[our_name] = data[profile_idx]
            else:
                var_data[our_name] = data
    
    # Extract measurements at each pressure level
    for i, pres in enumerate(pressures):
        if np.isnan(pres) or pres == 99999.0:
            continue
        
        record = MeasurementRecord(pressure=float(_safe_scalar(pres)))
        
        for our_name in ALL_VARIABLES.values():
            if our_name in var_data:
                data = var_data[our_name]
                if i < len(data):
                    val = data[i]
                    if not (np.isnan(val) or val == 99999.0):
                        setattr(record, our_name, float(_safe_scalar(val)))
        
        # Only include records with at least temperature or salinity
        if record.temperature is not None or record.salinity is not None:
            measurements.append(record)
    
    return measurements


def parse_netcdf_file(
    file_path: str,
    job_id: Optional[str] = None,
) -> ParseResult:
    """
    Parse an ARGO NetCDF profile file.
    
    Args:
        file_path: Path to the NetCDF file
        job_id: Optional job ID for logging context
    
    Returns:
        ParseResult with extracted data or error information
    """
    log = logger.bind(job_id=job_id, file_path=file_path)
    log.info("parse_started")
    
    try:
        # Compute file hash for deduplication
        file_hash = compute_file_hash(file_path)
        
        # Open the NetCDF file
        ds = xr.open_dataset(file_path)
        
        try:
            # Reject trajectory files (Q1 resolution)
            if _is_trajectory_file(ds, file_path):
                log.warning("trajectory_file_rejected")
                return ParseResult(
                    success=False,
                    error_message="Trajectory files are not supported. Please upload profile files only.",
                    file_hash=file_hash,
                )
            
            # Extract float info
            float_info = _extract_float_info(ds)
            log.info(
                "float_info_extracted",
                wmo_id=float_info.wmo_id,
                float_type=float_info.float_type,
            )
            
            # Extract profile info (first profile if multiple)
            profile_info = _extract_profile_info(ds, profile_idx=0)
            log.info(
                "profile_info_extracted",
                cycle_number=profile_info.cycle_number,
                n_levels=profile_info.n_levels,
            )
            
            # Extract measurements
            measurements = _extract_measurements(ds, profile_idx=0)
            log.info(
                "measurements_extracted",
                count=len(measurements),
            )
            
            return ParseResult(
                success=True,
                file_hash=file_hash,
                float_info=float_info,
                profile_info=profile_info,
                measurements=measurements,
            )
            
        finally:
            ds.close()
            
    except FileNotFoundError:
        log.error("file_not_found")
        return ParseResult(
            success=False,
            error_message=f"File not found: {file_path}",
        )
    except Exception as e:
        log.error("parse_failed", error=str(e))
        return ParseResult(
            success=False,
            error_message=f"Failed to parse NetCDF file: {str(e)}",
        )


def parse_netcdf_all_profiles(
    file_path: str,
    job_id: Optional[str] = None,
) -> list[ParseResult]:
    """
    Parse all profiles in a multi-profile NetCDF file.
    
    Some ARGO files contain multiple profiles (e.g., merged files).
    This function extracts each profile as a separate ParseResult.
    
    Args:
        file_path: Path to the NetCDF file
        job_id: Optional job ID for logging context
    
    Returns:
        List of ParseResult objects, one per profile
    """
    log = logger.bind(job_id=job_id, file_path=file_path)
    results = []
    
    try:
        file_hash = compute_file_hash(file_path)
        ds = xr.open_dataset(file_path)
        
        try:
            if _is_trajectory_file(ds, file_path):
                return [ParseResult(
                    success=False,
                    error_message="Trajectory files are not supported.",
                    file_hash=file_hash,
                )]
            
            # Determine number of profiles
            n_prof = 1
            if "N_PROF" in ds.dims:
                n_prof = ds.sizes["N_PROF"]
            elif "LATITUDE" in ds:
                lats = ds["LATITUDE"].values
                if lats.ndim >= 1:
                    n_prof = len(lats)
            
            log.info("parsing_multi_profile", n_profiles=n_prof)
            
            float_info = _extract_float_info(ds)
            
            for idx in range(n_prof):
                profile_info = _extract_profile_info(ds, profile_idx=idx)
                measurements = _extract_measurements(ds, profile_idx=idx)
                
                results.append(ParseResult(
                    success=True,
                    file_hash=file_hash,
                    float_info=float_info,
                    profile_info=profile_info,
                    measurements=measurements,
                ))
            
            return results
            
        finally:
            ds.close()
            
    except Exception as e:
        log.error("parse_failed", error=str(e))
        return [ParseResult(
            success=False,
            error_message=f"Failed to parse NetCDF file: {str(e)}",
        )]
