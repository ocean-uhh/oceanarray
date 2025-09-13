================
Development Roadmap
================

This document outlines the development roadmap for the OceanArray processing framework, focusing on features documented in the processing workflow that need implementation, technical improvements, and future functionality priorities.

.. contents::
   :local:
   :depth: 3

Status Overview
===============

The OceanArray framework currently provides a solid foundation for oceanographic data processing, but several key components documented in the processing framework require implementation or completion.

**Current Implementation Status:**

✅ **Implemented & Working**
  - Stage 1: Standardisation (``stage1.py``)  
  - Stage 2: Trimming & Clock Corrections (``stage2.py``)
  - Step 1: Time Gridding (``time_gridding.py``)
  - Clock Offset Analysis (``clock_offset.py``)
  - Data Readers (``readers.py``)
  - Basic QC visualization (``plotters.py``)
  - Configurable Logging System

🟡 **Partially Implemented**
  - Step 2: Vertical Gridding - physics-based interpolation exists (``rapid_interp.py``)

❌ **Documented but Not Implemented**
  - Stage 3: Automatic Quality Control using QARTOD standards
  - Stage 4: Calibration Information Integration (microcat focus)
  - Stage 5: Conversion to OceanSites format
  - Step 3: Concatenation of deployments  
  - Multi-site merging for boundary profiles

Priority 1: Core Missing Features
=================================

1. Stage 3: Automatic Quality Control using QARTOD Standards
------------------------------------------------------------

**Documentation**: ``docs/source/methods/auto_qc.rst``

**Purpose**: Apply systematic quality control checks following QARTOD (Quality Assurance/Quality Control of Real-Time Oceanographic Data) standards to identify and flag suspect data.

**Current State**: Basic QC functions exist in ``tools.py:run_qc()`` with salinity outlier detection, temporal spike detection, and visualization in ``plotters.py``.

**Missing Implementation**:
- Complete ``stage3.py`` module implementing full QARTOD test suite
- Integration with ``ioos_qc`` package for standardized tests
- QARTOD-compliant flag value handling (0,1,2,3,4,7,8,9)
- Configurable QC test parameters via YAML
- Automated QC report generation with summary statistics
- QC metadata preservation in NetCDF output

**QARTOD Tests to Implement**:
- Gross range test (min/max bounds)
- Climatological test (seasonal expectations)
- Spike test (temporal derivatives)
- Rate of change test
- Flat line test (stuck values)
- Multi-variate tests (T-S relationships)
- Neighbor test (spatial consistency)

**Estimated Effort**: 2-3 weeks

**Implementation Plan**:
  1. Create ``oceanarray/stage3.py`` module with ``QCProcessor`` class
  2. Design YAML-based QC configuration system for test parameters
  3. Integrate ``ioos_qc`` package for standardized QARTOD implementations
  4. Implement comprehensive QARTOD flag handling and metadata
  5. Add QC validation and reporting with summary statistics
  6. Integrate with Stage 2 → Stage 3 → Stage 4 pipeline

2. Stage 4: Calibration Information Integration (Microcat Focus)
----------------------------------------------------------------

**Documentation**: ``docs/source/methods/calibration.rst``

**Purpose**: Apply instrument calibration corrections, with initial focus on Sea-Bird MicroCAT conductivity-temperature sensors, incorporating pre- and post-deployment calibration information.

**Current State**: Basic microcat calibration functions exist in ``process_rodb.py`` for legacy RODB workflows.

**Missing Implementation**:
- Complete ``stage4.py`` module for modern CF-compliant calibration workflow
- Integration with Sea-Bird calibration certificate parsing
- Pre/post-deployment calibration comparison and drift analysis
- Conductivity cell thermal mass corrections
- Calibration uncertainty propagation through processing chain
- Calibration metadata preservation in NetCDF output
- Support for multiple calibration coefficient sets

**Calibration Features to Implement**:
- Sea-Bird calibration certificate parsing (.xmlcon, .cal files)
- Conductivity calibration equation application (frequency-based)
- Temperature calibration with ITS-90 conversion
- Pressure sensor calibration and atmospheric correction
- Thermal mass correction for conductivity measurements
- Calibration drift analysis between pre/post deployments
- Uncertainty quantification and propagation

**Estimated Effort**: 2-3 weeks

**Implementation Plan**:
  1. Create ``oceanarray/stage4.py`` module with ``CalibrationProcessor`` class
  2. Design calibration configuration system for coefficient management
  3. Implement Sea-Bird calibration certificate parsing
  4. Add thermal mass correction algorithms
  5. Create pre/post calibration comparison tools
  6. Add uncertainty propagation and metadata preservation
  7. Integrate with Stage 3 → Stage 4 → Stage 5 pipeline

3. Stage 5: OceanSites Format Conversion  
--------------------------------------------

**Documentation**: ``docs/source/methods/conversion.rst``

**Purpose**: Convert processed and calibrated data to OceanSites format specification for community data sharing and archival.

**Current State**: Some format conversion exists in ``convertOS.py``, but not the full OceanSites specification compliance.

**Missing Implementation**:
- Complete ``stage5.py`` module for OceanSites format conversion
- Global attribute validation and enforcement per OceanSites standards
- CF-convention compliance checking and validation
- Variable attribute standardization according to OceanSites vocabulary
- Comprehensive metadata template system
- Quality flag conversion to OceanSites standards

**Estimated Effort**: 2-3 weeks

**Implementation Plan**:
  1. Create ``oceanarray/stage5.py`` module with ``OceanSitesProcessor`` class
  2. Implement complete OceanSites format validation
  3. Add CF-compliance checking and enforcement
  4. Design metadata template system for OceanSites requirements
  5. Add quality flag conversion from QARTOD to OceanSites standards
  6. Integrate with Stage 4 → Stage 5 pipeline

4. Step 3: Deployment Concatenation
-----------------------------------

**Documentation**: ``docs/source/methods/concatenation.rst``

**Current State**: No implementation found.

**Missing Implementation**:
- Multi-deployment time series merging
- Gap handling and interpolation
- Consistent time-pressure grid creation
- Metadata preservation across deployments
- Quality flag propagation

**Estimated Effort**: 1-2 weeks

**Implementation Plan**:
  1. Create ``oceanarray/concatenation.py`` module
  2. Design deployment merging algorithm
  3. Implement gap filling strategies
  4. Add time-pressure grid standardization
  5. Create validation and QC checks

5. Enhanced Visualization System
--------------------------------

**Current State**: Basic plotting functions exist in ``plotters.py``.

**Missing Implementation**:
- Interactive plotting capabilities
- Multi-instrument comparison plots
- Time series overview with zoom functionality
- QC flag visualization overlays
- Deployment boundary and gap visualization
- Statistical summary plots
- Customizable plot templates

**Estimated Effort**: 2-3 weeks

**Implementation Plan**:
  1. Expand ``plotters.py`` with interactive features
  2. Add multi-instrument comparison tools
  3. Implement QC flag overlay visualization
  4. Create statistical summary plots
  5. Add customizable plotting templates
  6. Integrate with processing pipeline for automatic reporting

6. Intelligent Metadata Fallback System
----------------------------------------

**Current State**: Metadata extraction relies on explicit YAML configuration.

**Missing Implementation**:
- Filename pattern parsing for instrument type and serial number
- Fallback metadata extraction when YAML is incomplete
- Intelligent instrument identification from file patterns
- Automatic serial number detection from filenames
- Validation and warning system for inferred metadata

**Estimated Effort**: 1 week

**Implementation Plan**:
  1. Create filename parsing utilities in ``utilities.py``
  2. Design instrument type detection patterns
  3. Add serial number extraction from common filename formats
  4. Implement metadata validation and fallback logic
  5. Add logging and warnings for inferred metadata
  6. Integrate with Stage 1 processing pipeline

7. Comprehensive Mooring Processing Reports
-------------------------------------------

**Current State**: No automated reporting system exists.

**Missing Implementation**:
- HTML report generation for each mooring
- Processing completeness analysis (YAML vs actual files)
- Missing file detection and reporting
- Data coverage visualization and statistics
- Automated figure generation for all available variables
- Processing timeline and status summaries
- Integration with existing processing pipeline

**Estimated Effort**: 2-3 weeks

**Implementation Plan**:
  1. Create ``oceanarray/reporting.py`` module with ``ReportGenerator`` class
  2. Design HTML template system for mooring reports
  3. Implement file completeness checking (YAML vs ``*_use.nc`` vs raw files)
  4. Add automated visualization generation for all data variables
  5. Create processing status and timeline summaries
  6. Integrate with processing pipeline for automatic report generation
  7. Design directory structure: ``moor/proc/{mooring}/processing/{report,logs,figures}/``

Priority 2: Advanced Processing Features
=======================================

8. Multi-site Merging for Boundary Profiles
-------------------------------------------

**Documentation**: ``docs/source/methods/multisite_merging.rst``

**Current State**: No implementation found.

**Missing Implementation**:
- Cross-site data integration
- Boundary profile construction
- Static stability checking
- Site-specific weighting strategies
- Spatial interpolation methods

**Estimated Effort**: 3-4 weeks

**Implementation Plan**:
  1. Create ``oceanarray/multisite_merging.py`` module
  2. Implement spatial merging algorithms
  3. Add static stability validation
  4. Design site weighting strategies
  5. Create boundary profile outputs

9. Complete Vertical Gridding Integration
-----------------------------------------

**Documentation**: ``docs/source/methods/vertical_gridding.rst``

**Current State**: Physics-based interpolation exists in ``rapid_interp.py`` but needs integration.

**Missing Implementation**:
- Integration with main processing pipeline
- Climatology data management
- Configuration for different interpolation strategies
- Gap filling and extrapolation options
- Validation against known profiles

**Estimated Effort**: 1-2 weeks

**Implementation Plan**:
  1. Refactor ``rapid_interp.py`` for general use
  2. Create configuration system for interpolation parameters
  3. Add climatology data handling
  4. Integrate with mooring processing workflow
  5. Add validation and diagnostic tools

Priority 3: Enhanced Calibration System
======================================

10. Comprehensive Calibration Framework
--------------------------------------

**Documentation**: ``docs/source/methods/calibration.rst``

**Current State**: Basic microcat calibration exists in ``process_rodb.py``.

**Missing Implementation**:
- Multi-instrument calibration support (not just microcat)
- Structured calibration metadata handling
- Pre/post-cruise comparison workflows
- Calibration uncertainty propagation
- Automated calibration log parsing

**Estimated Effort**: 2-3 weeks

**Implementation Plan**:
  1. Expand ``process_rodb.py`` calibration functions
  2. Create calibration configuration system
  3. Add uncertainty propagation
  4. Design calibration workflow automation
  5. Add comprehensive logging and provenance

Priority 4: System Architecture Improvements
============================================

11. Methods Module Organization
------------------------------

**Current State**: Processing functions scattered across multiple modules.

**Improvement**: Create organized ``methods/`` directory structure:

.. code-block:: text

    oceanarray/methods/
    ├── __init__.py
    ├── auto_qc.py
    ├── calibration.py
    ├── concatenation.py  
    ├── conversion.py
    ├── multisite_merging.py
    └── vertical_gridding.py

**Estimated Effort**: 1 week

12. Enhanced Configuration System
--------------------------------

**Current State**: Basic logging configuration exists.

**Missing Features**:
- Global processing configuration
- Site-specific parameter management
- Processing pipeline configuration
- Validation and schema checking

**Estimated Effort**: 1-2 weeks

13. Test Coverage Improvement
-----------------------------

**Current State**: Basic tests exist in ``tests/`` directory.

**Missing Features**:
- End-to-end pipeline testing
- Method-specific unit tests
- Configuration validation tests
- Performance benchmarking

**Estimated Effort**: 2-3 weeks (ongoing)

**Technical Debt Note**: This represents accumulated testing debt where functionality exists but lacks comprehensive test coverage, making maintenance and refactoring more risky.

Priority 5: Advanced Analysis Features
=====================================

14. Data Storage Efficiency Improvements
-----------------------------------------

**Current State**: Standard NetCDF output with basic compression.

**Missing Implementation**:
- Optimized chunking strategies
- Advanced compression algorithms
- Memory-efficient processing for large datasets
- Streaming processing capabilities
- Storage format optimization

**Estimated Effort**: 2-3 weeks

**Implementation Plan**:
  1. Profile current storage bottlenecks
  2. Implement optimized chunking strategies
  3. Add advanced compression options
  4. Create memory-efficient processing pipelines
  5. Add storage format benchmarking

Development Milestones
=====================

Phase 1: Core Framework Completion (Months 1-3)
-----------------------------------------------
- Improve test coverage (address technical debt)
- Implement intelligent metadata fallback system
- Enhance visualization system
- **Implement comprehensive mooring processing reports**
- Complete auto QC framework
- Implement OceanSites format conversion
- Add deployment concatenation

Phase 2: Advanced Processing (Months 4-6)  
-----------------------------------------
- Organize methods module structure
- Enhance configuration system
- Implement multi-site merging
- Complete vertical gridding integration
- Enhance calibration framework

Phase 3: System Optimization (Months 7-9)
-----------------------------------------
- Improve data storage efficiency
- Performance optimization and profiling
- Create comprehensive documentation
- User experience improvements

Technical Debt and Maintenance
=============================

Ongoing Improvements
-------------------

1. **Code Quality**
   - Add type hints throughout codebase
   - Improve error handling and validation
   - Standardize documentation strings
   - Enhance logging throughout pipeline

2. **Performance**  
   - Profile processing bottlenecks
   - Optimize memory usage for large datasets
   - Add parallel processing capabilities
   - Implement caching strategies

3. **User Experience**
   - Create command-line interface
   - Add progress indicators for long operations
   - Improve error messages and debugging
   - Create tutorial notebooks

4. **Documentation**
   - Complete API documentation
   - Add processing examples
   - Create troubleshooting guides
   - Document best practices

Dependencies and External Integration
====================================

Key External Dependencies
------------------------
- ``ioos_qc``: For comprehensive QC implementation
- ``gsw`` (TEOS-10): For seawater property calculations  
- ``verticalnn``: For physics-based vertical interpolation
- ``xarray`` & ``netCDF4``: Core data handling
- ``dask``: For large dataset processing (future)

Integration Opportunities
------------------------
- **Pangaea**: Data publication workflows  
- **OceanSites**: Enhanced format compliance
- **ERDDAP**: Direct data ingestion capabilities

Community and Collaboration
===========================

Contribution Priorities
-----------------------
1. Method validation with known datasets
2. Cross-array compatibility testing
3. Performance benchmarking
4. User interface development
5. Processing workflow documentation

This roadmap provides a structured path toward completing the OceanArray processing framework while maintaining focus on documented requirements and practical implementation priorities.