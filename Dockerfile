# LOLM — Latent Order Language Model
# Vast.ai GPU training image
#
# Build:  docker build -t lolm .
# Run:    docker run --gpus all -v $(pwd)/runs:/workspace/runs lolm
#
# On Vast.ai, use image: vastai/base-image:cuda-12.8.1-auto
# Then clone repo and run setup.sh

FROM vastai/base-image:cuda-12.8.1-auto

WORKDIR /workspace

# Install Python dependencies
COPY requirements-gpu.txt .
RUN pip install --no-cache-dir -r requirements-gpu.txt

# Copy project
COPY . .

# Tokenize data at build time (optional — can also do at runtime)
# RUN python prepare_data.py

# Default: train full model
CMD ["python", "-u", "train.py", "--config", "configs/scale/300m_v3.yaml"]
