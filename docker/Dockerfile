ARG RMF_DEMOS_IMAGE=ghcr.io/open-rmf/rmf/rmf_demos@sha256:a6ed4f30b6f86833b54037aa5ce3535a078ea304de776b0d6b5ddb01b1e94478
FROM ${RMF_DEMOS_IMAGE}

USER root
WORKDIR /opt/adversarial-fleet-testing
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ros-kilted-navigation2 \
       ros-kilted-nav2-bringup \
       python3-venv \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md ./
COPY src ./src
COPY configs ./configs
RUN python3 -m venv --system-site-packages /opt/aft-venv \
    && /opt/aft-venv/bin/python -m pip install --no-cache-dir .

ENV PATH=/opt/aft-venv/bin:${PATH} \
    PYTHONUNBUFFERED=1 \
    ROS2CLI_DISABLE_DAEMON=1
ENTRYPOINT ["aft"]
