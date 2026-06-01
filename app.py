"""Maritime Scenario Builder — Streamlit front-end.

UI only. Collects multi-ship scenario inputs (region, ships, waypoints) for the
AMS P5 simulator. No physics runs here — the supervisor will guide the
integration of the existing MMG model in a later milestone.

Modelled on the previous student team's `streamlit_app.py`: sidebar controls,
two-column main area with a Folium map on the left and selection status on the
right. Extended to support multiple ships in one scenario, with click-to-add
waypoints per ship.
"""

from __future__ import annotations

import json
import random
from typing import List

import folium
import streamlit as st
from shapely.geometry import Point, Polygon
from streamlit_folium import st_folium

from core.regions import Region, available_regions, load_region
from core.scenario import ENCOUNTER_TYPES, Scenario, Ship, Waypoint, next_color


# ---------------------------------------------------------------------------
# Page setup
# ---------------------------------------------------------------------------

st.set_page_config(
    layout="wide",
    page_title="Ship Trajectory Simulation — Scenario Builder",
)


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

def _init_state() -> None:
    st.session_state.setdefault("ships", [])              # list[dict]
    st.session_state.setdefault("active_ship_idx", None)  # int | None
    st.session_state.setdefault("last_clicked", None)


_init_state()


def _new_ship_dict(index: int) -> dict:
    return {
        "ship_id": f"Ship_{index + 1}",
        "mmsi": 211_000_000 + random.randint(1, 999_999),
        "length_m": 100.0,
        "beam_m": 15.0,
        "draught_m": 5.0,
        "initial_speed_mps": 5.0,
        "initial_heading_deg": 0.0,
        "waypoints": [],   # list[(lat, lon)]
        "radar_rotation_s": 4.0,
        "color": next_color(index),
    }


def _ui_to_scenario(name: str, region_key: str, encounter_type: str) -> Scenario:
    ships: List[Ship] = []
    for s in st.session_state["ships"]:
        ships.append(Ship(
            ship_id=s["ship_id"],
            mmsi=int(s["mmsi"]),
            length_m=float(s["length_m"]),
            beam_m=float(s["beam_m"]),
            draught_m=float(s["draught_m"]),
            initial_speed_mps=float(s["initial_speed_mps"]),
            initial_heading_deg=float(s["initial_heading_deg"]),
            waypoints=[Waypoint(lat=lat, lon=lon) for (lat, lon) in s["waypoints"]],
            radar_rotation_s=float(s["radar_rotation_s"]),
            color=s["color"],
        ))
    return Scenario(
        name=name, region=region_key, encounter_type=encounter_type, ships=ships,
    )


def _region_polygon(region: Region) -> Polygon | None:
    """Return a shapely Polygon for in-bounds checks on map clicks."""
    if not region.bbox:
        return None
    # bbox is (lat, lon); shapely expects (x=lon, y=lat).
    return Polygon([(lon, lat) for (lat, lon) in region.bbox])


# ---------------------------------------------------------------------------
# Sidebar — simulation controls (mirrors previous group's layout)
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("Simulation Controls")

    region_options = available_regions()
    region_keys = [k for k, _ in region_options]
    region_labels = {k: name for k, name in region_options}

    location_style = st.selectbox(
        "Choose Location",
        region_keys,
        format_func=lambda k: region_labels[k],
    )
    region = load_region(location_style)

    if st.button("Reset Points"):
        for s in st.session_state["ships"]:
            s["waypoints"] = []
        st.session_state["last_clicked"] = None
        st.rerun()

    st.markdown("---")
    st.subheader("Ships")

    col_add, col_rm = st.columns(2)
    if col_add.button(" Add Ship", use_container_width=True):
        st.session_state["ships"].append(
            _new_ship_dict(len(st.session_state["ships"]))
        )
        st.session_state["active_ship_idx"] = len(st.session_state["ships"]) - 1

    if col_rm.button("🗑 Clear All", use_container_width=True):
        st.session_state["ships"] = []
        st.session_state["active_ship_idx"] = None
        st.rerun()

    if not st.session_state["ships"]:
        st.info("Click **Add Ship** to begin.")
    else:
        ship_labels = [s["ship_id"] for s in st.session_state["ships"]]
        active = st.selectbox(
            "Active ship (clicks on the map add a waypoint here)",
            list(range(len(ship_labels))),
            index=st.session_state["active_ship_idx"] or 0,
            format_func=lambda i: ship_labels[i],
        )
        st.session_state["active_ship_idx"] = active

        # Editable details for the active ship
        s = st.session_state["ships"][active]
        with st.expander(f"⚙ {s['ship_id']} parameters", expanded=False):
            s["ship_id"] = st.text_input("Ship ID", value=s["ship_id"], key=f"id_{active}")
            s["mmsi"] = st.number_input(
                "MMSI", min_value=100_000_000, max_value=999_999_999,
                value=int(s["mmsi"]), step=1, key=f"mmsi_{active}",
            )
            c1, c2, c3 = st.columns(3)
            s["length_m"] = c1.number_input(
                "Length (m)", 5.0, 400.0, float(s["length_m"]), 1.0, key=f"len_{active}",
            )
            s["beam_m"] = c2.number_input(
                "Beam (m)", 2.0, 60.0, float(s["beam_m"]), 0.5, key=f"beam_{active}",
            )
            s["draught_m"] = c3.number_input(
                "Draught (m)", 0.5, 25.0, float(s["draught_m"]), 0.1, key=f"dr_{active}",
            )
            c4, c5 = st.columns(2)
            s["initial_speed_mps"] = c4.number_input(
                "Speed (m/s)", 0.0, 30.0, float(s["initial_speed_mps"]), 0.1,
                key=f"sp_{active}",
            )
            s["initial_heading_deg"] = c5.number_input(
                "Heading (°)", 0.0, 360.0, float(s["initial_heading_deg"]), 1.0,
                key=f"hd_{active}",
            )
            s["radar_rotation_s"] = st.number_input(
                "Radar period (s)", 0.0, 120.0, float(s["radar_rotation_s"]), 0.5,
                key=f"rad_{active}",
                help="0 disables radar. Otherwise: seconds per full antenna rotation.",
            )
            s["color"] = st.color_picker("Map color", s["color"], key=f"col_{active}")

            c_undo, c_clear, c_remove = st.columns(3)
            if c_undo.button("↶ Undo wp", key=f"undo_{active}",
                             disabled=not s["waypoints"], use_container_width=True):
                s["waypoints"].pop()
                st.rerun()
            if c_clear.button("Clear wps", key=f"clr_{active}",
                              disabled=not s["waypoints"], use_container_width=True):
                s["waypoints"] = []
                st.rerun()
            if c_remove.button("Remove ship", key=f"rmship_{active}",
                               use_container_width=True):
                st.session_state["ships"].pop(active)
                st.session_state["active_ship_idx"] = (
                    None if not st.session_state["ships"]
                    else max(0, active - 1)
                )
                st.rerun()

    st.markdown("---")
    map_style = st.selectbox(
        "Map Style",
        ["OpenStreetMap", "CartoDB positron", "CartoDB dark_matter"],
    )

    st.markdown("---")
    st.subheader("Scenario")
    encounter_keys = [k for k, _, _ in ENCOUNTER_TYPES]
    encounter_labels = {k: lbl for k, lbl, _ in ENCOUNTER_TYPES}
    encounter_help = {k: hlp for k, _, hlp in ENCOUNTER_TYPES}
    encounter_type = st.selectbox(
        "Encounter type",
        encounter_keys,
        format_func=lambda k: encounter_labels[k],
        help=(
            "Tags the scenario with one of the supervisor's named encounters. "
            "Used by the backend later to drive the multi-ship scenario manager."
        ),
    )
    st.caption(encounter_help[encounter_type])

    scenario_name = st.text_input(
        "Scenario name",
        value=f"{region.display_name} — {encounter_labels[encounter_type]}",
    )
    scenario = _ui_to_scenario(scenario_name, location_style, encounter_type)
    st.download_button(
        "⬇ Save Scenario (JSON)",
        data=scenario.to_json(),
        file_name=f"{scenario_name.replace(' ', '_').replace('—', '-')}.json",
        mime="application/json",
        use_container_width=True,
        disabled=not st.session_state["ships"],
    )


# ---------------------------------------------------------------------------
# Main page styling (mirrors previous group)
# ---------------------------------------------------------------------------

st.markdown("""
    <style>
    .stSubheader { color: #2c3e50; border-bottom: 2px solid #f0f2f6;
                   padding-bottom: 0.5rem; margin-bottom: 1rem; }
    .small-font { font-size: 16px !important; }
    .stButton>button { border-radius: 10px; }
    </style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Map builder
# ---------------------------------------------------------------------------

def _build_map(region: Region, tiles: str) -> folium.Map:
    fmap = folium.Map(
        location=list(region.center),
        zoom_start=region.default_zoom,
        tiles=tiles,
    )

    # Study-area polygon (filled).
    if region.bbox:
        folium.Polygon(
            locations=region.bbox,
            color="#d7191c",
            weight=2,
            fill=True,
            fill_color="#fdae61",
            fill_opacity=0.25,
            tooltip="Working Area Boundary",
        ).add_to(fmap)

    # Line of sight (fairway centerline) for reference.
    if region.los:
        folium.PolyLine(
            locations=region.los,
            color="#ff8800",
            weight=2,
            dash_array="6,8",
            opacity=0.8,
            tooltip="Line of sight (fairway centerline)",
        ).add_to(fmap)

    # Per-ship waypoint markers + connecting polyline.
    for ship in st.session_state["ships"]:
        wps = ship["waypoints"]
        if not wps:
            continue
        if len(wps) >= 2:
            folium.PolyLine(
                locations=wps,
                color=ship["color"],
                weight=3,
                opacity=0.8,
                tooltip=f"{ship['ship_id']} route",
            ).add_to(fmap)
        for j, (lat, lon) in enumerate(wps):
            if j == 0:
                icon = folium.Icon(color="green", icon="ship", prefix="fa")
                label = f"{ship['ship_id']} — start"
            elif j == len(wps) - 1 and len(wps) > 1:
                icon = folium.Icon(color="red", icon="flag-checkered", prefix="fa")
                label = f"{ship['ship_id']} — end"
            else:
                icon = folium.Icon(color="blue", icon="circle", prefix="fa")
                label = f"{ship['ship_id']} — wp {j + 1}"
            folium.Marker(
                location=(lat, lon),
                popup=folium.Popup(f"{label}<br>{lat:.5f}, {lon:.5f}", max_width=220),
                icon=icon,
            ).add_to(fmap)

    return fmap


# ---------------------------------------------------------------------------
# Main two-column layout
# ---------------------------------------------------------------------------

col1, col2 = st.columns([4, 1])

with col1:
    st.subheader("1. Select Points on Map")

    fmap = _build_map(region, map_style)
    map_data = st_folium(
        fmap,
        width=900,
        height=560,
        returned_objects=["last_clicked"],
    )

    # Click handling: add a waypoint to the active ship if inside the polygon.
    if map_data and map_data.get("last_clicked"):
        click = map_data["last_clicked"]
        click_key = (round(click["lat"], 7), round(click["lng"], 7))

        if click_key != st.session_state.get("last_clicked"):
            st.session_state["last_clicked"] = click_key

            if st.session_state["active_ship_idx"] is None:
                st.warning("Add a ship first (sidebar → ➕ Add Ship).")
            else:
                poly = _region_polygon(region)
                inside = poly is None or poly.contains(Point(click["lng"], click["lat"]))
                if not inside:
                    st.warning("Please click inside the working area boundary.")
                else:
                    active = st.session_state["active_ship_idx"]
                    st.session_state["ships"][active]["waypoints"].append(
                        (click["lat"], click["lng"])
                    )
                    st.rerun()

    st.caption(
        "Click inside the orange boundary to add a waypoint to the active ship. "
        "First click = start, last click = end. Use the sidebar to switch which "
        "ship receives clicks, undo the last waypoint, or remove a ship."
    )

with col2:
    st.subheader("Scenario Status")

    if not st.session_state["ships"]:
        st.warning(" No ships yet")
        st.info("Use ** Add Ship** in the sidebar to begin.")
    else:
        total_wps = sum(len(s["waypoints"]) for s in st.session_state["ships"])
        st.markdown(
            f"<p class='small-font'><b>{len(st.session_state['ships'])}</b> ship(s), "
            f"<b>{total_wps}</b> waypoint(s) total</p>",
            unsafe_allow_html=True,
        )
        for i, s in enumerate(st.session_state["ships"]):
            is_active = i == st.session_state["active_ship_idx"]
            badge = "🟢" if is_active else "⚪"
            n = len(s["waypoints"])
            if n == 0:
                line = f"{badge} **{s['ship_id']}** — no waypoints"
            elif n == 1:
                line = f"{badge} **{s['ship_id']}** — start set, end pending"
            else:
                line = f"{badge} **{s['ship_id']}** — {n} waypoints"
            st.markdown(
                f"<span style='color:{s['color']}'>●</span> {line}",
                unsafe_allow_html=True,
            )

            if s["waypoints"]:
                first = s["waypoints"][0]
                last = s["waypoints"][-1]
                st.markdown(
                    f"<p class='small-font'>&nbsp;&nbsp;Start: {first[0]:.4f}, {first[1]:.4f}</p>",
                    unsafe_allow_html=True,
                )
                if len(s["waypoints"]) > 1:
                    st.markdown(
                        f"<p class='small-font'>&nbsp;&nbsp;End: {last[0]:.4f}, {last[1]:.4f}</p>",
                        unsafe_allow_html=True,
                    )

        st.progress(min(1.0, total_wps / max(2 * len(st.session_state["ships"]), 1)))

    with st.expander("Preview scenario JSON"):
        st.code(scenario.to_json(), language="json")


# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

st.markdown("---")
st.caption(
    "Scenario builder only — no physics runs here. The MMG model from the "
    "previous project will be wired in as the backend in a later milestone."
)
