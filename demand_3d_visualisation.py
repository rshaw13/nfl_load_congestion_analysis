import streamlit as st
import pandas as pd
import pydeck as pdk
import requests
from pathlib import Path

# ========================================================
# 1. PAGE SETUP & PATH CONFIGURATION
# ========================================================
st.set_page_config(layout="wide", page_title="CAISO Nodal & Grid Load Dashboard")

# Relative path resolution for Streamlit Cloud & local execution
BASE_DIR = Path(__file__).parent if "__file__" in globals() else Path(".")
DATA_DIR = BASE_DIR / "gridstatus_data" / "processed_summary"

csv_nodes_path = DATA_DIR / "master_congestion_and_lmp_deltas.csv"
csv_load_path = DATA_DIR / "master_load_deltas.csv"
csv_combined_path = DATA_DIR / "master_combined_metrics.csv"

# ========================================================
# 2. CONSTANT FLOATING GAME HEADER CARD OVERLAY
# ========================================================
texans_logo_url = "https://a.espncdn.com/i/teamlogos/nfl/500/hou.png"
sf49ers_logo_url = "https://a.espncdn.com/i/teamlogos/nfl/500/sf.png"

st.markdown(f"""
<div id="game-header-card" style="
    background: rgba(24, 24, 27, 0.92);
    backdrop-filter: blur(8px);
    border: 1px solid rgba(255, 255, 255, 0.15);
    border-radius: 12px;
    padding: 14px 24px;
    color: #FFFFFF;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.6);
    max-width: 650px;
    margin: 0 auto 20px auto;
    text-align: center;
">
    <div style="font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: #A1A1AA; font-weight: 600; margin-bottom: 6px;">
        NFL Game Day Analysis • Oct 26, 2025
    </div>
    
    <div style="display: flex; align-items: center; justify-content: space-between; margin: 8px 0;">
        <!-- Left: Texans Logo & Team Info -->
        <div style="display: flex; align-items: center; gap: 12px;">
            <img src="{texans_logo_url}" alt="Texans Logo" style="width: 40px; height: 40px; object-fit: contain;" />
            <div style="text-align: left;">
                <div style="font-size: 15px; font-weight: 700;">Houston Texans</div>
                <div style="font-size: 11px; color: #A1A1AA;">(3 - 4)</div>
            </div>
        </div>

        <!-- Center: Score -->
        <div style="font-size: 24px; font-weight: 800; color: #38BDF8; padding: 0 16px;">
            26 <span style="font-size: 16px; color: #71717A; font-weight: 400;">-</span> 15
        </div>

        <!-- Right: 49ers Team Info & Logo -->
        <div style="display: flex; align-items: center; gap: 12px;">
            <div style="text-align: right;">
                <div style="font-size: 15px; font-weight: 700;">SF 49ers</div>
                <div style="font-size: 11px; color: #A1A1AA;">(5 - 3)</div>
            </div>
            <img src="{sf49ers_logo_url}" alt="49ers Logo" style="width: 40px; height: 40px; object-fit: contain;" />
        </div>
    </div>

    <!-- Kickoff Subheader -->
    <div style="border-top: 1px solid rgba(255, 255, 255, 0.12); margin-top: 8px; padding-top: 8px; display: flex; justify-content: space-around; font-size: 12px; color: #E4E4E7;">
        <div><b>CA Kickoff:</b> 10:00 AM PDT</div>
        <div style="color: #52525B;">|</div>
        <div><b>TX Kickoff:</b> 12:00 PM CDT</div>
    </div>
</div>
""", unsafe_allow_html=True)

# ========================================================
# 3. DATA LOADING & PREPARATION
# ========================================================
@st.cache_data
def load_data():
    if not csv_nodes_path.exists():
        st.error(f"Master CSV not found at `{csv_nodes_path}`. Please verify your folder structure.")
        st.stop()
        
    df_nodes = pd.read_csv(csv_nodes_path)
    
    # Filter strictly for California nodes with valid coordinates
    df_caiso = df_nodes[(df_nodes["us_state"] == "California") & 
                        df_nodes["latitude"].notna() & 
                        df_nodes["longitude"].notna()].copy()
    
    # Load grid load summary dataset
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

    return df_caiso, df_load

@st.cache_data
def get_ca_geojson():
    url = "https://raw.githubusercontent.com/PublicPlot/geojson-us-states/master/50m/06.geojson"
    try:
        response = requests.get(url, timeout=5)
        return response.json()
    except Exception:
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

# Calculate California Load variance for 3D state extrusion
ca_load_row = df_load[df_load["market_region"].str.contains("CAISO|California|SYSTEM", case=False, na=False)]
if not ca_load_row.empty:
    row = ca_load_row.iloc[0]
    g_load = float(row.get("game_load_mw", row.get("game_value", 0)))
    b_load = float(row.get("baseline_load_mw", row.get("baseline_value", 0)))
    
    diff_val = b_load - g_load
    load_elevation_val = max(abs(diff_val), g_load - b_load)
    load_pct_diff = float(row.get("load_pct_change", ((g_load - b_load) / b_load * 100) if b_load else 0))
else:
    load_elevation_val = 3928.28
    load_pct_diff = -8.18

# Inject 3D height into GeoJSON properties
for feature in ca_geojson.get("features", []):
    feature["properties"]["elevation"] = float(load_elevation_val) * 20
    feature["properties"]["load_diff_mw"] = float(load_elevation_val)
    feature["properties"]["load_pct_diff"] = float(load_pct_diff)
    feature["properties"]["fill_color"] = [255, 140, 0, 180] if load_pct_diff >= 0 else [138, 43, 226, 180]

# ========================================================
# 4. SIDEBAR CONTROLS & CAMERA VIEW
# ========================================================
st.sidebar.header("Analytics Layers")
view_mode = st.sidebar.radio(
    "Select View Mode:",
    ["CAISO LMP Price (% Change)", "CAISO Congestion", "CAISO Losses", "Load Comparison"]
)

# Lock camera strictly to California
ca_view_state = pdk.ViewState(
    latitude=36.7783,
    longitude=-119.4179,
    zoom=5.5,
    pitch=50 if view_mode == "Load Comparison" else 40,
    bearing=0
)

# ========================================================
# 5. LAYER BUILDER & TOOLTIPS
# ========================================================
layers = []

if view_mode == "Load Comparison":
    # 3D Extruded State Boundary (Node bars hidden)
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
                "<b>Z-Axis Load Delta:</b> {properties.load_diff_mw:,.2f} MW<br/>"
                "<b>Load % Difference:</b> {properties.load_pct_diff:.2f}%",
        "style": {
            "backgroundColor": "#18181B",
            "color": "#FFFFFF",
            "fontSize": "12px",
            "borderRadius": "6px",
            "padding": "8px 12px"
        }
    }

else:
    # Set metric mapping and unique non-red/blue palettes for Congestion and Losses
    if view_mode == "CAISO Congestion":
        metric_col = "congestion_pct_change"
        metric_label = "Congestion % Change"
        pos_rgb, neg_rgb = [46, 204, 113, 220], [0, 150, 136, 220]  # Emerald / Teal
    elif view_mode == "CAISO Losses":
        metric_col = "loss_pct_change"
        metric_label = "Loss % Change"
        pos_rgb, neg_rgb = [241, 196, 15, 220], [155, 89, 182, 220]  # Amber / Purple
    else:  # LMP Price (% Change)
        metric_col = "lmp_pct_change"
        metric_label = "LMP Price % Change"
        pos_rgb, neg_rgb = [235, 64, 52, 220], [52, 137, 235, 220]  # Red / Blue

    df_plot = df_caiso.copy()
    df_plot["plot_metric"] = df_plot[metric_col].fillna(0)
    df_plot["elevation_height"] = df_plot["plot_metric"].abs() * 800
    df_plot["bar_color"] = df_plot["plot_metric"].apply(lambda val: pos_rgb if val >= 0 else neg_rgb)

    column_layer = pdk.Layer(
        "ColumnLayer",
        data=df_plot,
        get_position=["longitude", "latitude"],
        get_elevation="elevation_height",
        radius=3500,
        elevation_scale=1,
        get_fill_color="bar_color",
        pickable=True,
        auto_highlight=True,
        extruded=True
    )
    layers.append(column_layer)

    # Safe tooltip string formatting (prevents f-string single brace syntax error)
    tooltip = {
        "html": "<b>Node:</b> {location}<br/>"
                "<b>State:</b> {us_state}<br/>"
                "<hr style='margin: 5px 0;'>"
                "<b>" + metric_label + ":</b> {" + metric_col + ":.2f}%<br/>"
                "<b>Game Price:</b> ${game_lmp:.2f} /MWh<br/>"
                "<b>Baseline Price:</b> ${baseline_lmp:.2f} /MWh",
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
# 6. RENDER DECK & SUMMARY SIDEBAR
# ========================================================
col1, col2 = st.columns([3, 1])

with col1:
    st.pydeck_chart(pdk.Deck(
        layers=layers,
        initial_view_state=ca_view_state,
        tooltip=tooltip,
        map_style=pdk.map_styles.CARTO_DARK
    ))

with col2:
    st.markdown(f"### **{view_mode}**")
    st.markdown("---")
    
    if view_mode == "Load Comparison":
        st.metric(
            label="California Grid Load Delta",
            value=f"{load_elevation_val:,.2f} MW",
            delta=f"{load_pct_diff:.2f}%"
        )
        st.info("Bars hidden. California 3D boundary elevated based on load difference.")
    else:
        avg_pct = df_plot[metric_col].mean()
        max_idx = df_plot[metric_col].idxmax()
        min_idx = df_plot[metric_col].idxmin()
        
        st.metric(label=f"Avg {metric_label}", value=f"{avg_pct:.2f}%")
        st.markdown("---")
        if pd.notna(max_idx):
            st.write(f"**Max Shift:**\n{df_plot.loc[max_idx, 'location']} (`+{df_plot.loc[max_idx, metric_col]:.2f}%`)")
        if pd.notna(min_idx):
            st.write(f"**Min Shift:**\n{df_plot.loc[min_idx, 'location']} (`{df_plot.loc[min_idx, metric_col]:.2f}%`)")