# Multi-Ship Maritime Scenario Simulation

A browser-based simulator for ship traffic in two German waterways, the Rheinhafen
river port in Karlsruhe and the Cuxhaven estuary at the mouth of the Elbe. You build
a scenario by placing ships and waypoints on a map, give each ship its own entry time,
and the tool runs physics-based trajectories for all of them on one shared clock. The
result is an animated replay, a list of which ships met and how, and the exact times at
which each ship's rotating radar beam sweeps past sensors on the shore.

Lab project of the Autonomous Multisensor Systems group, Institute for Intelligent
Cooperating Systems, Otto von Guericke University Magdeburg, summer semester 2026.

[[_TOC_]]

## Motivation

Radar and traffic monitoring systems have to be tested against situations where several
ships share the same water at the same time. Real recordings rarely contain the exact
situation you need, such as two ships meeting head-on in a narrow channel, and you
cannot replay a recording with a slightly later ship or a bigger vessel.

A previous lab project built and validated a physics model for a single ship in these
two regions. This project takes that model as its engine and builds the multi-ship layer
on top of it: scenario building, time synchronisation, encounter analysis, playback and
simulated shore-sensor measurements.

## Features

**Building scenarios**

- Pick a region and add as many ships as you like
- Place waypoints by clicking on the map; ships steer through all of them in order
- Set size, speed, heading, radar rotation period and entry time per ship
- Load ready-made examples: crossing, head-on, overtaking, harbour traffic
- Save a scenario as JSON and import it again later

**Running and analysing**

- Realistic ship motion from the previous project's MMG physics model
- All ships on one shared clock, each entering at its own time
- Automatic encounter detection: head-on, crossing, overtaking, following
- Boundary check that warns when a ship leaves the working area

**Seeing the result**

- Animated map with ship shapes that point in their direction of travel
- Timeline slider to jump to any moment, plus Play, Pause and Reset
- Filters for individual ships and for time windows

**Passive radar sensing**

- Four fixed shore sensors per region
- Exact times at which each ship's radar beam sweeps past each sensor
- Realistic timing noise, with export to JSON and CSV

## Prerequisites

| What | Requirement |
|------|-------------|
| Operating system | Windows, macOS or Linux. Developed on Windows 11, also run on Linux. |
| Python | 3.12 (developed and tested on 3.12.8) |
| Git | Any recent version, for cloning the repository |
| Browser | Any current browser. The interface opens as a local web page. |
| Hardware | A normal laptop. No GPU and no special hardware needed. |
| Internet | Only for installing the packages and for loading the background map tiles. All calculations run offline. |

No system configuration has to be changed. Everything is installed inside a virtual
environment, so nothing is added to your global Python.

## Installation

**1. Clone the repository**

```bash
git clone https://code.ovgu.de/iks-ams/teaching/student-projects/sose26/p-9-maritime-scenario-simulation.git
cd p-9-maritime-scenario-simulation
```

**2. Create a virtual environment and install the dependencies**

Windows (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

macOS and Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**3. Start the application**

```bash
streamlit run app.py
```

Your browser opens at <http://localhost:8501>. If it does not open by itself, type that
address in manually.

If PowerShell refuses to run `Activate.ps1`, allow scripts for the current session with
`Set-ExecutionPolicy -Scope Process RemoteSigned` and try again.

## Usage

The sidebar walks you through five steps.

| Step | What you do |
|------|-------------|
| 1. Where | Choose Rheinhafen or Cuxhaven. |
| 2. Scenario | Pick a scenario type. *Custom* starts empty, the others load a ready-made example. A saved scenario file can also be imported here. |
| 3. Ships | Add ships, choose which one you are placing waypoints for, then click on the map. Open *Edit* to change size, speed, entry time or radar rotation. |
| 4. Weather | Optional. Set wind and current with the sliders. Calm conditions are used by default. |
| 5. Run | Choose the scenario length and press **Run simulation**. |

A ship needs at least two waypoints. For a route that follows a bend in the river, add
a waypoint at each bend, because with only two points a ship sails in a straight line.

After a run the main page shows six sections.

| Section | Content |
|---------|---------|
| 1. Select Points on Map | The map used for placing waypoints |
| 2. Trajectory Output | Summary per ship, boundary check, full result download |
| 3. Simulation Visualisation | Animated playback with timeline, filters and colour key |
| 4. Radar Simulation | Range and bearing of each ship from the region centre |
| 5. Encounter Analysis | Number and type of encounters, ship time windows, event timeline |
| 6. Passive Sensor Detections | Beam detection times per ship and sensor, with JSON and CSV download |

Two ready-made demonstration scenarios for Rheinhafen are in `scenarios/`. Import them
through step 2 to see the tool with realistic traffic.

## Scenario files

A scenario is a plain JSON file. **Save scenario as JSON** in the sidebar writes one and
**Import scenario** reads it back, restoring the region, the duration and every ship. The
import also accepts the larger file from *Download Full JSON*, which additionally holds
the computed trajectories.

```json
{
  "name": "Rheinhafen - Demo",
  "region": "rheinhafen",
  "encounter_type": "custom",
  "duration_s": 1800.0,
  "ships": [
    {
      "ship_id": "Barge_North",
      "mmsi": 211574354,
      "length_m": 110.0,
      "beam_m": 11.4,
      "draught_m": 2.8,
      "initial_speed_mps": 3.0,
      "initial_heading_deg": 50.4,
      "radar_rotation_s": 2.5,
      "color": "#1f77b4",
      "start_time_s": 0.0,
      "waypoints": [
        {"lat": 48.9830055, "lon": 8.2649655},
        {"lat": 49.0282495, "lon": 8.3011810}
      ]
    }
  ]
}
```

The example is shortened to one ship with its first and last waypoint. A real file lists
every ship with all of its waypoints.

| Field | Unit | Meaning |
|-------|------|---------|
| `region` | | `rheinhafen` or `cuxhaven` |
| `duration_s` | s | Length of the scenario on the shared clock |
| `mmsi` | | Nine-digit radio identity, 211 is the German country code |
| `length_m`, `beam_m`, `draught_m` | m | Ship length, width and depth below the waterline |
| `initial_speed_mps` | m/s | Requested speed, 5 m/s is about 10 knots |
| `initial_heading_deg` | ° | 0 is north, 90 is east |
| `radar_rotation_s` | s | Time for one full turn of the radar antenna |
| `start_time_s` | s | When the ship enters the scenario |
| `waypoints` | ° | Points the ship steers towards, in order |

## How it works

```
 User interface ──► MMG physics ──► Simulation manager ──┬──► Encounter analysis ──┐
 (ships, waypoints)  (one path per    (shared clock,     │                          ├──► Results view
                      ship)            entry times)      └──► Passive sensors ──────┘
```

**Physics.** Each ship's path is computed on its own by the MMG model from the previous
project: propeller, rudder, hull resistance, wind and current, solved in one-second
steps, with a rudder controller that steers towards the next waypoint. The model knows
nothing about other ships.

**Shared clock.** The simulation manager gives every ship an entry time and places its
path on one common timeline. A ship exists only between its entry time and the end of
its route. Two ships can therefore meet only while both are on the water. Routes that
cross on the map are not an encounter unless the ships are there at the same time.

**Encounters.** At every second, each pair of active ships closer than 500 m is
classified by the difference between their headings.

| Type | Heading difference |
|------|--------------------|
| Head-on | more than 150° |
| Crossing | 30° to 150° |
| Overtaking | up to 30°, first ship faster |
| Following | up to 30°, first ship not faster |

An event is recorded only when a pair enters a new situation, so one long meeting is not
reported once per second.

**Passive sensors.** Each ship's radar beam points north at the start of every rotation
and sweeps round once per `radar_rotation_s`. A shore sensor receives one pulse per
rotation, at the moment the beam points at it. Because that moment depends on where the
ship is by then, it is found with a short fixed-point iteration. A random timing error
with a standard deviation of 1 ms is added to mimic real hardware.

## Reproducibility

**Environment.** All dependencies in `requirements.txt` are pinned to the exact versions
the project was developed and tested with, on Python 3.12.8. The same Python version in
a fresh virtual environment gives the same setup as the final demonstration.

**What is deterministic.** For the same scenario file and weather settings, the physics,
the trajectories, the encounter analysis and the exact sensor detection times (`true_t`)
are identical on every run. Two things are random:

- the MMSI of a newly added ship, though a saved scenario keeps its MMSI, and
- the simulated timing noise in `measured_t`, which changes from run to run in the app
  and is fixed with `seed=42` in the self-test below.

No calculation depends on an online service. Live wind from OpenWeatherMap exists in the
code but is switched off, so results do not depend on the weather at the time of running.
An internet connection is needed only for the background map tiles.

**Self-tests.** Each core module can be run on its own as a quick check. Run these from
the project folder with the virtual environment active.

```bash
python -m core.simulation_manager   # same routes, different start times
python -m core.passive_radar        # sensor detection times with fixed seed
python -m core.sensors              # sensor positions for both regions
python -m core.trajectory           # simple trajectory output
python -m core.radar                # onboard radar detections
python visualize_sensors.py         # writes <region>_sensors_map.html
```

`core.simulation_manager` should report one crossing when both ships start at 0 s and no
encounters when the second ship starts one hour later. That is the central behaviour of
the shared clock. `core.sensors` should list every sensor as *on land (ok)*. Files
written by these checks are ignored by Git.

**Reference timings.** On a normal laptop a one-hour scenario with two ships runs in
about 2.6 s: physics 1.9 s, encounter analysis 0.2 s, sensor detection 0.4 s, onboard
radar under 0.1 s. Most of the waiting you notice in the browser comes from drawing the
animated map, not from the calculations.

## Project structure

```
p-9-maritime-scenario-simulation/
├── app.py                      Streamlit application (interface and results)
├── core/
│   ├── scenario.py             Ship, waypoint and scenario data model, JSON export
│   ├── regions.py              Loads region geometry, builds the river corridor
│   ├── scenario_builder.py     Ready-made example scenarios
│   ├── simulation_manager.py   Shared clock and encounter detection
│   ├── trajectory.py           Trajectory data types and interpolation
│   ├── radar.py                Onboard radar returns
│   ├── sensors.py              Shore sensor placement
│   ├── passive_radar.py        Beam detection times at the shore sensors
│   └── physics/
│       ├── mmg_model.py        Ship dynamics (MMG model)
│       ├── guidance.py         Heading and cross-track steering
│       ├── pipeline.py         Runs the physics for every ship in a scenario
│       └── coordinate_utils.py Distances, bearings and coordinate helpers
├── data/                       Fairway centrelines and working areas per region
├── scenarios/                  Demonstration scenarios for Rheinhafen
├── documentation/              Project report
├── presentation/               Presentation slides
├── visualize_sensors.py        Standalone map of the sensor positions
├── requirements.txt            Pinned dependencies
└── README.md
```

## ToDo and future work

Things that are known to be missing or imperfect, and where someone continuing this
project could start.

- **Ships do not react to each other.** Encounters are detected, but no ship changes
  course to avoid another. Adding a simple avoidance rule is the natural next step.
- **Straight lines with two waypoints.** The fairway-following route for a plain start
  and end point is looked up in a folder that is not part of this repository, so the code
  falls back to a straight line. Add waypoints at the bends, or restore that lookup data.
- **Sharp turns.** The physics model struggles with very tight turns, for example the
  entrances of two of the Rheinhafen port basins, where a ship can overshoot the turn.
- **Simplified encounter rules.** Fixed distance and angle thresholds are used rather
  than the full collision regulations (COLREGs).
- **Ideal sensors.** The sensor model ignores signal strength, terrain blocking and
  reflections, so every sweep is detected regardless of range.
- **Map smoothness.** Streamlit reloads the page on every click, so the map blinks
  briefly when a waypoint is placed and the animation flickers a little during playback.
  A higher *Animation Speed* value makes playback calmer. Removing this properly would
  mean replacing the map component.

## Resources

- [Streamlit](https://streamlit.io/) for the interface, [Folium](https://python-visualization.github.io/folium/) and [Plotly](https://plotly.com/python/) for the maps
- [Shapely](https://shapely.readthedocs.io/) for the geometry and [GeoPy](https://geopy.readthedocs.io/) for distances on the globe
- Map data © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors
- MMG standard method for ship manoeuvring, Yasukawa and Yoshimura, *Journal of Marine Science and Technology*, 2015
- Line-of-sight path following, Fossen, *Handbook of Marine Craft Hydrodynamics and Motion Control*, 2011
- MMSI country codes: [ITU Maritime Identification Digits](https://www.itu.int/en/ITU-R/terrestrial/fmd/Pages/mid.aspx)

## Documentation

- The project report is in `documentation/`.
- The presentation slides are in `presentation/`.
- This README explains setup and usage. The scenario file fields are listed under
  [Scenario files](#scenario-files) and the model behind the results under
  [How it works](#how-it-works).

## License

Released under the MIT License.

## Authors

| Member | Contribution | Contact |
|--------|--------------|---------|
| Mohammed Amaan Shaikh | User interface, simulation manager and shared clock, encounter detection, playback, scenario import and export | mohammed.shaikh@st.ovgu.de |
| Vivek Mohan Babu | Radar model, shore sensor placement, passive detection timing, fine time-step support | vivek.mohan@st.ovgu.de |

The ship physics, the fairway centrelines and the working-area polygons come from the
previous AMS lab project : *Simulation and Prediction of Ship Trajectories*

Supervised by the Autonomous Multisensor Systems group, Institute for Intelligent
Cooperating Systems, Otto von Guericke University Magdeburg.
