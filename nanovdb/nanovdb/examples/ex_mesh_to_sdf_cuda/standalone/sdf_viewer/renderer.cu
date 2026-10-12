// SPDX-License-Identifier: Apache-2.0
#include "render.cuh"
#include <nanovdb/GridHandle.h>
#include <nanovdb/io/IO.h>
#include <cuda_runtime.h>
#include <algorithm>
#include <cmath>
#include <cstring>
#include <memory>
#include <stdexcept>
#include <string>

namespace {
thread_local std::string lastError;
void check(cudaError_t status) {
    if(status!=cudaSuccess) throw std::runtime_error(cudaGetErrorString(status));
}
struct DeviceMemory {
    void* data=nullptr;
    size_t bytes=0;
    DeviceMemory()=default;
    DeviceMemory(const DeviceMemory&)=delete;
    ~DeviceMemory() { if(data) cudaFree(data); }
    void reserve(size_t size) {
        if(size<=bytes) return;
        if(data) { check(cudaFree(data)); data=nullptr; bytes=0; }
        check(cudaMalloc(&data,size)); bytes=size;
    }
};
struct Context {
    DeviceMemory grid, pixels, exhausted;
    Channels channels;
    bool indexGrid=false;
    float background=0, voxelSize=0;
};

template<typename T>
const T* channel(const nanovdb::NanoGrid<Index>& grid, const void* deviceGrid,
                 const char* name, uint64_t count, bool optional=false) {
    for(uint32_t i=0;i<grid.blindDataCount();++i) {
        const auto& meta=grid.blindMetaData(i);
        if(std::strncmp(meta.mName,name,nanovdb::GridBlindMetaData::MaxNameSize)!=0) continue;
        const T* host=meta.template getBlindData<T>();
        if(!host || meta.mValueCount!=count || meta.mValueSize!=sizeof(T))
            throw std::runtime_error(std::string("Invalid channel: ")+name);
        const auto offset=reinterpret_cast<const char*>(host)-reinterpret_cast<const char*>(&grid);
        if(offset<0 || uint64_t(offset)>grid.gridSize() || count>(grid.gridSize()-offset)/sizeof(T))
            throw std::runtime_error(std::string("Channel outside grid buffer: ")+name);
        return reinterpret_cast<const T*>(static_cast<const char*>(deviceGrid)+offset);
    }
    if(optional || count==0) return nullptr;
    throw std::runtime_error(std::string("Missing MeshToSDF channel: ")+name+". Regenerate with the current MeshToSDF driver.");
}

template<typename BuildT>
void describe(const nanovdb::NanoGrid<BuildT>& grid, GridInfo& info) {
    if(!grid.activeVoxelCount() || grid.indexBBox().empty()) throw std::runtime_error("Grid has no active voxels");
    info.activeVoxels=grid.activeVoxelCount(); info.gridBytes=grid.gridSize();
    for(int i=0;i<3;++i) {
        info.voxelSize[i]=grid.voxelSize()[i];
        info.indexMin[i]=grid.indexBBox().min()[i]; info.indexMax[i]=grid.indexBBox().max()[i];
        info.worldMin[i]=1.e300; info.worldMax[i]=-1.e300;
        if(!std::isfinite(info.voxelSize[i]) || info.voxelSize[i]<=0 ||
           std::abs(info.voxelSize[i]/grid.voxelSize()[0]-1.0)>1.e-5)
            throw std::runtime_error("Viewer requires a uniform voxel scale");
    }
    for(int bits=0;bits<8;++bits) {
        nanovdb::Vec3d p;
        for(int i=0;i<3;++i) p[i]=(bits&(1<<i))? info.indexMax[i]+1.:info.indexMin[i]-1.;
        p=grid.indexToWorld(p);
        for(int i=0;i<3;++i) { info.worldMin[i]=std::min(info.worldMin[i],p[i]); info.worldMax[i]=std::max(info.worldMax[i],p[i]); }
    }
    for(int a=0;a<3;++a) for(int b=a+1;b<3;++b) {
        nanovdb::Vec3d x(0.),y(0.); x[a]=1; y[b]=1;
        if(std::abs(grid.indexToWorldDir(x).dot(grid.indexToWorldDir(y)))>1.e-5*info.voxelSize[0]*info.voxelSize[0])
            throw std::runtime_error("Viewer does not support sheared transforms");
    }
}

template<typename BuildT>
__global__ void probeKernel(const nanovdb::NanoGrid<BuildT>* grid, Channels channels,
                            int count, const int32_t* coords, float* values) {
    const int i=int(blockIdx.x*blockDim.x+threadIdx.x);
    if(i<count) {
        Field<BuildT> field(*grid,channels);
        values[i]=field.getValue(Coord(coords[3*i],coords[3*i+1],coords[3*i+2]));
    }
}
}

extern "C" const char* sdf_error() { return lastError.c_str(); }
extern "C" void* sdf_open(const char* path, int32_t gridIndex, GridInfo* info) {
    try {
        if(!path || !info || gridIndex<0) throw std::runtime_error("Invalid open arguments");
        auto host=nanovdb::io::readGrid(path,gridIndex);
        auto ctx=std::make_unique<Context>();
        const auto* index=host.grid<Index>();
        const auto* scalar=host.grid<float>();
        if(!index && !scalar) throw std::runtime_error("Expected ValueOnIndex MeshToSDF or Float LevelSet .nvdb grid");
        if(index) describe(*index,*info); else describe(*scalar,*info);
        size_t available,total; check(cudaMemGetInfo(&available,&total));
        if(info->gridBytes+64*1024*1024>available)
            throw std::runtime_error("Grid needs "+std::to_string(info->gridBytes/(1024*1024))+" MiB; GPU has "+std::to_string(available/(1024*1024))+" MiB free. This viewer is GPU-resident, not out-of-core.");
        ctx->grid.reserve(info->gridBytes);
        ctx->indexGrid=bool(index); info->indexGrid=bool(index);
        ctx->voxelSize=float(info->voxelSize[0]);
        if(index) {
            if(!index->isSequential()) throw std::runtime_error("MeshToSDF masks require sequential nodes");
            auto& c=ctx->channels;
            c.sdf=channel<float>(*index,ctx->grid.data,"sdf",index->valueCount());
            c.leaf=reinterpret_cast<const nanovdb::Mask<3>*>(channel<uint64_t>(*index,ctx->grid.data,"leaf_invert",uint64_t(index->tree().nodeCount(0))*8));
            c.lower=reinterpret_cast<const nanovdb::Mask<4>*>(channel<uint64_t>(*index,ctx->grid.data,"lower_invert",uint64_t(index->tree().nodeCount(1))*64));
            c.upper=reinterpret_cast<const nanovdb::Mask<5>*>(channel<uint64_t>(*index,ctx->grid.data,"upper_invert",uint64_t(index->tree().nodeCount(2))*512));
            for(uint32_t i=0;i<index->blindDataCount();++i) {
                const auto& meta=index->blindMetaData(i);
                if(std::strncmp(meta.mName,"root_interior",nanovdb::GridBlindMetaData::MaxNameSize)==0) {
                    if(meta.mDataType == nanovdb::toGridType<int32_t>()) {
                        if(meta.mValueCount%3) throw std::runtime_error("Invalid root_interior count");
                        c.rootCount=meta.mValueCount/3;
                        c.root=reinterpret_cast<const Coord*>(channel<int32_t>(*index,ctx->grid.data,"root_interior",meta.mValueCount));
                    } else if(meta.mDataType == nanovdb::toGridType<uint8_t>()) {
                        const auto* extent=channel<int32_t>(*index,index,"root_extent",6);
                        uint64_t cells=1;
                        for(int axis=0;axis<3;++axis) {
                            const int32_t dim=extent[axis+3];
                            if(dim<=0 || cells>meta.mValueCount/uint64_t(dim))
                                throw std::runtime_error("Invalid root_extent dimensions");
                            cells*=uint64_t(dim);
                            c.rootMin[axis]=extent[axis]; c.rootDims[axis]=dim;
                        }
                        c.denseRoot=channel<uint8_t>(*index,ctx->grid.data,"root_interior",cells);
                    } else {
                        throw std::runtime_error("Unsupported root_interior element type");
                    }
                }
            }
            const auto offset=reinterpret_cast<const char*>(c.sdf)-static_cast<const char*>(ctx->grid.data);
            std::memcpy(&ctx->background,reinterpret_cast<const char*>(index)+offset,sizeof(float));
        } else {
            if(scalar->gridClass()!=nanovdb::GridClass::LevelSet)
                throw std::runtime_error("Float grid must be tagged LevelSet (density and UDF are not SDFs)");
            ctx->background=scalar->tree().background();
        }
        if(!std::isfinite(ctx->background) || ctx->background<=0) throw std::runtime_error("SDF background must be finite and positive");
        check(cudaMemcpy(ctx->grid.data,host.data(),info->gridBytes,cudaMemcpyHostToDevice));
        ctx->exhausted.reserve(sizeof(int));
        check(cudaMemGetInfo(&available,&total)); info->freeDeviceBytes=available;
        lastError.clear();
        return ctx.release();
    } catch(const std::exception& e) { lastError=e.what(); return nullptr; }
}
extern "C" void sdf_close(void* ptr) { delete static_cast<Context*>(ptr); }
extern "C" int sdf_render(void* ptr,const RenderSettings* s,int32_t width,int32_t height,
                          int32_t x,int32_t y,int32_t tw,int32_t th,int32_t samples,uint8_t* rgba) {
    try {
        auto* c=static_cast<Context*>(ptr);
        if(!c || !s || !rgba || width<1 || height<1 || width>32768 || height>32768 || x<0 || y<0 ||
           tw<1 || th<1 || int64_t(x)+tw>width || int64_t(y)+th>height || int64_t(tw)*th>16777216 || samples<1 || samples>256)
            throw std::runtime_error("Invalid render dimensions or samples");
        if(!(s->step>=.05f && s->step<=1.f) || !(s->shell>0) || !(s->density>=0) ||
           !(s->fov>0 && s->fov<175) || s->mode<0 || s->mode>5 || s->clipAxis< -1 || s->clipAxis>2)
            throw std::runtime_error("Invalid render settings");
        if((s->mode<=2 && std::abs(s->iso)*c->voxelSize>=c->background) ||
           (s->mode==1 && (std::abs(s->iso)+s->shell)*c->voxelSize>=c->background))
            throw std::runtime_error("Iso value / volume shell must stay strictly inside the SDF narrow band");
        c->pixels.reserve(size_t(tw)*th*4);
        check(cudaMemset(c->exhausted.data,0,sizeof(int)));
        const int blocks=(tw*th+127)/128;
        if(c->indexGrid) renderKernel<<<blocks,128>>>(static_cast<const nanovdb::NanoGrid<Index>*>(c->grid.data),c->channels,*s,width,height,x,y,tw,th,samples,static_cast<uchar4*>(c->pixels.data),static_cast<int*>(c->exhausted.data));
        else renderKernel<<<blocks,128>>>(static_cast<const nanovdb::NanoGrid<float>*>(c->grid.data),c->channels,*s,width,height,x,y,tw,th,samples,static_cast<uchar4*>(c->pixels.data),static_cast<int*>(c->exhausted.data));
        check(cudaGetLastError());
        check(cudaMemcpy(rgba,c->pixels.data,size_t(tw)*th*4,cudaMemcpyDeviceToHost));
        int exhausted=0; check(cudaMemcpy(&exhausted,c->exhausted.data,sizeof(int),cudaMemcpyDeviceToHost));
        if(exhausted) throw std::runtime_error("Ray traversal exhausted its budget or float precision; no incomplete image will be exported");
        return 1;
    } catch(const std::exception& e) { lastError=e.what(); return 0; }
}
extern "C" int sdf_probe(void* ptr,int32_t count,const int32_t* xyz,float* values) {
    try {
        auto* c=static_cast<Context*>(ptr);
        if(!c || count<=0 || !xyz || !values) throw std::runtime_error("Invalid probe arguments");
        DeviceMemory coords,output;
        coords.reserve(size_t(count)*3*sizeof(int32_t)); output.reserve(size_t(count)*sizeof(float));
        check(cudaMemcpy(coords.data,xyz,coords.bytes,cudaMemcpyHostToDevice));
        if(c->indexGrid) probeKernel<<<(count+127)/128,128>>>(static_cast<const nanovdb::NanoGrid<Index>*>(c->grid.data),c->channels,count,static_cast<int32_t*>(coords.data),static_cast<float*>(output.data));
        else probeKernel<<<(count+127)/128,128>>>(static_cast<const nanovdb::NanoGrid<float>*>(c->grid.data),c->channels,count,static_cast<int32_t*>(coords.data),static_cast<float*>(output.data));
        check(cudaGetLastError()); check(cudaMemcpy(values,output.data,output.bytes,cudaMemcpyDeviceToHost)); return 1;
    } catch(const std::exception& e) { lastError=e.what(); return 0; }
}
