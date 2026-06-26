"""Maritime Scenario Builder — Streamlit front-end.
MMG physics model — no constant-velocity fallback.
"""

from __future__ import annotations

import json
import random
from typing import List

import folium
import plotly.graph_objects as go
import streamlit as st
from shapely.geometry import Point, Polygon
from streamlit_folium import st_folium

from core.regions import Region, available_regions, load_region
from core.scenario import ENCOUNTER_TYPES, Scenario, Ship, Waypoint, next_color
from core.scenario_builder import build_scenario
from core.physics import scenario_with_physics, EnvParams
from core.simulation_manager import SimulationManager

st.set_page_config(layout="wide", page_title="Multi-Ship Trajectory Simulation")


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

def _init_state() -> None:
    st.session_state.setdefault("ships", [])
    st.session_state.setdefault("active_ship_idx", None)
    st.session_state.setdefault("last_clicked", None)
    st.session_state.setdefault("trajectory_result", None)
    st.session_state.setdefault("radar_result", None)
    st.session_state.setdefault("encounter_summary", None)
    st.session_state.setdefault("sim_running", False)

_init_state()


def _new_ship_dict(index: int) -> dict:
    return {
        "ship_id":             f"Ship_{index + 1}",
        "mmsi":                211_000_000 + random.randint(1, 999_999),
        "length_m":            100.0,
        "beam_m":              15.0,
        "draught_m":           5.0,
        "initial_speed_mps":   5.0,
        "initial_heading_deg": 0.0,
        "waypoints":           [],
        "radar_rotation_s":    6.0,
        "color":               next_color(index),
        "start_time_s":        0.0,
    }


def _ui_to_scenario(name: str, region_key: str, encounter_type: str,
                    duration_s: float) -> Scenario:
    ships: List[Ship] = []
    for s in st.session_state["ships"]:
        ships.append(Ship(
            ship_id=s["ship_id"], mmsi=int(s["mmsi"]),
            length_m=float(s["length_m"]), beam_m=float(s["beam_m"]),
            draught_m=float(s["draught_m"]),
            initial_speed_mps=float(s["initial_speed_mps"]),
            initial_heading_deg=float(s["initial_heading_deg"]),
            waypoints=[Waypoint(lat=lat, lon=lon) for (lat, lon) in s["waypoints"]],
            radar_rotation_s=float(s["radar_rotation_s"]),
            color=s["color"],
            start_time_s=float(s.get("start_time_s", 0.0)),
        ))
    return Scenario(name=name, region=region_key,
                    encounter_type=encounter_type,
                    duration_s=float(duration_s), ships=ships)


def _region_polygon(region: Region) -> Polygon | None:
    if not region.bbox:
        return None
    return Polygon([(lon, lat) for (lat, lon) in region.bbox])


def _point_in_region(lat: float, lon: float, region: Region) -> bool:
    poly = _region_polygon(region)
    if poly is None:
        return True
    return poly.contains(Point(lon, lat))


def _clear_sim() -> None:
    for k in ["sim_step", "sim_trajs", "sim_ids", "sim_colors"]:
        st.session_state.pop(k, None)
    st.session_state["sim_running"] = False


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("Simulation Controls")

    region_options = available_regions()
    region_keys    = [k for k, _ in region_options]
    region_labels  = {k: name for k, name in region_options}

    location_style = st.selectbox(
        "Choose Location", region_keys,
        format_func=lambda k: region_labels[k],
    )
    region = load_region(location_style)

    if st.button("Reset Points"):
        for s in st.session_state["ships"]:
            s["waypoints"] = []
        st.session_state["last_clicked"] = None
        st.session_state["trajectory_result"] = None
        st.session_state["radar_result"] = None
        _clear_sim()
        st.rerun()

    st.markdown("---")
    st.subheader("Scenario")

    encounter_keys   = [k for k, _, _ in ENCOUNTER_TYPES]
    encounter_labels = {k: lbl for k, lbl, _ in ENCOUNTER_TYPES}
    encounter_help   = {k: hlp for k, _, hlp in ENCOUNTER_TYPES}

    encounter_type = st.selectbox(
        "Encounter type", encounter_keys,
        format_func=lambda k: encounter_labels[k],
    )
    st.caption(encounter_help[encounter_type])

    scenario_name = st.text_input(
        "Scenario name",
        value=f"{region.display_name} — {encounter_labels[encounter_type]}",
    )
    scenario_duration_s = st.number_input(
        "Scenario duration (s)", 60.0, 36000.0, 3600.0, 60.0,
        help="Total scenario length on the shared clock. The encounter "
             "analysis stops at this time and ignores any ship whose start "
             "time is beyond it.",
    )

    if encounter_type != "custom":
        if st.button(
            f"⚡ Auto-Generate: {encounter_labels[encounter_type]}",
            use_container_width=True,
        ):
            raw_ships = build_scenario(encounter_type, location_style)
            # Validate all auto-generated waypoints are inside the boundary
            poly = _region_polygon(region)
            if poly is not None:
                for s in raw_ships:
                    s["waypoints"] = [
                        (lat, lon) for (lat, lon) in s["waypoints"]
                        if poly.contains(Point(lon, lat))
                    ]
            st.session_state["ships"] = raw_ships
            st.session_state["active_ship_idx"] = 0 if raw_ships else None
            st.session_state["trajectory_result"] = None
            st.session_state["radar_result"] = None
            _clear_sim()
            st.rerun()

    st.markdown("---")
    st.subheader("Ships")

    col_add, col_rm = st.columns(2)
    if col_add.button("➕ Add Ship", use_container_width=True):
        st.session_state["ships"].append(_new_ship_dict(len(st.session_state["ships"])))
        st.session_state["active_ship_idx"] = len(st.session_state["ships"]) - 1

    if col_rm.button("🗑 Clear All", use_container_width=True):
        st.session_state["ships"] = []
        st.session_state["active_ship_idx"] = None
        st.session_state["trajectory_result"] = None
        st.session_state["radar_result"] = None
        _clear_sim()
        st.rerun()

    if not st.session_state["ships"]:
        st.info("Use ⚡ Auto-Generate or ➕ Add Ship to begin.")
    else:
        ship_labels = [s["ship_id"] for s in st.session_state["ships"]]
        active = st.selectbox(
            "Active ship",
            list(range(len(ship_labels))),
            index=st.session_state["active_ship_idx"] or 0,
            format_func=lambda i: ship_labels[i],
        )
        st.session_state["active_ship_idx"] = active
        s = st.session_state["ships"][active]

        with st.expander(f"⚙ {s['ship_id']} parameters", expanded=False):
            s["ship_id"] = st.text_input("Ship ID", s["ship_id"], key=f"id_{active}")
            s["mmsi"]    = st.number_input("MMSI", 100_000_000, 999_999_999,
                                           int(s["mmsi"]), 1, key=f"mmsi_{active}")
            c1, c2, c3 = st.columns(3)
            s["length_m"]  = c1.number_input("Length (m)", 5.0, 400.0, float(s["length_m"]),  1.0, key=f"len_{active}")
            s["beam_m"]    = c2.number_input("Beam (m)",   2.0,  60.0, float(s["beam_m"]),    0.5, key=f"beam_{active}")
            s["draught_m"] = c3.number_input("Draught (m)",0.5,  25.0, float(s["draught_m"]), 0.1, key=f"dr_{active}")
            c4, c5 = st.columns(2)
            s["initial_speed_mps"]   = c4.number_input("Speed (m/s)",  0.0, 30.0,  float(s["initial_speed_mps"]),   0.1, key=f"sp_{active}")
            s["initial_heading_deg"] = c5.number_input("Heading (°)",   0.0, 360.0, float(s["initial_heading_deg"]), 1.0, key=f"hd_{active}")
            s["radar_rotation_s"]    = st.number_input("Radar period (s)", 1.0, 120.0, float(s["radar_rotation_s"]), 0.5, key=f"rad_{active}")
            s["start_time_s"]        = st.number_input(
                "Start time (s)", 0.0, 36000.0,
                float(s.get("start_time_s", 0.0)), 10.0, key=f"start_{active}",
                help="Seconds after t=0 when this ship enters the scene. "
                     "Use this to stagger ships so paths that cross on the map "
                     "are not flagged as encounters unless ships are actually "
                     "present at the same time.",
            )
            s["color"] = st.color_picker("Color", s["color"], key=f"col_{active}")

            cu, cc, cr = st.columns(3)
            if cu.button("↶ Undo",  key=f"undo_{active}", disabled=not s["waypoints"], use_container_width=True):
                s["waypoints"].pop(); st.rerun()
            if cc.button("Clear",   key=f"clr_{active}",  disabled=not s["waypoints"], use_container_width=True):
                s["waypoints"] = []; st.rerun()
            if cr.button("Remove",  key=f"rm_{active}",   use_container_width=True):
                st.session_state["ships"].pop(active)
                st.session_state["active_ship_idx"] = (
                    None if not st.session_state["ships"] else max(0, active - 1))
                st.rerun()

    # -----------------------------------------------------------------------
    # Environment (MMG physics inputs)
    # -----------------------------------------------------------------------
    st.markdown("---")
    st.subheader("🌊 Environment")

    wind_speed    = st.slider("Wind speed (m/s)",    0.0,  20.0,  0.0, 0.5)
    wind_dir      = st.slider("Wind direction (°)",  0,    360,   0,   5)
    current_speed = st.slider("Current speed (m/s)", 0.0,   2.0,  0.7, 0.1)
    current_dir   = st.slider("Current from (°)",    0,    360,  200,  5)

    use_live_wind = st.checkbox(
        "Fetch live wind (OpenWeatherMap)", value=True,
        help="Overrides the wind sliders above with real-time data for the simulation area."
    )

    st.markdown("---")
    map_style_folium = st.selectbox(
        "Map Style", ["OpenStreetMap", "CartoDB positron", "CartoDB dark_matter"])
    map_style_plotly = {
        "OpenStreetMap":       "open-street-map",
        "CartoDB positron":    "carto-positron",
        "CartoDB dark_matter": "carto-darkmatter",
    }.get(map_style_folium, "open-street-map")

    st.markdown("---")
    scenario = _ui_to_scenario(scenario_name, location_style, encounter_type,
                               scenario_duration_s)
    st.download_button(
        "⬇ Save Scenario (JSON)", data=scenario.to_json(),
        file_name=f"{scenario_name.replace(' ','_').replace('—','-')}.json",
        mime="application/json", use_container_width=True,
        disabled=not st.session_state["ships"],
    )

    st.markdown("---")
    st.subheader("Run Simulation")

    if st.button("▶ Build Trajectories (MMG Physics)",
                 disabled=not st.session_state["ships"],
                 use_container_width=True):
        missing = [s["ship_id"] for s in st.session_state["ships"]
                   if len(s["waypoints"]) < 2]
        if missing:
            st.warning(f"Need ≥ 2 waypoints: {', '.join(missing)}")
        else:
            from core.radar import embed_radar_in_scenario

            ep = EnvParams(
                wind_speed_mps    = float(wind_speed),
                wind_dir_deg      = float(wind_dir),
                current_speed_mps = float(current_speed),
                current_dir_deg   = float(current_dir),
            )

            with st.spinner("Running MMG physics simulation…"):
                scen_dict = scenario.to_dict()
                result    = scenario_with_physics(
                    scen_dict,
                    env_params    = ep,
                    dt            = 1.0,
                    use_live_wind = use_live_wind,
                )
                # Forward per-ship timing onto the physics output (the
                # physics layer ignores it; the SimulationManager reads it).
                start_map = {s["ship_id"]: s.get("start_time_s", 0.0)
                             for s in scen_dict.get("ships", [])}
                for s in result.get("ships", []):
                    s["start_time_s"] = float(start_map.get(s["ship_id"], 0.0))
                result["duration_s"] = float(scenario_duration_s)

            radar_origin = region.center
            radar_s      = (st.session_state["ships"][0]["radar_rotation_s"]
                            if st.session_state["ships"] else 6.0)
            result = embed_radar_in_scenario(result, radar_origin, radar_s)

            with st.spinner("Running encounter analysis…"):
                mgr = SimulationManager(
                    result, dt=1.0,
                    max_duration_s=float(scenario_duration_s),
                )
                for _ in mgr.run():
                    pass
                st.session_state["encounter_summary"] = mgr.summary()

            st.session_state["trajectory_result"] = result
            st.session_state["radar_result"]      = result
            _clear_sim()
            st.rerun()

    if st.session_state.get("sim_running"):
        if st.button("⏹ Stop", use_container_width=True):
            _clear_sim(); st.rerun()


# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------

st.markdown("""<style>
.stSubheader{color:#2c3e50;border-bottom:2px solid #f0f2f6;
             padding-bottom:.5rem;margin-bottom:1rem;}
.small-font{font-size:16px !important;}
.stButton>button{border-radius:10px;}
</style>""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Folium map
# ---------------------------------------------------------------------------

def _build_folium_map(region: Region, tiles: str) -> folium.Map:
    fmap = folium.Map(location=list(region.center),
                      zoom_start=region.default_zoom, tiles=tiles)
    if region.bbox:
        folium.Polygon(locations=region.bbox, color="#d7191c", weight=2,
                       fill=True, fill_color="#fdae61", fill_opacity=0.25,
                       tooltip="Working Area").add_to(fmap)
    if region.los:
        folium.PolyLine(locations=region.los, color="#5bc8f5", weight=2,
                        dash_array="6,8", opacity=0.9,
                        tooltip="Line of Sight").add_to(fmap)
    for ship in st.session_state["ships"]:
        wps = ship["waypoints"]
        if not wps:
            continue
        if len(wps) >= 2:
            folium.PolyLine(locations=wps, color=ship["color"], weight=3,
                            opacity=0.8, tooltip=f"{ship['ship_id']} route").add_to(fmap)
        for j, (lat, lon) in enumerate(wps):
            icon = folium.Icon(
                color="green" if j == 0 else "red" if j == len(wps) - 1 and len(wps) > 1 else "blue",
                icon="ship" if j == 0 else "flag-checkered" if j == len(wps) - 1 and len(wps) > 1 else "circle",
                prefix="fa",
            )
            label = (f"{ship['ship_id']} — "
                     + ("start" if j == 0
                        else "end" if j == len(wps) - 1 and len(wps) > 1
                        else f"wp {j+1}"))
            folium.Marker(
                location=(lat, lon),
                popup=folium.Popup(f"{label}<br>{lat:.5f},{lon:.5f}", max_width=220),
                icon=icon,
            ).add_to(fmap)
    return fmap


# ---------------------------------------------------------------------------
# Plotly animation
# ---------------------------------------------------------------------------

def _build_animation(result: dict, region: Region,
                     map_style: str, speed_ms: int) -> go.Figure:
    """Animate ships on the shared simulation clock.

    Each ship is hidden before its ``start_time_s`` and held at its last
    point after its trajectory ends, so a ship that enters at t=600s
    actually appears 600s into the animation.
    """
    fig   = go.Figure()
    ships = result.get("ships", [])

    # Line of Sight — dotted light blue
    if region.los:
        fig.add_trace(go.Scattermap(
            lon=[p[1] for p in region.los], lat=[p[0] for p in region.los],
            mode="lines+markers",
            line=dict(width=2, color="#5bc8f5"),
            marker=dict(size=4, color="#5bc8f5"),
            name="Line of Sight", opacity=0.9))

    # Per-ship alive window on the shared clock.
    ship_meta = []
    for ship in ships:
        traj = ship.get("trajectory", [])
        if not traj:
            ship_meta.append(None)
            continue
        start_s = float(ship.get("start_time_s", 0.0))
        end_s   = start_s + (len(traj) - 1)
        ship_meta.append({"start_s": start_s, "end_s": end_s})

    for ship, meta in zip(ships, ship_meta):
        traj = ship.get("trajectory", [])
        if not traj or meta is None:
            continue
        # Ship Path — solid line, faint ghost
        fig.add_trace(go.Scattermap(
            lon=[p["lon"] for p in traj], lat=[p["lat"] for p in traj],
            mode="lines", line=dict(width=2, color=ship["color"]),
            name=f"{ship['ship_id']} path", opacity=0.3))
        # Animated trail placeholder — empty until the ship enters
        fig.add_trace(go.Scattermap(
            lon=[], lat=[],
            mode="lines", line=dict(width=3, color=ship["color"]),
            name=f"{ship['ship_id']} trail"))
        # Ship Position — empty until entry, then a red dot
        fig.add_trace(go.Scattermap(
            lon=[], lat=[],
            mode="markers+text",
            marker=dict(size=12, color="red"),
            text=[ship["ship_id"]], textposition="top right",
            textfont=dict(size=10, color=ship["color"]),
            name=f"{ship['ship_id']} position"))

    # Animation timeline: cover the whole scenario, not just the longest traj.
    scenario_end = max(
        (m["end_s"] for m in ship_meta if m is not None),
        default=0.0,
    )
    timeline_end = max(float(result.get("duration_s", scenario_end)), scenario_end)

    radar_s = ships[0].get("radar_rotation_s", 6.0) if ships else 6.0
    step    = max(1.0, float(radar_s))                 # seconds per frame
    frames  = []

    t  = 0.0
    fi = 0
    while t <= timeline_end + 1e-6:
        fd = []

        # LOS in every frame — dotted light blue
        if region.los:
            fd.append(go.Scattermap(
                lon=[p[1] for p in region.los], lat=[p[0] for p in region.los],
                mode="lines+markers",
                line=dict(width=2, color="#5bc8f5"),
                marker=dict(size=4, color="#5bc8f5"),
                opacity=0.9))

        for ship, meta in zip(ships, ship_meta):
            traj = ship.get("trajectory", [])

            # Ship Path ghost — solid, faint (always visible for context)
            fd.append(go.Scattermap(
                lon=[p["lon"] for p in traj], lat=[p["lat"] for p in traj],
                mode="lines", line=dict(width=2, color=ship["color"]), opacity=0.15))

            if not traj or meta is None:
                fd.append(go.Scattermap(lon=[], lat=[], mode="lines"))
                fd.append(go.Scattermap(lon=[], lat=[], mode="markers"))
                continue

            local_t = t - meta["start_s"]
            if local_t < 0:
                # Ship has not entered the scene yet — hide it.
                fd.append(go.Scattermap(lon=[], lat=[], mode="lines"))
                fd.append(go.Scattermap(lon=[], lat=[], mode="markers"))
                continue

            idx   = min(int(round(local_t)), len(traj) - 1)
            trail = traj[max(0, idx - 40): idx + 1]
            cur   = traj[idx]
            done  = t > meta["end_s"]
            label = (f"{ship['ship_id']} t={t:.0f}s "
                     f"{cur['heading']:.0f}°"
                     + (" ⛔" if done else ""))

            # Animated trail — solid ship color
            fd.append(go.Scattermap(
                lon=[p["lon"] for p in trail], lat=[p["lat"] for p in trail],
                mode="lines", line=dict(width=3, color=ship["color"])))

            # Ship Position — red dot
            fd.append(go.Scattermap(
                lon=[cur["lon"]], lat=[cur["lat"]],
                mode="markers+text",
                marker=dict(size=12, color="red"),
                text=[label],
                textposition="top right",
                textfont=dict(size=9, color=ship["color"])))

        frames.append(go.Frame(data=fd, name=f"f{fi}"))
        t  += step
        fi += 1

    fig.frames = frames
    fig.update_layout(
        height=540,
        map=dict(style=map_style,
                 center=dict(lat=region.center[0], lon=region.center[1]),
                 zoom=region.default_zoom - 1),
        updatemenus=[dict(
            type="buttons", showactive=True, direction="left",
            x=0.1, xanchor="right", y=1.08, yanchor="top",
            bgcolor="rgba(255,255,255,0.15)", bordercolor="#DDD", borderwidth=1,
            pad={"r": 10, "t": 10, "b": 10},
            buttons=[
                dict(label="▶️ Play", method="animate",
                     args=[None, {"frame": {"duration": speed_ms, "redraw": True},
                                  "fromcurrent": True, "mode": "immediate"}]),
                dict(label="⏹ Stop", method="animate",
                     args=[[None], {"frame": {"duration": 0, "redraw": False},
                                    "mode": "immediate",
                                    "transition": {"duration": 0}}]),
                dict(label="⏮ Reset", method="animate",
                     args=[["f0"], {"frame": {"duration": 0, "redraw": True},
                                    "mode": "immediate",
                                    "transition": {"duration": 0}}]),
            ],
        )],
        legend=dict(font=dict(size=11)),
        margin={"r": 0, "t": 60, "l": 0, "b": 0},
    )
    return fig


# ---------------------------------------------------------------------------
# Radar polar plot
# ---------------------------------------------------------------------------

def _build_radar_polar(result: dict) -> go.Figure:
    fig = go.Figure()
    for ship in result.get("ships", []):
        rrs = ship.get("radar_returns", [])
        if not rrs:
            continue
        fig.add_trace(go.Scatterpolar(
            r=[r["range_m"]  for r in rrs],
            theta=[r["azimuth"] for r in rrs],
            mode="markers",
            marker=dict(size=5, color=ship["color"], opacity=0.7),
            name=ship["ship_id"],
            hovertemplate=(
                "<b>%{fullData.name}</b><br>"
                "Range: %{r:.0f}m<br>"
                "Az: %{theta:.1f}°<extra></extra>"),
        ))
    fig.update_layout(
        title="Radar Returns — Range vs Azimuth",
        polar=dict(radialaxis=dict(visible=True, title="Range (m)"),
                   angularaxis=dict(direction="clockwise", rotation=90)),
        height=380, showlegend=True,
    )
    return fig


# ---------------------------------------------------------------------------
# Main layout
# ---------------------------------------------------------------------------

col1, col2 = st.columns([4, 1])

with col1:
    st.subheader("1. Select Points on Map")
    fmap     = _build_folium_map(region, map_style_folium)
    map_data = st_folium(fmap, width=900, height=500, returned_objects=["last_clicked"])

    if not st.session_state.get("sim_running"):
        if map_data and map_data.get("last_clicked"):
            click     = map_data["last_clicked"]
            click_key = (round(click["lat"], 7), round(click["lng"], 7))
            if click_key != st.session_state.get("last_clicked"):
                st.session_state["last_clicked"] = click_key
                if st.session_state["active_ship_idx"] is None:
                    st.warning("Add a ship first.")
                else:
                    if not _point_in_region(click["lat"], click["lng"], region):
                        st.warning("⛔ Click inside the orange boundary — that point is outside the working area.")
                    else:
                        active = st.session_state["active_ship_idx"]
                        st.session_state["ships"][active]["waypoints"].append(
                            (click["lat"], click["lng"]))
                        st.rerun()

    st.caption("Click inside the orange boundary to add waypoints, "
               "or use ⚡ Auto-Generate in the sidebar.")

with col2:
    st.subheader("Scenario Status")
    if not st.session_state["ships"]:
        st.warning("No ships yet")
        st.info("Use **⚡ Auto-Generate** or **➕ Add Ship**.")
    else:
        total_wps = sum(len(s["waypoints"]) for s in st.session_state["ships"])
        st.markdown(
            f"<p class='small-font'><b>{len(st.session_state['ships'])}</b> ship(s), "
            f"<b>{total_wps}</b> waypoint(s)</p>", unsafe_allow_html=True)
        for i, s in enumerate(st.session_state["ships"]):
            badge = "🟢" if i == st.session_state["active_ship_idx"] else "⚪"
            n     = len(s["waypoints"])
            line  = (f"{badge} **{s['ship_id']}** — "
                     + ("no waypoints" if n == 0
                        else "end pending" if n == 1
                        else f"{n} wps ✅"))
            st.markdown(f"<span style='color:{s['color']}'>●</span> {line}",
                        unsafe_allow_html=True)
            if s["waypoints"]:
                st.markdown(
                    f"<p class='small-font'>&nbsp;&nbsp;"
                    f"Start: {s['waypoints'][0][0]:.4f},{s['waypoints'][0][1]:.4f}</p>",
                    unsafe_allow_html=True)
                if len(s["waypoints"]) > 1:
                    st.markdown(
                        f"<p class='small-font'>&nbsp;&nbsp;"
                        f"End: {s['waypoints'][-1][0]:.4f},{s['waypoints'][-1][1]:.4f}</p>",
                        unsafe_allow_html=True)
        st.progress(min(1.0, total_wps / max(2 * len(st.session_state["ships"]), 1)))

    with st.expander("Preview scenario JSON"):
        st.code(scenario.to_json(), language="json")


# ---------------------------------------------------------------------------
# Section 2 — Trajectory output
# ---------------------------------------------------------------------------

st.markdown("---")

if st.session_state.get("trajectory_result"):
    result = st.session_state["trajectory_result"]
    st.subheader("2. Trajectory Output")
    col_a, col_b = st.columns(2)
    with col_a:
        for ship in result["ships"]:
            pts = ship.get("trajectory", [])
            rrs = ship.get("radar_returns", [])
            if pts:
                st.markdown(
                    f"<span style='color:{ship['color']}'>●</span> "
                    f"**{ship['ship_id']}** — {len(pts)} traj pts · "
                    f"{len(rrs)} radar returns · {pts[-1]['t']:.1f} s",
                    unsafe_allow_html=True)
    with col_b:
        st.download_button(
            "⬇ Download Full JSON",
            data=json.dumps(result, indent=2),
            file_name="multi_ship_simulation.json",
            mime="application/json")
    with st.expander("Preview JSON"):
        st.code(json.dumps(result, indent=2)[:2000] + "\n...", language="json")
    st.markdown("---")


# ---------------------------------------------------------------------------
# Section 3 — Animated visualisation
# ---------------------------------------------------------------------------

if st.session_state.get("trajectory_result"):
    result = st.session_state["trajectory_result"]
    st.subheader("3. Simulation Visualisation")
    speed_ms = st.slider("Animation Speed (ms/frame)", 50, 800, 200, 50)
    fig_anim = _build_animation(result, region, map_style_plotly, speed_ms)
    st.plotly_chart(fig_anim, use_container_width=True)
    st.caption("▶️ Play animates all ships simultaneously. "
               "Trail shows recent path. Ship position shown as red dot.")
    st.markdown("---")


# ---------------------------------------------------------------------------
# Section 4 — Radar visualisation
# ---------------------------------------------------------------------------

if st.session_state.get("radar_result"):
    result = st.session_state["radar_result"]
    st.subheader("4. Radar Simulation")
    col_r1, col_r2 = st.columns([1, 1])
    with col_r1:
        st.plotly_chart(_build_radar_polar(result), use_container_width=True)
    with col_r2:
        st.markdown("**Radar Return Summary**")
        for ship in result["ships"]:
            rrs = ship.get("radar_returns", [])
            if not rrs:
                continue
            ranges = [r["range_m"]  for r in rrs]
            azs    = [r["azimuth"]  for r in rrs]
            st.markdown(
                f"<span style='color:{ship['color']}'>●</span> "
                f"**{ship['ship_id']}**<br>"
                f"&nbsp;&nbsp;Sweeps: {len(rrs)}<br>"
                f"&nbsp;&nbsp;Range: {min(ranges):.0f}–{max(ranges):.0f} m<br>"
                f"&nbsp;&nbsp;Azimuth: {min(azs):.1f}°–{max(azs):.1f}°<br>"
                f"&nbsp;&nbsp;RCS: {rrs[0]['rcs_dbm2']} dBm²",
                unsafe_allow_html=True)
            st.markdown("")
    st.markdown("---")


# ---------------------------------------------------------------------------
# Section 5 — Encounter analysis (multi-ship simulation manager)
# ---------------------------------------------------------------------------

if st.session_state.get("encounter_summary"):
    summary = st.session_state["encounter_summary"]
    st.subheader("5. Encounter Analysis")

    icon = {"head_on": "🚨", "crossing": "⚠️",
            "overtaking": "↗️", "following": "➡️"}

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Duration",  f"{summary['duration_s']:.0f} s")
    m2.metric("Ships",     summary["ship_count"])
    m3.metric("Encounters", summary["events_total"])
    by_type = summary["events_by_type"]
    worst   = "head_on" if by_type.get("head_on") else (
              "crossing" if by_type.get("crossing") else (
              "overtaking" if by_type.get("overtaking") else "—"))
    m4.metric("Worst type", f"{icon.get(worst,'')} {worst}")

    if by_type:
        st.markdown("**Breakdown:** " + " · ".join(
            f"{icon.get(k,'')} {k} × {v}" for k, v in by_type.items()))

    windows = summary.get("ship_windows", [])
    if windows:
        st.markdown("**Ship presence on the shared clock**")
        for w in windows:
            st.markdown(
                f"&nbsp;&nbsp;**{w['ship_id']}** — alive "
                f"`t={w['start_time_s']:.0f}s → {w['end_time_s']:.0f}s`",
                unsafe_allow_html=True,
            )

    if summary["events"]:
        st.markdown("**Event timeline**")
        for ev in summary["events"][:25]:
            ships = " ↔ ".join(ev["ships"])
            st.markdown(
                f"&nbsp;&nbsp;`t={ev['t']:>6.1f}s` "
                f"{icon.get(ev['type'],'')} **{ev['type']}** — "
                f"{ships} · {ev['distance_m']:.0f} m apart "
                f"(Δhdg {ev['hdg_diff']:.0f}°)",
                unsafe_allow_html=True)
        if len(summary["events"]) > 25:
            st.caption(f"… and {len(summary['events']) - 25} more events.")
    else:
        st.success("No close-quarters encounters detected.")
    st.markdown("---")


# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

st.caption("Multi-ship trajectory simulation — MMG physics model.")