// SPDX-License-Identifier: Apache-2.0
// CPU-only extraction of actual root metadata; never expands tiles into voxels.
#include <nanovdb/io/IO.h>
#include "polyscope_cells.h"
#include <array>
#include <cmath>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <limits>
#include <set>
#include <stdexcept>
#include <vector>
using Key=std::array<int32_t,3>;
static Key key(nanovdb::Coord p) {return {p[0],p[1],p[2]};}
static void array(const std::vector<Key>& values) {
    std::cout<<'[';bool comma=false;
    for(auto p:values) {if(comma)std::cout<<',';comma=true;std::cout<<'['<<p[0]<<','<<p[1]<<','<<p[2]<<']';}
    std::cout<<']';
}
int main(int argc,char** argv) {
    try {
        bool upperFill=false,hasROI=false;PolyscopeCellSelection selection;
        if(argc<2)throw std::runtime_error("Usage: sdf_export_polyscope_roots grid.nvdb [--upper-fill] [--cells-dir path --roi minX minY minZ maxX maxY maxZ | --all-cells]");
        for(int i=2;i<argc;++i) {
            std::string option=argv[i];
            if(option=="--upper-fill")upperFill=true;
            else if(option=="--cells-dir" && i+1<argc) {selection.directory=argv[++i];selection.enabled=true;}
            else if(option=="--all-cells")selection.all=true;
            else if(option=="--roi" && i+6<argc) {
                hasROI=true;
                for(int a=0;a<6;++a) {int64_t v=std::stoll(argv[++i]);if(v<INT32_MIN||v>INT32_MAX)throw std::runtime_error("ROI coordinate overflow");selection.roi[a]=int32_t(v);}
                for(int a=0;a<3;++a)if(selection.roi[a]>selection.roi[a+3])throw std::runtime_error("Inverted ROI bounds");
            }else throw std::runtime_error("Unknown or incomplete option: "+option);
        }
        if(selection.all && hasROI)throw std::runtime_error("Choose --roi or --all-cells");
        if(selection.enabled && !selection.all && !hasROI)throw std::runtime_error("--cells-dir requires --roi or --all-cells");
        if(!selection.enabled && (selection.all||hasROI))throw std::runtime_error("Cell selection requires --cells-dir");
        auto handle=nanovdb::io::readGrid(argv[1]);const auto* grid=handle.grid<nanovdb::ValueOnIndex>();
        if(!grid || !grid->activeVoxelCount())throw std::runtime_error("Expected nonempty ValueOnIndex MeshToSDF grid");
        const double dx=grid->voxelSize()[0];auto origin=grid->indexToWorld(nanovdb::Vec3d(0));
        if(!std::isfinite(dx)||dx<=0)throw std::runtime_error("Invalid voxel size");
        for(int a=0;a<3;++a) {nanovdb::Vec3d p(0);p[a]=1;p=grid->indexToWorld(p)-origin;
            for(int b=0;b<3;++b)if(std::abs(p[b]-(a==b?dx:0))>dx*1e-6)throw std::runtime_error("Polyscope export requires uniform axis-aligned transform");}
        std::vector<Key> roots,uppers,unmarked,fill,overlaps;
        const int32_t* extent=nullptr;const uint8_t* dense=nullptr;uint64_t denseCount=0;
        const nanovdb::Mask<5>* masks=nullptr;bool hasRoot=false;
        for(uint32_t i=0;i<grid->blindDataCount();++i) {
            const auto& m=grid->blindMetaData(i);
            if(std::strcmp(m.mName,"root_extent")==0) {if(m.mValueCount!=6)throw std::runtime_error("Invalid root_extent");extent=m.getBlindData<int32_t>();}
            if(std::strcmp(m.mName,"upper_invert")==0 && upperFill) {
                if(m.mValueCount!=uint64_t(grid->tree().nodeCount(2))*512)throw std::runtime_error("Invalid upper mask length");
                masks=reinterpret_cast<const nanovdb::Mask<5>*>(m.getBlindData<uint64_t>());
            }
            if(std::strcmp(m.mName,"root_interior")==0) {
                hasRoot=true;
                if(m.mDataType==nanovdb::toGridType<int32_t>()) {
                    const auto* p=m.getBlindData<int32_t>();if(!p||m.mValueCount%3)throw std::runtime_error("Invalid root origin list");
                    for(uint64_t n=0;n<m.mValueCount;n+=3)roots.push_back({p[n],p[n+1],p[n+2]});
                }else if(m.mDataType==nanovdb::toGridType<uint8_t>()) {dense=m.getBlindData<uint8_t>();denseCount=m.mValueCount;}
                else throw std::runtime_error("Unsupported root format");
            }
        }
        if(dense) {
            uint64_t cells=1;
            if(!extent)throw std::runtime_error("Missing dense root_extent");
            for(int a=0;a<3;++a) {if(extent[a+3]<=0 || cells>denseCount/uint64_t(extent[a+3]))throw std::runtime_error("Invalid root dimensions");cells*=extent[a+3];}
            if(cells!=denseCount)throw std::runtime_error("Invalid dense root count");
            for(uint64_t n=0;n<cells;++n)if(dense[n]) {
                int64_t p[3]={int64_t(n/(uint64_t(extent[4])*extent[5]))+extent[0],int64_t(n/extent[5]%extent[4])+extent[1],int64_t(n%extent[5])+extent[2]};Key k;
                for(int a=0;a<3;++a) {p[a]*=4096;if(p[a]<INT32_MIN||p[a]>INT32_MAX)throw std::runtime_error("Root coordinate overflow");k[a]=int32_t(p[a]);}roots.push_back(k);
            }
        }
        std::set<Key> marked;
        for(auto p:roots) {
            if((nanovdb::Coord(p[0],p[1],p[2])&4095)!=nanovdb::Coord(0) || !marked.insert(p).second)throw std::runtime_error("Unaligned or duplicate root origin");
            if(grid->tree().root().probeChild(nanovdb::Coord(p[0],p[1],p[2])))overlaps.push_back(p);
        }
        const auto* nodes=grid->tree().template getFirstNode<2>();
        if(upperFill && grid->tree().nodeCount(2) && !masks)throw std::runtime_error("Missing upper_invert masks");
        for(uint32_t i=0;i<grid->tree().nodeCount(2);++i) {
            const auto& node=nodes[i];uppers.push_back(key(node.origin()));
            if(upperFill)for(uint32_t w=0;w<512;++w) {
                uint64_t bits=masks[i].words()[w]&~node.childMask().words()[w];
                while(bits) {uint32_t bit=__builtin_ctzll(bits);bits&=bits-1;fill.push_back(key(node.offsetToGlobalCoord(w*64+bit)));}
            }
        }
        auto lo=grid->indexBBox().min()>>12,hi=grid->indexBBox().max()>>12;
        for(int64_t i=lo[0];i<=hi[0];++i)for(int64_t j=lo[1];j<=hi[1];++j)for(int64_t k=lo[2];k<=hi[2];++k) {
            nanovdb::Coord p(int32_t(i*4096),int32_t(j*4096),int32_t(k*4096));
            if(!grid->tree().root().probeChild(p) && !marked.count(key(p)))unmarked.push_back(key(p));
        }
        auto cellManifest=exportPolyscopeCells(*grid,roots,selection);
        std::cout<<std::setprecision(17)<<"{\"format\":\"polyscope-mesh-sdf-roots-v1\",\"active_voxels\":"<<grid->activeVoxelCount()
                 <<",\"voxel_size\":"<<dx<<",\"translation\":["<<origin[0]<<','<<origin[1]<<','<<origin[2]<<"],\"root_channel_present\":"<<(hasRoot?"true":"false")<<",\"root_origins\":";
        array(roots);std::cout<<",\"upper_origins\":";array(uppers);std::cout<<",\"unmarked_root_origins\":";array(unmarked);
        std::cout<<",\"root_child_overlaps\":";array(overlaps);std::cout<<",\"upper_fill_included\":"<<(upperFill?"true":"false")<<",\"upper_fill_origins\":";array(fill);std::cout<<",\"index_min\":["<<grid->indexBBox().min()[0]<<','<<grid->indexBBox().min()[1]<<','<<grid->indexBBox().min()[2]<<"],\"index_max\":["<<grid->indexBBox().max()[0]<<','<<grid->indexBBox().max()[1]<<','<<grid->indexBBox().max()[2]<<"],\"cell_selection\":"<<cellManifest<<"}\n";
    }catch(const std::exception& e) {std::cerr<<"FAIL: "<<e.what()<<'\n';return 1;}
}
