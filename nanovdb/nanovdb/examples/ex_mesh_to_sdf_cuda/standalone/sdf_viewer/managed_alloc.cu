// SPDX-License-Identifier: Apache-2.0
// Link-time allocation adapter for the optional oversubscribed validation driver.
// No NanoVDB source changes: GNU ld wraps runtime calls from the existing driver.
#include <cuda_runtime.h>
#include <cstdio>
#include <mutex>
#include <unordered_map>
namespace {
std::mutex mutex;
std::unordered_map<void*,size_t> sizes;
size_t live=0,peak=0;
cudaError_t allocate(void** pointer,size_t bytes) {
    cudaError_t error=cudaMallocManaged(pointer,bytes,cudaMemAttachGlobal);
    if(error==cudaSuccess) {
        std::lock_guard<std::mutex> lock(mutex);sizes[*pointer]=bytes;live+=bytes;
        if(live>peak) {peak=live;if(peak>size_t(8)<<30)std::fprintf(stderr,"Managed live allocation high water: %.2f GiB\n",double(peak)/(1ull<<30));}
    }return error;
}
void forget(void* p) {std::lock_guard<std::mutex> lock(mutex);auto it=sizes.find(p);if(it!=sizes.end()) {live-=it->second;sizes.erase(it);}}
}
extern "C" cudaError_t __wrap_cudaMalloc(void** p,size_t bytes) {return allocate(p,bytes);}
extern "C" cudaError_t __wrap_cudaMallocAsync(void** p,size_t bytes,cudaStream_t) {return allocate(p,bytes);}
extern "C" cudaError_t __real_cudaFree(void*);
extern "C" cudaError_t __wrap_cudaFree(void* p) {cudaError_t e=__real_cudaFree(p);if(e==cudaSuccess)forget(p);return e;}
extern "C" cudaError_t __wrap_cudaFreeAsync(void* p,cudaStream_t stream) {
    cudaError_t e=cudaStreamSynchronize(stream);if(e!=cudaSuccess)return e;
    return __wrap_cudaFree(p);
}
