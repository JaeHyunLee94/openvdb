// SPDX-License-Identifier: Apache-2.0
// Exact sparse cell selection for Polyscope; binary output avoids huge JSON arrays.
#pragma once
#include <nanovdb/NanoVDB.h>
#include <array>
#include <cmath>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <vector>

struct PolyscopeCellSelection {
    bool enabled=false,all=false;
    std::filesystem::path directory;
    std::array<int32_t,6> roi{};
    bool intersects(nanovdb::Coord p,int dim) const {
        if(all)return true;
        for(int a=0;a<3;++a)if(p[a]>roi[a+3] || int64_t(p[a])+dim-1<roi[a])return false;
        return true;
    }
};
struct PolyscopeCellWriter {
    struct Record {int32_t xyz[3];float value;};
    static_assert(sizeof(Record)==16,"Unexpected cell record layout");
    std::ofstream file;uint64_t count=0;
    explicit PolyscopeCellWriter(const std::filesystem::path& path):file(path,std::ios::binary) {if(!file)throw std::runtime_error("Cannot create cell file");}
    void add(nanovdb::Coord p,float v) {Record r{{p[0],p[1],p[2]},v};file.write(reinterpret_cast<const char*>(&r),sizeof(r));++count;}
    void finish() {file.flush();if(!file)throw std::runtime_error("Cell file write failed (check disk space)");}
};

template<int Level>
void exportInteriorLevel(const nanovdb::NanoGrid<nanovdb::ValueOnIndex>& grid,
                         const nanovdb::Mask<(Level==0?3:Level==1?4:5)>* masks,
                         const PolyscopeCellSelection& selection,PolyscopeCellWriter& output,float background) {
    using BuildT=nanovdb::ValueOnIndex;
    const auto* nodes=grid.tree().template getFirstNode<Level>();
    constexpr int size=Level==0?1:Level==1?8:128;
    for(uint32_t i=0;i<grid.tree().nodeCount(Level);++i) {
        const auto& node=nodes[i];
        if(!selection.intersects(node.origin(),node.DIM))continue;
        const auto& excluded=[&]()->const auto& {if constexpr(Level==0)return node.valueMask();else return node.childMask();}();
        for(uint32_t w=0;w<excluded.WORD_COUNT;++w) {
            uint64_t bits=masks[i].words()[w]&~excluded.words()[w];
            while(bits) {
                uint32_t bit=__builtin_ctzll(bits);bits&=bits-1;
                auto p=node.offsetToGlobalCoord(w*64+bit);
                if(selection.intersects(p,size))output.add(p,-background);
            }
        }
    }
}

inline std::string exportPolyscopeCells(const nanovdb::NanoGrid<nanovdb::ValueOnIndex>& grid,
                 const std::vector<std::array<int32_t,3>>& roots,const PolyscopeCellSelection& selection) {
    if(!selection.enabled)return "null";
    const uint32_t endian=1;if(*reinterpret_cast<const uint8_t*>(&endian)!=1)throw std::runtime_error("Cell export currently requires little-endian host");
    const nanovdb::Mask<3>* leaf=nullptr;const nanovdb::Mask<4>* lower=nullptr;const nanovdb::Mask<5>* upper=nullptr;const float* sdf=nullptr;
    for(uint32_t i=0;i<grid.blindDataCount();++i) {
        const auto& m=grid.blindMetaData(i);
        if(std::strcmp(m.mName,"sdf")==0) {if(m.mValueCount!=grid.valueCount())throw std::runtime_error("SDF slot count mismatch");sdf=m.getBlindData<float>();}
        auto mask=[&](const char* name,int level,int words) {
            if(std::strcmp(m.mName,name)!=0)return static_cast<const uint64_t*>(nullptr);
            if(m.mValueCount!=uint64_t(grid.tree().nodeCount(level))*words)throw std::runtime_error("Fill mask length mismatch");
            return m.getBlindData<uint64_t>();
        };
        if(auto* p=mask("leaf_invert",0,8))leaf=reinterpret_cast<const nanovdb::Mask<3>*>(p);
        if(auto* p=mask("lower_invert",1,64))lower=reinterpret_cast<const nanovdb::Mask<4>*>(p);
        if(auto* p=mask("upper_invert",2,512))upper=reinterpret_cast<const nanovdb::Mask<5>*>(p);
    }
    if(!sdf || !leaf || !lower || !upper || !std::isfinite(sdf[0]) || sdf[0]<=0)throw std::runtime_error("Missing or invalid full-space SDF channels");
    std::filesystem::create_directories(selection.directory);
    PolyscopeCellWriter a(selection.directory/"leaf.bin"),b(selection.directory/"lower.bin"),c(selection.directory/"upper.bin"),d(selection.directory/"root.bin"),e(selection.directory/"active.bin");
    exportInteriorLevel<0>(grid,leaf,selection,a,sdf[0]);exportInteriorLevel<1>(grid,lower,selection,b,sdf[0]);exportInteriorLevel<2>(grid,upper,selection,c,sdf[0]);
    for(auto r:roots) {nanovdb::Coord p(r[0],r[1],r[2]);if(!grid.tree().root().probeChild(p) && selection.intersects(p,4096))d.add(p,-sdf[0]);}
    const auto* nodes=grid.tree().template getFirstNode<0>();
    for(uint32_t i=0;i<grid.tree().nodeCount(0);++i) {
        const auto& node=nodes[i];if(!selection.intersects(node.origin(),node.DIM))continue;
        for(uint32_t w=0;w<8;++w) {
            uint64_t bits=node.valueMask().words()[w];
            while(bits) {uint32_t bit=__builtin_ctzll(bits);bits&=bits-1;auto p=node.offsetToGlobalCoord(w*64+bit);
                if(selection.intersects(p,1))e.add(p,sdf[node.getValue(p)]);}
        }
    }
    a.finish();b.finish();c.finish();d.finish();e.finish();
    std::ostringstream out;out<<"{\"record_bytes\":16,\"endianness\":\"little\",\"all\":"<<(selection.all?"true":"false")<<",\"roi\":[";
    for(int i=0;i<6;++i) {if(i)out<<',';out<<selection.roi[i];}
    out<<"],\"counts\":["<<a.count<<','<<b.count<<','<<c.count<<','<<d.count<<','<<e.count<<"]}";return out.str();
}
