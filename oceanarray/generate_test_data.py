#!/usr/bin/env python3
"""
Generate test_data_raw.nc from the real CNV file for Stage 2 testing.
"""
import yaml
from pathlib import Path
from oceanarray.stage1 import MooringProcessor


def create_test_stage1_data():
    """Create test data by running Stage 1 on the real CNV file."""

    # Set up test directory structure
    test_dir = Path("test_data_temp")
    raw_dir = test_dir / "moor" / "raw" / "test_deployment" / "microcat"
    proc_dir = test_dir / "moor" / "proc" / "test_mooring"

    raw_dir.mkdir(parents=True, exist_ok=True)
    proc_dir.mkdir(parents=True, exist_ok=True)

    # Copy the real CNV file
    source_cnv = Path("data/test_data.cnv")
    dest_cnv = raw_dir / "test_data.cnv"

    if not source_cnv.exists():
        print(f"ERROR: Source CNV file not found at {source_cnv}")
        print("Please ensure data/test_data.cnv exists")
        return False

    dest_cnv.write_text(source_cnv.read_text())
    print(f"Copied CNV file to {dest_cnv}")

    # Create YAML configuration
    yaml_data = {
        'name': 'test_mooring',
        'waterdepth': 1000,
        'longitude': -30.0,
        'latitude': 60.0,
        'deployment_latitude': '60 00.000 N',
        'deployment_longitude': '030 00.000 W',
        'deployment_time': '2018-08-12T08:00:00',  # Before data starts
        'recovery_time': '2018-08-26T20:47:24',    # After data ends
        'seabed_latitude': '60 00.000 N',
        'seabed_longitude': '030 00.000 W',
        'directory': 'moor/raw/test_deployment/',
        'instruments': [
            {
                'instrument': 'microcat',
                'serial': 7518,
                'depth': 100,
                'filename': 'test_data.cnv',
                'file_type': 'sbe-cnv',
                'clock_offset': 300,  # 5 minutes offset for testing
                'start_time': '2018-08-12T08:00:00',
                'end_time': '2018-08-26T20:47:24'
            }
        ]
    }

    config_file = proc_dir / "test_mooring.mooring.yaml"
    with open(config_file, 'w') as f:
        yaml.dump(yaml_data, f)

    print(f"Created YAML config at {config_file}")

    # Run Stage 1 processing
    processor = MooringProcessor(str(test_dir))
    success = processor.process_mooring("test_mooring")

    if success:
        # Move the generated file to data/ directory
        generated_file = proc_dir / "microcat" / "test_mooring_7518_raw.nc"
        target_file = Path("data/test_data_raw.nc")

        if generated_file.exists():
            target_file.write_bytes(generated_file.read_bytes())
            print(f"Successfully created {target_file}")

            # Also copy the YAML for Stage 2 tests
            target_yaml = Path("data/test_mooring.yaml")
            target_yaml.write_text(config_file.read_text())
            print(f"Copied YAML config to {target_yaml}")

            # Cleanup temp directory
            import shutil
            shutil.rmtree(test_dir)
            print(f"Cleaned up temporary directory")

            return True
        else:
            print(f"ERROR: Expected output file not found at {generated_file}")
            return False
    else:
        print("ERROR: Stage 1 processing failed")
        return False


if __name__ == "__main__":
    success = create_test_stage1_data()
    if success:
        print("\nTest data generation completed successfully!")
        print("Files created:")
        print("  - data/test_data_raw.nc")
        print("  - data/test_mooring.yaml")
        print("\nYou can now run Stage 2 tests with real data.")
    else:
        print("\nTest data generation failed.")
