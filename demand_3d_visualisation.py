import streamlit as st
import pandas as pd
import pydeck as pdk
import json
import requests

# ========================================================
# 1. PAGE SETUP & CONFIGURATION
# ========================================================
st.set_page_config(layout="wide", page_title="CAISO Nodal & Grid Load Dashboard")

st.title("⚡ CAISO Grid Load & Nodal Market Analytics")

# ========================================================
# 2. DATA LOADING & PREPARATION
# ========================================================
@st.cache_data
def load_data():
    # Load nodal dataset
    df_nodes = pd.read_csv("master_congestion_and_lmp_deltas.csv")
    
    # Filter exclusively for California nodes
    df_caiso = df_nodes[df_nodes["us_state"] == "California"].copy()
    
    # Load grid load summary dataset
    try:
        df_load = pd.read_csv("master_load_deltas.csv")
    except Exception:
        # Fallback if consolidated in master_combined_metrics.csv
        df_combined = pd.read_csv("master_combined_metrics.csv")
        df_load = df_combined[df_combined["category"] == "Load"].copy()
        df_load.rename(columns={
            "entity_id": "market_region",
            "delta_value": "load_delta_mw",
            "pct_change": "load_pct_change"
        }, inplace=True)

    return df_caiso, df_load

@st.cache_data
def get_ca_geojson():
    # Fetch California state GeoJSON boundary for 3D extrusion
    url = "https://raw.githubusercontent.com/PublicPlot/geojson-us-states/master/50m/06.geojson"
    try:
        response = requests.get(url)
        return response.json()
    except Exception:
        # Fallback simplified box polygon for California boundary if offline
        return {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [-124.4, 42.0], [-120.0, 42.0], [-120.0, 39.0], 
                        [-114.6, 35.0], [-114.6, 32.5], [-117.1, 32.5], 
                        [-124.4, 40.0], [-124.4, 42.0]
                    ]]
                },
                "properties": {"name": "California"}
            }]
        }

df_caiso, df_load = load_data()
ca_geojson = get_ca_geojson()

# Calculate California Load variance for 3D elevation height
ca_load_row = df_load[df_load["market_region"].str.contains("CAISO|California|SYSTEM", case=False, na=False)]
if not ca_load_row.empty:
    g_load = ca_load_row.iloc[0].get("game_load_mw", ca_load_row.iloc[0].get("game_value", 0))
    b_load = ca_load_row.iloc[0].get("baseline_load_mw", ca_load_row.iloc[0].get("baseline_value", 0))
    
    diff_val = b_load - g_load
    load_elevation_val = max(abs(diff_val), g_load - b_load)
    load_pct_diff = ca_load_row.iloc[0].get("load_pct_change", (diff_val / b_load) * 100 if b_load else 0)
else:
    load_elevation_val = 3928.28  # Fallback MW elevation
    load_pct_diff = -8.18

# Attach calculated height property to GeoJSON features
for feature in ca_geojson.get("features", []):
    feature["properties"]["elevation"] = float(load_elevation_val) * 25  # Scale factor for 3D visibility
    feature["properties"]["load_diff_mw"] = float(load_elevation_val)
    feature["properties"]["load_pct_diff"] = float(load_pct_diff)

# ========================================================
# 3. VIEW MODE CONTROLS
# ========================================================
st.sidebar.header("Navigation & Display Modes")
view_mode = st.sidebar.radio(
    "Select Display Layer:",
    ["CAISO LMP Price (% Change)", "CAISO Congestion", "CAISO Losses", "Load Comparison"]
)

# Initial Camera View Locked strictly on California
ca_view_state = pdk.ViewState(
    latitude=36.7783,
    longitude=-119.4179,
    zoom=5.5,
    pitch=45 if view_mode == "Load Comparison" else 40,
    bearing=0
)

# ========================================================
# 4. COLOR AND METRIC MAPPER
# ========================================================
layers = []
tooltip = {}

if view_mode == "Load Comparison":
    # Extrude California State Boundary in 3D to Z-value height
    ca_layer = pdk.Layer(
        "GeoJsonLayer",
        ca_geojson,
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
    layers.append(ca_layer)
    
    tooltip = {
        "html": "<b>Region:</b> California (CAISO)<br/>"
                "<b>Z-Axis Load Delta Height:</b> {properties.load_diff_mw:,.2f} MW<br/>"
                "<b>Load % Difference:</b> {properties.load_pct_diff:.2f}%",
        "style": {"backgroundColor": "#0F172A", "color": "white"}
    }

else:
    # Select target column & distinct palette for Congestion / Loss views
    if view_mode == "CAISO Congestion":
        metric_col = "congestion_pct_change"
        metric_label = "Congestion % Change"
        pos_rgb, neg_rgb = [46, 204, 113, 200], [0, 150, 136, 200]
    elif view_mode == "CAISO Losses":
        metric_col = "loss_pct_change"
        metric_label = "Loss % Change"
        pos_rgb, neg_rgb = [241, 196, 15, 200], [155, 89, 182, 200]
    else:  # LMP Price (% Change)
        metric_col = "lmp_pct_change"
        metric_label = "LMP Price % Change"
        pos_rgb, neg_rgb = [231, 76, 60, 200], [52, 152, 219, 200]

    # Pre-process dataframe with explicit RGBA color vectors and elevation scalar
    df_plot = df_caiso.copy()
    df_plot["plot_metric"] = df_plot[metric_col].fillna(0)
    df_plot["elevation_height"] = df_plot["plot_metric"].abs() * 800
    df_plot["bar_color"] = df_plot["plot_metric"].apply(lambda val: pos_rgb if val >= 0 else neg_rgb)

    column_layer = pdk.Layer(
        "ColumnLayer",
        data=df_plot,
        get_position=["longitude", "latitude"],
        get_elevation="elevation_height",
        radius=3200,
        elevation_scale=1,
        get_fill_color="bar_color",
        pickable=True,
        auto_highlight=True
    )
    layers.append(column_layer)

    # Fixed: Standard string formatting (no f-string) so PyDeck template syntax works cleanly
    tooltip = {
        "html": "<b>Node:</b> {location}<br/>"
                "<b>" + metric_label + ":</b> {" + metric_col + ":.2f}%<br/>"
                "<b>Game Price:</b> ${game_lmp:.2f}/MWh<br/>"
                "<b>Baseline Price:</b> ${baseline_lmp:.2f}/MWh",
        "style": {"backgroundColor": "#1E293B", "color": "white"}
    }

# ========================================================
# 5. RENDER PYDECK MAP & METRIC HEADERS
# ========================================================
col1, col2 = st.columns([3, 1])

with col1:
    st.pydeck_chart(pdk.Deck(
        layers=layers,
        initial_view_state=ca_view_state,
        tooltip=tooltip,
        map_style="mapbox://styles/mapbox/dark-v10"
    ))

with col2:
    st.markdown(f"### View Summary: **{view_mode}**")
    if view_mode == "Load Comparison":
        st.metric(
            label="California Grid Load Delta",
            value=f"{load_elevation_val:,.2f} MW",
            delta=f"{load_pct_diff:.2f}%"
        )
        st.info("California state boundaries extruded in 3D relative to peak load deviation.")
    else:
        avg_pct = df_caiso[metric_col].mean()
        max_node = df_caiso.loc[df_caiso[metric_col].idxmax()]
        min_node = df_caiso.loc[df_caiso[metric_col].idxmin()]
        
        st.metric(label=f"Average CAISO {view_mode}", value=f"{avg_pct:.2f}%")
        st.markdown("---")
        st.write(f"**Highest Increase:** {max_node['location']} ({max_node[metric_col]:.2f}%)")
        st.write(f"**Highest Decrease:** {min_node['location']} ({min_node[metric_col]:.2f}%)")