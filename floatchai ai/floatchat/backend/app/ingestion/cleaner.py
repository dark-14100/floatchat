"""
FloatChat Data Cleaner Module

Performs data normalization and outlier detection on parsed oceanographic data.
Flags values outside physically plausible ranges without removing them,
allowing downstream consumers to decide how to handle flagged data.

Outlier Bounds (from oceanographic literature):
- Temperature: -2.5°C to 40°C
- Salinity: 0 to 42 PSU
- Pressure: 0 to 12000 dbar
- Dissolved Oxygen: 0 to 600 µmol/kg
- Chlorophyll-a: 0 to 100 mg/m³
- Nitrate: 0 to 50 µmol/kg
- pH: 7.0 to 8.5
"""

from dataclasses import dataclass, field
from typing import Optional

import structlog

from app.ingestion.parser import MeasurementRecord, ParseResult

logger = structlog.get_logger(__name__)


# Outlier bounds for oceanographic variables
# Format: (min_value, max_value)
OUTLIER_BOUNDS = {
    "temperature": (-2.5, 40.0),
    "salinity": (0.0, 42.0),
    "pressure": (0.0, 12000.0),
    "oxygen": (0.0, 600.0),
    "chlorophyll_a": (0.0, 100.0),
    "nitrate": (0.0, 50.0),
    "ph": (7.0, 8.5),
}


@dataclass
class CleaningStats:
    """Statistics from the cleaning process."""
    total_records: int = 0
    flagged_records: int = 0
    flags_by_variable: dict[str, int] = field(default_factory=dict)
    
    @property
    def flagged_percentage(self) -> float:
        """Percentage of records with at least one flag."""
        if self.total_records == 0:
            return 0.0
        return (self.flagged_records / self.total_records) * 100


@dataclass
class CleanedMeasurement:
    """
    Measurement record with outlier flags.
    
    Original values are preserved; flags indicate which values are outliers.
    """
    pressure: float
    temperature: Optional[float] = None
    salinity: Optional[float] = None
    oxygen: Optional[float] = None
    chlorophyll_a: Optional[float] = None
    nitrate: Optional[float] = None
    ph: Optional[float] = None
    
    # Outlier flags (True = outlier detected)
    temperature_flag: bool = False
    salinity_flag: bool = False
    pressure_flag: bool = False
    oxygen_flag: bool = False
    chlorophyll_a_flag: bool = False
    nitrate_flag: bool = False
    ph_flag: bool = False
    
    @property
    def has_outlier(self) -> bool:
        """Check if any variable is flagged as an outlier."""
        return any([
            self.temperature_flag,
            self.salinity_flag,
            self.pressure_flag,
            self.oxygen_flag,
            self.chlorophyll_a_flag,
            self.nitrate_flag,
            self.ph_flag,
        ])


@dataclass
class CleaningResult:
    """Result of the cleaning process."""
    success: bool
    measurements: list[CleanedMeasurement] = field(default_factory=list)
    stats: CleaningStats = field(default_factory=CleaningStats)
    error_message: Optional[str] = None


def _is_outlier(value: Optional[float], variable: str) -> bool:
    """
    Check if a value is outside the valid range for a variable.
    
    Args:
        value: The value to check (None values are not outliers)
        variable: The variable name (must be in OUTLIER_BOUNDS)
    
    Returns:
        True if the value is an outlier, False otherwise
    """
    if value is None:
        return False
    
    if variable not in OUTLIER_BOUNDS:
        return False
    
    min_val, max_val = OUTLIER_BOUNDS[variable]
    return value < min_val or value > max_val


def clean_measurement(record: MeasurementRecord) -> CleanedMeasurement:
    """
    Clean a single measurement record by flagging outliers.
    
    Args:
        record: Raw measurement from the parser
    
    Returns:
        CleanedMeasurement with outlier flags set
    """
    cleaned = CleanedMeasurement(
        pressure=record.pressure,
        temperature=record.temperature,
        salinity=record.salinity,
        oxygen=record.oxygen,
        chlorophyll_a=record.chlorophyll_a,
        nitrate=record.nitrate,
        ph=record.ph,
    )
    
    # Apply outlier detection
    cleaned.pressure_flag = _is_outlier(record.pressure, "pressure")
    cleaned.temperature_flag = _is_outlier(record.temperature, "temperature")
    cleaned.salinity_flag = _is_outlier(record.salinity, "salinity")
    cleaned.oxygen_flag = _is_outlier(record.oxygen, "oxygen")
    cleaned.chlorophyll_a_flag = _is_outlier(record.chlorophyll_a, "chlorophyll_a")
    cleaned.nitrate_flag = _is_outlier(record.nitrate, "nitrate")
    cleaned.ph_flag = _is_outlier(record.ph, "ph")
    
    return cleaned


def clean_measurements(
    measurements: list[MeasurementRecord],
    job_id: Optional[str] = None,
) -> CleaningResult:
    """
    Clean a list of measurement records.
    
    Args:
        measurements: List of raw measurements from the parser
        job_id: Optional job ID for logging context
    
    Returns:
        CleaningResult with cleaned measurements and statistics
    """
    log = logger.bind(job_id=job_id) if job_id else logger
    
    log.info("cleaning_started", record_count=len(measurements))
    
    if not measurements:
        return CleaningResult(
            success=True,
            measurements=[],
            stats=CleaningStats(),
        )
    
    cleaned_measurements = []
    stats = CleaningStats(total_records=len(measurements))
    stats.flags_by_variable = {var: 0 for var in OUTLIER_BOUNDS.keys()}
    
    for record in measurements:
        cleaned = clean_measurement(record)
        cleaned_measurements.append(cleaned)
        
        # Update statistics
        if cleaned.has_outlier:
            stats.flagged_records += 1
        
        # Count flags by variable
        if cleaned.temperature_flag:
            stats.flags_by_variable["temperature"] += 1
        if cleaned.salinity_flag:
            stats.flags_by_variable["salinity"] += 1
        if cleaned.pressure_flag:
            stats.flags_by_variable["pressure"] += 1
        if cleaned.oxygen_flag:
            stats.flags_by_variable["oxygen"] += 1
        if cleaned.chlorophyll_a_flag:
            stats.flags_by_variable["chlorophyll_a"] += 1
        if cleaned.nitrate_flag:
            stats.flags_by_variable["nitrate"] += 1
        if cleaned.ph_flag:
            stats.flags_by_variable["ph"] += 1
    
    log.info(
        "cleaning_complete",
        total_records=stats.total_records,
        flagged_records=stats.flagged_records,
        flagged_percentage=f"{stats.flagged_percentage:.2f}%",
        flags_by_variable=stats.flags_by_variable,
    )
    
    return CleaningResult(
        success=True,
        measurements=cleaned_measurements,
        stats=stats,
    )


def clean_parse_result(
    parse_result: ParseResult,
    job_id: Optional[str] = None,
) -> CleaningResult:
    """
    Clean measurements from a ParseResult.
    
    Convenience function that extracts measurements from a ParseResult
    and applies cleaning.
    
    Args:
        parse_result: Result from parse_netcdf_file()
        job_id: Optional job ID for logging context
    
    Returns:
        CleaningResult with cleaned measurements and statistics
    """
    log = logger.bind(job_id=job_id) if job_id else logger
    
    if not parse_result.success:
        log.warning(
            "cleaning_skipped_failed_parse",
            error=parse_result.error_message,
        )
        return CleaningResult(
            success=False,
            error_message=f"Cannot clean failed parse: {parse_result.error_message}",
        )
    
    return clean_measurements(parse_result.measurements, job_id=job_id)


def get_outlier_bounds() -> dict[str, tuple[float, float]]:
    """
    Get the current outlier bounds configuration.
    
    Returns:
        Dictionary mapping variable names to (min, max) tuples
    """
    return OUTLIER_BOUNDS.copy()


def validate_against_bounds(
    value: float,
    variable: str,
) -> tuple[bool, Optional[str]]:
    """
    Validate a single value against outlier bounds.
    
    Args:
        value: The value to validate
        variable: The variable name
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if variable not in OUTLIER_BOUNDS:
        return True, None
    
    min_val, max_val = OUTLIER_BOUNDS[variable]
    
    if value < min_val:
        return False, f"{variable} value {value} is below minimum {min_val}"
    if value > max_val:
        return False, f"{variable} value {value} is above maximum {max_val}"
    
    return True, None
