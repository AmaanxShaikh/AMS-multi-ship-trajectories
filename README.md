# Maritime Scenario Builder

Front-end (UI only) for the **AMS P5** multi-ship + radar trajectory simulator
(University of Magdeburg, AMS group, SoSe 2025/26).

Per the supervisor's kickoff: **build the front-end first**. Physics integration
comes later, guided in the lab.

This app collects scenario inputs from the user — region, ships, waypoints,
ship parameters — and exports them as a scenario JSON. No simulation runs
here. The look and structure mirror the previous student team's
`streamlit_app.py` (sidebar controls + two-column main area with a Folium map),
extended to support multiple ships per scenario.

## What it does

- Pick a region (Rheinhafen or Cuxhaven). The Folium map shows the study-area
  polygon (orange) and the line-of-sight centerline (dashed orange) so the
  user knows where ships can travel.
- Add as many ships as needed via the sidebar.
- For each ship, set:
  - ID, MMSI, length / beam / draught
  - Initial speed (m/s) and heading (°)
  - Optional radar rotation period (s)
  - A colour for the map
- The **active ship** receives waypoints whenever the user clicks inside the
  boundary. First click = start, last click = end. Switch active ship in the
  sidebar to add waypoints for a different one.
- Sidebar shows live status: number of ships, waypoints per ship, start/end
  coordinates.
- **Save Scenario** downloads the configuration as JSON.

## What it does NOT do (by design)

- No physics, no trajectories, no simulation output. That's a later milestone.
- No collision logic — the supervisor confirmed incoming/outgoing lanes are
  already separated in the existing polygon data, so collisions don't need
  handling.

## How to run

```powershell
cd C:\Users\shaik\OneDrive\Desktop\maritime-scenario-builder
.\.venv\Scripts\Activate.ps1
streamlit run app.py
```

The app opens at http://localhost:8501.

## Project layout

```
maritime-scenario-builder/
├── app.py                  Streamlit UI
├── core/
│   ├── scenario.py         Ship / Waypoint / Scenario dataclasses + JSON export
│   └── regions.py          Loads LOS + bounding-box JSON per region
├── data/                   Region geometry copied from the previous team
│   ├── rheinhafen_los.json
│   ├── rheinhafen_bbox.json
│   ├── cuxhaven_los.json
│   └── cuxhaven_bbox.json
├── requirements.txt
└── README.md
```

## Scenario JSON shape (output)

```jsonc
{
  "name": "Rheinhafen scenario",
  "region": "rheinhafen",
  "encounter_type": "head_on",
  "ships": [
    {
      "ship_id": "Ship_1",
      "mmsi": 211000123,
      "length_m": 100.0,
      "beam_m": 15.0,
      "draught_m": 5.0,
      "initial_speed_mps": 5.0,
      "initial_heading_deg": 0.0,
      "waypoints": [
        {"lat": 48.96635, "lon": 8.23388},
        {"lat": 48.96766, "lon": 8.23674}
      ],
      "radar_rotation_s": 4.0,
      "color": "#1f77b4"
    }
  ]
}
```

The physics backend (a later milestone) will consume this JSON and produce the
per-ship trajectories.

## Roadmap

| Phase | Deliverable |
|-------|-------------|
| 1 | UI MVP (this) — collect multi-ship scenario inputs |
| 2 | Wire in the previous team's MMG model as the backend |
| 3 | Add a Plotly animated trajectory view (à la previous team) |
| 4 | Radar rotation simulation per ship |
| 5 | Evaluation panel (cross-track error vs. AIS) |

## References

- Previous team's report: `../AMS/AMS__Simulation_and_Prediction_of_Ship_Trajectories.pdf`
- Previous team's UI: `../AMS/streamlit_app.py` and `../AMS/StreamLit UI Ship Simulation/simulation_v2.py`
- AIS datasets: `../AMS/AMS Data.zip` (Rheinhafen + Cuxhaven CSV/zip dumps, plus prior simulation outputs)
