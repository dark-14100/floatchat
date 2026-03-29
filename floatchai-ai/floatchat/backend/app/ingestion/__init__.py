"""
Data ingestion pipeline module.

Exports:
    parse_netcdf_file: Parse a single profile from NetCDF file
    parse_netcdf_all_profiles: Parse all profiles from multi-profile NetCDF
    ParseResult: Result dataclass from parsing
    FloatInfo: Float metadata dataclass
    ProfileInfo: Profile metadata dataclass
    MeasurementRecord: Single measurement dataclass
    clean_measurements: Clean and flag outliers in measurements
    clean_parse_result: Clean measurements from ParseResult
    CleanedMeasurement: Measurement with outlier flags
    CleaningResult: Result of cleaning process
    CleaningStats: Statistics from cleaning
"""

from app.ingestion.cleaner import (
    CleanedMeasurement,
    CleaningResult,
    CleaningStats,
    clean_measurements,
    clean_parse_result,
)
from app.ingestion.parser import (
    FloatInfo,
    MeasurementRecord,
    ParseResult,
    ProfileInfo,
    parse_netcdf_all_profiles,
    parse_netcdf_file,
)

__all__ = [
    # Parser exports
    "parse_netcdf_file",
    "parse_netcdf_all_profiles",
    "ParseResult",
    "FloatInfo",
    "ProfileInfo",
    "MeasurementRecord",
    # Cleaner exports
    "clean_measurements",
    "clean_parse_result",
    "CleanedMeasurement",
    "CleaningResult",
    "CleaningStats",
]

