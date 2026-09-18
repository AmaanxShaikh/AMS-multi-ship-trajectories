# Multi-Ship Trajectory Simulation

A browser-based simulator for multi-ship traffic in two German waterways: the
**Rheinhafen** river port in Karlsruhe and the **Cuxhaven** estuary at the
mouth of the Elbe. Users set up scenarios with any number of ships, run
physics-based trajectories for all of them on a shared clock, replay the
traffic on a map, see which ships meet and how, and compute when each ship's
radar beam would be picked up by sensors on the shore.

Lab project of the **Autonomous Multisensor Systems (AMS)** group, Institute
for Intelligent Cooperating Systems, Otto von Guericke University Magdeburg,
summer semester 2026.

---

## Contents

- [Why this project](#why-this-project)
- [Features](#features)
- [Quick start](#quick-start)
- [Using the app](#using-the-app)
- [Scenario files](#scenario-files)
- [How it works](#how-it-works)
- [Reproducibility](#reproducibility)
- [Project structure](#project-structure)
- [Known limitations](#known-limitations)
- [Team and credits](#team-and-credits)

---

## Why this project

Radar and traffic monitoring systems need to be tested against traffic where
several ships share the same water at the same time. Real recordings rarely
contain the exact situation you need, such as two ships meeting head-on in a
narrow channel, and you cannot replay them with a slightly later ship or a
bigger vessel.

A previous lab project built and validated a physics model for **one** ship in
these two regions. This project takes that model as its engine and builds the
multi-ship layer on top of it: scenario building, time synchronisation,
encounter analysis, playback, and simulated shore-sensor measurements.

---

## Features

**Building scenarios**
- Pick a region and add as many ships as you like
- Place waypoints by clicking on the map; ships steer through all of them in order
- Set size, speed, heading, radar rotation period and **entry time** for each ship
- Load ready-made examples (crossing, head-on, overtaking, harbour traffic)
- Save a scenario as JSON and import it again later

**Running and analysing**
- Realistic ship motion from the previous project's MMG physics model
- All ships on **one shared clock**, each entering at its own time
- Automatic **encounter detection**: head-on, crossing, overtaking, following
- Boundary check that warns when a ship leaves the working area

**Seeing the result**
- Animated map with ship shapes that point in their direction of travel
- Timeline slider to jump to any moment, plus Play, Pause and Reset
- Filters for individual ships and time windows

**Passive radar sensing**
- Four fixed shore sensors per region
- Exact times at which each ship's rotating radar beam sweeps past each sensor
- Realistic timing noise, with export to JSON and CSV

---

## Quick start

You need **Python 3.12** and Git. The steps below take a few minutes on a
normal internet connection.

**1. Get the code**

```bash
git clone https://github.com/AmaanxShaikh/AMS-multi-ship-trajectories.git
cd AMS-multi-ship-trajectories
```

**2. Create a virtual environment and install the dependencies**

Windows (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**3. Start the app**

```bash
streamlit run app.py
```

Your browser opens at <http://localhost:8501>. If it does not, open that
address yourself.

> **Tip:** If PowerShell refuses to run `Activate.ps1`, allow scripts for the
> current session with `Set-ExecutionPolicy -Scope Process RemoteSigned` and
> try again.

---

## Using the app

The sidebar walks you through five steps.

| Step | What you do |
|------|-------------|
| **1. Where** | Choose Rheinhafen or Cuxhaven. |
| **2. Scenario** | Pick a scenario type. *Custom* starts empty; the others offer a ready-made example. You can also import a saved scenario file here. |
| **3. Ships** | Add ships, choose which one you are placing waypoints for, then click on the map. Open *Edit* to change a ship's size, speed, entry time or radar rotation. |
| **4. Weather** | Optional. Set wind and current with the sliders; calm conditions are used by default. |
| **5. Run** | Choose the scenario length and press **Run simulation**. |

A ship needs at least two waypoints. For routes that follow a bend in the
river, add a waypoint at each bend; with only two points a ship sails in a
straight line.

After a run, the main page shows six sections:

| Section | Content |
|---------|---------|
| 1. Select Points on Map | The map used for placing waypoints |
| 2. Trajectory Output | Summary per ship, boundary check, full result download |
| 3. Simulation Visualisation | Animated playback with timeline, filters and a colour key |
| 4. Radar Simulation | Range and bearing of each ship from the region centre |
| 5. Encounter Analysis | Number and type of encounters, ship time windows, event timeline |
| 6. Passive Sensor Detections | Beam detection times per ship and sensor, with JSON and CSV download |

---

## Scenario files

A scenario is a plain JSON file. **Save scenario as JSON** in the sidebar
writes one, and **Import scenario** reads it back, restoring the region, the
duration and every ship. The import also accepts the larger file from
*Download Full JSON*, which additionally contains the computed trajectories.

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
        {"lat": 49.0282495, "lon": 8.301181}
      ]
    }
  ]
}
```

The example is shortened to one ship with its first and last waypoint; a
real file lists every ship and all of its waypoints.

| Field | Unit | Meaning |
|-------|------|---------|
| `region` | | `rheinhafen` or `cuxhaven` |
| `duration_s` | s | Length of the scenario on the shared clock |
| `mmsi` | | Nine-digit radio identity; 211 is the German country code |
| `length_m`, `beam_m`, `draught_m` | m | Ship length, width and depth below the waterline |
| `initial_speed_mps` | m/s | Requested speed (5 m/s is about 10 knots) |
| `initial_heading_deg` | ° | 0 = north, 90 = east |
| `radar_rotation_s` | s | Time for one full turn of the radar antenna |
| `start_time_s` | s | When the ship enters the scenario |
| `waypoints` | ° | Points the ship steers towards, in order |

---

## How it works

```
 User interface ──► MMG physics ──► Simulation manager ──┬──► Encounter analysis ──┐
 (ships, waypoints)  (one path per    (shared clock,     │                          ├──► Results view
                      ship)            entry times)      └──► Passive sensors ──────┘
```

**Physics.** Each ship's path is computed on its own by the MMG model from the
previous project: propeller, rudder, hull resistance, wind and current, solved
in one-second steps, with a rudder controller that steers towards the next
waypoint. The model knows nothing about other ships.

**Shared clock.** The simulation manager gives every ship an entry time and
places its path on one common timeline. A ship only exists between its entry
time and the end of its route. Two ships can therefore only meet while both
are on the water; routes that cross on the map are not an encounter unless
the ships are there at the same time.

**Encounters.** At every second, each pair of active ships closer than
500 m is classified by the difference between their headings:

| Type | Heading difference |
|------|--------------------|
| Head-on | more than 150° |
| Crossing | 30° to 150° |
| Overtaking | up to 30°, first ship faster |
| Following | up to 30°, first ship not faster |

An event is only recorded when a pair enters a new situation, so one long
meeting is not reported once per second.

**Passive sensors.** Each ship's radar beam points north at the start of every
rotation and sweeps round once per `radar_rotation_s`. A shore sensor receives
one pulse per rotation, at the moment the beam points at it. Because that
moment depends on where the ship is, it is found by a short fixed-point
iteration. A random timing error with a standard deviation of 1 ms is added to
mimic real hardware.

---

## Reproducibility

**Environment.** All dependencies in `requirements.txt` are pinned to the
exact versions the project was developed and tested with, on Python 3.12.8.
Using the same Python version and a fresh virtual environment gives you the
same setup as the final demonstration.

**What is deterministic.** For the same scenario file and weather settings,
the physics, the trajectories, the encounter analysis and the exact sensor
detection times (`true_t`) are the same on every run. Two things are random:

- the MMSI of a newly added ship (a saved scenario keeps its MMSI), and
- the simulated timing noise in `measured_t`. In the app it changes from run
  to run; the self-test below fixes it with `seed=42`.

No calculation depends on an online service. Live wind from OpenWeatherMap
exists in the code but is switched off, so results do not depend on the
weather at the time of running. An internet connection is only needed to
load the background map tiles.

**Self-tests.** Each core module can be run on its own as a quick check. Run
these from the project folder with the virtual environment active:

```bash
python -m core.simulation_manager   # same routes, different start times
python -m core.passive_radar        # sensor detection times with fixed seed
python -m core.sensors              # sensor positions for both regions
python -m core.trajectory           # simple trajectory output
python -m core.radar                # onboard radar detections
python visualize_sensors.py         # writes <region>_sensors_map.html
```

`core.simulation_manager` should report **one crossing** when both ships start
at 0 s and **no encounters** when the second ship starts one hour later. That
is the central behaviour of the shared clock. `core.sensors` should list every
sensor as *on land (ok)*. Files written by these checks are ignored by Git.

**Reference timings.** On a normal laptop, a one-hour scenario with two ships
runs in about 2.6 s: physics 1.9 s, encounter analysis 0.2 s, sensor detection
0.4 s, onboard radar under 0.1 s. Most of the waiting you notice in the
browser comes from drawing the animated map, not from the calculations.

---

## Project structure

```
AMS-multi-ship-trajectories/
├── app.py                      Streamlit application (interface and results)
├── core/
│   ├── scenario.py             Ship, waypoint and scenario data model, JSON export
│   ├── regions.py              Loads region geometry; builds the river corridor
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
├── visualize_sensors.py        Standalone map of the sensor positions
├── requirements.txt            Pinned dependencies
└── README.md
```

---

## Known limitations

- **Ships do not react to each other.** Encounters are detected, but no ship
  changes course to avoid another.
- **Straight lines with two waypoints.** The fairway-following route for a
  plain start and end point is looked up in a folder that is not part of this
  repository, so the code falls back to a straight line. Add waypoints at bends.
- **Sharp turns.** The physics model struggles with very tight turns, such as
  the entrances of two of the Rheinhafen port basins.
- **Simplified encounter rules.** Fixed distance and angle thresholds, not the
  full collision regulations (COLREGs).
- **Ideal sensors.** The sensor model ignores signal strength, terrain
  blocking and reflections.
- **Map smoothness.** Streamlit reloads the page on every click, so the map
  blinks briefly when a waypoint is placed and the animation flickers slightly
  during playback. A higher *Animation Speed* value makes playback calmer.

---

## Team and credits

| Member | Contribution |
|--------|--------------|
| **Mohammed Amaan Shaikh** | User interface, simulation manager and shared clock, encounter detection, playback, scenario import and export |
| **Vivek Mohan Babu** | Radar model, shore sensor placement, passive detection timing, fine time-step support |
| **Rakshit** (until June 2026) | Physics integration for several ships, first example scenarios |

The ship physics, fairway centrelines and working-area polygons come from the
previous AMS lab project by **Vineet Kumar Agarwal, Aishwarya Chincholi Vasant
Madhav and Nishanth Battu**, *Simulation and Prediction of Ship Trajectories*
(Final Report, September 2025). Map data © OpenStreetMap contributors.

Supervised by the Autonomous Multisensor Systems group, Otto von Guericke
University Magdeburg.
