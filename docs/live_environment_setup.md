# Live Open-RMF environment setup

Validated on 2026-07-20/21 using Docker Desktop on Windows 11 with the Linux/WSL2
engine. The container is Ubuntu 24.04 and contains ROS 2 Kilted, Gazebo Ionic,
Open-RMF, `rmf_demos`, and this repository's `aft` package.

## Reproducible installation

Run these commands in PowerShell from the repository root:

```powershell
docker desktop start
docker version
docker pull ghcr.io/open-rmf/rmf/rmf_demos@sha256:a6ed4f30b6f86833b54037aa5ce3535a078ea304de776b0d6b5ddb01b1e94478
docker volume create aft-gz-cache
docker compose -f docker/docker-compose.yml build aft
docker compose -f docker/docker-compose.yml run --rm aft health-check --config configs/default.yaml
```

The named `aft-gz-cache` volume is required by `docker-compose.yml` and preserves
Gazebo Fuel assets between runs. The Compose service uses host networking so the
Gazebo transport and ROS DDS participants can communicate inside Docker Desktop.

The derived image installs the packages absent from the upstream demo image:

```text
ros-kilted-navigation2
ros-kilted-nav2-bringup
python3-venv
adversarial-fleet-testing 0.1.0 in /opt/aft-venv
```

## Image and component versions

The upstream image is pinned, rather than selected by a moving tag:

```text
ghcr.io/open-rmf/rmf/rmf_demos@sha256:a6ed4f30b6f86833b54037aa5ce3535a078ea304de776b0d6b5ddb01b1e94478
```

The inspected Linux/amd64 image and derived image contained:

| Component | Version |
| --- | --- |
| Ubuntu | 24.04.4 LTS (Noble) |
| ROS distribution | Kilted |
| `ros-kilted-ros-base` | `0.12.0-2noble.20260604.102317` |
| Gazebo Sim (Ionic) | 9.5.0 |
| `rmf_demos_gz` | 2.9.0 |
| `rmf_demos_tasks` | 2.9.0 |
| `rmf_fleet_adapter` | 2.13.0 |
| `rmf_traffic` | 3.8.0 |
| `rmf_task_ros2` | 2.13.0 |
| Nav2 / `nav2_bringup` | 1.4.2 (`1.4.2-1noble.20260615.084032`) |
| Cyclone DDS RMW package | `4.0.2-2noble.20260604.024809` |
| `rosbag2_transport` | 0.32.0 (`0.32.0-2noble.20260604.074434`) |
| `rosbag2_storage_mcap` | 0.32.0 (`0.32.0-2noble.20260604.042034`) |
| Python | 3.12.3 |
| `adversarial-fleet-testing` | 0.1.0 |

Docker Desktop was 4.46.0, with Docker client/server 28.4.0, linux/amd64, 20
logical CPUs, and approximately 8.1 GiB assigned to the Linux VM.

## Required environment and ROS setup

The image and runner use:

```bash
export ROS_DISTRO=kilted
export ROS_DOMAIN_ID=0
export ROS2CLI_DISABLE_DAEMON=1
export AFT_RMF_IMAGE='ghcr.io/open-rmf/rmf/rmf_demos@sha256:a6ed4f30b6f86833b54037aa5ce3535a078ea304de776b0d6b5ddb01b1e94478'
source /opt/ros/kilted/setup.bash
source /rmf_demos_ws/install/setup.bash
```

`PATH` in the derived image begins with `/opt/aft-venv/bin`. `ROS_DOMAIN_ID=0`
is required for this pinned Office image. Domain 42 allowed the graph and clock
to appear but the slotcar plugins could not resolve their map level and never
published usable robot states.

## Manual Office launch

The exact validated launch command is:

```powershell
docker compose -f docker/docker-compose.yml run --rm --name aft-rmf-office --entrypoint bash aft -lc "source /opt/ros/kilted/setup.bash && source /rmf_demos_ws/install/setup.bash && ros2 launch rmf_demos_gz office.launch.xml headless:=1 use_sim_time:=true sim_update_rate:=100"
```

From a second PowerShell terminal, a patrol can be submitted with:

```powershell
docker exec aft-rmf-office bash -lc "source /opt/ros/kilted/setup.bash && source /rmf_demos_ws/install/setup.bash && ros2 run rmf_demos_tasks dispatch_patrol -p coe lounge -n 1 --use_sim_time"
```

The live inspection returned `success: true`, status `queued`, and task ID
`patrol.dispatch-a46321aa38`. Stop the manual session with:

```powershell
docker stop --timeout 30 aft-rmf-office
docker ps
```

The automated runs use the same launch arguments. A GUI launch was not used for
the benchmark because Qt/RViz display initialization is not reliable in this
headless Docker Desktop environment. Robot motion was instead verified from live
fleet poses and the captured MCAP data.

## Scenario and replay commands

```powershell
docker compose -f docker/docker-compose.yml run --rm aft run-scenario --scenario configs/example_scenario.yaml --config configs/default.yaml
docker compose -f docker/docker-compose.yml run --rm aft replay --package /opt/adversarial-fleet-testing/results/runs/<run_id>
```

`results` is bind-mounted at `/opt/adversarial-fleet-testing/results`, so artifacts
written in the container are retained on the host.
