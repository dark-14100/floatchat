# FloatChat -- Product Requirements Document

## Overview

FloatChat is an AI-powered conversational interface that enables users
to explore ARGO oceanographic datasets using natural language. The
system converts complex NetCDF datasets into structured data and
provides search, analytics, and visualization through a chat interface.

------------------------------------------------------------------------

# 1. Purpose / Business Context

## Background

Oceanographic datasets such as those from the ARGO float program are
massive and complex. Data is typically stored in NetCDF files and
requires domain knowledge and programming skills to interpret.

## Problem

Most potential users cannot easily query or visualize ARGO data.

Typical workflow today: 1. Download datasets 2. Write scripts 3. Process
manually 4. Generate plots

Even simple questions require technical expertise.

## Problem Size

-   4000+ active floats
-   Millions of ocean profiles
-   Global ocean coverage

## Impact

FloatChat reduces exploration time from hours to seconds and enables
non‑technical users to explore ocean datasets.

------------------------------------------------------------------------

# 2. Product Vision

Create a conversational interface for ocean data that allows users to
ask questions and instantly receive insights and visualizations.

Natural Language → Data Discovery → Visualization

------------------------------------------------------------------------

# 3. User Personas

### Ocean Researcher

Needs fast analysis and data export.

### Climate Analyst

Needs insights without coding.

### Student

Needs intuitive learning tools.

------------------------------------------------------------------------

# 4. Product Scope

## In Scope

-   NetCDF ingestion
-   Natural language queries
-   Visualization dashboard
-   Chat interface
-   Geospatial search

## Out of Scope (initial)

-   Real-time streaming
-   Authentication systems
-   Multi‑dataset integrations

------------------------------------------------------------------------

# 5. High Level Architecture

    ARGO NetCDF
          │
          ▼
    Processing Pipeline
          │
          ▼
    PostgreSQL + PostGIS
          │
          ▼
    Vector DB (FAISS/Chroma)
          │
          ▼
    RAG + LLM Engine
          │
          ▼
    API Layer
          │
          ▼
    Chat UI + Visualizations

------------------------------------------------------------------------

# 6. Functional Requirements

## Data Ingestion

-   Parse NetCDF files
-   Extract temperature, salinity, depth, location
-   Store structured data

## Vector Search

Metadata embeddings enable semantic dataset discovery.

## Natural Language Query

User query → LLM → SQL → Database results.

## Visualization

-   Maps
-   Depth plots
-   Time series
-   Comparison charts

## Export

-   CSV
-   NetCDF
-   JSON

------------------------------------------------------------------------

# 7. Technical Stack

## Frontend

-   React / Next.js
-   TailwindCSS
-   Plotly
-   Leaflet

## Backend

-   Python
-   FastAPI

## Data Processing

-   xarray
-   pandas
-   netCDF4
-   dask

## Databases

-   PostgreSQL
-   PostGIS
-   FAISS / Chroma

## AI

-   GPT / LLaMA / Mistral / Qwen
-   LangChain / LlamaIndex

## Infrastructure

-   Docker
-   Cloud Run / AWS

------------------------------------------------------------------------

# 8. Database Schema (Initial)

## floats

-   float_id
-   deployment_date
-   region

## profiles

-   profile_id
-   float_id
-   latitude
-   longitude
-   timestamp

## measurements

-   measurement_id
-   profile_id
-   depth
-   temperature
-   salinity

------------------------------------------------------------------------

# 9. Non Functional Requirements

Performance - \<3s response for simple queries

Scalability - Millions of rows supported

Reliability - Logging - retries - monitoring

Security - rate limiting - API protection

------------------------------------------------------------------------

# 10. Testing Plan

### Business Tests

Query: show salinity near equator\
Expected: correct map and dataset.

### Technical Tests

NetCDF ingestion produces valid database rows.

------------------------------------------------------------------------

# 11. Release Plan

Phase 1\
Data ingestion and database.

Phase 2\
AI query layer.

Phase 3\
Chat UI and visualizations.

Phase 4\
Public prototype.

------------------------------------------------------------------------

# 12. Open Questions

-   Which LLM will power production?
-   Dataset size for initial deployment?
-   Hosting provider?

------------------------------------------------------------------------

# 13. Future Roadmap

-   Satellite datasets
-   Real-time ocean monitoring
-   AI anomaly detection

------------------------------------------------------------------------

# 14. Version

v1.0 Initial PRD
