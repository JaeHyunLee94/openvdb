// SPDX-License-Identifier: Apache-2.0
// Deterministic analytic reference plus an index-grid fixture with every mask level.
#include <nanovdb/tools/CreatePrimitives.h>
#include <nanovdb/tools/CreateNanoGrid.h>
#include <nanovdb/io/IO.h>
#include <filesystem>
#include <iostream>

int main(int argc, char** argv) {
    if(argc!=2) return 1;
    const std::filesystem::path dir(argv[1]);
    std::filesystem::create_directories(dir);
    auto sphere=nanovdb::tools::createLevelSetSphere<float>(1.0,nanovdb::Vec3d(0),1.0/64.0,3.0);
    nanovdb::io::writeGrid((dir/"sphere.nvdb").string(),sphere);
    // Equivalent index grid verifies interpolation across leaf/tile boundaries.
    {
        using namespace nanovdb;
        const auto& src = *sphere.grid<float>();
        tools::CreateNanoGrid<NanoGrid<float>> convert(src);
        convert.addBlindData("sdf", GridBlindDataSemantic::LevelSet, GridBlindDataClass::ChannelArray,
                             GridType::Float, src.activeVoxelCount()+1, sizeof(float));
        const char* names[] = {"leaf_invert", "lower_invert", "upper_invert"};
        const int words[] = {8, 64, 512};
        for (int level=0; level<3; ++level)
            convert.addBlindData(names[level], GridBlindDataSemantic::Unknown, GridBlindDataClass::ChannelArray,
                                 toGridType<uint64_t>(), uint64_t(src.tree().nodeCount(level))*words[level], 8);
        auto handle = convert.getHandle<ValueOnIndex>(0, false, false);
        auto* dst = handle.grid<ValueOnIndex>();
        float* values = dst->getBlindData<float>(0);
        values[0] = src.tree().background();
        auto* masks = reinterpret_cast<Mask<3>*>(dst->getBlindData<uint64_t>(1));
        for (uint32_t i=0; i<dst->tree().nodeCount(0); ++i) {
            const auto& leaf = dst->tree().getFirstLeaf()[i];
            masks[i].setOff();
            for (uint32_t n=0; n<512; ++n) {
                const float value = src.tree().getValue(leaf.offsetToGlobalCoord(n));
                if (value < 0) masks[i].setOn(n);
                if (leaf.isActive(n)) values[leaf.getValue(n)] = value;
            }
        }
        auto fillMasks = [&](auto* nodes, auto* masks, uint32_t count) {
            for (uint32_t i=0; i<count; ++i) {
                masks[i].setOff();
                for (uint32_t n=0; n<nodes[i].SIZE; ++n)
                    if (src.tree().getValue(nodes[i].offsetToGlobalCoord(n)) < 0) masks[i].setOn(n);
            }
        };
        fillMasks(dst->tree().getFirstLower(), reinterpret_cast<Mask<4>*>(dst->getBlindData<uint64_t>(2)), dst->tree().nodeCount(1));
        fillMasks(dst->tree().getFirstUpper(), reinterpret_cast<Mask<5>*>(dst->getBlindData<uint64_t>(3)), dst->tree().nodeCount(2));
        tools::updateChecksum(dst, CheckMode::Disable);
        io::writeGrid((dir/"sphere-index.nvdb").string(), handle);
    }
    // Deliberately tiny topology spans three leaves and different sign-storage levels.
    nanovdb::tools::build::Grid<float> source(3.f);
    auto a=source.getAccessor();
    a.setValue(nanovdb::Coord(0,0,0),-.25f);
    a.setValue(nanovdb::Coord(7,7,7),.25f);
    a.setValue(nanovdb::Coord(16,0,0),.5f);
    a.setValue(nanovdb::Coord(-8,0,0),-.5f);
    auto scalar=nanovdb::tools::createNanoGrid(source);
    const auto& src=*scalar.grid<float>();
    nanovdb::tools::CreateNanoGrid<nanovdb::NanoGrid<float>> converter(src);
    using namespace nanovdb;
    // Explicit SDF channel; channels=0 avoids auto-generated channel names/order.
    converter.addBlindData("sdf",GridBlindDataSemantic::LevelSet,GridBlindDataClass::ChannelArray,GridType::Float,5,4);
    converter.addBlindData("leaf_invert",GridBlindDataSemantic::Unknown,GridBlindDataClass::ChannelArray,toGridType<uint64_t>(),src.tree().nodeCount(0)*8,8);
    converter.addBlindData("lower_invert",GridBlindDataSemantic::Unknown,GridBlindDataClass::ChannelArray,toGridType<uint64_t>(),src.tree().nodeCount(1)*64,8);
    converter.addBlindData("upper_invert",GridBlindDataSemantic::Unknown,GridBlindDataClass::ChannelArray,toGridType<uint64_t>(),src.tree().nodeCount(2)*512,8);
    converter.addBlindData("root_interior",GridBlindDataSemantic::Unknown,GridBlindDataClass::ChannelArray,GridType::Int32,3,4);
    auto index=converter.getHandle<ValueOnIndex>(0,false,false);
    auto* grid=index.grid<ValueOnIndex>();
    auto* sdf=grid->getBlindData<float>(0);
    sdf[0]=3.f;
    for(uint32_t i=0;i<grid->tree().nodeCount(0);++i) {
        const auto& leaf=grid->tree().getFirstLeaf()[i];
        for(auto it=leaf.beginValueOn();it;++it) sdf[*it]=src.tree().getValue(it.getCoord());
    }
    auto* leafMasks=reinterpret_cast<Mask<3>*>(grid->getBlindData<uint64_t>(1));
    auto* lowerMasks=reinterpret_cast<Mask<4>*>(grid->getBlindData<uint64_t>(2));
    auto* upperMasks=reinterpret_cast<Mask<5>*>(grid->getBlindData<uint64_t>(3));
    for(uint32_t i=0;i<grid->tree().nodeCount(0);++i) leafMasks[i].setOff();
    for(uint32_t i=0;i<grid->tree().nodeCount(1);++i) lowerMasks[i].setOff();
    for(uint32_t i=0;i<grid->tree().nodeCount(2);++i) upperMasks[i].setOff();
    for(uint32_t i=0;i<grid->tree().nodeCount(0);++i)
        if(grid->tree().getFirstLeaf()[i].origin()==Coord(0)) leafMasks[i].setOn(NanoLeaf<ValueOnIndex>::CoordToOffset(Coord(1,1,1)));
    for(uint32_t i=0;i<grid->tree().nodeCount(1);++i)
        if(grid->tree().getFirstLower()[i].origin()==Coord(0)) lowerMasks[i].setOn(NanoLower<ValueOnIndex>::CoordToOffset(Coord(8,0,0)));
    for(uint32_t i=0;i<grid->tree().nodeCount(2);++i)
        if(grid->tree().getFirstUpper()[i].origin()==Coord(0)) upperMasks[i].setOn(NanoUpper<ValueOnIndex>::CoordToOffset(Coord(128,0,0)));
    int32_t* root=grid->getBlindData<int32_t>(4);root[0]=4096;root[1]=root[2]=0;
    tools::updateChecksum(grid,CheckMode::Disable);
    nanovdb::io::writeGrid((dir/"masks.nvdb").string(),index);
    // Older committed producers encode a dense root mask plus tile-coordinate extent.
    {
        tools::CreateNanoGrid<NanoGrid<float>> denseConverter(src);
        for (uint32_t i=0; i<4; ++i) {
            const auto& m=grid->blindMetaData(i);
            denseConverter.addBlindData(m.mName,m.mSemantic,m.mDataClass,m.mDataType,m.mValueCount,m.mValueSize);
        }
        denseConverter.addBlindData("root_interior",GridBlindDataSemantic::Unknown,GridBlindDataClass::ChannelArray,toGridType<uint8_t>(),3,1);
        denseConverter.addBlindData("root_extent",GridBlindDataSemantic::Unknown,GridBlindDataClass::ChannelArray,toGridType<int32_t>(),6,4);
        auto denseHandle=denseConverter.getHandle<ValueOnIndex>(0,false,false);
        auto* dense=denseHandle.grid<ValueOnIndex>();
        for (uint32_t i=0; i<4; ++i) {
            const auto& m=grid->blindMetaData(i);
            std::memcpy(const_cast<void*>(dense->blindMetaData(i).blindData()),m.blindData(),m.mValueCount*m.mValueSize);
        }
        auto* values=dense->getBlindData<uint8_t>(4);values[0]=0;values[1]=1;values[2]=0;
        auto* extent=dense->getBlindData<int32_t>(5);
        const int32_t dimensions[6]={0,0,0,3,1,1};std::memcpy(extent,dimensions,sizeof(dimensions));
        tools::updateChecksum(dense,CheckMode::Disable);
        io::writeGrid((dir/"dense-masks.nvdb").string(),denseHandle);
        const_cast<GridBlindMetaData&>(dense->blindMetaData(5)).setName("missing_extent");
        io::writeGrid((dir/"missing-extent.nvdb").string(),denseHandle);
    }
    // Loader should reject a topology whose SDF channel is missing.
    const_cast<GridBlindMetaData&>(grid->blindMetaData(0)).setName("wrong_channel");
    nanovdb::io::writeGrid((dir/"missing-channel.nvdb").string(),index);
    std::cout<<"Wrote analytic sphere and mask fixtures to "<<dir<<'\n';
}
