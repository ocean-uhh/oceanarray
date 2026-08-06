# Migrating from --basedir to --raw-dir / --proc-dir

The `--basedir` flag has been **removed**.  All subcommands now require
`--raw-dir` and `--proc-dir` instead.  Passing `--basedir` prints a migration
message naming the replacement and exits without processing.  This document
explains how to convert an old `--basedir` layout to the current one.

---

## New canonical directory layout

```
{raw_dir}/                          # --raw-dir  (cruise level)
    {mooring}/
        {mooring}.mooring.yaml
        {instrument}/
            raw_file.asc
            raw_file.aqd
            ...

{proc_dir}/                         # --proc-dir  (cruise level)
    {mooring}/
        {mooring}.mooring.yaml      # copy or symlink from raw_dir
        {instrument}/
            {mooring}_{serial}_stage1.nc
            {mooring}_{serial}_stage2.nc
            {mooring}_{serial}_stage3.nc
        {mooring}_stack.nc
        {mooring}_grid.nc
        processing_logs/
            {mooring}_{timestamp}_stage1.mooring.log
            ...
        report/
            {mooring}_report.html
            {mooring}_stack_report.html
            {mooring}_grid_report.html
            instrument/
                {mooring}_{serial}_report.html
```

### Concrete example

```
/Volumes/T9/odb2026/raw/            # --raw-dir
    dsG3_1_2026/
        dsG3_1_2026.mooring.yaml
        microcat/
            26261_recovery.asc
            26262_recovery.asc
        aquadopp/
            A400118_dsG3.aqd
            A400118_dsG3.hdr

/local/proc/                        # --proc-dir
    dsG3_1_2026/
        dsG3_1_2026.mooring.yaml    # place a copy here before running
        microcat/
            dsG3_1_2026_26261_stage1.nc
            dsG3_1_2026_26261_stage2.nc
            dsG3_1_2026_26261_stage3.nc
        aquadopp/
            dsG3_1_2026_400118_stage1.nc
        dsG3_1_2026_stack.nc
        dsG3_1_2026_grid.nc
        report/
            dsG3_1_2026_report.html
            instrument/
                dsG3_1_2026_26261_report.html
```

---

## New shell script pattern

```bash
#!/usr/bin/env bash
RAW=/Volumes/T9/odb2026/raw
PROC=/local/proc
MOORING=dsG3_1_2026

oceanarray run "$MOORING" \
    --raw-dir "$RAW" \
    --proc-dir "$PROC" \
    --dp 10 \
    --force
```

Individual steps:

```bash
oceanarray process dsG3_1_2026 --raw-dir $RAW --proc-dir $PROC --stage 1 2 3
oceanarray stack   dsG3_1_2026 --proc-dir $PROC
oceanarray grid    dsG3_1_2026 --proc-dir $PROC --dp 10
oceanarray report  dsG3_1_2026 --raw-dir $RAW --proc-dir $PROC --instruments --stack --grid
```

---

## Migration steps

### Step 1: reorganise your raw files (mooring-first layout)

```
# Old instrument-first layout:
raw/{instrument}/{mooring}/filename

# New mooring-first layout:
raw/{mooring}/{instrument}/filename
```

Example:

```bash
OLD_RAW=/Volumes/T9/odb2026
NEW_RAW=/Volumes/T9/odb2026/raw

mkdir -p $NEW_RAW/dsG3_1_2026/microcat
mv $OLD_RAW/microcat/dsG3_1_2026/*.asc $NEW_RAW/dsG3_1_2026/microcat/

mkdir -p $NEW_RAW/dsG3_1_2026/aquadopp
mv $OLD_RAW/aquadopp/dsG3_1_2026/*.aqd $NEW_RAW/dsG3_1_2026/aquadopp/
```

### Step 2: place the YAML in the proc directory

The YAML must be at `{proc_dir}/{mooring}/{mooring}.mooring.yaml`
(same location as today under `--basedir`).

```bash
PROC=/local/proc
MOORING=dsG3_1_2026

cp $NEW_RAW/$MOORING/$MOORING.mooring.yaml $PROC/$MOORING/
```

### Step 3: remove `directory:` from the YAML (or keep as override)

If your YAML has a `directory:` key, you can remove it — `--raw-dir`
takes over.  If you leave it in and it is an absolute path, it acts as
an override for the raw root for that mooring (and a WARNING is printed).

### Step 4: update your shell scripts

```bash
# Before
oceanarray run $MOORING --basedir $DATA

# After
oceanarray run $MOORING --raw-dir $RAW --proc-dir $PROC
```

---

## What `--basedir` used to mean

The old `--basedir DIR` resolved paths as:

| File | Old path |
|------|----------|
| YAML | `DIR/proc/{mooring}/{mooring}.mooring.yaml` |
| Raw  | `DIR/{directory}/{instrument}/{mooring}/filename` |
| NC output | `DIR/proc/{mooring}/{instrument}/` |
| Reports | `DIR/proc/{mooring}/report/` |
| Logs | `DIR/proc/{mooring}/` (flat) |

The new `--raw-dir`/`--proc-dir` flags give you explicit control over
each root, support mooring-first raw layout, and put logs in a
`processing_logs/` subdirectory.
