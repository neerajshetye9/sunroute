#!/usr/bin/env bash
# ==============================================================================
# SunRoute: Native llama.cpp CUDA Builder for Jetson Orin Nano (sm_87)
# Target: Jetson Orin Nano Super 8GB, L4T R39.2.1 / JetPack 7.2 (aarch64)
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BUILD_DIR="${PROJECT_ROOT}/build/llama.cpp"
INSTALL_PREFIX="${PROJECT_ROOT}/bin"

echo "=== SunRoute: Building llama.cpp natively on Jetson ==="

# 1. Environment and Architecture Checks
ARCH="$(uname -m)"
echo "Detected architecture: ${ARCH}"
if [[ "${ARCH}" != "aarch64" && "${ARCH}" != "arm64" ]]; then
    echo "WARNING: Expected aarch64 (Jetson Orin). Current host is ${ARCH}."
    echo "Proceeding with standard CUDA / Host build settings."
fi

# Locate CUDA compiler
export PATH="/usr/local/cuda/bin:${PATH}"
export LD_LIBRARY_PATH="/usr/local/cuda/lib64:${LD_LIBRARY_PATH:-}"

if command -v nvcc >/dev/null 2>&1; then
    NVCC_VERSION="$(nvcc --version | grep "release" || true)"
    echo "Found nvcc: ${NVCC_VERSION}"
else
    echo "WARNING: nvcc not found in PATH or /usr/local/cuda/bin."
    echo "Make sure JetPack 7.2 CUDA toolkit is installed if compiling for GPU."
fi

# Check cmake
if ! command -v cmake >/dev/null 2>&1; then
    echo "ERROR: cmake is required to build llama.cpp."
    echo "Install via: sudo apt-get update && sudo apt-get install -y cmake build-essential"
    exit 1
fi

# 2. Check/Record nvpmodel power mode
if command -v nvpmodel >/dev/null 2>&1; then
    echo "Current Jetson Power Mode:"
    nvpmodel -q || true
fi

# 3. Clone or Update llama.cpp source
mkdir -p "${PROJECT_ROOT}/build"
mkdir -p "${INSTALL_PREFIX}"

LLAMA_REPO="https://github.com/ggerganov/llama.cpp.git"
if [ ! -d "${BUILD_DIR}/.git" ]; then
    echo "Cloning llama.cpp into ${BUILD_DIR}..."
    git clone --depth 1 "${LLAMA_REPO}" "${BUILD_DIR}"
else
    echo "Updating existing llama.cpp repository in ${BUILD_DIR}..."
    git -C "${BUILD_DIR}" pull --ff-only || true
fi

# 4. Configure and Build
# sm_87 corresponds to NVIDIA Orin architecture (Ampere-based Tegra)
CMAKE_ARGS=(
    "-B" "${BUILD_DIR}/build"
    "-S" "${BUILD_DIR}"
    "-DCMAKE_BUILD_TYPE=Release"
    "-DCMAKE_INSTALL_PREFIX=${INSTALL_PREFIX}"
    "-DLLAMA_BUILD_TESTS=OFF"
    "-DLLAMA_BUILD_EXAMPLES=ON"
    "-DLLAMA_BUILD_SERVER=ON"
)

if command -v nvcc >/dev/null 2>&1; then
    echo "Enabling GGML_CUDA with sm_87 (Orin)..."
    CMAKE_ARGS+=(
        "-DGGML_CUDA=ON"
        "-DCMAKE_CUDA_ARCHITECTURES=87"
    )
else
    echo "Building CPU-only fallback (no nvcc found)..."
    CMAKE_ARGS+=(
        "-DGGML_CUDA=OFF"
    )
fi

echo "Running cmake configuration..."
cmake "${CMAKE_ARGS[@]}"

NUM_JOBS="$(nproc 2>/dev/null || echo 4)"
echo "Building with ${NUM_JOBS} parallel jobs..."
cmake --build "${BUILD_DIR}/build" --config Release -j "${NUM_JOBS}"

echo "Installing binaries into ${INSTALL_PREFIX}..."
cmake --install "${BUILD_DIR}/build" --prefix "${INSTALL_PREFIX}"

echo "=== Build Complete ==="
echo "Binaries available in: ${INSTALL_PREFIX}/bin"
ls -la "${INSTALL_PREFIX}/bin" || true
