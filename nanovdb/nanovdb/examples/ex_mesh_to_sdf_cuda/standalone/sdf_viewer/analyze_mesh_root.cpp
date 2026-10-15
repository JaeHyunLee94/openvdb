// SPDX-License-Identifier: Apache-2.0
#include "mesh_geometry.h"
#include <nanovdb/io/IO.h>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <set>
using namespace mesh_oracle;
int main(int argc,char** argv) {
    try {
        if(argc!=2 && argc!=3)throw std::runtime_error("Usage: sdf_analyze_mesh_root mesh.obj [grid.nvdb]");
        Mesh mesh(argv[1]);std::cout<<std::setprecision(17);
        if(argc==2) {
            auto best=mesh.findCube();V c=best.second;
            std::cout<<"{\"vertices\":"<<mesh.vertices.size()<<",\"triangles\":"<<mesh.faces.size()<<",\"area\":"<<mesh.area
                     <<",\"signed_volume\":"<<mesh.volume<<",\"closed_oriented_edges\":true,\"cube_half_width\":"<<best.first
                     <<",\"cube_center\":["<<c[0]<<','<<c[1]<<','<<c[2]<<"],\"winding\":"<<mesh.winding(c)
                     <<",\"area_per_cube_side_squared\":"<<mesh.area/(4*best.first*best.first)<<"}\n";
            return best.first>0?0:1;
        }
        if(std::strcmp(argv[2],"--points")==0) {
            V p;double radius;bool comma=false;std::cout<<'[';
            while(std::cin>>p[0]>>p[1]>>p[2]>>radius) {
                if(comma)std::cout<<',';comma=true;double w=mesh.winding(p);
                bool inside=std::abs(w)>.5,skip=mesh.surface(p,radius);
                if(!skip && (inside!=mesh.inside(p) || std::abs(w-std::round(w))>1e-5))throw std::runtime_error("Ambiguous independent point classification");
                std::cout<<"{\"inside\":"<<(inside?"true":"false")<<",\"skip\":"<<(skip?"true":"false")<<",\"winding\":"<<w<<'}';
            }std::cout<<"]\n";return 0;
        }
        auto handle=nanovdb::io::readGrid(argv[2]);const auto* grid=handle.grid<nanovdb::ValueOnIndex>();
        if(!grid)throw std::runtime_error("Expected ValueOnIndex grid");
        std::vector<nanovdb::Coord> roots;const int32_t* ext=nullptr;const uint8_t* dense=nullptr;uint64_t count=0;
        for(uint32_t i=0;i<grid->blindDataCount();++i) {
            const auto& m=grid->blindMetaData(i);
            if(std::strcmp(m.mName,"root_extent")==0) {if(m.mValueCount!=6)throw std::runtime_error("Bad root extent");ext=m.getBlindData<int32_t>();}
            if(std::strcmp(m.mName,"root_interior")==0) {
                if(m.mDataType==nanovdb::toGridType<int32_t>()) {
                    const auto* p=m.getBlindData<int32_t>();if(!p||m.mValueCount%3)throw std::runtime_error("Bad root coordinates");
                    for(uint64_t j=0;j<m.mValueCount;j+=3)roots.emplace_back(p[j],p[j+1],p[j+2]);
                }else if(m.mDataType==nanovdb::toGridType<uint8_t>()) {dense=m.getBlindData<uint8_t>();count=m.mValueCount;}
                else throw std::runtime_error("Unknown root metadata");
            }
        }
        if(dense) {
            if(!ext || ext[3]<=0||ext[4]<=0||ext[5]<=0 || uint64_t(ext[3])*ext[4]*ext[5]!=count)throw std::runtime_error("Bad dense root dimensions");
            for(uint64_t j=0;j<count;++j)if(dense[j])roots.emplace_back(int((int64_t(j/(uint64_t(ext[4])*ext[5]))+ext[0])*4096),int((int64_t(j/ext[5]%ext[4])+ext[1])*4096),int((int64_t(j%ext[5])+ext[2])*4096));
        }
        std::set<std::array<int,3>> unique;bool passed=true;
        std::cout<<"{\"active_voxels\":"<<grid->activeVoxelCount()<<",\"grid_bytes\":"<<grid->gridSize()<<",\"root_tiles\":"<<roots.size()<<",\"roots\":[";
        bool comma=false;
        for(auto p:roots) {
            if((p&4095)!=nanovdb::Coord(0)||grid->tree().root().probeChild(p))throw std::runtime_error("Root overlaps child or is unaligned");
            if(!unique.insert({p[0],p[1],p[2]}).second)throw std::runtime_error("Duplicate root");
            auto q=grid->indexToWorld(nanovdb::Vec3d(p[0]+2047.5,p[1]+2047.5,p[2]+2047.5));V c{{q[0],q[1],q[2]}};
            double half=2048*grid->voxelSize()[0],w=mesh.winding(c);
            bool hit=mesh.surface(c,half),contained=!hit && std::abs(std::abs(w)-1)<1e-5;
            passed &= contained;
            if(comma)std::cout<<',';comma=true;std::cout<<"{\"origin\":["<<p[0]<<','<<p[1]<<','<<p[2]<<"],\"winding\":"<<w
                <<",\"surface_intersection\":"<<(hit?"true":"false")<<",\"contained\":"<<(contained?"true":"false")<<'}';
        }
        std::cout<<"],\"passed\":"<<(passed?"true":"false")<<"}\n";return passed?0:2;
    }catch(const std::exception& e) {std::cerr<<"FAIL: "<<e.what()<<'\n';return 1;}
}
