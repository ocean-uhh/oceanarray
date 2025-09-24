=======================================
OceanArray Data Format Specification
=======================================

This specification defines the preferred final format for data output from the oceanarray processing pipeline. It builds upon the OceanSITES data format while incorporating elements from the OG1 (OceanGliders) format and making specific choices for oceanographic mooring data.

.. contents:: Table of Contents
   :local:
   :depth: 3

1. Overview
===========

The oceanarray format follows NetCDF-4 conventions with CF (Climate and Forecast) metadata standards. This format ensures interoperability while optimizing for oceanographic time series data from moored instruments.

2. Key Design Decisions
=======================

.. warning::
   The following choices differ from referenced standards and may need future revision based on community feedback.

2.1. Deviations from OceanSITES Standard
-----------------------------------------

.. list-table:: Format Deviations Summary
   :widths: 25 35 40
   :header-rows: 1

   * - Aspect
     - OceanSITES Standard
     - OceanArray Choice
   * - Vertical Dimension
     - ``DEPTH``
     - ``N_LEVELS`` (follows CCHDO)
   * - Units Format
     - ``degrees_north``
     - ``degree_north`` (UDUNITS)
   * - Time Format
     - ``YYYY-MM-DDThh:mm:ssZ``
     - ``YYYYmmddTHHMMss`` (OG1 style)
   * - Vocabulary Requirements
     - Optional for most attributes
     - Mandatory where applicable

**Rationale for N_LEVELS**: The CCHDO community uses ``N_LEVELS`` as the standard vertical dimension name, providing better alignment with hydrographic data processing workflows.

**Rationale for UDUNITS**: Strict adherence to UDUNITS ensures compatibility with scientific software packages and avoids ambiguity in unit interpretation.

**Rationale for Time Format**: The OG1 time format provides a more compact representation suitable for attribute strings while maintaining ISO 8601 compatibility.

3. Dimensions
=============

3.1. Required Dimensions
------------------------

.. list-table:: Dimension Specifications
   :widths: 15 15 70
   :header-rows: 1

   * - Name
     - Type
     - Description
   * - ``TIME``
     - Unlimited
     - Temporal coordinate, unlimited for time series data
   * - ``N_LEVELS``
     - Fixed
     - Vertical coordinate (depth/pressure levels)
   * - ``STRING_LENGTH``
     - Fixed
     - Maximum string length for text variables (typically 64 or 128)

3.2. Optional Dimensions
------------------------

.. list-table:: Optional Dimension Specifications
   :widths: 15 15 70
   :header-rows: 1

   * - Name
     - Type
     - Description
   * - ``N_INSTRUMENTS``
     - Fixed
     - Number of distinct instruments when applicable
   * - ``N_SAMPLES``
     - Fixed
     - Raw sample dimension for burst-mode instruments

**Dimension Ordering**: Following OceanSITES convention, dimensions should be ordered as ``(TIME, Z, Y, X)``. CF recommends T,Z,Y,X order in variable definitions.

**OceanSITES Standard Dimensions**:
- ``TIME`` = unlimited (number of time steps)
- ``DEPTH`` = fixed (number of depth levels) **[OceanSITES standard]**  
- ``LATITUDE`` = 1 (dimension of LATITUDE coordinate)
- ``LONGITUDE`` = 1 (dimension of LONGITUDE coordinate)

**OceanArray Choice**: We use ``N_LEVELS`` instead of ``DEPTH`` to align with CCHDO conventions, while maintaining the same T,Z,Y,X ordering principle.

4. Coordinate Variables
=======================

4.1. Time Coordinate
--------------------

.. list-table:: TIME Variable Attributes
   :widths: 25 75
   :header-rows: 1

   * - Attribute
     - Value
   * - ``standard_name``
     - ``"time"``
   * - ``long_name``
     - ``"time"``
   * - ``units``
     - ``"seconds since 1970-01-01T00:00:00Z"``
   * - ``calendar``
     - ``"gregorian"``
   * - ``axis``
     - ``"T"``
   * - ``_FillValue``
     - ``<appropriate fill value>``

**Time Encoding**: Time values are stored as double precision seconds since the Unix epoch, providing microsecond precision suitable for high-frequency oceanographic measurements.

4.2. Spatial Coordinates
-------------------------

.. list-table:: Spatial Coordinate Attributes
   :widths: 15 25 60
   :header-rows: 1

   * - Variable
     - Required Attributes
     - Example Values
   * - ``LATITUDE``
     - | ``standard_name = "latitude"``
       | ``units = "degree_north"``
       | ``axis = "Y"``
     - ``valid_range = [-90.0, 90.0]``
   * - ``LONGITUDE``
     - | ``standard_name = "longitude"``
       | ``units = "degree_east"``
       | ``axis = "X"``
     - ``valid_range = [-180.0, 180.0]``
   * - ``DEPTH`` or ``PRESSURE``
     - | ``standard_name = "depth"`` or ``"sea_water_pressure"``
       | ``units = "meter"`` or ``"decibar"``
       | ``axis = "Z"``
       | ``positive = "down"``
     - ``valid_min = 0.0``

5. Data Variables
=================

5.1. Required Attributes
------------------------

All scientific data variables must include the following attributes:

.. list-table:: Mandatory Data Variable Attributes
   :widths: 25 75
   :header-rows: 1

   * - Attribute
     - Description
   * - ``long_name``
     - Human-readable descriptive name
   * - ``standard_name``
     - CF standard name (when applicable)
   * - ``vocabulary``
     - URL or identifier for controlled vocabulary **[OceanArray Enhancement]**
   * - ``units``
     - Physical units following UDUNITS standard
   * - ``_FillValue``
     - Fill value with same data type as variable, outside valid range
   * - ``valid_range`` or ``valid_min/max``
     - Physically meaningful data range
   * - ``ancillary_variables``
     - Associated QC variable name (e.g., ``"<PARAM>_QC"``)
   * - ``coordinates``
     - Space-separated list of coordinate variables
   * - ``sensor``
     - Sensor identifier: ``"SENSOR_<type>_<serial_number>"``

**Example Data Variable**:

.. code-block:: none

   TEMP:long_name = "Sea Water Temperature";
   TEMP:standard_name = "sea_water_temperature";
   TEMP:vocabulary = "https://vocab.nerc.ac.uk/collection/P07/current/";
   TEMP:units = "degree_Celsius";
   TEMP:_FillValue = -999.0f;
   TEMP:valid_range = -2.0f, 40.0f;
   TEMP:ancillary_variables = "TEMP_QC";
   TEMP:coordinates = "TIME LONGITUDE LATITUDE DEPTH";
   TEMP:sensor = "SENSOR_CTD_12345";

**Vocabulary Enhancement**: Unlike base OceanSITES, oceanarray format mandates vocabulary specification to ensure semantic interoperability and automated data discovery.

6. Quality Control Variables
============================

6.1. QC Flag System
-------------------

Following the OceanSITES quality control flag system:

.. list-table:: QC Flag Values and Meanings
   :widths: 10 30 60
   :header-rows: 1

   * - Flag
     - OceanSITES Meaning
     - Description
   * - 0
     - ``unknown``
     - Quality not evaluated or unknown
   * - 1
     - ``good_data``
     - Data passed all quality tests
   * - 2
     - ``probably_good_data``
     - Data likely good but not fully verified
   * - 3
     - ``potentially_correctable_bad_data``
     - Bad data that might be correctable
   * - 4
     - ``bad_data``
     - Data failed critical quality tests
   * - 7
     - ``nominal_value``
     - Constant or reference value
   * - 8
     - ``interpolated_value``
     - Gap-filled or estimated data
   * - 9
     - ``missing_value``
     - Data point is missing

**QC Variable Attributes**:

.. code-block:: none

   <PARAM>_QC:long_name = "<PARAM> Quality Flag";
   <PARAM>_QC:flag_values = 0, 1, 2, 3, 4, 7, 8, 9;
   <PARAM>_QC:flag_meanings = "unknown good_data probably_good_data potentially_correctable_bad_data bad_data nominal_value interpolated_value missing_value";
   <PARAM>_QC:valid_range = 0, 9;

6.2. Comparison with IOC Standards
----------------------------------

.. list-table:: QC Flag Comparison: OceanSITES vs IOC
   :widths: 10 40 50
   :header-rows: 1

   * - Flag
     - OceanSITES Interpretation
     - IOC Interpretation
   * - 2
     - ``probably_good_data`` (assumes quality)
     - ``Test was not evaluated`` (no assumption)
   * - 3
     - ``potentially_correctable_bad_data`` (implies fixable)
     - ``Suspect data`` (subjective failure)

**OceanArray Choice**: We follow the OceanSITES interpretation as it better aligns with time series oceanographic data practices where data quality assessment is often probabilistic rather than binary.

7. Global Attributes
====================

7.1. Dataset Identification
----------------------------

**Core OceanSITES Discovery Attributes**

.. list-table:: OceanSITES Dataset Identification
   :widths: 20 15 65
   :header-rows: 1

   * - Attribute
     - Requirement
     - Description / Example
   * - ``site_code``
     - Required (GDAC)
     - | OceanSITES site name where platform installed
       | ``site_code="CIS"`` **[OceanArray: adapt to local naming]**
   * - ``platform_code``
     - Required (GDAC)
     - | Unique platform identifier assigned by PI or provider  
       | ``platform_code="CIS-1"``
   * - ``data_mode``
     - Required (GDAC)
     - | Data quality mode: R (real-time), P (provisional), D (delayed)
       | ``data_mode="D"`` **[OceanArray: typically "D" for processed data]**
   * - ``title``
     - Required
     - | Free-format dataset description for human readers
       | ``title="Processed CIS-1 Mooring Time Series Data"``
   * - ``summary``
     - Required
     - | Detailed description (up to 100 words) for data discovery
       | ``summary="Oceanographic mooring data processed through oceanarray pipeline..."``
   * - ``id``
     - Required
     - | Unique dataset identifier (often filename without .nc)
       | ``id="OA_CIS-1_L2_200502_TS"``
   * - ``naming_authority``
     - Required
     - | Organization managing dataset names
       | ``naming_authority="oceanarray"`` **[OceanArray: not "OceanSITES"]**
   * - ``wmo_platform_code``
     - Optional
     - | WMO identifier unique within OceanSITES project
       | ``wmo_platform_code="48409"``
   * - ``source``
     - Required
     - | Platform type from SeaVoX L06 vocabulary
       | ``source="subsurface mooring"``
   * - ``theme``
     - Optional
     - | OceanSITES theme areas (comma-separated)
       | ``theme="Air/sea flux reference, Global Ocean Watch"``

**OceanArray Adaptations**: 
- Use ``naming_authority="oceanarray"`` to distinguish processed datasets
- ``data_mode`` typically "D" (delayed-mode) for quality-controlled processed data  
- Adapt ``site_code`` and ``platform_code`` to local deployment naming conventions

**Additional Processing Attributes**

.. list-table:: OceanArray Processing Attributes
   :widths: 25 75
   :header-rows: 1

   * - Attribute
     - Description
   * - ``processing_level``
     - Processing level from OceanSITES reference table 3
   * - ``QC_indicator``
     - Overall dataset quality: "excellent", "probably good", "mixed", "unknown"
   * - ``format_version``
     - OceanArray format version (e.g., "OceanArray-1.0")
   * - ``data_type``
     - ``"OceanSITES time-series data"`` (maintains compatibility)

7.2. Contributor Information
----------------------------

Following OG1 pattern, consolidating OceanSITES ``creator_*`` and ``principal_investigator_*`` fields into comprehensive ``contributor_*`` attributes that support multiple contributors.

.. list-table:: Contributor Attributes (OceanArray Format)
   :widths: 25 15 60
   :header-rows: 1

   * - Attribute
     - Requirement
     - Description / Example
   * - ``contributor_name``
     - Required
     - | Semi-colon separated list of contributor full names
       | ``contributor_name = "Dr. Jane Smith; Dr. John Doe; Prof. Alice Johnson"``
   * - ``contributor_email``
     - Required
     - | Semi-colon separated list of contact email addresses
       | ``contributor_email = "jane.smith@whoi.edu; john.doe@noc.ac.uk; alice.johnson@uni.edu"``
   * - ``contributor_role``
     - Required
     - | Semi-colon separated list of roles (controlled vocabulary)
       | ``contributor_role = "principalInvestigator; coInvestigator; dataManager"``
   * - ``contributor_role_vocabulary``
     - Required
     - | URL for role vocabulary **[OceanArray Enhancement]**
       | ``contributor_role_vocabulary = "http://vocab.nerc.ac.uk/collection/W08/"``
   * - ``contributor_institution``
     - Required
     - | Semi-colon separated list of institutional affiliations
       | ``contributor_institution = "WHOI; NOC; University of Ocean Sciences"``
   * - ``contributor_institution_vocabulary``
     - Optional
     - | URL for institution vocabulary **[OceanArray Enhancement]**
       | ``contributor_institution_vocabulary = "https://edmo.seadatanet.org/"``
   * - ``contributor_orcid``
     - Recommended
     - | Semi-colon separated list of ORCID identifiers
       | ``contributor_orcid = "https://orcid.org/0000-0001-2345-6789; https://orcid.org/0000-0002-3456-7890; https://orcid.org/0000-0003-4567-8901"``

**Multiple Contributors Example**:

.. code-block:: none

   contributor_name = "Dr. Jane Smith; Dr. John Doe; Prof. Alice Johnson";
   contributor_email = "jane.smith@whoi.edu; john.doe@noc.ac.uk; alice.johnson@uni.edu";
   contributor_role = "principalInvestigator; coInvestigator; dataManager";
   contributor_role_vocabulary = "http://vocab.nerc.ac.uk/collection/W08/";
   contributor_institution = "Woods Hole Oceanographic Institution; National Oceanography Centre; University of Ocean Sciences";
   contributor_institution_vocabulary = "https://edmo.seadatanet.org/";
   contributor_orcid = "https://orcid.org/0000-0001-2345-6789; https://orcid.org/0000-0002-3456-7890; https://orcid.org/0000-0003-4567-8901";

**Single Contributor Example**:

.. code-block:: none

   contributor_name = "Dr. Jane Smith";
   contributor_email = "jane.smith@whoi.edu";
   contributor_role = "principalInvestigator";
   contributor_role_vocabulary = "http://vocab.nerc.ac.uk/collection/W08/";
   contributor_institution = "Woods Hole Oceanographic Institution";
   contributor_institution_vocabulary = "https://edmo.seadatanet.org/";
   contributor_orcid = "https://orcid.org/0000-0001-2345-6789";

**Controlled Vocabulary for Roles**:

.. list-table:: Standard Contributor Roles
   :widths: 25 75
   :header-rows: 1

   * - Role Value
     - Description
   * - ``principalInvestigator``
     - Lead scientist responsible for the project
   * - ``coInvestigator``
     - Co-lead or significant contributor to project science
   * - ``dataManager``
     - Responsible for data processing, quality control, and management
   * - ``technician``
     - Technical support for instrument deployment and maintenance
   * - ``student``
     - Graduate or undergraduate student contributor
   * - ``postdoc``
     - Postdoctoral researcher contributor
   * - ``collaborator``
     - External collaborator or visiting scientist

**OceanSITES Field Mapping**:

.. list-table:: OceanSITES to OceanArray Field Consolidation
   :widths: 40 60
   :header-rows: 1

   * - OceanSITES Fields (Multiple)
     - OceanArray Consolidated Field
   * - ``principal_investigator``
     - | ``contributor_name`` (role: principalInvestigator)
   * - ``principal_investigator_email``
     - | ``contributor_email`` (role: principalInvestigator)
   * - ``principal_investigator_url``
     - | Use ORCID in ``contributor_orcid``
   * - ``principal_investigator_id``
     - | ``contributor_orcid``
   * - ``creator_name``
     - | ``contributor_name`` (role: dataManager)
   * - ``creator_email``
     - | ``contributor_email`` (role: dataManager)
   * - ``creator_url``
     - | Use ORCID in ``contributor_orcid``
   * - ``creator_id``
     - | ``contributor_orcid``
   * - ``creator_institution``
     - | ``contributor_institution``

**Implementation Notes**:

1. **Ordering**: Contributors should be listed in order of contribution significance
2. **Separator**: Use semi-colon (`;`) separation for multiple values, consistent with ACDD
3. **Consistency**: All contributor attribute lists must have the same number of entries
4. **ORCID Priority**: Prefer ORCID identifiers over URLs for persistent identification
5. **Vocabulary Enhancement**: Unlike base OceanSITES, vocabulary URLs are required for semantic clarity

**Validation Example**:

.. code-block:: python

   # Valid: 3 contributors, all attributes have 3 entries
   contributor_name = "A; B; C"
   contributor_email = "a@x.edu; b@y.edu; c@z.edu" 
   contributor_role = "principalInvestigator; coInvestigator; dataManager"
   
   # Invalid: mismatched count
   contributor_name = "A; B; C"
   contributor_email = "a@x.edu; b@y.edu"  # Missing third email

**OceanArray Enhancement**: This consolidation reduces metadata redundancy while maintaining full attribution information and supporting multiple contributors per dataset, following OG1 best practices.

7.3. Temporal Attributes
------------------------

.. list-table:: Time-related Global Attributes
   :widths: 30 70
   :header-rows: 1

   * - Attribute
     - Description / Format
   * - ``time_coverage_start``
     - ``YYYYmmddTHHMMss`` (OG1 format)
   * - ``time_coverage_end``
     - ``YYYYmmddTHHMMss`` (OG1 format)
   * - ``time_coverage_duration``
     - ISO 8601 duration format
   * - ``date_created``
     - ``YYYYmmddTHHMMss`` (creation timestamp)
   * - ``date_modified``
     - ``YYYYmmddTHHMMss`` (last modification)

**Time Format Rationale**: The compact ``YYYYmmddTHHMMss`` format reduces attribute string length while maintaining human readability and ISO 8601 compatibility.

7.4. Geospatial and Temporal Coverage
--------------------------------------

**7.4.1. Geospatial Coverage Attributes**

.. list-table:: Geospatial Coverage (OceanSITES + ACDD)
   :widths: 30 70
   :header-rows: 1

   * - Attribute
     - Description / Example
   * - ``sea_area``
     - | Geographical coverage using SeaVoX Water Body Gazetteer (C19)
       | ``sea_area="North Atlantic Ocean"``
   * - ``geospatial_lat_min``
     - | Southernmost latitude (-90 to 90)
       | ``geospatial_lat_min=59.8``
   * - ``geospatial_lat_max``
     - | Northernmost latitude (-90 to 90)
       | ``geospatial_lat_max=59.8``
   * - ``geospatial_lat_units``
     - | Must conform to UDUNITS
       | ``geospatial_lat_units="degree_north"`` **[OceanArray: UDUNITS format]**
   * - ``geospatial_lon_min``
     - | Westernmost longitude (-180 to 180)
       | ``geospatial_lon_min=-41.2``
   * - ``geospatial_lon_max``
     - | Easternmost longitude (-180 to 180) 
       | ``geospatial_lon_max=-41.2``
   * - ``geospatial_lon_units``
     - | Must conform to UDUNITS
       | ``geospatial_lon_units="degree_east"`` **[OceanArray: UDUNITS format]**
   * - ``geospatial_vertical_min``
     - | Minimum depth/height of measurements
       | ``geospatial_vertical_min=10.0``
   * - ``geospatial_vertical_max``
     - | Maximum depth/height of measurements
       | ``geospatial_vertical_max=2000.0``
   * - ``geospatial_vertical_positive``
     - | Direction convention: "up" or "down"
       | ``geospatial_vertical_positive="down"``
   * - ``geospatial_vertical_units``
     - | Units of depth/pressure/height
       | ``geospatial_vertical_units="meter"``

**7.4.2. Temporal Coverage Attributes**

.. list-table:: Temporal Coverage (OceanSITES + ACDD)
   :widths: 30 70
   :header-rows: 1

   * - Attribute
     - Description / Example
   * - ``time_coverage_start``
     - | Start date in OG1 format **[OceanArray: not ISO8601]**
       | ``time_coverage_start="20060301T000000"``
   * - ``time_coverage_end``
     - | End date in OG1 format **[OceanArray: not ISO8601]**
       | ``time_coverage_end="20060305T235929"``
   * - ``time_coverage_duration``
     - | ISO 8601 duration format
       | ``time_coverage_duration="P415D"`` or ``"P1Y1M3D"``
   * - ``time_coverage_resolution``
     - | Sampling interval in ISO 8601 format
       | ``time_coverage_resolution="PT30M"`` (30 minutes)

**7.4.3. Platform Deployment Information**

.. list-table:: Platform Deployment Attributes (JCOMMOPS)
   :widths: 35 65
   :header-rows: 1

   * - Attribute
     - Description / Example
   * - ``platform_deployment_date``
     - | Deployment date in OG1 format **[OceanArray: not ISO8601]**
       | ``platform_deployment_date="20100220T000000"``
   * - ``platform_deployment_ship_name``
     - | Deployment vessel name
       | ``platform_deployment_ship_name="R/V Melville"``
   * - ``platform_deployment_cruise_name``
     - | Deployment cruise identifier
       | ``platform_deployment_cruise_name="MV1406"``
   * - ``platform_deployment_ship_ICES_code``
     - | ICES ship code for deployment vessel
       | ``platform_deployment_ship_ICES_code="318M"``
   * - ``platform_deployment_cruise_ExpoCode``
     - | ICES ship code + cruise start date
       | ``platform_deployment_cruise_ExpoCode="318M20100220"``
   * - ``platform_recovery_date``
     - | Recovery date in OG1 format **[OceanArray: not ISO8601]**
       | ``platform_recovery_date="20120113T000000"``
   * - ``platform_recovery_ship_name``
     - | Recovery vessel name
       | ``platform_recovery_ship_name="R/V Endeavor"``
   * - ``platform_recovery_cruise_name``
     - | Recovery cruise identifier  
       | ``platform_recovery_cruise_name="EN472"``
   * - ``platform_recovery_ship_ICES_code``
     - | ICES ship code for recovery vessel
       | ``platform_recovery_ship_ICES_code="32EV"``
   * - ``platform_recovery_cruise_ExpoCode``
     - | ICES ship code + cruise start date  
       | ``platform_recovery_cruise_ExpoCode="32EV20120113"``

**Time Format Choice**: OceanArray uses the OG1 compact format (``YYYYmmddTHHMMss``) instead of OceanSITES ISO8601 format (``YYYY-MM-DDThh:mm:ssZ``) for temporal attributes.

7.5. Publication and Attribution
---------------------------------

**7.5.1. Publisher Information**

.. list-table:: Publisher Attributes (ACDD)
   :widths: 25 75
   :header-rows: 1

   * - Attribute
     - Description / Example
   * - ``publisher_name``
     - | Name of person responsible for metadata and formatting
       | ``publisher_name="Al Plueddemann"``
   * - ``publisher_email``
     - | Email of person responsible for file formatting
       | ``publisher_email="aplueddemann at whoi.edu"``
   * - ``publisher_url``
     - | Web address of institution or data publisher
       | ``publisher_url="http://www.whoi.edu/profile/aplueddemann/"``
   * - ``publisher_id``
     - | Unique ID (ORCID) of person responsible for publication
       | ``publisher_id="https://orcid.org/0000-0001-5044-7079"``

**7.5.2. References and Citation**

.. list-table:: Citation and Reference Attributes
   :widths: 25 75
   :header-rows: 1

   * - Attribute
     - Description / Example
   * - ``references``
     - | Published references describing data or methods
       | ``references="http://www.oceansites.org, http://oceanarray.org"``
   * - ``citation``
     - | Citation for use in publications
       | ``citation="These data were processed by oceanarray and made available..."``
   * - ``license``
     - | Data distribution policy statement
       | ``license="Data available free of charge under OceanArray terms..."``
   * - ``acknowledgement``
     - | Support acknowledgment text
       | ``acknowledgement="Principal funding provided by..."``

**7.5.3. Data Assembly and Updates**

.. list-table:: Data Management Attributes (OceanSITES)
   :widths: 25 75
   :header-rows: 1

   * - Attribute
     - Description / Example
   * - ``data_assembly_center``
     - | Data Assembly Center responsible for file
       | ``data_assembly_center="OceanArray"`` **[OceanArray: not OceanSITES DAC]**
   * - ``update_interval``
     - | Update schedule in ISO 8601 format or "void"
       | ``update_interval="void"`` (for final processed datasets)

**7.5.4. Provenance and Quality**

.. list-table:: Provenance Attributes
   :widths: 25 75
   :header-rows: 1

   * - Attribute  
     - Description / Example
   * - ``date_created``
     - | File creation date in OG1 format **[OceanArray: not ISO8601]**
       | ``date_created="20160411T083500"``
   * - ``date_modified``
     - | Last modification date in OG1 format **[OceanArray: not ISO8601]**
       | ``date_modified="20170301T150000"``
   * - ``history``
     - | Audit trail of data modifications (one line per modification)
       | ``history="2024-01-15T10:30:00Z: oceanarray stage1 processing, J.Smith"``
   * - ``processing_level``
     - | Processing level from OceanSITES reference table 3
       | ``processing_level="Data verified against model or other contextual information"``
   * - ``QC_indicator``
     - | Overall dataset quality assessment
       | ``QC_indicator="excellent"`` (excellent/probably good/mixed/unknown)

**7.5.5. Keywords and Discovery**

.. list-table:: Keyword Attributes (ACDD)
   :widths: 25 75
   :header-rows: 1

   * - Attribute
     - Description / Example
   * - ``keywords_vocabulary``
     - | Controlled vocabulary used for keywords
       | ``keywords_vocabulary="GCMD Science Keywords"``
   * - ``keywords``
     - | Comma-separated discovery terms
       | ``keywords="EARTH SCIENCE>Oceans>Ocean Temperature"``
   * - ``comment``
     - | Miscellaneous information about data or methods
       | ``comment="Data processed through oceanarray pipeline version 1.0"``

7.6. Conventions and Standards
-------------------------------

.. list-table:: Metadata Conventions
   :widths: 30 70
   :header-rows: 1

   * - Attribute
     - Required Value
   * - ``Conventions``
     - ``"CF-1.8, OceanSITES-1.4, OceanArray-1.0"``
   * - ``format_version``
     - ``"OceanArray-1.0"``
   * - ``netcdf_version``
     - NetCDF version used (e.g., ``"4.8.1"``)
   * - ``data_type``
     - ``"OceanSITES time-series data"``
   * - ``cdm_data_type``
     - ``"Station"`` (for THREDDS/CDM)
   * - ``featureType``
     - ``"timeSeries"`` or ``"timeSeriesProfile"`` (CF-1.5+ DSG)
   * - ``array``
     - Optional: array grouping (e.g., ``"WHOTS"``)
   * - ``network``  
     - Optional: network grouping based on logistics/infrastructure

8. Units Convention
===================

8.1. Physical Units
--------------------

All units must follow the UDUNITS-2 standard:

.. list-table:: Common Unit Specifications
   :widths: 25 25 50
   :header-rows: 1

   * - Quantity
     - UDUNITS Format
     - Notes
   * - Latitude
     - ``degree_north``
     - Not ``degrees_north`` (OceanSITES)
   * - Longitude
     - ``degree_east``
     - Not ``degrees_east`` (OceanSITES)
   * - Temperature
     - ``degree_Celsius``
     - Preferred over ``degC``
   * - Pressure
     - ``decibar``
     - Standard oceanographic unit
   * - Depth
     - ``meter``
     - Standard SI unit
   * - Salinity
     - ``1`` or ``psu``
     - Dimensionless or practical salinity units
   * - Current Speed
     - ``meter second-1``
     - SI derived unit
   * - Current Direction
     - ``degree``
     - Angular measurement
   * - Ocean Transport
     - ``sverdrup``
     - 1 Sv = 10^6 m³/s (note: not ``sv`` to avoid conflict with sievert)

**UDUNITS Compliance**: Strict adherence to `UDUNITS-2 <https://docs.unidata.ucar.edu/udunits/current/>`_ ensures compatibility with analysis tools like Python's cf_units, NCO, and CDO. See the `UDUNITS-2 base unit definitions <https://docs.unidata.ucar.edu/udunits/current/udunits2-base.xml>`_ for canonical unit specifications.

**Oceanographic Unit Notes**:
- **Sverdrup**: Use full name ``"sverdrup"`` to avoid conflict with ``"sv"`` (sievert, radiation dose unit)
- **Standard Value**: 1 sverdrup = 1 × 10⁶ m³/s (one million cubic meters per second)
- **Typical Usage**: Ocean volume transport, meridional overturning circulation measurements

9. File Naming Convention
==========================

The oceanarray format adapts OceanSITES naming conventions for processed oceanographic data, following patterns established by the amocarray project for large-scale ocean arrays.

9.1. Individual Instrument Files
---------------------------------

**OceanArray Individual File Convention**:

``OS_[PlatformCode]_[DeploymentCode]_[ProcessingLevel]_[InstrumentType].nc``

**Component Definitions**:

.. list-table:: Individual File Name Components
   :widths: 20 80
   :header-rows: 1

   * - Component
     - Description / Example
   * - ``OS``
     - OceanSITES prefix (maintains compatibility)
   * - ``[PlatformCode]``
     - | Platform identifier from deployment metadata
       | Example: ``WHOTS-1``, ``CIS-1``
   * - ``[DeploymentCode]``
     - | Deployment identifier (date-based or sequential)
       | Example: ``202401`` (January 2024), ``D01`` (deployment 1)
   * - ``[ProcessingLevel]``
     - | OceanArray processing stage
       | ``L1`` - Stage 1 processed (CF-compliant, calibrated)
       | ``L2`` - Stage 2 processed (quality controlled)
       | ``L3`` - Time-gridded data
   * - ``[InstrumentType]``
     - | Instrument/parameter type identifier
       | ``CTD``, ``ADCP``, ``MET``

**Examples**:
- ``OS_WHOTS-1_202401_L2_CTD.nc``
- ``OS_CIS-1_D05_L1_ADCP.nc``

9.2. Higher-Level Products
---------------------------

**OceanArray follows OceanSITES higher-level convention**:

``OS_[PSPANCode]_[StartEndCode]_[ContentType]_[PARTX].nc``

**Component Definitions**:

.. list-table:: Higher-Level File Name Components  
   :widths: 20 80
   :header-rows: 1

   * - Component
     - Description / Example
   * - ``OS``
     - OceanSITES prefix (maintains compatibility)
   * - ``[PSPANCode]``
     - | Platform/Site/Project/Array/Network code
       | ``WHOTS`` (site), ``RAPIDMOC`` (array), ``OSNAP`` (array)
   * - ``[StartEndCode]``
     - | Time range: ``YYYYMMDD-YYYYMMDD`` format
       | ``20240101-20241231``, ``20040401-20230211``
   * - ``[ContentType]``
     - | **LTS** - Long time series (native resolution)
       | **GRD** - Gridded data (averaged/interpolated) 
       | **DPR** - Derived products (transports, fluxes)
   * - ``[PARTX]``
     - | Optional: data type and temporal resolution
       | ``transports_T10D`` (10-day transports)
       | ``sections_T1M`` (monthly sections)
       | ``gridded_mooring`` (gridded mooring data)

**Higher-Level Examples** (following amocarray patterns):
- ``OS_RAPID_20040401-20230211_DPR_transports_T10D.nc`` - 10-day RAPID transport time series
- ``OS_WHOTS_20240101-20241231_GRD_sections_T1M.nc`` - Monthly WHOTS section data
- ``OS_OSNAP_20140801-20200601_LTS_gridded_mooring.nc`` - OSNAP long time series

9.3. Processing Level vs Content Type
--------------------------------------

.. list-table:: Individual vs Higher-Level File Distinctions
   :widths: 25 35 40
   :header-rows: 1

   * - File Category
     - Naming Pattern
     - Purpose
   * - **Individual Instruments**
     - ``OS_[Platform]_[Deploy]_L[1-3]_[Instrument].nc``
     - | Single instrument processing
       | oceanarray stages 1-3
   * - **Mooring-Level**
     - ``OS_[Platform]_[TimeRange]_LTS_mooring.nc``
     - | Multiple instruments from same mooring
       | Native temporal resolution
   * - **Site/Array Products**
     - ``OS_[Array]_[TimeRange]_[GRD/DPR]_[Product].nc``
     - | Cross-mooring calculations
       | Scientific products

9.4. Temporal Resolution Codes
-------------------------------

**Following ISO 8601 duration format in PARTX field**:

.. list-table:: Temporal Resolution Examples
   :widths: 15 85
   :header-rows: 1

   * - Code
     - Description
   * - ``T30M``
     - 30-minute data
   * - ``T1H``
     - Hourly data
   * - ``T6H``
     - 6-hourly data
   * - ``T12H``
     - 12-hourly data (twice daily)
   * - ``P1D``
     - Daily data
   * - ``T10D``
     - 10-day data
   * - ``P1M``
     - Monthly data
   * - ``P1Y``
     - Annual data

9.5. OceanSITES Compatibility
------------------------------

**Maintaining OceanSITES Standards**:
- Field separator: ``_`` (underscore only)
- Time format: ``YYYYMMDD-YYYYMMDD`` for ranges
- Content type codes: ``LTS``, ``GRD``, ``DPR``
- ISO 8601 temporal resolution codes

**OceanArray Adaptations**:
- Processing levels: ``L1/L2/L3`` for individual files (replaces data mode R/P/D/M)
- Explicit instrument types: ``CTD``, ``ADCP``, ``MET`` for individual files

**amocarray Alignment**:
- Follows established patterns for large ocean arrays
- Uses descriptive PARTX fields (``transports_T10D``, ``sections_T1M``)
- Maintains OceanSITES higher-level product structure

9.6. Validation Rules
----------------------

**Required Elements**:
- Files must start with ``OS_`` prefix
- Time ranges must be valid dates in ``YYYYMMDD`` format  
- Processing levels must match content (L1/L2/L3 or LTS/GRD/DPR)
- No underscores within individual field components

**Valid Examples**:
- ✅ ``OS_WHOTS-1_202401_L2_CTD.nc``
- ✅ ``OS_RAPID_20040401-20230211_DPR_transports_T10D.nc``
- ❌ ``WHOTS_L2_CTD.nc`` (missing OS prefix)
- ❌ ``OS_WHOTS_2024_01_L2_CTD.nc`` (underscores in date)

10. Implementation Guidelines
=============================

10.1. Data Type Recommendations
--------------------------------

.. list-table:: Recommended Data Types
   :widths: 25 25 50
   :header-rows: 1

   * - Variable Type
     - NetCDF Type
     - Rationale
   * - Time coordinates
     - ``double``
     - Microsecond precision
   * - Spatial coordinates
     - ``double``
     - High precision positioning
   * - Scientific measurements
     - ``float``
     - Balance of precision and file size
   * - QC flags
     - ``byte``
     - Memory efficient
   * - String attributes
     - ``string`` or ``char``
     - UTF-8 compatible

10.2. Compression Settings
---------------------------

Recommended NetCDF-4 compression for time series data:
- **Compression**: ``zlib=True, complevel=6``
- **Chunking**: ``(time_chunk_size, 1, 1, ...)`` where ``time_chunk_size ≈ 1000``
- **Fill values**: Use appropriate type-specific fill values

**Performance Note**: These settings typically achieve 70-90% compression for oceanographic time series while maintaining fast read access.

11. Validation Tools
====================

The oceanarray package will provide validation utilities:

.. code-block:: python

   import oceanarray.validation as oav
   
   # Validate format compliance
   oav.validate_format(dataset_path)
   
   # Check attribute completeness
   oav.validate_attributes(dataset)
   
   # Verify QC flag consistency
   oav.validate_qc_flags(dataset)

.. note::
   **Development Status**: The validation module is planned for future development. See the :doc:`roadmap` for implementation timeline and current development priorities.

11.1. Compliance Checklist
---------------------------

- [ ] All required dimensions present
- [ ] Coordinate variables properly attributed
- [ ] Data variables include mandatory attributes
- [ ] QC variables follow flag specification
- [ ] Global attributes complete
- [ ] Units follow UDUNITS standard
- [ ] Time format consistent
- [ ] Vocabulary URLs accessible

12. Future Considerations
=========================

12.1. Standards Evolution
--------------------------

This specification may be updated to maintain alignment with:

- **OceanSITES**: Future versions may require reconciliation of dimension names
- **CF Conventions**: Updates to standard names and attribute requirements  
- **Community Feedback**: Practical usage may reveal needed adjustments

**Version Control**: Format changes will be tracked through semantic versioning (``OceanArray-X.Y.Z``) with clear migration guidance.

13. References
==============

**Format Standards**
- `OceanSITES Data Format Reference Manual <https://www.ocean-ops.org/oceansites/docs/oceansites_data_format_reference_manual.pdf>`_ (Version 1.4)
- `OG1 Format Specification <https://oceangliderscommunity.github.io/OG-format-user-manual/OG_Format.html>`_ (OceanGliders)
- `CF Conventions <http://cfconventions.org/>`_ (Climate and Forecast)
- `ACDD Conventions <https://wiki.esipfed.org/Attribute_Convention_for_Data_Discovery>`_ (Attribute Convention for Data Discovery)

**Technical Standards**
- `UDUNITS-2 <https://docs.unidata.ucar.edu/udunits/current/>`_ (Units specification)
- `UDUNITS-2 Base Units <https://docs.unidata.ucar.edu/udunits/current/udunits2-base.xml>`_ (Canonical unit definitions)
- `NetCDF-4 <https://www.unidata.ucar.edu/software/netcdf/>`_ (File format)
- `ISO 8601 <https://en.wikipedia.org/wiki/ISO_8601>`_ (Date and time format)

**Vocabulary Resources**
- `SeaVoX Platform Categories (L06) <https://www.bodc.ac.uk/resources/vocabularies/vocabulary_search/L06/>`_ (for ``source`` attribute)
- `SeaVoX Water Body Gazetteer (C19) <https://www.bodc.ac.uk/resources/vocabularies/vocabulary_search/C19/>`_ (for ``sea_area`` attribute)  
- `SeaVoX Device Catalogue (L22) <https://www.bodc.ac.uk/resources/vocabularies/vocabulary_search/L22/>`_ (for sensors and instruments)
- `ICES Ship Codes (C17) <https://ocean.ices.dk/codes/ShipCodes.aspx>`_ (for deployment/recovery ship codes)
- `BODC Ship Codes <https://www.bodc.ac.uk/resources/vocabularies/vocabulary_search/C17/>`_ (alternative ICES ship code source)
- `CF Standard Names <https://cfconventions.org/standard-names.html>`_
- `GCMD Science Keywords <https://gcmd.earthdata.nasa.gov/kms/>`_

**Additional Resources**
- `OceanSITES Website <http://www.oceansites.org>`_ (project information)
- `EPSG Coordinate Reference Systems <http://www.epsg.org/>`_ (for coordinate reference frames)
- `WMO Platform IDs <http://wmo.int/pages/prog/amp/mmop/wmo-number-rules.html>`_ (for ``wmo_platform_code``)
- `NetCDF User Guide <https://unidata.ucar.edu/software/netcdf/docs/user_guide.html>`_
- `NetCDF Best Practices <https://unidata.ucar.edu/software/netcdf/docs/BestPractices.html>`_
- `NOAA-NCEI NetCDF Templates <http://www.nodc.noaa.gov/data/formats/netcdf/>`_