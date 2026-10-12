// SPDX-License-Identifier: Apache-2.0
#pragma once
#include <cstdint>

// All distances are world units except step, shell, and iso (voxel units).
struct RenderSettings {
    float eye[3], target[3], up[3];
    float color[3], background[3];
    float fov, orthoScale, step, iso, density, shell, ao, exposure;
    float clipPosition; // index coordinate of the clipping/slice plane
    int32_t mode;      // 0 surface, 1 shell volume, 2 normals, 3 full sign slice, 4 active cubes, 5 active sign slice
    int32_t clipAxis;  // -1 disabled; 0,1,2 index-space X,Y,Z; keep <= plane
    int32_t orthographic, transparent;
};
struct GridInfo {
    double worldMin[3], worldMax[3], voxelSize[3];
    int32_t indexMin[3], indexMax[3];
    uint64_t activeVoxels, gridBytes, freeDeviceBytes;
    int32_t indexGrid;
};
extern "C" {
const char* sdf_error();
void* sdf_open(const char* path, int32_t gridIndex, GridInfo* info);
void sdf_close(void* context);
int sdf_render(void* context, const RenderSettings* settings,
               int32_t width, int32_t height, int32_t x, int32_t y,
               int32_t tileWidth, int32_t tileHeight, int32_t samples, uint8_t* rgba);
// Raw integer-coordinate queries, useful for verifying deep-interior sign preservation.
int sdf_probe(void* context, int32_t count, const int32_t* xyz, float* values);
}
