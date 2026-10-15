// SPDX-License-Identifier: Apache-2.0
#pragma once
#include "renderer.h"
#include "field.cuh"
#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>

// Count stored negative childless regions, not a dense expansion of their volume.
// These bounds also cover valid fill outside the active-value bounding box.
inline void includeFillBox(Coord origin, int dim, int level, GridInfo& info) {
    for(int axis=0;axis<3;++axis) {
        const int64_t end=int64_t(origin[axis])+dim-1;
        if(end>std::numeric_limits<int32_t>::max()) throw std::runtime_error("Interior fill exceeds coordinate range");
        info.fillIndexMin[axis]=std::min(info.fillIndexMin[axis],origin[axis]);
        info.fillIndexMax[axis]=std::max(info.fillIndexMax[axis],int32_t(end));
    }
    ++info.fillBoxes[level];
}

template<typename BuildT, int Level>
void collectNodeFill(const nanovdb::NanoGrid<BuildT>& grid, const Channels& host, GridInfo& info) {
    const auto* nodes=grid.tree().template getFirstNode<Level>();
    constexpr int dim=Level==0?1:(Level==1?8:128);
    for(uint32_t i=0;i<grid.tree().nodeCount(Level);++i) {
        const auto& node=nodes[i];
        const auto& excluded=[&]() -> const auto& {
            if constexpr(Level==0) return node.valueMask();
            else return node.childMask();
        }();
        for(uint32_t word=0;word<excluded.WORD_COUNT;++word) {
            uint64_t bits=~excluded.words()[word];
            if constexpr(nanovdb::util::is_same<BuildT,Index>::value) {
                if constexpr(Level==0) bits&=host.leaf[i].words()[word];
                else if constexpr(Level==1) bits&=host.lower[i].words()[word];
                else bits&=host.upper[i].words()[word];
            }
            while(bits) {
                const uint32_t offset=word*64+uint32_t(__builtin_ctzll(bits));
                bits&=bits-1;
                if constexpr(nanovdb::util::is_same<BuildT,float>::value)
                    if(!std::signbit(node.getValue(node.offsetToGlobalCoord(offset)))) continue;
                includeFillBox(node.offsetToGlobalCoord(offset),dim,Level,info);
            }
        }
    }
}

template<typename BuildT>
void collectFill(const nanovdb::NanoGrid<BuildT>& grid, const Channels& host,
                 Channels& device, GridInfo& info) {
    for(int a=0;a<3;++a) { info.fillIndexMin[a]=info.indexMin[a]; info.fillIndexMax[a]=info.indexMax[a]; }
    for(auto& count:info.fillBoxes) count=0;
    collectNodeFill<BuildT,0>(grid,host,info);
    collectNodeFill<BuildT,1>(grid,host,info);
    collectNodeFill<BuildT,2>(grid,host,info);
    auto addRoot=[&](Coord origin) {
        if((origin&4095)!=Coord(0)) throw std::runtime_error("Unaligned root interior origin");
        // Child nodes take precedence over a root-tile flag in field lookup too.
        if(!grid.tree().root().probeChild(origin)) includeFillBox(origin,4096,3,info);
    };
    if constexpr(nanovdb::util::is_same<BuildT,Index>::value) {
        for(uint64_t n=0;n<host.rootCount;++n) addRoot(host.root[n]);
        const uint64_t cells=uint64_t(host.rootDims[0])*host.rootDims[1]*host.rootDims[2];
        if(host.denseRoot) for(uint64_t n=0;n<cells;++n) if(host.denseRoot[n]) {
            const uint64_t z=n%host.rootDims[2], yz=n/host.rootDims[2];
            const uint64_t y=yz%host.rootDims[1], x=yz/host.rootDims[1];
            const int64_t tile[3]={int64_t(host.rootMin[0])+int64_t(x),int64_t(host.rootMin[1])+int64_t(y),int64_t(host.rootMin[2])+int64_t(z)};
            Coord origin;
            for(int a=0;a<3;++a) {
                const int64_t value=tile[a]*4096;
                if(value<std::numeric_limits<int32_t>::min() || value>std::numeric_limits<int32_t>::max())
                    throw std::runtime_error("Root interior exceeds coordinate range");
                origin[a]=int32_t(value);
            }
            addRoot(origin);
        }
    } else {
        const auto& root=grid.tree().root();
        for(auto it=root.cbeginValueAll();it;++it) if(std::signbit(*it)) addRoot(it.getCoord());
    }
    for(int a=0;a<3;++a) { device.fillMin[a]=info.fillIndexMin[a]; device.fillMax[a]=info.fillIndexMax[a]; }
}
