# Copyright Contributors to the OpenVDB Project
# SPDX-License-Identifier: Apache-2.0
#
#[=======================================================================[

  CMake Configuration for NanoVDB Examples

#]=======================================================================]

cmake_minimum_required(VERSION 3.24)
project(NanoVDBExamples LANGUAGES CXX)

include(GNUInstallDirs)

###############################################################################

message(STATUS "----------------------------------------------------")
message(STATUS "---------- Configuring NanoVDB Examples ------------")
message(STATUS "----------------------------------------------------")

###############################################################################

if(WIN32)
  file(MAKE_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/x64/Release")
endif()

# -----------------------------------------------------------------------------`
# helper function
# -----------------------------------------------------------------------------`
function(NANOVDB_EXAMPLE)
  set(options OPENVDB)
  set(oneValueArgs NAME)
  set(multiValueArgs)
  cmake_parse_arguments(NANOVDB_EXAMPLE
    "${options}" "${oneValueArgs}" "${multiValueArgs}" ${ARGN})

  set(EXAMPLE_NAME ${NANOVDB_EXAMPLE_NAME})
  set(EXAMPLE_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/${EXAMPLE_NAME}")

  file(GLOB EXAMPLE_HEADER_FILES
    ${EXAMPLE_ROOT}/*.h
    ${EXAMPLE_ROOT}/*.inl
    ${EXAMPLE_ROOT}/*.hh
    ${EXAMPLE_ROOT}/*.hpp
    ${EXAMPLE_ROOT}/*.cuh)

  file(GLOB EXAMPLE_SOURCE_FILES
    ${EXAMPLE_ROOT}/*.c
    ${EXAMPLE_ROOT}/*.cc
    ${EXAMPLE_ROOT}/*.cpp)

  file(GLOB EXAMPLE_SOURCE_CUDA_FILES ${EXAMPLE_ROOT}/*.cu)

  # configure CUDA
  if(NOT NANOVDB_USE_CUDA AND EXAMPLE_SOURCE_CUDA_FILES)
    message(WARNING " - CUDA required to build ${EXAMPLE_NAME}. Skipping.")
    return()
  endif()

  if(NANOVDB_EXAMPLE_OPENVDB AND NOT NANOVDB_USE_OPENVDB)
    message(WARNING " - OpenVDB required to build ${EXAMPLE_NAME}. Skipping.")
    return()
  endif()

  add_executable(${EXAMPLE_NAME}
    ${EXAMPLE_SOURCE_FILES}
    ${EXAMPLE_SOURCE_CUDA_FILES}
    ${EXAMPLE_HEADER_FILES})

  # Propagate MSVC Runtime from the OpenVDB library (if VDB_MSVC_RUNTIME_SELECTION
  # has been set then we're building and linking against OpenVDB, see the root
  # NanoVDB CMakeLists.txt)
  if(VDB_MSVC_RUNTIME_SELECTION)
    set_target_properties(${EXAMPLE_NAME} PROPERTIES
      MSVC_RUNTIME_LIBRARY ${VDB_MSVC_RUNTIME_SELECTION})
  endif()

  target_include_directories(${EXAMPLE_NAME} PUBLIC ex_util)
  target_link_libraries(${EXAMPLE_NAME} PRIVATE nanovdb)

  install(TARGETS ${EXAMPLE_NAME} DESTINATION ${NANOVDB_INSTALL_DOCDIR}/examples)
endfunction()

# -----------------------------------------------------------------------

#if(NANOVDB_BUILD_BENCHMARK)
#  add_subdirectory(benchmark)
#endif()

nanovdb_example(NAME "ex_make_custom_nanovdb")
nanovdb_example(NAME "ex_make_custom_nanovdb_cuda")
nanovdb_example(NAME "ex_make_funny_nanovdb")
nanovdb_example(NAME "ex_make_typed_grids")
nanovdb_example(NAME "ex_make_nanovdb_sphere")
nanovdb_example(NAME "ex_write_nanovdb_grids")
nanovdb_example(NAME "ex_openvdb_to_nanovdb" OPENVDB)
nanovdb_example(NAME "ex_openvdb_to_nanovdb_accessor" OPENVDB)
nanovdb_example(NAME "ex_openvdb_to_nanovdb_cuda" OPENVDB)
nanovdb_example(NAME "ex_read_nanovdb_sphere")
nanovdb_example(NAME "ex_read_nanovdb_sphere_accessor")
nanovdb_example(NAME "ex_read_nanovdb_sphere_accessor_cuda")
nanovdb_example(NAME "ex_index_grid_cuda")
nanovdb_example(NAME "ex_nodemanager_cuda" OPENVDB)
nanovdb_example(NAME "ex_voxels_to_grid_cuda")
nanovdb_example(NAME "ex_voxels_to_grid_mgpu")
nanovdb_example(NAME "ex_modify_nanovdb_thrust")
nanovdb_example(NAME "ex_map_pool_buffer")
nanovdb_example(NAME "ex_bump_pool_buffer")
nanovdb_example(NAME "ex_collide_level_set")
nanovdb_example(NAME "ex_raytrace_fog_volume")
nanovdb_example(NAME "ex_raytrace_level_set")
nanovdb_example(NAME "ex_raytrace_iso_surface")
nanovdb_example(NAME "ex_dilate_nanovdb_cuda" OPENVDB)
nanovdb_example(NAME "ex_merge_nanovdb_cuda" OPENVDB)
nanovdb_example(NAME "ex_refine_nanovdb_cuda" OPENVDB)
nanovdb_example(NAME "ex_coarsen_nanovdb_cuda" OPENVDB)
nanovdb_example(NAME "ex_mesh_to_grid_cuda" OPENVDB)
nanovdb_example(NAME "ex_connected_components_cuda")
nanovdb_example(NAME "ex_mesh_to_sdf_cuda")
nanovdb_example(NAME "ex_mesh_to_sdf_fluid_cuda")
if(TARGET ex_mesh_to_sdf_fluid_cuda)
  target_compile_definitions(ex_mesh_to_sdf_fluid_cuda PRIVATE CCCL_DISABLE_CUB_UMBRELLA_HEADER_WARNING)
  add_executable(ex_mesh_to_sdf_fluid_scene_cuda ex_mesh_to_sdf_fluid_cuda/scene/scene_main.cu)
  target_link_libraries(ex_mesh_to_sdf_fluid_scene_cuda PRIVATE nanovdb)
  target_compile_definitions(ex_mesh_to_sdf_fluid_scene_cuda PRIVATE CCCL_DISABLE_CUB_UMBRELLA_HEADER_WARNING)
  add_executable(ex_mesh_to_sdf_fluid_scene_float_cuda ex_mesh_to_sdf_fluid_cuda/scene/scene_main.cu)
  target_link_libraries(ex_mesh_to_sdf_fluid_scene_float_cuda PRIVATE nanovdb)
  target_compile_definitions(ex_mesh_to_sdf_fluid_scene_float_cuda PRIVATE
    CCCL_DISABLE_CUB_UMBRELLA_HEADER_WARNING FLUID_USE_FLOAT)
  foreach(precision double float)
    add_executable(ex_mesh_to_sdf_fluid_scale_${precision}_verify ex_mesh_to_sdf_fluid_cuda/scalable/verify_scalability.cu)
    target_link_libraries(ex_mesh_to_sdf_fluid_scale_${precision}_verify PRIVATE nanovdb)
    target_compile_definitions(ex_mesh_to_sdf_fluid_scale_${precision}_verify PRIVATE CCCL_DISABLE_CUB_UMBRELLA_HEADER_WARNING)
    if(precision STREQUAL "float")
      target_compile_definitions(ex_mesh_to_sdf_fluid_scale_${precision}_verify PRIVATE FLUID_USE_FLOAT)
    endif()
  endforeach()
  add_executable(ex_mesh_to_sdf_fluid_scene_verify ex_mesh_to_sdf_fluid_cuda/scene/verify_scene.cu)
  add_executable(ex_mesh_to_sdf_fluid_affine_verify ex_mesh_to_sdf_fluid_cuda/scene/verify_affine_limiter.cu)
  target_link_libraries(ex_mesh_to_sdf_fluid_affine_verify PRIVATE nanovdb)
  target_compile_definitions(ex_mesh_to_sdf_fluid_affine_verify PRIVATE CCCL_DISABLE_CUB_UMBRELLA_HEADER_WARNING)

  add_executable(ex_mesh_to_sdf_fluid_water_verify ex_mesh_to_sdf_fluid_cuda/scene/verify_water.cu)
  add_executable(ex_mesh_to_sdf_fluid_contact_escape_verify ex_mesh_to_sdf_fluid_cuda/scene/verify_contact_escape.cu)
  target_link_libraries(ex_mesh_to_sdf_fluid_contact_escape_verify PRIVATE nanovdb)
  target_compile_definitions(ex_mesh_to_sdf_fluid_contact_escape_verify PRIVATE FLUID_USE_FLOAT CCCL_DISABLE_CUB_UMBRELLA_HEADER_WARNING)
  target_link_libraries(ex_mesh_to_sdf_fluid_water_verify PRIVATE nanovdb)
  target_compile_definitions(ex_mesh_to_sdf_fluid_water_verify PRIVATE CCCL_DISABLE_CUB_UMBRELLA_HEADER_WARNING)
  target_link_libraries(ex_mesh_to_sdf_fluid_scene_verify PRIVATE nanovdb)
  target_compile_definitions(ex_mesh_to_sdf_fluid_scene_verify PRIVATE CCCL_DISABLE_CUB_UMBRELLA_HEADER_WARNING)


endif()
if(TARGET openvdb AND NANOVDB_USE_OPENVDB)
  add_executable(ex_mesh_to_sdf_fluid_surface_inspect ex_mesh_to_sdf_fluid_cuda/scene/inspect_surface.cc)
  target_link_libraries(ex_mesh_to_sdf_fluid_surface_inspect PRIVATE nanovdb)
  add_executable(ex_mesh_to_sdf_fluid_surface ex_mesh_to_sdf_fluid_cuda/scene/mesh_surface.cc)
  target_link_libraries(ex_mesh_to_sdf_fluid_surface PRIVATE openvdb nanovdb)
endif()
nanovdb_example(NAME "propagate_sign_test")
nanovdb_example(NAME "ex_shrink_wrap" OPENVDB)

if(CUDAToolkit_FOUND)
  nanovdb_example(NAME "ex_make_mgpu_nanovdb") # requires cuRAND
  target_link_libraries(ex_make_mgpu_nanovdb PRIVATE CUDA::curand)
endif()

if(NANOVDB_USE_MAGICAVOXEL)
  nanovdb_example(NAME "ex_vox_to_nanovdb")
endif()
# add_subdirectory(ex_sph_benchmark)

# many of the sample projects depend on a data directory. This allows Debug
# launching from the cmake binary working directory.
file(MAKE_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/data")
