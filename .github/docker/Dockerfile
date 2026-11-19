# Stage 1 image (reviewer 2026-11-15): today's exact software, pre-installed, so a job skips
# the 5-10 min apt/pip install and its network failures. Same binaries as the apt install
# in the workflows => same answers. Pinned: Ubuntu 24.04, openfoam2412-default, PY_DEPS.
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update -q && apt-get install -y -q curl ca-certificates python3 python3-pip python3-venv \
      libopengl0 libglu1-mesa libegl1 libgl1 libgomp1 libxkbcommon0 git \
 && curl -s https://dl.openfoam.com/add-debian-repo.sh | bash \
 && apt-get install -y -q openfoam2412-default && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/py && /opt/py/bin/pip install --no-cache-dir pytest numpy==2.4.6 scipy==1.17.1 pandas \
      trimesh==5.2.0 scikit-image shapely rtree==1.4.1 mapbox-earcut manifold3d==3.5.4 \
      fast_simplification==0.2.0 jax jaxlib matplotlib pymeshlab==2025.7.post1
ENV PATH=/opt/py/bin:$PATH FOAM_BASHRC=/usr/lib/openfoam/openfoam2412/etc/bashrc
