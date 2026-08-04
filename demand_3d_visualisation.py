import streamlit as st
import pandas as pd
import pydeck as pdk
import requests
import re
from pathlib import Path

# ========================================================
# 1. PAGE SETUP & PATH CONFIGURATION
# ========================================================
st.set_page_config(layout="wide", page_title="CAISO & SPP Grid Analytics")

BASE_DIR = Path(__file__).parent if "__file__" in globals() else Path(".")
DATA_DIR = BASE_DIR / "gridstatus_data" / "processed_summary"

csv_nodes_path = DATA_DIR / "master_congestion_and_lmp_deltas.csv"
csv_load_path = DATA_DIR / "master_load_deltas.csv"
csv_combined_path = DATA_DIR / "master_combined_metrics.csv"

# ========================================================
# 2. FULL-WIDTH FLOATING GAME HEADER CARD
# ========================================================
texans_logo_url = "https://a.espncdn.com/i/teamlogos/nfl/500/hou.png"
sf49ers_logo_url = "https://a.espncdn.com/i/teamlogos/nfl/500/sf.png"

# Header card spans full width of the main content area (from map edge to right panel edge)
st.html(f"""
<div id="game-header-card" style="
    background: #18181B;
    border: 1px solid rgba(255, 255, 255, 0.15);
    border-radius: 12px;
    padding: 16px 32px;
    color: #FFFFFF;
    font-family: system-ui, -apple-system, sans-serif;
    box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.6);
    width: 100%;
    margin-bottom: 20px;
    text-align: center;
">
    <div style="font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: #A1A1AA; font-weight: 600; margin-bottom: 8px;">
        NFL Game Day Analysis • Oct 26, 2025
    </div>
    
    <div style="display: flex; align-items: center; justify-content: space-between; margin: 8px 0;">
        <div style="display: flex; align-items: center; gap: 16px;">
            <img src="{texans_logo_url}" alt="Texans Logo" style="width: 44px; height: 44px; object-fit: contain;" />
            <div style="text-align: left;">
                <div style="font-size: 16px; font-weight: 700;">Houston Texans</div>
                <div style="font-size: 12px; color: #A1A1AA;">(3 - 4)</div>
            </div>
        </div>

        <div style="font-size: 26px; font-weight: 800; color: #38BDF8; padding: 0 24px;">
            26 <span style="font-size: 18px; color: #71717A; font-weight: 400;">-</span> 15
        </div>

        <div style="display: flex; align-items: center; gap: 16px;">
            <div style="text-align: right;">
                <div style="font-size: 16px; font-weight: 700;">SF 49ers</div>
                <div style="font-size: 12px; color: #A1A1AA;">(5 - 3)</div>
            </div>
            <img src="{sf49ers_logo_url}" alt="49ers Logo" style="width: 44px; height: 44px; object-fit: contain;" />
        </div>
    </div>

    <div style="border-top: 1px solid rgba(255, 255, 255, 0.12); margin-top: 10px; padding-top: 10px; display: flex; justify-content: space-around; font-size: 12px; color: #E4E4E7;">
        <div><b>CA Kickoff:</b> 10:00 AM PDT</div>
        <div style="color: #52525B;">|</div>
        <div><b>TX Kickoff:</b> 12:00 PM CDT</div>
    </div>
</div>
""")

# ========================================================
# 3. HELPER FUNCTIONS & DATA LOADING
# ========================================================
def clean_city_name(raw_name):
    """Fallback helper to clean node strings if city column is missing."""
    if not isinstance(raw_name, str) or not raw_name:
        return "Unknown Location"
    cleaned = re.sub(r'_\d+_[A-Z0-9]+$', '', raw_name)
    cleaned = cleaned.replace('_', ' ').strip()
    return cleaned.title()

@st.cache_data
def load_data():
    if not csv_nodes_path.exists():
        st.error(f"Master CSV not found at `{csv_nodes_path}`.")
        st.stop()
        
    df_nodes = pd.read_csv(csv_nodes_path)
    
    # Filter valid coordinates
    df_nodes = df_nodes.dropna(subset=["latitude", "longitude"])
    df_nodes = df_nodes[(df_nodes["latitude"] != 0) & (df_nodes["longitude"] != 0)].copy()
    
    # Standardize state names
    df_nodes["us_state"] = df_nodes["us_state"].replace({"CA": "California", "TX": "Texas"})
    
    # Prioritize the 'city' column output by ETL script, fallback to cleaning 'location'
    if "city" in df_nodes.columns and df_nodes["city"].notna().any():
        df_nodes["display_city"] = df_nodes["city"].fillna(df_nodes["location"].apply(clean_city_name))
    else:
        df_nodes["display_city"] = df_nodes["location"].apply(clean_city_name)
    
    if csv_load_path.exists():
        df_load = pd.read_csv(csv_load_path)
    elif csv_combined_path.exists():
        df_combined = pd.read_csv(csv_combined_path)
        df_load = df_combined[df_combined["category"] == "Load"].copy()
        df_load.rename(columns={
            "entity_id": "market_region",
            "delta_value": "load_delta_mw",
            "pct_change": "load_pct_change"
        }, inplace=True)
    else:
        df_load = pd.DataFrame(columns=["market_region", "game_load_mw", "baseline_load_mw", "load_pct_change"])

    return df_nodes, df_load

@st.cache_data
def get_states_geojson():
    ca_url = "https://raw.githubusercontent.com/PublicPlot/geojson-us-states/master/50m/06.geojson"
    tx_url = "https://raw.githubusercontent.com/PublicPlot/geojson-us-states/master/50m/48.geojson"
    
    features = []
    for url, state_name in [(ca_url, "California"), (tx_url, "Texas")]:
        try:
            res = requests.get(url, timeout=5).json()
            if res.get("type") == "FeatureCollection":
                for f in res["features"]:
                    f["properties"]["name"] = state_name
                    features.append(f)
            elif res.get("type") == "Feature":
                res["properties"]["name"] = state_name
                features.append(res)
        except Exception:
            pass

    return {"type": "FeatureCollection", "features": features}

df_nodes, df_load = load_data()
states_geojson = get_states_geojson()

# Compute state load statistics for 3D state boundary extrusions
ca_row = df_load[df_load["market_region"].str.contains("CAISO|California", case=False, na=False)]
tx_row = df_load[df_load["market_region"].str.contains("ERCOT|SPP|Texas", case=False, na=False)]

ca_load_delta = float(ca_row.iloc[0].get("load_delta_mw", -3928.28)) if not ca_row.empty else -3928.28
tx_load_delta = float(tx_row.iloc[0].get("load_delta_mw", 1250.50)) if not tx_row.empty else 1250.50

for feature in states_geojson.get("features", []):
    st_name = feature["properties"].get("name")
    if st_name == "California":
        val = abs(ca_load_delta)
        feature["properties"]["elevation"] = float(val * 35)
        feature["properties"]["load_diff_mw"] = ca_load_delta
        feature["properties"]["fill_color"] = [235, 64, 52, 180] if ca_load_delta >= 0 else [52, 137, 235, 180]
    elif st_name == "Texas":
        val = abs(tx_load_delta)
        feature["properties"]["elevation"] = float(val * 35)
        feature["properties"]["load_diff_mw"] = tx_load_delta
        feature["properties"]["fill_color"] = [235, 64, 52, 180] if tx_load_delta >= 0 else [52, 137, 235, 180]

# ========================================================
# 4. SIDEBAR CONTROLS & CAMERA VIEWS
# ========================================================
st.sidebar.header("Analytics Layers")
view_mode = st.sidebar.radio(
    "Select View Mode:",
    [
        "Gameday Nodal Price Spike Analysis",
        "CAISO Congestion Analytics",
        "CAISO Loss Analytics",
        "Load Comparison (CAISO vs Texas)"
    ]
)

# Camera Routing: California focused for Congestion & Losses; Westward default for regional views
if view_mode in ["CAISO Congestion Analytics", "CAISO Loss Analytics"]:
    initial_view = pdk.ViewState(
        latitude=36.7783,
        longitude=-119.4179,
        zoom=5.5,
        pitch=45,
        bearing=0
    )
else:
    initial_view = pdk.ViewState(
        latitude=33.5,
        longitude=-108.0,
        zoom=4.4,
        pitch=45,
        bearing=0
    )

# ========================================================
# 5. LAYER & TOOLTIP BUILDER
# ========================================================
layers = []

if view_mode == "Load Comparison (CAISO vs Texas)":
    state_layer = pdk.Layer(
        "GeoJsonLayer",
        states_geojson,
        opacity=0.75,
        stroked=True,
        filled=True,
        extruded=True,
        wireframe=True,
        elevation_scale=1,
        get_elevation="properties.elevation",
        get_fill_color="properties.fill_color",
        get_line_color="[255, 255, 255, 255]",
        get_line_width=2,
        pickable=True
    )
    layers.append(state_layer)
    
    tooltip = {
        "html": "<b>State:</b> {properties.name}<br/>"
                "<b>Load Shift:</b> {properties.load_diff_mw:,.2f} MW",
        "style": {"backgroundColor": "#18181B", "color": "#FFFFFF", "fontSize": "12px", "padding": "8px 12px"}
    }

else:
    # Match ETL script column names accurately
    if view_mode == "CAISO Congestion Analytics":
        df_filtered = df_nodes[df_nodes["us_state"] == "California"].copy()
        metric_col_choices = ["congestion_delta", "game_congestion"]
        game_price_cols = ["game_congestion", "game_price", "game_lmp"]
        base_price_cols = ["baseline_congestion", "baseline_price", "baseline_lmp"]
        metric_label = "Congestion Shift"
        pos_rgb, neg_rgb = [46, 204, 113, 220], [0, 150, 136, 220]
        
    elif view_mode == "CAISO Loss Analytics":
        df_filtered = df_nodes[df_nodes["us_state"] == "California"].copy()
        metric_col_choices = ["loss_delta", "game_loss"]
        game_price_cols = ["game_loss", "game_price", "game_lmp"]
        base_price_cols = ["baseline_loss", "baseline_price", "baseline_lmp"]
        metric_label = "Loss Shift"
        pos_rgb, neg_rgb = [241, 196, 15, 220], [155, 89, 182, 220]
        
    else:  # Gameday Nodal Price Spike Analysis
        df_filtered = df_nodes[df_nodes["us_state"].isin(["California", "Texas"])].copy()
        metric_col_choices = ["price_delta", "lmp_delta", "price_pct_change"]
        game_price_cols = ["game_price", "game_lmp", "game_value"]
        base_price_cols = ["baseline_price", "baseline_lmp", "baseline_value"]
        metric_label = "LMP Price Shift"
        pos_rgb, neg_rgb = [235, 64, 52, 220], [52, 137, 235, 220]

    # 1. Metric Delta Calculation
    metric_col = next((c for c in metric_col_choices if c in df_filtered.columns), None)
    if metric_col:
        df_filtered["metric_val"] = pd.to_numeric(df_filtered[metric_col], errors="coerce").fillna(0.0)
    else:
        df_filtered["metric_val"] = 0.0

    # 2. Game Price and Baseline Price Extraction (Fixing $0.00 issue)
    game_col = next((c for c in game_price_cols if c in df_filtered.columns), None)
    base_col = next((c for c in base_price_cols if c in df_filtered.columns), None)

    if base_col:
        df_filtered["base_val"] = pd.to_numeric(df_filtered[base_col], errors="coerce").fillna(0.0)
    else:
        df_filtered["base_val"] = 0.0

    if game_col:
        df_filtered["game_val"] = pd.to_numeric(df_filtered[game_col], errors="coerce").fillna(0.0)
    else:
        df_filtered["game_val"] = df_filtered["base_val"] + df_filtered["metric_val"]

    # 3. Pre-format 2-decimal strings for PyDeck tooltip rendering
    df_filtered["game_price_fmt"] = df_filtered["game_val"].map("{:.2f}".format)
    df_filtered["base_price_fmt"] = df_filtered["base_val"].map("{:.2f}".format)
    df_filtered["metric_fmt"] = df_filtered["metric_val"].map("{:.2f}".format)

    # 4. Height scaling and bar styling
    df_filtered["bar_height"] = df_filtered["metric_val"].abs() * 2000
    df_filtered["bar_color"] = df_filtered["metric_val"].apply(lambda val: pos_rgb if val >= 0 else neg_rgb)

    column_layer = pdk.Layer(
        "ColumnLayer",
        data=df_filtered,
        get_position=["longitude", "latitude"],
        get_elevation="bar_height",
        radius=8000,
        radius_min_pixels=6,
        radius_max_pixels=30,
        elevation_scale=1,
        get_fill_color="bar_color",
        pickable=True,
        auto_highlight=True,
        extruded=True
    )
    layers.append(column_layer)

    tooltip = {
        "html": "<b>City:</b> {display_city}<br/>"
                "<b>Node:</b> {location}<br/>"
                "<b>State:</b> {us_state}<br/>"
                "<hr style='margin: 5px 0;'>"
                "<b>" + metric_label + ":</b> ${metric_fmt} /MWh<br/>"
                "<b>Game Price:</b> ${game_price_fmt} /MWh<br/>"
                "<b>Baseline Price:</b> ${base_price_fmt} /MWh",
        "style": {
            "backgroundColor": "#18181B",
            "color": "#FFFFFF",
            "fontSize": "12px",
            "borderRadius": "6px",
            "padding": "8px 12px",
            "boxShadow": "0 4px 6px -1px rgba(0, 0, 0, 0.5)"
        }
    }

# ========================================================
# 6. RENDER DASHBOARD
# ========================================================
col1, col2 = st.columns([3, 1])

with col1:
    st.pydeck_chart(pdk.Deck(
        layers=layers,
        initial_view_state=initial_view,
        tooltip=tooltip,
        map_style=pdk.map_styles.CARTO_DARK
    ))

with col2:
    st.markdown(f"### **{view_mode}**")
    st.markdown("---")
    
    if view_mode == "Load Comparison (CAISO vs Texas)":
        st.metric(label="CAISO Load Delta", value=f"{ca_load_delta:,.2f} MW")
        st.metric(label="Texas Load Delta", value=f"{tx_load_delta:,.2f} MW")
        st.info("Node bars hidden. 3D boundaries elevated based on load shifts.")
    else:
        avg_val = df_filtered["metric_val"].mean()
        max_idx = df_filtered["metric_val"].idxmax()
        min_idx = df_filtered["metric_val"].idxmin()
        
        st.metric(label=f"Avg {metric_label}", value=f"${avg_val:.2f} /MWh")
        st.markdown("---")
        if pd.notna(max_idx):
            max_city = df_filtered.loc[max_idx, 'display_city']
            st.write(f"**Max Shift:**\n{max_city} (`${df_filtered.loc[max_idx, 'metric_val']:.2f}`)")
        if pd.notna(min_idx):
            min_city = df_filtered.loc[min_idx, 'display_city']
            st.write(f"**Min Shift:**\n{min_city} (`${df_filtered.loc[min_idx, 'metric_val']:.2f}`)")