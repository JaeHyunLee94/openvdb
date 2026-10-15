// SPDX-License-Identifier: Apache-2.0
// Independent analytic oracle for an axis-aligned closed cube's root output.
#include <nanovdb/io/IO.h>
#include <array>
#include <cmath>
#include <cstring>
#include <iostream>
#include <set>
#include <vector>
#include <stdexcept>

int main(int argc,char** argv) {
    try {
        if(argc!=8) throw std::runtime_error("Usage: sdf_check_cube_mesh_roots grid.nvdb minX minY minZ maxX maxY maxZ");
        auto handle=nanovdb::io::readGrid(argv[1]);
        const auto* grid=handle.grid<nanovdb::ValueOnIndex>();
        if(!grid) throw std::runtime_error("Expected a ValueOnIndex SDF grid");
        nanovdb::Vec3d lo,hi;
        for(int a=0;a<3;++a) { lo[a]=std::stod(argv[a+2]); hi[a]=std::stod(argv[a+5]); }
        lo=grid->worldToIndex(lo); hi=grid->worldToIndex(hi);
        const float* sdf=nullptr;
        const int32_t* origins=nullptr;uint64_t rootCount=0;
        const uint8_t* dense=nullptr;uint64_t denseCount=0;
        const int32_t* extent=nullptr;const char* format="none";
        for(uint32_t i=0;i<grid->blindDataCount();++i) {
            const auto& m=grid->blindMetaData(i);
            if(std::strcmp(m.mName,"sdf")==0) sdf=m.getBlindData<float>();
            if(std::strcmp(m.mName,"root_extent")==0) {
                extent=m.getBlindData<int32_t>();
                if(!extent || m.mValueCount!=6) throw std::runtime_error("Invalid root extent");
            }
            if(std::strcmp(m.mName,"root_interior")==0) {
                if(m.mDataType==nanovdb::toGridType<int32_t>()) {
                    origins=m.getBlindData<int32_t>();
                    if(!origins || m.mValueCount%3) throw std::runtime_error("Invalid coordinate-list root format");
                    rootCount=m.mValueCount/3;format="coordinate-list";
                } else if(m.mDataType==nanovdb::toGridType<uint8_t>()) {
                    dense=m.getBlindData<uint8_t>();denseCount=m.mValueCount;format="dense";
                } else throw std::runtime_error("Unsupported root format");
            }
        }
        if(!sdf || !(sdf[0]>0)) throw std::runtime_error("Missing positive SDF background");
        const double band=sdf[0]/grid->voxelSize()[0];
        using Key=std::array<int,3>;
        std::set<Key> expected,actual;
        const auto min=grid->indexBBox().min()>>12, max=grid->indexBBox().max()>>12;
        // Root positions wholly inside the exact box and farther than the band
        // from every face must have no active samples anywhere in the tile.
        for(int i=min[0];i<=max[0];++i) for(int j=min[1];j<=max[1];++j) for(int k=min[2];k<=max[2];++k) {
            Key p={i*4096,j*4096,k*4096};bool inside=true;
            for(int a=0;a<3;++a)
                inside &= p[a]>lo[a]+band+1.e-3 && p[a]+4095<hi[a]-band-1.e-3;
            if(inside) expected.insert(p);
        }
        std::vector<nanovdb::Coord> roots;
        for(uint64_t n=0;n<rootCount;++n) roots.emplace_back(origins[n*3],origins[n*3+1],origins[n*3+2]);
        if(dense) {
            if(!extent) throw std::runtime_error("Dense root mask needs root_extent");
            uint64_t count=1;
            for(int a=0;a<3;++a) {
                if(extent[a+3]<=0 || count>denseCount/uint64_t(extent[a+3])) throw std::runtime_error("Invalid dense root dimensions");
                count*=uint64_t(extent[a+3]);
            }
            if(count!=denseCount) throw std::runtime_error("Dense root length mismatch");
            for(uint64_t n=0;n<count;++n) if(dense[n]) {
                int64_t tile[3]={int64_t(n/(uint64_t(extent[4])*extent[5]))+extent[0],
                                  int64_t(n/extent[5]%extent[4])+extent[1],int64_t(n%extent[5])+extent[2]};
                for(int a=0;a<3;++a) if(tile[a]<-524288 || tile[a]>524287) throw std::runtime_error("Root coordinate overflow");
                roots.emplace_back(int(tile[0]*4096),int(tile[1]*4096),int(tile[2]*4096));
            }
        }
        for(const nanovdb::Coord p:roots) {
            if((p&4095)!=nanovdb::Coord(0) || grid->tree().root().probeChild(p))
                throw std::runtime_error("Root tile unaligned or overlaps an Upper child");
            if(!actual.insert({p[0],p[1],p[2]}).second) throw std::runtime_error("Duplicate root tile");
            // Check geometric cube corners, including the half-voxel footprint.
            for(int a=0;a<3;++a) if(!(p[a]-.5>lo[a] && p[a]+4095.5<hi[a]))
                throw std::runtime_error("Returned root cube crosses the exact mesh boundary");
        }
        if(actual!=expected) throw std::runtime_error("Actual and analytic root sets differ: got "+std::to_string(actual.size())+", expected "+std::to_string(expected.size()));
        std::cout<<"{\"passed\":true,\"active_voxels\":"<<grid->activeVoxelCount()
                 <<",\"grid_bytes\":"<<grid->gridSize()<<",\"root_format\":\""<<format<<"\""<<",\"root_tiles\":"<<actual.size()
                 <<",\"root_voxels_represented\":"<<(uint64_t(actual.size())*(uint64_t(1)<<36))
                 <<",\"root_origins\":[";
        bool comma=false;
        for(auto p:actual) { if(comma)std::cout<<',';comma=true;std::cout<<'['<<p[0]<<','<<p[1]<<','<<p[2]<<']'; }
        std::cout<<"]}\n";
    } catch(const std::exception& e) { std::cerr<<"FAIL: "<<e.what()<<'\n';return 1; }
}
