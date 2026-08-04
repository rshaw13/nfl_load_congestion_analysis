from pathlib import Path
import pandas as pd

# ========================================================
# 1. PATHS, DIRECTORIES & LOOKUP TABLES
# ========================================================
lmp_input_folder = Path("C:/Users/ryans/Desktop/Ryan S/nfl_grid_analysis/gridstatus_data/lmp_csvs")
load_input_folder = Path("C:/Users/ryans/Desktop/Ryan S/nfl_grid_analysis/gridstatus_data/load_csvs")
output_folder = Path("C:/Users/ryans/Desktop/Ryan S/nfl_grid_analysis/gridstatus_data/processed_summary")
nodes_file = Path("C:/Users/ryans/Desktop/Ryan S/nfl_grid_analysis/nodes_with_states.csv")

output_folder.mkdir(parents=True, exist_ok=True)
nodes_df = pd.read_csv(nodes_file) if nodes_file.exists() else None

game_date_str = "2025-10-26"

# Hardcoded fallback for unmapped coordinates and states
FALLBACK_NODES = {
    "ANAHEIM_6_N001"    : {"city" : "Anaheim, CA", "us_state": "California", "latitude": 33.8531627, "longitude": -117.857995},
    "BALCH1_7_N001"     : {"city" : "Fresno, CA", "us_state": "California", "latitude": 36.908933, "longitude": -119.087736},
    "BEARTAP_1_N001"    : {"city" : "Bakersfield, CA", "us_state": "California", "latitude": 35.38, "longitude": -119.0},
    "MKT_SUB_LNODEONC"  : {"city" : "Los Angeles, CA", "us_state": "California", "latitude": 34.04330978, "longitude": -118.2462089},
    "OAKLAND_1_N001"    : {"city" : "Oakland, CA", "us_state": "California", "latitude": 37.797435, "longitude": -122.2809076},
    "PGSF_2_PDRP58-APND": {"city" : "San Francisco, CA", "us_state": "California", "latitude": 37.768483, "longitude": -122.441301},
    "SNJOSEB_1_N001"    : {"city" : "San Jose, CA", "us_state": "California", "latitude": 37.34102433, "longitude": -121.9009494},
    "SOUTHBY_6_N001"    : {"city" : "Sacramento, CA", "us_state": "California", "latitude": 38.5756129, "longitude": -121.497588},
    "URBAN_6_N001"      : {"city" : "San Diego, CA", "us_state": "California", "latitude": 32.71336176, "longitude": -117.151456},
    "SCEW_2_PDRP89-APND": {"city" : "Long Beach, CA", "us_state": "California", "latitude": 33.767884, "longitude": -118.149024},
    "AUSTPL_ALL"        : {"city" : "Austin, TX", "us_state": "Texas", "latitude": 30.293692, "longitude": -97.784416},
    "CBY_CBY_G1"        : {"city" : "Baytown, TX", "us_state": "Texas", "latitude": 29.750566, "longitude": -94.923326},
    "CNTRY_RN"          : {"city" : "Arlington, TX", "us_state": "Texas", "latitude": 32.688263, "longitude": -97.084527},
    "CR_RN"             : {"city" : "Houston, TX", "us_state": "Texas", "latitude": 29.776876, "longitude": -95.3799},
    "HLSES_UNIT5"       : {"city" : "Fort Worth, TX", "us_state": "Texas", "latitude": 32.727748, "longitude": -97.219188},
    "ODESW_RN"          : {"city" : "Odessa, TX", "us_state": "Texas", "latitude": 31.871254, "longitude": -102.398561},
    "P2_DGR2_RN"        : {"city" : "San Antonio, TX", "us_state": "Texas", "latitude": 29.357551, "longitude": -98.412407},
    "PRCRK_RN"          : {"city" : "Dallas, TX", "us_state": "Texas", "latitude": 32.775217, "longitude": -96.662261},
}


def process_file_timestamps(df, filename):
    """Parses timestamps per file based on market area (US/Central for Texas, US/Pacific for California)."""
    is_ercot = any(k in filename.lower() for k in ["ercot", "texas"])
    market_tz = "US/Central" if is_ercot else "US/Pacific"

    time_col = next(
        (c for c in ["interval_start_local", "datetime_local", "time", "interval_start_utc", "datetime"] if c in df.columns),
        None,
    )
    if not time_col:
        return df

    dt_utc = pd.to_datetime(df[time_col], utc=True, errors="coerce")
    df["dt_local"] = dt_utc.dt.tz_convert(market_tz)
    df["market_tz"] = market_tz
    df["market_region"] = "ERCOT" if is_ercot else "CAISO"
    return df


# ========================================================
# PIPELINE 1: LOAD / DEMAND COMPARISON (CAISO & ERCOT)
# ========================================================
print("=" * 60)
print("PROCESSING GRID LOAD / DEMAND FILES")
print("=" * 60)

load_csv_files = list(load_input_folder.glob("*.csv"))
load_dfs = []

for f in load_csv_files:
    try:
        temp_df = pd.read_csv(f)
        temp_df["source_file"] = f.name
        temp_df = process_file_timestamps(temp_df, f.name)

        # Map load/demand column
        load_col = next((c for c in ["load", "load_mw", "demand", "mw"] if c in temp_df.columns), None)
        if load_col:
            temp_df["load_mw"] = temp_df[load_col]

            # Entity column (System Total, Zone, etc.)
            if "region" in temp_df.columns:
                temp_df["entity_id"] = temp_df["region"]
            elif "zone" in temp_df.columns:
                temp_df["entity_id"] = temp_df["zone"]
            else:
                temp_df["entity_id"] = temp_df["market_region"] + "_SYSTEM_TOTAL"

            load_dfs.append(temp_df)
    except Exception as e:
        print(f" -> Error processing load file {f.name}: {e}")

if load_dfs:
    full_load_df = pd.concat(load_dfs, ignore_index=True)
    full_load_df["dt_local"] = pd.to_datetime(full_load_df["dt_local"], utc=True)

    # 10 AM - 1 PM window filter
    target_start = pd.to_datetime("10:00:00").time()
    target_end = pd.to_datetime("13:00:00").time()

    load_window_mask = (
        (full_load_df["dt_local"].dt.time >= target_start) &
        (full_load_df["dt_local"].dt.time <= target_end)
    )
    time_window_load = full_load_df[load_window_mask].copy()

    # Split Game Day vs Baseline
    game_load_mask = time_window_load["dt_local"].dt.strftime("%Y-%m-%d") == game_date_str
    game_load_df = time_window_load[game_load_mask]
    baseline_load_df = time_window_load[~game_load_mask]

    game_load_stats = game_load_df.groupby(["entity_id", "market_region"])["load_mw"].mean().reset_index()
    game_load_stats.rename(columns={"load_mw": "game_load_mw"}, inplace=True)

    baseline_load_stats = baseline_load_df.groupby(["entity_id", "market_region"])["load_mw"].mean().reset_index()
    baseline_load_stats.rename(columns={"load_mw": "baseline_load_mw"}, inplace=True)

    load_summary = pd.merge(game_load_stats, baseline_load_stats, on=["entity_id", "market_region"], how="outer")

    # Load Deltas and Percentage Changes
    load_summary["load_delta_mw"] = load_summary["game_load_mw"] - load_summary["baseline_load_mw"]
    load_summary["load_pct_change"] = (
        load_summary["load_delta_mw"] / load_summary["baseline_load_mw"].abs()
    ) * 100

    master_load_file = output_folder / "master_load_deltas.csv"
    load_summary.to_csv(master_load_file, index=False)
    print(f"SUCCESS: Saved Load Summary -> {master_load_file}")


# ========================================================
# PIPELINE 2: NODAL PRICE & CONGESTION DATASETS
# ========================================================
print("=" * 60)
print("PROCESSING NODAL PRICE (LMP / SPP) & CONGESTION FILES")
print("=" * 60)

lmp_csv_files = list(lmp_input_folder.glob("*.csv"))
lmp_dfs = []

for f in lmp_csv_files:
    try:
        temp_df = pd.read_csv(f)
        temp_df["source_file"] = f.name
        temp_df = process_file_timestamps(temp_df, f.name)

        # Standardize Location / Node column
        temp_df = temp_df.rename(columns={
            "settlement_point": "location",
            "pnode_id": "location",
            "node": "location"
        })

        # Texas/ERCOT: pull only 'spp' as primary price ('price'), set congestion/loss to NA
        if "spp" in temp_df.columns:
            temp_df["price"] = temp_df["spp"]
            temp_df["congestion"] = pd.NA
            temp_df["loss"] = pd.NA
        # California/CAISO: pull 'lmp', 'congestion', 'loss'
        elif "lmp" in temp_df.columns:
            temp_df["price"] = temp_df["lmp"]
            temp_df["congestion"] = temp_df.get("congestion", temp_df.get("mcc", 0.0))
            temp_df["loss"] = temp_df.get("loss", temp_df.get("mlc", 0.0))

        lmp_dfs.append(temp_df)
    except Exception as e:
        print(f" -> Error processing {f.name}: {e}")

if lmp_dfs:
    full_lmp_df = pd.concat(lmp_dfs, ignore_index=True)
    full_lmp_df["dt_local"] = pd.to_datetime(full_lmp_df["dt_local"], utc=True)

    # 10 AM - 1 PM local market window filter
    target_start = pd.to_datetime("10:00:00").time()
    target_end = pd.to_datetime("13:00:00").time()

    window_mask = (
        (full_lmp_df["dt_local"].dt.time >= target_start) &
        (full_lmp_df["dt_local"].dt.time <= target_end)
    )
    time_window_df = full_lmp_df[window_mask].copy()

    # Split Game Day vs Baseline
    game_mask = time_window_df["dt_local"].dt.strftime("%Y-%m-%d") == game_date_str
    game_df = time_window_df[game_mask]
    baseline_df = time_window_df[~game_mask]

    target_components = ["price", "congestion", "loss"]

    game_stats = game_df.groupby("location")[target_components].mean().reset_index()
    game_stats.columns = ["location"] + [f"game_{c}" for c in target_components]

    baseline_stats = baseline_df.groupby("location")[target_components].mean().reset_index()
    baseline_stats.columns = ["location"] + [f"baseline_{c}" for c in target_components]

    lmp_summary = pd.merge(game_stats, baseline_stats, on="location", how="outer")

    # Percentage change for simple price (LMP for CA / SPP for TX)
    lmp_summary["price_delta"] = lmp_summary["game_price"] - lmp_summary["baseline_price"]
    lmp_summary["price_pct_change"] = (
        lmp_summary["price_delta"] / lmp_summary["baseline_price"].abs()
    ) * 100

    # Congestion & Loss deltas for nodes that support them
    for comp in ["congestion", "loss"]:
        lmp_summary[f"{comp}_delta"] = lmp_summary[f"game_{comp}"] - lmp_summary[f"baseline_{comp}"]
        lmp_summary[f"{comp}_pct_change"] = (
            lmp_summary[f"{comp}_delta"] / lmp_summary[f"baseline_{comp}"].abs()
        ) * 100

    # 1. Merge with nodes_with_states.csv lookup table if available
    if nodes_df is not None:
        lmp_summary = pd.merge(
            lmp_summary,
            nodes_df[["node_id", "us_state", "latitude", "longitude"]],
            left_on="location",
            right_on="node_id",
            how="left"
        ).drop(columns=["node_id"], errors="ignore")

    # 2. Hardcode fallback lookup for unmapped coordinates and states
    for loc, info in FALLBACK_NODES.items():
        mask = lmp_summary["location"] == loc
        if mask.any():
            if "us_state" not in lmp_summary.columns:
                lmp_summary["us_state"] = pd.NA
            if "latitude" not in lmp_summary.columns:
                lmp_summary["latitude"] = pd.NA
            if "longitude" not in lmp_summary.columns:
                lmp_summary["longitude"] = pd.NA

            lmp_summary.loc[mask & lmp_summary["us_state"].isna(), "us_state"] = info["us_state"]
            lmp_summary.loc[mask & lmp_summary["latitude"].isna(), "latitude"] = info["latitude"]
            lmp_summary.loc[mask & lmp_summary["longitude"].isna(), "longitude"] = info["longitude"]

    master_lmp_file = output_folder / "master_congestion_and_lmp_deltas.csv"
    lmp_summary.to_csv(master_lmp_file, index=False)
    print(f"SUCCESS: Saved LMP/SPP & Congestion Summary -> {master_lmp_file}")