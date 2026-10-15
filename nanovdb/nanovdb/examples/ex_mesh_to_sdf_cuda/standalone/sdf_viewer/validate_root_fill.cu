// SPDX-License-Identifier: Apache-2.0
// Tests the real PropagateSign header. No renderer field queries form the oracle.
#include <nanovdb/tools/cuda/PropagateSign.cuh>
#include <nanovdb/tools/CreateNanoGrid.h>
#include <nanovdb/cuda/GridHandle.cuh>
#include <nanovdb/io/IO.h>
#include <algorithm>
#include <array>
#include <cstring>
#include <filesystem>
#include <iostream>
#include <queue>
#include <random>
#include <set>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <tuple>
#include <vector>

using Coord=nanovdb::Coord;
using Index=nanovdb::ValueOnIndex;
using Key=std::array<int,3>;
using RootOp=nanovdb::tools::cuda::signing::detail::RootPropagationFunctor;

void require(bool condition,const std::string& message) {
    if(!condition) throw std::runtime_error(message);
}
struct Stream {
    cudaStream_t value{};
    Stream() { cudaCheck(cudaStreamCreateWithFlags(&value,cudaStreamNonBlocking)); }
    ~Stream() { cudaStreamDestroy(value); }
};
size_t offset(Coord p,Coord dims) { return (size_t(p[0])*dims[1]+p[1])*dims[2]+p[2]; }
Coord coordinate(size_t n,Coord dims) {
    return Coord(int(n/(size_t(dims[1])*dims[2])),int(n/dims[2]%dims[1]),int(n%dims[2]));
}
std::vector<uint8_t> bfs(const std::vector<uint8_t>& walls,const std::vector<uint8_t>& seeds,Coord dims) {
    std::vector<uint8_t> reached(walls.size(),0);
    std::queue<Coord> frontier;
    for(size_t n=0;n<walls.size();++n) if(seeds[n] && !walls[n]) {
        reached[n]=1;frontier.push(coordinate(n,dims));
    }
    while(!frontier.empty()) {
        const Coord p=frontier.front();frontier.pop();
        for(int axis=0;axis<3;++axis) for(int direction:{-1,1}) {
            Coord q=p;q[axis]+=direction;
            if(q[axis]<0 || q[axis]>=dims[axis]) continue;
            const size_t n=offset(q,dims);
            if(!walls[n] && !reached[n]) { reached[n]=1;frontier.push(q); }
        }
    }
    return reached;
}
void testFlood(const std::string& name,Coord dims,std::vector<uint8_t> walls,
               std::vector<uint8_t> seeds,cudaStream_t stream,int expectedCount=-1) {
    const auto expected=bfs(walls,seeds,dims);
    const int count=int(std::count(expected.begin(),expected.end(),uint8_t(1)));
    if(expectedCount>=0) require(count==expectedCount,"Invalid CPU fixture: "+name);
    nanovdb::cuda::Buffer<uint8_t> dWalls(stream,walls.size(),nanovdb::cuda::noInit);
    nanovdb::cuda::Buffer<uint8_t> dMask(stream,seeds.size(),nanovdb::cuda::noInit);
    cudaCheck(cudaMemcpyAsync(dWalls.data(),walls.data(),walls.size(),cudaMemcpyHostToDevice,stream));
    cudaCheck(cudaMemcpyAsync(dMask.data(),seeds.data(),seeds.size(),cudaMemcpyHostToDevice,stream));
    nanovdb::util::cuda::operatorKernel<RootOp><<<1,RootOp::MaxThreadsPerBlock,0,stream>>>(dWalls.data(),dMask.data(),dims);
    cudaCheckError();
    std::vector<uint8_t> actual(seeds.size());
    cudaCheck(cudaMemcpyAsync(actual.data(),dMask.data(),actual.size(),cudaMemcpyDeviceToHost,stream));
    cudaCheck(cudaStreamSynchronize(stream));
    for(size_t n=0;n<actual.size();++n) require(actual[n]==expected[n],name+": GPU/CPU mismatch at cell "+std::to_string(n));
    std::cout<<"PASS flood: "<<name<<" ("<<actual.size()<<" cells, "<<count<<" reached)\n";
}
void testRootKernel(cudaStream_t stream) {
    const Coord dims(7,7,7);
    auto walls=std::vector<uint8_t>(343,0),seeds=walls;
    for(int i=1;i<=5;++i) for(int j=1;j<=5;++j) for(int k=1;k<=5;++k)
        if(i==1 || i==5 || j==1 || j==5 || k==1 || k==5) walls[offset(Coord(i,j,k),dims)]=1;
    seeds[offset(Coord(3),dims)]=1;
    testFlood("closed shell keeps interior isolated",dims,walls,seeds,stream,27);
    auto noSeeds=std::vector<uint8_t>(343,0);
    testFlood("no negative seeds does not invent fill",dims,walls,noSeeds,stream,0);
    auto wallSeed=noSeeds;wallSeed[offset(Coord(1,3,3),dims)]=1;
    testFlood("seed on Upper-child wall is cleared",dims,walls,wallSeed,stream,0);
    auto outside=noSeeds;outside[0]=1;
    testFlood("outside seed cannot cross closed wall",dims,walls,outside,stream,218);
    auto open=walls;open[offset(Coord(1,3,3),dims)]=0;
    testFlood("one-cell passage connects the two regions",dims,open,seeds,stream,246);
    const Coord twoDims(13,7,7);
    std::vector<uint8_t> twoWalls(13*7*7,0),twoSeeds(twoWalls.size(),0);
    for(int start:{1,7}) for(int i=start;i<=start+4;++i) for(int j=1;j<=5;++j) for(int k=1;k<=5;++k)
        if(i==start || i==start+4 || j==1 || j==5 || k==1 || k==5) twoWalls[offset(Coord(i,j,k),twoDims)]=1;
    twoSeeds[offset(Coord(3),twoDims)]=1;
    testFlood("unseeded disconnected cavity stays empty",twoDims,twoWalls,twoSeeds,stream,27);
    std::mt19937 random(20261015);
    for(int iteration=0;iteration<8;++iteration) {
        const Coord shape(iteration<4?17:65,iteration<4?11:17,iteration<4?9:5);
        const size_t cells=size_t(shape[0])*shape[1]*shape[2];
        std::vector<uint8_t> randomWalls(cells),randomSeeds(cells,0);
        for(auto& wall:randomWalls) wall=(random()%100)<31;
        for(int n=0;n<8;++n) randomSeeds[random()%cells]=1;
        testFlood("deterministic random topology "+std::to_string(iteration),shape,randomWalls,randomSeeds,stream);
    }
}

// Accommodate both the current tuple-return API and the committed getter API.
template<typename Operator>
auto propagate(Operator& op) {
    if constexpr(std::is_void_v<decltype(op.propagate())>) {
        op.propagate();
        return std::make_tuple(op.getLeafInteriorMasks(),op.getLowerInteriorMasks(),
                               op.getUpperInteriorMasks(),op.getRootInteriorTileOrigins());
    } else return op.propagate();
}

void testPipeline(const std::string& name,Coord tileMin,Coord dims,bool inside,
                  cudaStream_t stream,const std::filesystem::path& exportPath={}) {
    using namespace nanovdb;
    // Root-scale topology fixture: each boundary root position has one Upper
    // child with one active leaf seed. No dense 4096^3 wall is allocated.
    // This validates hierarchy propagation, not voxelization of a watertight mesh.
    constexpr float dx=1.f/4096.f;
    tools::build::Grid<float> source(3.f*dx,"root_fill_topology_fixture");
    source.setTransform(1.0/4096.0);
    auto accessor=source.getAccessor();
    std::set<Key> expected;
    for(int i=0;i<dims[0];++i) for(int j=0;j<dims[1];++j) for(int k=0;k<dims[2];++k) {
        Coord origin((tileMin[0]+i)*4096,(tileMin[1]+j)*4096,(tileMin[2]+k)*4096);
        if(i==0 || j==0 || k==0 || i==dims[0]-1 || j==dims[1]-1 || k==dims[2]-1)
            accessor.setValue(origin+Coord(4),inside?-dx:dx);
        else if(inside) expected.insert({origin[0],origin[1],origin[2]});
    }
    auto scalar=tools::createNanoGrid(source);
    const auto& src=*scalar.grid<float>();
    tools::CreateNanoGrid<NanoGrid<float>> converter(src);
    converter.addBlindData("sdf",GridBlindDataSemantic::LevelSet,GridBlindDataClass::ChannelArray,GridType::Float,src.activeVoxelCount()+1,4);
    const char* maskNames[]={"leaf_invert","lower_invert","upper_invert"};
    const int words[]={8,64,512};
    for(int level=0;level<3;++level)
        converter.addBlindData(maskNames[level],GridBlindDataSemantic::Unknown,GridBlindDataClass::ChannelArray,
                              toGridType<uint64_t>(),uint64_t(src.tree().nodeCount(level))*words[level],8);
    if(!expected.empty()) converter.addBlindData("root_interior",GridBlindDataSemantic::Unknown,GridBlindDataClass::ChannelArray,GridType::Int32,expected.size()*3,4);
    auto host=converter.getHandle<Index>(0,false,false);
    auto* grid=host.grid<Index>();
    for(uint32_t n=0;n<grid->blindDataCount();++n) {
        const auto& meta=grid->blindMetaData(n);
        std::memset(const_cast<void*>(meta.blindData()),0,meta.mValueCount*meta.mValueSize);
    }
    float* sdf=grid->getBlindData<float>(0);
    std::fill(sdf,sdf+grid->valueCount(),inside?-dx:dx);sdf[0]=3.f*dx;
    tools::updateChecksum(grid,CheckMode::Disable);
    auto device=nanovdb::cuda::copyTo<nanovdb::cuda::Buffer<std::byte>>(host,stream);
    std::vector<int8_t> signs(grid->valueCount(),inside?int8_t(-1):int8_t(1));signs[0]=1;
    nanovdb::cuda::Buffer<int8_t> dSigns(stream,signs.size(),nanovdb::cuda::noInit);
    cudaCheck(cudaMemcpyAsync(dSigns.data(),signs.data(),signs.size(),cudaMemcpyHostToDevice,stream));
    tools::cuda::PropagateSign<Index> op(device.deviceGrid<Index>(),dSigns.data(),stream);
    auto outputs=propagate(op);
    auto& roots=std::get<3>(outputs);
    std::vector<Coord> origins(roots.size());
    if(!origins.empty()) cudaCheck(cudaMemcpyAsync(origins.data(),roots.data(),origins.size()*sizeof(Coord),cudaMemcpyDeviceToHost,stream));
    cudaCheck(cudaStreamSynchronize(stream));
    std::set<Key> actual;
    for(const Coord p:origins) {
        require((p&4095)==Coord(0),name+": unaligned root origin");
        require(!grid->tree().root().probeChild(p),name+": root output overlaps an Upper child");
        require(actual.insert({p[0],p[1],p[2]}).second,name+": duplicate root origin");
    }
    require(actual==expected,name+": root origin set differs from analytic topology truth (got "+std::to_string(actual.size())+", expected "+std::to_string(expected.size())+")");
    std::cout<<"PASS pipeline: "<<name<<" ("<<grid->tree().nodeCount(2)<<" Upper walls, "<<actual.size()<<" root fills)\n";
    if(!exportPath.empty()) {
        auto copyMask=[&](auto& buffer,int channel) {
            const auto& meta=grid->blindMetaData(channel);
            require(buffer.size_bytes()==meta.mValueCount*meta.mValueSize,"Mask byte count mismatch");
            cudaCheck(cudaMemcpyAsync(const_cast<void*>(meta.blindData()),buffer.data(),buffer.size_bytes(),cudaMemcpyDeviceToHost,stream));
        };
        copyMask(std::get<0>(outputs),1);copyMask(std::get<1>(outputs),2);copyMask(std::get<2>(outputs),3);
        cudaCheck(cudaStreamSynchronize(stream));
        if(!origins.empty()) std::memcpy(grid->getBlindData<int32_t>(4),origins.data(),origins.size()*sizeof(Coord));
        tools::updateChecksum(grid,CheckMode::Disable);
        std::filesystem::create_directories(exportPath.parent_path().empty()?".":exportPath.parent_path());
        io::writeGrid(exportPath.string(),host);
        std::cout<<"Exported real PropagateSign output: "<<exportPath<<'\n';
    }
}
int main(int argc,char** argv) {
    try {
        std::filesystem::path output;
        if(argc==3 && std::string(argv[1])=="--output") output=argv[2];
        else if(argc!=1) { std::cerr<<"Usage: "<<argv[0]<<" [--output fixture.nvdb]\n";return 2; }
        Stream stream;
        testRootKernel(stream.value);
        testPipeline("3x3x3 negative shell",Coord(0),Coord(3),true,stream.value,output);
        testPipeline("3x3x3 positive shell",Coord(0),Coord(3),false,stream.value);
        testPipeline("translated negative-coordinate shell",Coord(-4,-3,-2),Coord(3),true,stream.value);
        testPipeline("unequal dimensions and multiple interior tiles",Coord(-2,1,-3),Coord(4,5,6),true,stream.value);
        testPipeline("fully occupied root range has no absent tile",Coord(-1),Coord(2),true,stream.value);
        std::cout<<"PASS: 14 root-kernel/CPU-BFS cases and 5 full-pipeline cases\n";
        return 0;
    } catch(const std::exception& e) { std::cerr<<"FAIL: "<<e.what()<<'\n';return 1; }
}
