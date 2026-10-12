// SPDX-License-Identifier: Apache-2.0
#pragma once
#include <nanovdb/NanoVDB.h>
#include <nanovdb/math/SampleFromVoxels.h>

using Vec = nanovdb::Vec3f;
using Coord = nanovdb::Coord;
using Index = nanovdb::ValueOnIndex;

// These masks are part of this branch's MeshToSDF file contract. A plain
// ChannelAccessor would return +background for every inactive interior voxel.
struct Channels {
    const float* sdf = nullptr;
    const nanovdb::Mask<3>* leaf = nullptr;
    const nanovdb::Mask<4>* lower = nullptr;
    const nanovdb::Mask<5>* upper = nullptr;
    const Coord* root = nullptr;
    uint64_t rootCount = 0;
    const uint8_t* denseRoot = nullptr;
    Coord rootMin{0}, rootDims{0};
};

template<typename BuildT>
struct Field {
    using ValueType = float;
    using CoordType = Coord;
    const nanovdb::NanoGrid<BuildT>& grid;
    nanovdb::DefaultReadAccessor<BuildT> acc;
    Channels channels;

    __device__ Field(const nanovdb::NanoGrid<BuildT>& g, Channels c)
        : grid(g), acc(g.tree().root()), channels(c) {}

    __device__ float getValue(const Coord& p) const {
        if constexpr (nanovdb::util::is_same<BuildT, float>::value) {
            return acc.getValue(p);
        } else {
            const uint64_t index = acc.getValue(p);
            if (index) return channels.sdf[index];
            const auto& tree = grid.tree();
            bool inside = false;
            // Cached pointers can survive a cache miss; check each node origin.
            if (const auto* leaf = acc.template getNode<0>(); leaf && leaf->origin() == (p & ~7)) {
                const auto id = leaf - tree.template getFirstNode<0>();
                inside = channels.leaf[id].isOn(nanovdb::NanoLeaf<BuildT>::CoordToOffset(p));
            } else if (const auto* lower = acc.template getNode<1>(); lower && lower->origin() == (p & ~127)) {
                const auto id = lower - tree.template getFirstNode<1>();
                inside = channels.lower[id].isOn(nanovdb::NanoLower<BuildT>::CoordToOffset(p));
            } else if (const auto* upper = acc.template getNode<2>(); upper && upper->origin() == (p & ~4095)) {
                const auto id = upper - tree.template getFirstNode<2>();
                inside = channels.upper[id].isOn(nanovdb::NanoUpper<BuildT>::CoordToOffset(p));
            } else {
                if (channels.denseRoot) {
                    const Coord q = (p >> 12) - channels.rootMin;
                    if (q[0]>=0 && q[1]>=0 && q[2]>=0 && q[0]<channels.rootDims[0] &&
                        q[1]<channels.rootDims[1] && q[2]<channels.rootDims[2]) {
                        const uint64_t offset = (uint64_t(q[0])*channels.rootDims[1]+q[1])*channels.rootDims[2]+q[2];
                        inside = channels.denseRoot[offset] != 0;
                    }
                }
                const Coord origin = (p >> 12) << 12;
                for (uint64_t i = 0; i < channels.rootCount; ++i)
                    if (channels.root[i] == origin) { inside = true; break; }
            }
            return inside ? -channels.sdf[0] : channels.sdf[0];
        }
    }
};
