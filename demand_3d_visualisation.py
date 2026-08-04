import streamlit as st
import pandas as pd
import pydeck as pdk
import requests
import re
from pathlib import Path

# ========================================================
# 1. PAGE SETUP & PATH CONFIGURATION
# ========================================================
st.set_page_config(layout="wide", page_title="NFL Grid Analysis")

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
        <div><b>TX Kickoff:</b> 12:00 PM CDT</div>
        <div style="color: #52525B;">|</div>
        <div><b>Game Duration:</b> 2hrs 58min</div>
        <div style="color: #52525B;">|</div>
        <div><b>CA Kickoff:</b> 10:00 AM PDT</div>
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
    
    # Strictly use 'City' or 'city' column from master congestion CSV
    city_col = next((c for c in ["City", "city"] if c in df_nodes.columns), None)
    if city_col and df_nodes[city_col].notna().any():
        df_nodes["display_city"] = df_nodes[city_col].fillna(df_nodes["location"].apply(clean_city_name))
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

# Compute state load statistics
ca_row = df_load[df_load["market_region"].str.contains("CAISO|California", case=False, na=False)]
tx_row = df_load[df_load["market_region"].str.contains("ERCOT|SPP|Texas", case=False, na=False)]

ca_load_delta = float(ca_row.iloc[0].get("load_delta_mw", -3928.28)) if not ca_row.empty else -3928.28
tx_load_delta = float(tx_row.iloc[0].get("load_delta_mw", 1250.50)) if not tx_row.empty else 1250.50

ca_game_load = float(ca_row.iloc[0].get("game_load_mw", 22450.0)) if not ca_row.empty else 22450.0
ca_base_load = float(ca_row.iloc[0].get("baseline_load_mw", 26378.28)) if not ca_row.empty else 26378.28

tx_game_load = float(tx_row.iloc[0].get("game_load_mw", 48500.0)) if not tx_row.empty else 48500.0
tx_base_load = float(tx_row.iloc[0].get("baseline_load_mw", 47249.50)) if not tx_row.empty else 47249.50

for feature in states_geojson.get("features", []):
    st_name = feature["properties"].get("name")
    if st_name == "California":
        val = abs(ca_load_delta)
        feature["properties"]["elevation"] = float(val * 35)
        feature["properties"]["load_diff_mw"] = ca_load_delta
        feature["properties"]["fill_color"] = [235, 64, 52, 180]
    elif st_name == "Texas":
        val = abs(tx_load_delta)
        feature["properties"]["elevation"] = float(val * 35)
        feature["properties"]["load_diff_mw"] = tx_load_delta
        feature["properties"]["fill_color"] = [52, 137, 235, 180]

# ========================================================
# 4. SIDEBAR CONTROLS & CAMERA VIEWS
# ========================================================
st.sidebar.header("Analytics Layers")
view_mode = st.sidebar.radio(
    "Select View Mode:",
    [
        "Gametime Nodal Price Spike Analysis",
        "Gametime CAISO Congestion Analytics",
        "Gametime CAISO Loss Analytics",
        "Gametime Load Comparison (CAISO vs ERCOT)"
    ]
)

# Camera Routing: CAISO view shifted south to 35.2 latitude
if view_mode in ["Gametime CAISO Congestion Analytics", "Gametime CAISO Loss Analytics"]:
    initial_view = pdk.ViewState(
        latitude=35.2,
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

if view_mode == "Gametime Load Comparison (CAISO vs ERCOT)":
    # 1. Render 3D State Boundaries
    state_layer = pdk.Layer(
        "GeoJsonLayer",
        states_geojson,
        opacity=0.35,
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

    load_scale = 10.0

    load_bar_data = pd.DataFrame([
        {
            "display_city": "California System Load",
            "us_state": "California",
            "latitude": 36.7783,
            "longitude": -119.4179,
            "load_delta": ca_load_delta,
            "load_delta_fmt": f"{ca_load_delta:,.0f}",
            "game_load_fmt": f"{ca_game_load:,.0f}",
            "base_load_fmt": f"{ca_base_load:,.0f}",
            "game_height": ca_game_load * load_scale,
            "total_stacked_height": (ca_game_load + abs(ca_base_load - ca_game_load)) * load_scale
        },
        {
            "display_city": "Texas System Load",
            "us_state": "Texas",
            "latitude": 31.9686,
            "longitude": -99.9018,
            "load_delta": tx_load_delta,
            "load_delta_fmt": f"{tx_load_delta:,.0f}",
            "game_load_fmt": f"{tx_game_load:,.0f}",
            "base_load_fmt": f"{tx_base_load:,.0f}",
            "game_height": tx_game_load * load_scale,
            "total_stacked_height": (tx_game_load + abs(tx_base_load - tx_game_load)) * load_scale
        }
    ])

    # 1. Red Top Column Layer (Difference stacked on top of Gametime Load)
    difference_column_layer = pdk.Layer(
        "ColumnLayer",
        data=load_bar_data,
        get_position=["longitude", "latitude"],
        get_elevation="total_stacked_height",
        radius=75000,
        radius_min_pixels=20,
        radius_max_pixels=100,
        elevation_scale=1,
        get_fill_color="[235, 64, 52, 220]",  # Red for Load Difference
        pickable=True,
        auto_highlight=True,
        extruded=True
    )

    # 2. Blue Base Column Layer (Gametime Load)
    game_column_layer = pdk.Layer(
        "ColumnLayer",
        data=load_bar_data,
        get_position=["longitude", "latitude"],
        get_elevation="game_height",
        radius=75000,
        radius_min_pixels=20,
        radius_max_pixels=100,
        elevation_scale=1,
        get_fill_color="[52, 137, 235, 240]",  # Blue for Gametime Load
        pickable=True,
        auto_highlight=True,
        extruded=True
    )

    layers.append(difference_column_layer)
    layers.append(game_column_layer)
    
    tooltip = {
        "html": "<b>Region:</b> {display_city}<br/>"
                "<b>State:</b> {us_state}<br/>"
                "<hr style='margin: 5px 0;'>"
                "<b>Load Shift:</b> {load_delta_fmt} MW<br/>"
                "<b>Game Load:</b> {game_load_fmt} MW<br/>"
                "<b>Baseline Load:</b> {base_load_fmt} MW",
        "style": {
            "backgroundColor": "#18181B",
            "color": "#FFFFFF",
            "fontSize": "12px",
            "borderRadius": "6px",
            "padding": "8px 12px",
            "boxShadow": "0 4px 6px -1px rgba(0, 0, 0, 0.5)"
        }
    }

else:
    # Set mode-specific metrics, colors, and height scaling multipliers
    if view_mode == "Gametime CAISO Congestion Analytics":
        df_filtered = df_nodes[df_nodes["us_state"] == "California"].copy()
        metric_col_choices = ["congestion_delta", "game_congestion"]
        metric_label = "Congestion Shift"
        pos_rgb, neg_rgb = [46, 204, 113, 220], [0, 150, 136, 220]
        height_multiplier = 20000
        bar_radius = 8000
        
    elif view_mode == "Gametime CAISO Loss Analytics":
        df_filtered = df_nodes[df_nodes["us_state"] == "California"].copy()
        metric_col_choices = ["loss_delta", "game_loss"]
        metric_label = "Loss Shift"
        pos_rgb, neg_rgb = [241, 196, 15, 220], [155, 89, 182, 220]
        height_multiplier = 20000
        bar_radius = 8000
        
    else:  # Gametime Nodal Price Spike Analysis
        df_filtered = df_nodes[df_nodes["us_state"].isin(["California", "Texas"])].copy()
        metric_col_choices = ["price_delta", "lmp_delta", "price_pct_change"]
        metric_label = "LMP Price Shift"
        pos_rgb, neg_rgb = [235, 64, 52, 220], [52, 137, 235, 220]
        height_multiplier = 6000
        bar_radius = 8800

    # 1. Primary Metric Shift
    metric_col = next((c for c in metric_col_choices if c in df_filtered.columns), None)
    if metric_col:
        df_filtered["metric_val"] = pd.to_numeric(df_filtered[metric_col], errors="coerce").fillna(0.0)
    else:
        df_filtered["metric_val"] = 0.0

    # 2. Extract actual Game Price & Baseline Price
    game_price_cols = ["game_price", "game_lmp", "game_value"]
    base_price_cols = ["baseline_price", "baseline_lmp", "baseline_value"]

    game_col = next((c for c in game_price_cols if c in df_filtered.columns), None)
    base_col = next((c for c in base_price_cols if c in df_filtered.columns), None)

    if game_col:
        df_filtered["game_val"] = pd.to_numeric(df_filtered[game_col], errors="coerce").fillna(0.0)
    else:
        df_filtered["game_val"] = 0.0

    if base_col:
        df_filtered["base_val"] = pd.to_numeric(df_filtered[base_col], errors="coerce").fillna(0.0)
    else:
        df_filtered["base_val"] = 0.0

    # 3. Pre-format strings for PyDeck tooltip rendering
    df_filtered["game_price_fmt"] = df_filtered["game_val"].map("{:.2f}".format)
    df_filtered["base_price_fmt"] = df_filtered["base_val"].map("{:.2f}".format)
    df_filtered["metric_fmt"] = df_filtered["metric_val"].map("{:.2f}".format)

    # 4. Height scaling and bar styling
    df_filtered["bar_height"] = df_filtered["metric_val"].abs() * height_multiplier
    df_filtered["bar_color"] = df_filtered["metric_val"].apply(lambda val: pos_rgb if val >= 0 else neg_rgb)

    column_layer = pdk.Layer(
        "ColumnLayer",
        data=df_filtered,
        get_position=["longitude", "latitude"],
        get_elevation="bar_height",
        radius=bar_radius,
        radius_min_pixels=6,
        radius_max_pixels=35,
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
    # Color Legend Header HTML per mode
    if view_mode == "Gametime Load Comparison (CAISO vs ERCOT)":
        legend_html = """
        <div style="display: flex; gap: 20px; margin-bottom: 10px; font-size: 13px; font-weight: 600;">
            <div style="display: flex; align-items: center; gap: 8px;">
                <span style="width: 14px; height: 14px; background-color: #3489EB; border-radius: 3px; display: inline-block;"></span> Gametime Load (Blue)
            </div>
            <div style="display: flex; align-items: center; gap: 8px;">
                <span style="width: 14px; height: 14px; background-color: #EB4034; border-radius: 3px; display: inline-block;"></span> Baseline Load Difference (Red)
            </div>
        </div>
        """
    elif view_mode == "Gametime CAISO Congestion Analytics":
        legend_html = """
        <div style="display: flex; gap: 20px; margin-bottom: 10px; font-size: 13px; font-weight: 600;">
            <div style="display: flex; align-items: center; gap: 8px;">
                <span style="width: 14px; height: 14px; background-color: #2ECC71; border-radius: 3px; display: inline-block;"></span> Positive Congestion Shift (Green)
            </div>
            <div style="display: flex; align-items: center; gap: 8px;">
                <span style="width: 14px; height: 14px; background-color: #009688; border-radius: 3px; display: inline-block;"></span> Negative Congestion Shift (Teal)
            </div>
        </div>
        """
    elif view_mode == "Gametime CAISO Loss Analytics":
        legend_html = """
        <div style="display: flex; gap: 20px; margin-bottom: 10px; font-size: 13px; font-weight: 600;">
            <div style="display: flex; align-items: center; gap: 8px;">
                <span style="width: 14px; height: 14px; background-color: #F1C40F; border-radius: 3px; display: inline-block;"></span> Positive Loss Shift (Yellow)
            </div>
            <div style="display: flex; align-items: center; gap: 8px;">
                <span style="width: 14px; height: 14px; background-color: #9B59B6; border-radius: 3px; display: inline-block;"></span> Negative Loss Shift (Purple)
            </div>
        </div>
        """
    else:
        legend_html = """
        <div style="display: flex; gap: 20px; margin-bottom: 10px; font-size: 13px; font-weight: 600;">
            <div style="display: flex; align-items: center; gap: 8px;">
                <span style="width: 14px; height: 14px; background-color: #EB4034; border-radius: 3px; display: inline-block;"></span> Positive Price Shift (Red)
            </div>
            <div style="display: flex; align-items: center; gap: 8px;">
                <span style="width: 14px; height: 14px; background-color: #3489EB; border-radius: 3px; display: inline-block;"></span> Negative Price Shift (Blue)
            </div>
        </div>
        """

    st.html(legend_html)

    st.pydeck_chart(pdk.Deck(
        layers=layers,
        initial_view_state=initial_view,
        tooltip=tooltip,
        map_style=pdk.map_styles.CARTO_DARK
    ))

with col2:
    st.markdown(f"### **{view_mode}**")
    st.markdown("---")
    
    if view_mode == "Gametime Load Comparison (CAISO vs ERCOT)":
        st.metric(label="CAISO Load Delta", value=f"{ca_load_delta:,.0f} MW")
        st.metric(label="ERCOT Load Delta", value=f"{tx_load_delta:,.0f} MW")
    elif view_mode == "Gametime Nodal Price Spike Analysis":
        ca_df = df_filtered[df_filtered["us_state"] == "California"]
        tx_df = df_filtered[df_filtered["us_state"] == "Texas"]
        
        ca_avg = ca_df["metric_val"].mean() if not ca_df.empty else 0.0
        tx_avg = tx_df["metric_val"].mean() if not tx_df.empty else 0.0

        st.metric(label="Avg CA Gametime Price Shift", value=f"${ca_avg:.2f} /MWh")
        st.metric(label="Average TX Gametime Price Shift", value=f"${tx_avg:.2f} /MWh")
        st.markdown("---")

        max_idx = df_filtered["metric_val"].idxmax()
        min_idx = df_filtered["metric_val"].idxmin()

        if pd.notna(max_idx):
            max_city = df_filtered.loc[max_idx, 'display_city']
            st.write(f"**Max Shift:**\n{max_city} (`${df_filtered.loc[max_idx, 'metric_val']:.2f}`)")
        if pd.notna(min_idx):
            min_city = df_filtered.loc[min_idx, 'display_city']
            st.write(f"**Min Shift:**\n{min_city} (`${df_filtered.loc[min_idx, 'metric_val']:.2f}`)")

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