"""Maritime Scenario Builder - Streamlit front-end.
MMG physics model - no constant-velocity fallback.
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
from core.sensors import default_sensor_layout
from core.passive_radar import simulate_passive_detections, trajectory_from_dict

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
    st.session_state.setdefault("passive_result", None)

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


def _corridor_polygon(region: Region) -> Polygon | None:
    if not region.river_corridor:
        return None
    return Polygon([(lon, lat) for (lat, lon) in region.river_corridor])


def _point_in_region(lat: float, lon: float, region: Region) -> bool:
    poly = _region_polygon(region)
    if poly is None:
        return True
    return poly.contains(Point(lon, lat))


def _snap_to_los(lat: float, lon: float, region: Region) -> tuple[float, float]:
    """Return the point on the region's LOS line closest to (lat, lon).

    Used to correct auto-generated waypoints that were placed slightly off
    the river so ships don't try to sail on land.
    """
    if not region.los:
        return lat, lon
    from shapely.geometry import LineString, Point as _Pt
    line = LineString([(ln, la) for (la, ln) in region.los])
    p = _Pt(lon, lat)
    nearest = line.interpolate(line.project(p))
    return (nearest.y, nearest.x)


def _count_out_of_bounds(result: dict, region: Region) -> dict[str, int]:
    """Count trajectory points outside the working-area polygon, per ship.

    Returns a {ship_id: count} mapping. Ships fully inside the polygon map
    to 0. If the region has no polygon defined, every ship maps to 0.
    """
    poly = _region_polygon(region)
    counts: dict[str, int] = {}
    if poly is None:
        return {s["ship_id"]: 0 for s in result.get("ships", [])}
    for ship in result.get("ships", []):
        n_out = sum(
            1 for p in ship.get("trajectory", [])
            if not poly.contains(Point(p["lon"], p["lat"]))
        )
        counts[ship["ship_id"]] = n_out
    return counts


def _clear_sim() -> None:
    for k in ["sim_step", "sim_trajs", "sim_ids", "sim_colors"]:
        st.session_state.pop(k, None)
    st.session_state["sim_running"] = False


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("Ship Simulator")
    st.caption("Set up ships, pick a scenario, and run the simulation.")

    # -----------------------------------------------------------------------
    # Step 1 - Location
    # -----------------------------------------------------------------------
    st.markdown("### Step 1 - Where")
    region_options = available_regions()
    region_keys    = [k for k, _ in region_options]
    region_labels  = {k: name for k, name in region_options}

    location_style = st.selectbox(
        "Location", region_keys,
        format_func=lambda k: region_labels[k],
        help="Pick which port area to simulate.",
    )
    region = load_region(location_style)

    # -----------------------------------------------------------------------
    # Step 2 - Scenario type
    # -----------------------------------------------------------------------
    st.markdown("### Step 2 - Scenario")
    encounter_keys   = [k for k, _, _ in ENCOUNTER_TYPES]
    encounter_labels = {k: lbl for k, lbl, _ in ENCOUNTER_TYPES}
    encounter_help   = {k: hlp for k, _, hlp in ENCOUNTER_TYPES}

    encounter_type = st.selectbox(
        "Scenario type", encounter_keys,
        format_func=lambda k: encounter_labels[k],
        help="Custom = you build the ships yourself. "
             "Others give you a ready-made example you can then edit.",
    )
    st.caption(encounter_help[encounter_type])

    if encounter_type != "custom":
        if st.button(
            f"Load {encounter_labels[encounter_type]} example",
            use_container_width=True,
            type="primary",
        ):
            raw_ships = build_scenario(encounter_type, location_style)
            for s in raw_ships:
                s["waypoints"] = [
                    _snap_to_los(lat, lon, region)
                    for (lat, lon) in s["waypoints"]
                ]
            st.session_state["ships"] = raw_ships
            st.session_state["active_ship_idx"] = 0 if raw_ships else None
            st.session_state["trajectory_result"] = None
            st.session_state["radar_result"] = None
            st.session_state["passive_result"] = None
            _clear_sim()
            st.rerun()

    # -----------------------------------------------------------------------
    # Step 3 - Ships
    # -----------------------------------------------------------------------
    st.markdown("### Step 3 - Ships")
    st.caption("Click on the map to place waypoints for the selected ship.")

    col_add, col_rm = st.columns(2)
    if col_add.button("Add a ship", use_container_width=True):
        st.session_state["ships"].append(_new_ship_dict(len(st.session_state["ships"])))
        st.session_state["active_ship_idx"] = len(st.session_state["ships"]) - 1

    if col_rm.button("Remove all", use_container_width=True):
        st.session_state["ships"] = []
        st.session_state["active_ship_idx"] = None
        st.session_state["trajectory_result"] = None
        st.session_state["radar_result"] = None
        st.session_state["passive_result"] = None
        _clear_sim()
        st.rerun()

    if not st.session_state["ships"]:
        st.info("No ships yet. Click 'Add a ship' or load an example above.")
    else:
        ship_labels = [s["ship_id"] for s in st.session_state["ships"]]
        active = st.selectbox(
            "Which ship am I placing waypoints for?",
            list(range(len(ship_labels))),
            index=st.session_state["active_ship_idx"] or 0,
            format_func=lambda i: ship_labels[i],
        )
        st.session_state["active_ship_idx"] = active
        s = st.session_state["ships"][active]

        with st.expander(f"Edit {s['ship_id']}", expanded=False):
            s["ship_id"] = st.text_input("Name", s["ship_id"], key=f"id_{active}")
            s["mmsi"]    = st.number_input(
                "MMSI (ship's radio ID)", 100_000_000, 999_999_999,
                int(s["mmsi"]), 1, key=f"mmsi_{active}",
            )
            c1, c2, c3 = st.columns(3)
            s["length_m"]  = c1.number_input("Length (m)", 5.0, 400.0, float(s["length_m"]),  1.0, key=f"len_{active}")
            s["beam_m"]    = c2.number_input("Width (m)",  2.0,  60.0, float(s["beam_m"]),    0.5, key=f"beam_{active}")
            s["draught_m"] = c3.number_input("Depth (m)",  0.5,  25.0, float(s["draught_m"]), 0.1,
                                             key=f"dr_{active}", help="How deep the hull sits below the water.")
            c4, c5 = st.columns(2)
            s["initial_speed_mps"]   = c4.number_input(
                "Speed (m/s)", 0.0, 30.0,
                float(s["initial_speed_mps"]), 0.1, key=f"sp_{active}",
                help="5 m/s is roughly 10 knots.",
            )
            s["initial_heading_deg"] = c5.number_input(
                "Facing (0-360)", 0.0, 360.0,
                float(s["initial_heading_deg"]), 1.0, key=f"hd_{active}",
                help="0 = North, 90 = East, 180 = South, 270 = West.",
            )
            s["start_time_s"] = st.number_input(
                "Enters the scene after (seconds)",
                0.0, 36000.0, float(s.get("start_time_s", 0.0)), 10.0,
                key=f"start_{active}",
                help="Leave at 0 for ships that are there from the start. "
                     "Use higher values to stagger arrivals.",
            )
            s["radar_rotation_s"] = st.number_input(
                "Radar rotation (seconds per turn)",
                1.0, 120.0, float(s["radar_rotation_s"]), 0.5,
                key=f"rad_{active}",
            )
            s["color"] = st.color_picker("Colour on the map", s["color"], key=f"col_{active}")

            cu, cc, cr = st.columns(3)
            if cu.button("Undo last",  key=f"undo_{active}", disabled=not s["waypoints"], use_container_width=True):
                s["waypoints"].pop(); st.rerun()
            if cc.button("Clear waypoints",   key=f"clr_{active}",  disabled=not s["waypoints"], use_container_width=True):
                s["waypoints"] = []; st.rerun()
            if cr.button("Delete ship",  key=f"rm_{active}",   use_container_width=True):
                st.session_state["ships"].pop(active)
                st.session_state["active_ship_idx"] = (
                    None if not st.session_state["ships"] else max(0, active - 1))
                st.rerun()

    # -----------------------------------------------------------------------
    # Step 4 - Environment (collapsed by default)
    # -----------------------------------------------------------------------
    with st.expander("Step 4 - Weather (optional)", expanded=False):
        st.caption("Leave at defaults for calm conditions.")
        wind_speed    = st.slider("Wind speed (m/s)",       0.0, 20.0, 0.0, 0.5,
                                  help="0 = calm.")
        wind_dir      = st.slider("Wind coming from (deg)", 0,   360,  0,   5,
                                  help="0 = North, 90 = East.")
        current_speed = st.slider("Current speed (m/s)",    0.0,  2.0, 0.7, 0.1)
        current_dir   = st.slider("Current coming from (deg)", 0, 360, 200,  5)
    # Live wind fetch removed per supervisor's note - use the sliders only.
    use_live_wind = False

    # -----------------------------------------------------------------------
    # Step 5 - Run
    # -----------------------------------------------------------------------
    st.markdown("### Step 5 - Run")

    scenario_name = st.text_input(
        "Scenario name",
        value=f"{region.display_name} - {encounter_labels[encounter_type]}",
    )

    duration_presets = {
        "15 minutes": 900.0,
        "30 minutes": 1800.0,
        "1 hour": 3600.0,
        "2 hours": 7200.0,
        "Custom (seconds)": None,
    }
    duration_choice = st.selectbox(
        "How long should the scenario run for?",
        list(duration_presets.keys()),
        index=2,
    )
    if duration_presets[duration_choice] is None:
        scenario_duration_s = st.number_input(
            "Custom duration (seconds)", 60.0, 36000.0, 3600.0, 60.0,
        )
    else:
        scenario_duration_s = duration_presets[duration_choice]

    scenario = _ui_to_scenario(scenario_name, location_style, encounter_type,
                               scenario_duration_s)

    if st.button("Run simulation", type="primary",
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

            with st.spinner("Running MMG physics simulation"):
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

            with st.spinner("Running encounter analysis"):
                mgr = SimulationManager(
                    result, dt=1.0,
                    max_duration_s=float(scenario_duration_s),
                )
                for _ in mgr.run():
                    pass
                st.session_state["encounter_summary"] = mgr.summary()

            with st.spinner("Simulating passive sensor detections"):
                sensors = default_sensor_layout(region)
                passive_trajs = [
                    trajectory_from_dict(s) for s in result["ships"]
                    if s.get("trajectory")
                ]
                rotation_periods = {
                    s["ship_id"]: float(s.get("radar_rotation_s", 6.0))
                    for s in result["ships"]
                }
                st.session_state["passive_result"] = simulate_passive_detections(
                    passive_trajs, sensors, rotation_periods,
                    noise_sigma_s=0.001,
                )

            st.session_state["trajectory_result"] = result
            st.session_state["radar_result"]      = result
            _clear_sim()
            st.rerun()

    if st.session_state.get("sim_running"):
        if st.button("Stop", use_container_width=True):
            _clear_sim(); st.rerun()

    st.download_button(
        "Save scenario as JSON",
        data=scenario.to_json(),
        file_name=f"{scenario_name.replace(' ','_').replace('-','-')}.json",
        mime="application/json", use_container_width=True,
        disabled=not st.session_state["ships"],
    )

    if st.button("Reset waypoints", use_container_width=True,
                 disabled=not any(s["waypoints"] for s in st.session_state["ships"])):
        for s in st.session_state["ships"]:
            s["waypoints"] = []
        st.session_state["last_clicked"] = None
        st.session_state["trajectory_result"] = None
        st.session_state["radar_result"] = None
        st.session_state["passive_result"] = None
        _clear_sim()
        st.rerun()

    # -----------------------------------------------------------------------
    # Advanced (collapsed by default)
    # -----------------------------------------------------------------------
    with st.expander("Advanced options", expanded=False):
        map_style_folium = st.selectbox(
            "Map style",
            ["OpenStreetMap", "CartoDB positron", "CartoDB dark_matter"],
        )
        show_sensors = st.checkbox(
            "Show passive sensors on map", value=True,
            help="Fixed shore sensors used for the passive radar-timestamp "
                 "task (see docs/radar_research.md). Auto-placed near the "
                 "coastline for the selected region -- not user-placed yet.",
        )
    map_style_plotly = {
        "OpenStreetMap":       "open-street-map",
        "CartoDB positron":    "carto-positron",
        "CartoDB dark_matter": "carto-darkmatter",
    }.get(map_style_folium, "open-street-map")


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

def _build_folium_map(region: Region, tiles: str, show_sensors: bool = True) -> folium.Map:
    # prefer_canvas=True uses canvas rendering instead of SVG - much faster
    # when there are many markers/polygons, which reduces the click blink.
    fmap = folium.Map(location=list(region.center),
                      zoom_start=region.default_zoom, tiles=tiles,
                      prefer_canvas=True)
    if show_sensors:
        for sensor in default_sensor_layout(region):
            folium.CircleMarker(
                location=(sensor.lat, sensor.lon),
                radius=8, color="#000000", weight=2,
                fill=True, fill_color="#ffcc00", fill_opacity=1.0,
                tooltip=f"Passive sensor {sensor.sensor_id}",
                popup=folium.Popup(
                    f"{sensor.sensor_id}<br>{sensor.lat:.5f}, {sensor.lon:.5f}",
                    max_width=200),
            ).add_to(fmap)
            folium.map.Marker(
                location=(sensor.lat, sensor.lon),
                icon=folium.DivIcon(html=f"""<div style="font-size:11px;
                    font-weight:bold;transform:translate(10px,-6px);">
                    {sensor.sensor_id}</div>"""),
            ).add_to(fmap)

    if region.bbox:
        folium.Polygon(locations=region.bbox, color="#d7191c", weight=2,
                       fill=True, fill_color="#fdae61", fill_opacity=0.15,
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
        last_idx = len(wps) - 1
        for j, (lat, lon) in enumerate(wps):
            is_start = (j == 0)
            is_end   = (j == last_idx and last_idx > 0)
            label = (f"{ship['ship_id']} - "
                     + ("start" if is_start
                        else "end" if is_end
                        else f"wp {j+1}"))
            if is_start or is_end:
                # keep the recognisable start/end pins
                icon = folium.Icon(
                    color="green" if is_start else "red",
                    icon="ship" if is_start else "flag-checkered",
                    prefix="fa",
                )
                folium.Marker(
                    location=(lat, lon),
                    popup=folium.Popup(f"{label}<br>{lat:.5f},{lon:.5f}", max_width=220),
                    icon=icon,
                ).add_to(fmap)
            else:
                # intermediate waypoints as lightweight canvas circles
                folium.CircleMarker(
                    location=(lat, lon),
                    radius=5,
                    color=ship["color"], weight=2,
                    fill=True, fill_color=ship["color"], fill_opacity=0.9,
                    tooltip=label,
                ).add_to(fmap)
    return fmap


# ---------------------------------------------------------------------------
# Plotly animation
# ---------------------------------------------------------------------------

def _build_animation(result: dict, region: Region,
                     map_style: str, speed_ms: int,
                     visible_ship_ids: List[str] | None = None,
                     window_start_s: float = 0.0,
                     window_end_s:   float | None = None) -> go.Figure:
    """Animate ships on the shared simulation clock.

    Each ship is hidden before its ``start_time_s`` and held at its last
    point after its trajectory ends, so a ship that enters at t=600s
    actually appears 600s into the animation.

    ``visible_ship_ids`` filters which ships are drawn at all.
    ``window_start_s`` / ``window_end_s`` restrict the timeline played.
    """
    fig   = go.Figure()
    ships = result.get("ships", [])
    if visible_ship_ids is not None:
        ships = [s for s in ships if s["ship_id"] in visible_ship_ids]

    # Line of Sight - dotted light blue
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

    def _ship_shape(lat: float, lon: float, heading_deg: float,
                    length_m: float, beam_m: float
                    ) -> tuple[list[float], list[float]]:
        """Small ship-outline polygon (pointed bow) around the position.

        Drawn at ~3x real size so it reads as a ship without covering the
        map. Returns (lats, lons) of the closed outline.
        """
        import math as _m
        scale = 2.0
        L = max(25.0, length_m * scale) / 2.0     # half-length in metres
        B = max(8.0,  beam_m   * scale) / 2.0     # half-beam in metres
        h = _m.radians(heading_deg)
        # local (forward, starboard): pointed bow, flat stern
        local = [(L, 0.0), (0.4 * L, B), (-L, B),
                 (-L, -B), (0.4 * L, -B), (L, 0.0)]
        lat_rad = _m.radians(lat)
        m_per_deg_lat = 111_000.0
        m_per_deg_lon = 111_000.0 * max(_m.cos(lat_rad), 1e-6)
        lats, lons = [], []
        for x, y in local:
            east_m  = x * _m.sin(h) + y * _m.cos(h)
            north_m = x * _m.cos(h) - y * _m.sin(h)
            lats.append(lat + north_m / m_per_deg_lat)
            lons.append(lon + east_m  / m_per_deg_lon)
        return lats, lons

    def _course_deg(p1: dict, p2: dict) -> float:
        """Compass bearing (0 = North, clockwise) from p1 to p2.

        Used to orient the hull along the actual path instead of the stored
        heading, whose convention differs between physics versions.
        """
        import math as _m
        lat1, lat2 = _m.radians(p1["lat"]), _m.radians(p2["lat"])
        dlon = _m.radians(p2["lon"] - p1["lon"])
        x = _m.sin(dlon) * _m.cos(lat2)
        y = (_m.cos(lat1) * _m.sin(lat2)
             - _m.sin(lat1) * _m.cos(lat2) * _m.cos(dlon))
        return (_m.degrees(_m.atan2(x, y)) + 360.0) % 360.0

    # Only animate ships that actually have a trajectory; keeps the frame
    # trace indexing simple and skips dead weight.
    active = [(s, m) for s, m in zip(ships, ship_meta)
              if s.get("trajectory") and m is not None]

    base_idx = 1 if region.los else 0   # LOS occupies trace 0 when present
    moving_indices: list[int] = []

    for k, (ship, meta) in enumerate(active):
        traj = ship["trajectory"]
        # Ship Path - solid line, faint ghost (static, drawn once)
        fig.add_trace(go.Scattermap(
            lon=[p["lon"] for p in traj], lat=[p["lat"] for p in traj],
            mode="lines", line=dict(width=2, color=ship["color"]),
            name=f"{ship['ship_id']} path", opacity=0.3))
        # Animated trail placeholder - empty until the ship enters
        fig.add_trace(go.Scattermap(
            lon=[], lat=[],
            mode="lines", line=dict(width=3, color=ship["color"]),
            name=f"{ship['ship_id']} trail"))
        # Ship hull - small ship-shaped polygon, empty until entry
        fig.add_trace(go.Scattermap(
            lon=[], lat=[],
            mode="lines", line=dict(width=1, color=ship["color"]),
            fill="toself", fillcolor=ship["color"], opacity=0.9,
            name=f"{ship['ship_id']} hull"))
        # Ship label - text pinned next to the hull
        fig.add_trace(go.Scattermap(
            lon=[], lat=[],
            mode="markers+text",
            marker=dict(size=1, color=ship["color"]),
            text=[ship["ship_id"]], textposition="top right",
            textfont=dict(size=10, color=ship["color"]),
            name=f"{ship['ship_id']} label"))
        # trail, hull, label are the per-frame moving traces (ghost is not)
        moving_indices += [base_idx + 4 * k + 1,
                           base_idx + 4 * k + 2,
                           base_idx + 4 * k + 3]

    # Animation timeline: cover the whole scenario, not just the longest traj.
    scenario_end = max(
        (m["end_s"] for m in ship_meta if m is not None),
        default=0.0,
    )
    timeline_end = max(float(result.get("duration_s", scenario_end)), scenario_end)
    if window_end_s is not None:
        timeline_end = min(timeline_end, float(window_end_s))
    timeline_start = max(0.0, float(window_start_s))

    # Frame step: at least the radar period, but never more than ~150 frames
    # total - keeps the figure light so the page loads fast even for a
    # full-hour scenario.
    radar_s = ships[0].get("radar_rotation_s", 6.0) if ships else 6.0
    span    = max(1.0, timeline_end - timeline_start)
    step    = max(1.0, float(radar_s), span / 150.0)   # seconds per frame
    frames  = []

    t  = timeline_start
    fi = 0
    frame_times: list[float] = []
    while t <= timeline_end + 1e-6:
        # Each frame only carries the moving traces (trail, hull, label per
        # ship); the map tiles, LOS, and path ghosts stay untouched between
        # frames, which removes most of the redraw cost and flicker.
        fd = []

        for ship, meta in active:
            traj = ship["trajectory"]
            local_t = t - meta["start_s"]

            if local_t < 0:
                # Ship has not entered the scene yet - hide it.
                fd.append(go.Scattermap(lon=[], lat=[], mode="lines"))
                fd.append(go.Scattermap(lon=[], lat=[], mode="lines"))
                fd.append(go.Scattermap(lon=[], lat=[], mode="markers"))
                continue

            idx   = min(int(round(local_t)), len(traj) - 1)
            trail = traj[max(0, idx - 40): idx + 1]
            cur   = traj[idx]
            label = f"{ship['ship_id']} t={t:.0f}s {cur['heading']:.0f}°"

            # Animated trail - solid ship color
            fd.append(go.Scattermap(
                lon=[p["lon"] for p in trail], lat=[p["lat"] for p in trail],
                mode="lines", line=dict(width=3, color=ship["color"])))

            # Ship hull - oriented along the actual path direction
            prev_pt = traj[max(0, idx - 1)]
            next_pt = traj[min(len(traj) - 1, idx + 1)]
            course  = (_course_deg(prev_pt, next_pt)
                       if prev_pt is not next_pt else 0.0)
            s_lats, s_lons = _ship_shape(
                cur["lat"], cur["lon"], course,
                float(ship.get("length_m", 100.0)),
                float(ship.get("beam_m", 15.0)))
            fd.append(go.Scattermap(
                lon=s_lons, lat=s_lats,
                mode="lines", line=dict(width=1, color=ship["color"]),
                fill="toself", fillcolor=ship["color"], opacity=0.9))

            # Label next to the hull
            fd.append(go.Scattermap(
                lon=[cur["lon"]], lat=[cur["lat"]],
                mode="markers+text",
                marker=dict(size=1, color=ship["color"]),
                text=[label], textposition="top right",
                textfont=dict(size=9, color=ship["color"])))

        frames.append(go.Frame(data=fd, name=f"f{fi}",
                               traces=moving_indices))
        frame_times.append(t)
        t  += step
        fi += 1

    fig.frames = frames

    # Scrubber: one step per frame, labelled by time in seconds.
    slider_steps = [
        dict(
            method="animate",
            args=[
                [f"f{i}"],
                dict(mode="immediate",
                     frame=dict(duration=0, redraw=True),
                     transition=dict(duration=0)),
            ],
            label=f"{ft:.0f}",
        )
        for i, ft in enumerate(frame_times)
    ]
    scrubber = dict(
        active=0,
        currentvalue=dict(prefix="Time: ", suffix=" s",
                          visible=True, xanchor="left",
                          font=dict(size=12, color="#333")),
        pad=dict(t=40, b=10, l=10, r=10),
        len=0.9, x=0.05, y=-0.02,
        steps=slider_steps,
    )

    # Backward playback: build frame names in reverse.
    reverse_frames = [f"f{i}" for i in range(len(frames) - 1, -1, -1)]

    fig.update_layout(
        height=560,
        map=dict(style=map_style,
                 center=dict(lat=region.center[0], lon=region.center[1]),
                 zoom=region.default_zoom - 1),
        sliders=[scrubber],
        updatemenus=[dict(
            type="buttons", showactive=True, direction="left",
            x=0.1, xanchor="right", y=1.08, yanchor="top",
            bgcolor="rgba(255,255,255,0.15)", bordercolor="#DDD", borderwidth=1,
            pad={"r": 10, "t": 10, "b": 10},
            buttons=[
                dict(label="Play", method="animate",
                     args=[None, {"frame": {"duration": speed_ms, "redraw": True},
                                  "fromcurrent": True, "mode": "immediate"}]),
                dict(label="Play reverse", method="animate",
                     args=[reverse_frames,
                           {"frame": {"duration": speed_ms, "redraw": True},
                            "mode": "immediate",
                            "transition": {"duration": 0}}]),
                dict(label="Pause", method="animate",
                     args=[[None], {"frame": {"duration": 0, "redraw": False},
                                    "mode": "immediate",
                                    "transition": {"duration": 0}}]),
                dict(label="Reset", method="animate",
                     args=[["f0"], {"frame": {"duration": 0, "redraw": True},
                                    "mode": "immediate",
                                    "transition": {"duration": 0}}]),
            ],
        )],
        legend=dict(font=dict(size=11)),
        margin={"r": 0, "t": 60, "l": 0, "b": 40},
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
        title="Radar Returns - Range vs Azimuth",
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
    fmap     = _build_folium_map(region, map_style_folium, show_sensors)
    # Stable key lets Streamlit reuse the map iframe across reruns instead of
    # tearing it down; returned_objects limits payload back to Python.
    map_data = st_folium(
        fmap, width=900, height=500,
        returned_objects=["last_clicked"],
        key="scenario_map",
    )

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
                        st.warning("Click inside the orange boundary - that point is outside the working area.")
                    else:
                        active = st.session_state["active_ship_idx"]
                        st.session_state["ships"][active]["waypoints"].append(
                            (click["lat"], click["lng"]))
                        st.rerun()

    st.caption("Click inside the orange boundary to add waypoints, "
               "or use Auto-Generate in the sidebar.")

with col2:
    st.subheader("Scenario Status")
    if not st.session_state["ships"]:
        st.warning("No ships yet")
        st.info("Use **Auto-Generate** or **Add Ship**.")
    else:
        total_wps = sum(len(s["waypoints"]) for s in st.session_state["ships"])
        st.markdown(
            f"<p class='small-font'><b>{len(st.session_state['ships'])}</b> ship(s), "
            f"<b>{total_wps}</b> waypoint(s)</p>", unsafe_allow_html=True)
        for i, s in enumerate(st.session_state["ships"]):
            badge = "" if i == st.session_state["active_ship_idx"] else ""
            n     = len(s["waypoints"])
            line  = (f"{badge} **{s['ship_id']}** - "
                     + ("no waypoints" if n == 0
                        else "end pending" if n == 1
                        else f"{n} wps"))
            st.markdown(f"<span style='color:{s['color']}'></span> {line}",
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
# Section 2 - Trajectory output
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
            wps = ship.get("waypoints", [])
            if pts:
                st.markdown(
                    f"<span style='color:{ship['color']}'></span> "
                    f"**{ship['ship_id']}** - {len(wps)} waypoints · "
                    f"{len(pts)} traj pts · "
                    f"{len(rrs)} radar returns · {pts[-1]['t']:.1f} s",
                    unsafe_allow_html=True)
    with col_b:
        st.download_button(
            "Download Full JSON",
            data=json.dumps(result, indent=2),
            file_name="multi_ship_simulation.json",
            mime="application/json")
    with st.expander("Preview JSON"):
        st.code(json.dumps(result, indent=2)[:2000] + "\n...", language="json")

    # Working-area boundary check - flag any ship whose trajectory exits
    # the orange polygon (supervisor: "should not go outside the polygon").
    oob = _count_out_of_bounds(result, region)
    total_oob = sum(oob.values())
    if total_oob == 0:
        st.success("All ships stayed inside the working-area boundary.")
    else:
        offenders = [f"**{sid}** ({n} pts)"
                     for sid, n in oob.items() if n > 0]
        st.warning(
            "Some trajectories exit the working-area polygon: "
            + ", ".join(offenders)
        )
    st.markdown("---")


# ---------------------------------------------------------------------------
# Section 3 - Animated visualisation
# ---------------------------------------------------------------------------

if st.session_state.get("trajectory_result"):
    result = st.session_state["trajectory_result"]
    st.subheader("3. Simulation Visualisation")

    all_ship_ids = [s["ship_id"] for s in result.get("ships", [])]
    scenario_end = float(result.get("duration_s", 3600.0))

    fc1, fc2 = st.columns([1, 2])
    with fc1:
        visible_ids = st.multiselect(
            "Show ships", all_ship_ids, default=all_ship_ids,
            help="Hide individual ships to focus on a subset.",
        )
        speed_ms = st.slider("Animation Speed (ms/frame)", 50, 800, 200, 50)
    with fc2:
        window = st.slider(
            "Time window (s)", 0.0, max(scenario_end, 60.0),
            (0.0, max(scenario_end, 60.0)), 10.0,
            help="Restrict the animation timeline to a subrange of the "
                 "scenario clock, e.g. play only the 10-minute slice "
                 "where the interesting traffic happens.",
        )

    fig_anim = _build_animation(
        result, region, map_style_plotly, speed_ms,
        visible_ship_ids=visible_ids,
        window_start_s=window[0],
        window_end_s=window[1],
    )
    st.plotly_chart(fig_anim, use_container_width=True)
    st.caption(
        "Play animates ships on the shared simulation clock. Use the "
        "filters above to focus on specific ships or a time slice."
    )
    st.markdown("---")


# ---------------------------------------------------------------------------
# Section 4 - Radar visualisation
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
                f"<span style='color:{ship['color']}'></span> "
                f"**{ship['ship_id']}**<br>"
                f"&nbsp;&nbsp;Sweeps: {len(rrs)}<br>"
                f"&nbsp;&nbsp;Range: {min(ranges):.0f}-{max(ranges):.0f} m<br>"
                f"&nbsp;&nbsp;Azimuth: {min(azs):.1f}°-{max(azs):.1f}°<br>"
                f"&nbsp;&nbsp;RCS: {rrs[0]['rcs_dbm2']} dBm²",
                unsafe_allow_html=True)
            st.markdown("")
    st.markdown("---")


# ---------------------------------------------------------------------------
# Section 5 - Encounter analysis (multi-ship simulation manager)
# ---------------------------------------------------------------------------

if st.session_state.get("encounter_summary"):
    summary = st.session_state["encounter_summary"]
    st.subheader("5. Encounter Analysis")

    icon = {"head_on": "", "crossing": "",
            "overtaking": "", "following": ""}

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Duration",  f"{summary['duration_s']:.0f} s")
    m2.metric("Ships",     summary["ship_count"])
    m3.metric("Encounters", summary["events_total"])
    by_type = summary["events_by_type"]
    worst   = "head_on" if by_type.get("head_on") else (
              "crossing" if by_type.get("crossing") else (
              "overtaking" if by_type.get("overtaking") else "-"))
    m4.metric("Worst type", f"{icon.get(worst,'')} {worst}")

    if by_type:
        st.markdown("**Breakdown:** " + " · ".join(
            f"{icon.get(k,'')} {k} × {v}" for k, v in by_type.items()))

    windows = summary.get("ship_windows", [])
    if windows:
        st.markdown("**Ship presence on the shared clock**")
        for w in windows:
            st.markdown(
                f"&nbsp;&nbsp;**{w['ship_id']}** - alive "
                f"`t={w['start_time_s']:.0f}s {w['end_time_s']:.0f}s`",
                unsafe_allow_html=True,
            )

    if summary["events"]:
        st.markdown("**Event timeline**")
        for ev in summary["events"][:25]:
            ships = " ".join(ev["ships"])
            st.markdown(
                f"&nbsp;&nbsp;`t={ev['t']:>6.1f}s` "
                f"{icon.get(ev['type'],'')} **{ev['type']}** - "
                f"{ships} · {ev['distance_m']:.0f} m apart "
                f"(Δhdg {ev['hdg_diff']:.0f}°)",
                unsafe_allow_html=True)
        if len(summary["events"]) > 25:
            st.caption(f"and {len(summary['events']) - 25} more events.")
    else:
        st.success("No close-quarters encounters detected.")
    st.markdown("---")


# ---------------------------------------------------------------------------
# Section 6 - Passive sensor detections (SeaSentry-style timestamps)
# ---------------------------------------------------------------------------

if st.session_state.get("passive_result"):
    passive = st.session_state["passive_result"]
    st.subheader("6. Passive Sensor Detections")
    st.caption(
        "Simulated timestamps of when each ship's radar beam sweeps past "
        "each fixed shore sensor. No angle is "
        "recorded, only timing - same as a real passive sensor."
    )

    n_sensors = len(passive["sensors"])
    n_dets    = len(passive["detections"])
    ships_seen = sorted({d["ship_id"] for d in passive["detections"]})

    m1, m2, m3 = st.columns(3)
    m1.metric("Sensors", n_sensors)
    m2.metric("Detections", n_dets)
    m3.metric("Ships detected", len(ships_seen))

    with st.expander("Sensor positions", expanded=False):
        st.dataframe(passive["sensors"], use_container_width=True)

    with st.expander("Detections per ship / sensor", expanded=False):
        from collections import Counter
        counts = Counter((d["ship_id"], d["sensor_id"]) for d in passive["detections"])
        st.dataframe(
            [{"ship_id": sid, "sensor_id": sen, "detections": n}
             for (sid, sen), n in sorted(counts.items())],
            use_container_width=True,
        )

    with st.expander("Preview detections (first 50)", expanded=False):
        st.dataframe(passive["detections"][:50], use_container_width=True)

    col_dl1, col_dl2 = st.columns(2)
    with col_dl1:
        st.download_button(
            "Download detections as JSON",
            data=json.dumps(passive, indent=2),
            file_name="passive_detections.json",
            mime="application/json", use_container_width=True,
        )
    with col_dl2:
        import io
        import csv as _csv
        buf = io.StringIO()
        writer = _csv.DictWriter(
            buf, fieldnames=["ship_id", "sensor_id", "sweep", "true_t", "measured_t"])
        writer.writeheader()
        writer.writerows(passive["detections"])
        st.download_button(
            "Download detections as CSV",
            data=buf.getvalue(),
            file_name="passive_detections.csv",
            mime="text/csv", use_container_width=True,
        )
    st.markdown("---")


# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

st.caption("Multi-ship trajectory simulation - MMG physics model.")