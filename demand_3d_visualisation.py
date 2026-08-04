import streamlit as st
import pandas as pd
import pydeck as pdk
import requests
from pathlib import Path

# ========================================================
# 1. PAGE SETUP & PATH CONFIGURATION
# ========================================================
st.set_page_config(layout="wide", page_title="CAISO & SPP Texas Grid Analytics")

BASE_DIR = Path(__file__).parent if "__file__" in globals() else Path(".")
DATA_DIR = BASE_DIR / "gridstatus_data" / "processed_summary"

csv_nodes_path = DATA_DIR / "master_congestion_and_lmp_deltas.csv"
csv_load_path = DATA_DIR / "master_load_deltas.csv"
csv_combined_path = DATA_DIR / "master_combined_metrics.csv"

# ========================================================
# 2. FLOATING GAME HEADER CARD OVERLAY
# ========================================================
texans_logo_url = "https://a.espncdn.com/i/teamlogos/nfl/500/hou.png"
sf49ers_logo_url = "https://a.espncdn.com/i/teamlogos/nfl/500/sf.png"

st.html(f"""
<div id="game-header-card" style="
    background: #18181B;
    border: 1px solid rgba(255, 255, 255, 0.15);
    border-radius: 12px;
    padding: 16px 24px;
    color: #FFFFFF;
    font-family: system-ui, -apple-system, sans-serif;
    box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.6);
    max-width: 650px;
    margin: 0 auto 20px auto;
    text-align: center;
">
    <div style="font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: #A1A1AA; font-weight: 600; margin-bottom: 8px;">
        NFL Game Day Analysis • Oct 26, 2025
    </div>
    
    <div style="display: flex; align-items: center; justify-content: space-between; margin: 8px 0;">
        <div style="display: flex; align-items: center; gap: 12px;">
            <img src="{texans_logo_url}" alt="Texans Logo" style="width: 40px; height: 40px; object-fit: contain;" />
            <div style="text-align: left;">
                <div style="font-size: 15px; font-weight: 700;">Houston Texans</div>
                <div style="font-size: 11px; color: #A1A1AA;">(3 - 4)</div>
            </div>
        </div>

        <div style="font-size: 24px; font-weight: 800; color: #38BDF8; padding: 0 16px;">
            26 <span style="font-size: 16px; color: #71717A; font-weight: 400;">-</span> 15
        </div>

        <div style="display: flex; align-items: center; gap: 12px;">
            <div style="text-align: right;">
                <div style="font-size: 15px; font-weight: 700;">SF 49ers</div>
                <div style="font-size: 11px; color: #A1A1AA;">(5 - 3)</div>
            </div>
            <img src="{sf49ers_logo_url}" alt="49ers Logo" style="width: 40px; height: 40px; object-fit: contain;" />
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
# 3. DATA LOADING & GEOJSON PREPARATION
# ========================================================
@st.cache_data
def load_data():
    if not csv_nodes_path.exists():
        st.error(f"Master CSV not found at `{csv_nodes_path}`.")
        st.stop()
        
    df_nodes = pd.read_csv(csv_nodes_path)
    
    # Pre-clean numeric columns and filter for California and Texas
    df_nodes = df_nodes.dropna(subset=["latitude", "longitude"])
    df_nodes = df_nodes[(df_nodes["latitude"] != 0) & (df_nodes["longitude"] != 0)]
    
    # Standardize state naming
    df_nodes["us_state"] = df_nodes["us_state"].replace({"CA": "California", "TX": "Texas"})
    
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
            else:
                res["properties"]["name"] = state_name
                features.append(res)
        except Exception:
            pass

    return {"type": "FeatureCollection", "features": features}

df_nodes, df_load = load_data()
states_geojson = get_states_geojson()

# Compute state load statistics
ca_row = df_load[df_load["market_region"].str.contains("CAISO|California", case=False, na=False)]
tx_row = df_load[df_load["market_region"].str.contains("ERCOT|SPP|Texas", case=False, na=False)]

ca_load_delta = float(ca_row.iloc[0].get("load_delta_mw", -3928.28)) if not ca_row.empty else -3928.28
tx_load_delta = float(tx_row.iloc[0].get("load_delta_mw", 1250.50)) if not tx_row.empty else 1250.50

for feature in states_geojson.get("features", []):
    st_name = feature["properties"].get("name")
    if st_name == "California":
        val = abs(ca_load_delta)
        feature["properties"]["elevation"] = val * 20
        feature["properties"]["load_diff_mw"] = ca_load_delta
        feature["properties"]["fill_color"] = [235, 64, 52, 180] if ca_load_delta >= 0 else [52, 137, 235, 180]
    elif st_name == "Texas":
        val = abs(tx_load_delta)
        feature["properties"]["elevation"] = val * 20
        feature["properties"]["load_diff_mw"] = tx_load_delta
        feature["properties"]["fill_color"] = [235, 64, 52, 180] if tx_load_delta >= 0 else [52, 137, 235, 180]

# ========================================================
# 4. SIDEBAR CONTROLS & CAMERA VIEWS
# ========================================================
st.sidebar.header("Analytics Layers")
view_mode = st.sidebar.radio(
    "Select View Mode:",
    [
        "LMP Price Shifts (CAISO vs SPP/Texas)",
        "CAISO Congestion Analytics",
        "CAISO Loss Analytics",
        "Load Comparison (CAISO vs Texas)"
    ]
)

# View camera routing: CAISO Congestion zeroes in on CA; others frame both CA and TX
if view_mode == "CAISO Congestion Analytics":
    initial_view = pdk.ViewState(
        latitude=36.7783,
        longitude=-119.4179,
        zoom=5.5,
        pitch=45,
        bearing=0
    )
else:
    initial_view = pdk.ViewState(
        latitude=32.0,
        longitude=-102.0,
        zoom=4.2,
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
        opacity=0.7,
        stroked=True,
        filled=True,
        extruded=True,
        wireframe=True,
        get_elevation="properties.elevation",
        get_fill_color="properties.fill_color",
        get_line_color="[255, 255, 255, 255]",
        get_line_width=2,
        pickable=True
    )
    layers.append(state_layer)
    
    tooltip = {
        "html": "<b>State:</b> {properties.name}<br/>"
                "<b>Load Delta:</b> {properties.load_diff_mw:,.2f} MW",
        "style": {"backgroundColor": "#18181B", "color": "#FFFFFF", "fontSize": "12px", "padding": "8px 12px"}
    }

else:
    # Filter dataset per selected view mode
    if view_mode == "CAISO Congestion Analytics":
        df_filtered = df_nodes[df_nodes["us_state"] == "California"].copy()
        possible_metric_cols = ["congestion_delta", "congestion_pct_change", "game_congestion"]
        metric_label = "Congestion Shift"
        pos_rgb, neg_rgb = [46, 204, 113, 220], [0, 150, 136, 220]
    elif view_mode == "CAISO Loss Analytics":
        df_filtered = df_nodes[df_nodes["us_state"] == "California"].copy()
        possible_metric_cols = ["loss_delta", "loss_pct_change", "game_loss"]
        metric_label = "Loss Shift"
        pos_rgb, neg_rgb = [241, 196, 15, 220], [155, 89, 182, 220]
    else:  # LMP Price Shifts (CAISO vs SPP/Texas)
        df_filtered = df_nodes[df_nodes["us_state"].isin(["California", "Texas"])].copy()
        possible_metric_cols = ["lmp_delta", "lmp_pct_change", "congestion_delta"]
        metric_label = "LMP Price Shift"
        pos_rgb, neg_rgb = [235, 64, 52, 220], [52, 137, 235, 220]

    metric_col = next((c for c in possible_metric_cols if c in df_filtered.columns), possible_metric_cols[0])
    
    # Format display columns to 2 decimal places to ensure clean tooltips
    df_filtered["metric_val"] = df_filtered[metric_col].fillna(0) if metric_col in df_filtered.columns else 0.0
    
    game_col = next((c for c in ["game_lmp", "game_congestion", "game_loss"] if c in df_filtered.columns), None)
    base_col = next((c for c in ["baseline_lmp", "baseline_congestion", "baseline_loss"] if c in df_filtered.columns), None)
    
    df_filtered["game_price_fmt"] = df_filtered[game_col].map("{:.2f}".format) if game_col else "0.00"
    df_filtered["base_price_fmt"] = df_filtered[base_col].map("{:.2f}".format) if base_col else "0.00"
    df_filtered["metric_fmt"] = df_filtered["metric_val"].map("{:.2f}".format)

    # Elevation & Bar Styling: Radius set to 8000m with min/max pixel constraints for zoom scaling
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
        "html": "<b>Node:</b> {location}<br/>"
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
        st.info("Bars hidden. 3D boundaries elevated based on load shifts.")
    else:
        avg_val = df_filtered["metric_val"].mean()
        max_idx = df_filtered["metric_val"].idxmax()
        min_idx = df_filtered["metric_val"].idxmin()
        
        st.metric(label=f"Avg {metric_label}", value=f"${avg_val:.2f} /MWh")
        st.markdown("---")
        if pd.notna(max_idx):
            st.write(f"**Max Shift:**\n{df_filtered.loc[max_idx, 'location']} (`${df_filtered.loc[max_idx, 'metric_val']:.2f}`)")
        if pd.notna(min_idx):
            st.write(f"**Min Shift:**\n{df_filtered.loc[min_idx, 'location']} (`${df_filtered.loc[min_idx, 'metric_val']:.2f}`)")