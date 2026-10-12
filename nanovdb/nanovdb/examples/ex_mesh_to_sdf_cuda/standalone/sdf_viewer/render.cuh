// SPDX-License-Identifier: Apache-2.0
#pragma once
#include "renderer.h"
#include "field.cuh"
#include <nanovdb/math/Ray.h>
#include <nanovdb/math/HDDA.h>

using Ray = nanovdb::math::Ray<float>;
__device__ inline Vec unit(Vec v) { return v / fmaxf(v.length(), 1.e-20f); }
__device__ inline float clamp01(float v) { return fminf(1.f, fmaxf(0.f, v)); }
__device__ inline Vec vec(const float* p) { return Vec(p[0], p[1], p[2]); }
__device__ inline Coord floorCoord(Vec p) { return Coord(int(floorf(p[0])), int(floorf(p[1])), int(floorf(p[2]))); }

__device__ inline bool clipBox(Vec o, Vec d, Vec lo, Vec hi, float& nearT, float& farT) {
    nearT = 0; farT = 1.e30f;
    for (int a = 0; a < 3; ++a) {
        if (fabsf(d[a]) < 1.e-20f) {
            if (o[a] < lo[a] || o[a] > hi[a]) return false;
        } else {
            float t0 = (lo[a] - o[a]) / d[a], t1 = (hi[a] - o[a]) / d[a];
            nearT = fmaxf(nearT, fminf(t0, t1));
            farT = fminf(farT, fmaxf(t0, t1));
        }
    }
    return nearT < farT;
}

template<typename Sampler>
__device__ Vec gradient(const Sampler& sample, Vec p) {
    const Vec x(.5f, 0, 0), y(0, .5f, 0), z(0, 0, .5f);
    return Vec(sample(p+x)-sample(p-x), sample(p+y)-sample(p-y), sample(p+z)-sample(p-z));
}

template<typename BuildT, typename Sampler>
__device__ Vec shade(const nanovdb::NanoGrid<BuildT>& grid, const Sampler& sample,
                     Vec p, Vec view, const RenderSettings& s, float dx) {
    Vec n = unit(grid.indexToWorldGradF(gradient(sample, p)));
    if (s.mode == 2) return (n + Vec(1.f)) * .5f;
    if (n.dot(view) < 0) n = -n;
    const Vec light = unit(view + Vec(-.6f, .9f, .35f));
    float diffuse = fmaxf(0.f, n.dot(light));
    float specular = powf(fmaxf(0.f, n.dot(unit(light+view))), 64.f) * .22f;
    float occlusion = 0.f;
    if (s.ao > 0 && s.mode != 1) {
        const Vec ni = unit(grid.worldToIndexDirF(n));
        for (int i = 1; i <= 4; ++i) {
            float distance = float(1 << i);
            float sdf = (sample(p + ni*distance) - s.iso*dx) / dx;
            occlusion += fmaxf(0.f, distance-sdf) / distance * .16f;
        }
    }
    float ambient = .25f + .15f * clamp01(n[1] * .5f + .5f);
    float rim = .12f * powf(1.f - fmaxf(0.f,n.dot(view)), 3.f);
    float strength = (ambient + diffuse*.6f) * (1.f-clamp01(occlusion*s.ao));
    return vec(s.color)*strength + Vec(specular+rim);
}

struct Pixel { Vec rgb{0.f}; float alpha = 0.f; };

// Each active sample is a unit cube centered at its integer index coordinate.
// Shift the traversal ray by +0.5 so HDDA's integer cell boundaries match cubes.
// This is an exact topology traversal, with no SDF interpolation or iso threshold.
template<typename BuildT>
__device__ Pixel traceVoxels(const nanovdb::NanoGrid<BuildT>& grid, Field<BuildT>& field,
                            Vec o, Vec d, Vec worldDirection, const RenderSettings& s, int* exhausted) {
    Pixel result;
    Vec lo(grid.indexBBox().min()), hi=Vec(grid.indexBBox().max())+Vec(1.f);
    if(s.clipAxis>=0) hi[s.clipAxis]=fminf(hi[s.clipAxis],s.clipPosition+.5f);
    if(hi[0]<=lo[0] || hi[1]<=lo[1] || hi[2]<=lo[2]) return result;
    float t0,t1;
    o+=Vec(.5f);
    if(!clipBox(o,d,lo,hi,t0,t1)) return result;
    Ray ray(o,d,t0,t1);
    auto dimAt=[&](Coord p) { const int n=int(field.acc.getDim(p,ray)); return n==0?4096:n; };
    nanovdb::math::HDDA<Ray> hdda(ray,dimAt(floorCoord(ray.start())));
    int visits=0;
    do {
        if(++visits>2000000) { atomicExch(exhausted,1); return result; }
        hdda.update(ray,dimAt(hdda.voxel()));
        const Coord cell=hdda.voxel();
        if(hdda.dim()!=1 || hdda.next()<=hdda.time() || !field.acc.isActive(cell)) continue;
        const Vec local=ray(hdda.time())-Vec(cell)-Vec(.5f);
        int axis=0;
        if(fabsf(local[1])>fabsf(local[axis])) axis=1;
        if(fabsf(local[2])>fabsf(local[axis])) axis=2;
        if(s.clipAxis>=0 && fabsf(ray(hdda.time())[s.clipAxis]-.5f-s.clipPosition)<1.e-3f)
            axis=s.clipAxis;
        Vec n(0.f);n[axis]=d[axis]>0?-1.f:1.f;
        n=unit(grid.indexToWorldGradF(n));
        float edge=1.f;
        for(int a=0;a<3;++a) if(a!=axis && fabsf(local[a])>.465f) edge=.58f;
        const Vec color=signbit(field.getValue(cell))?Vec(.85f,.15f,.045f):Vec(.04f,.32f,.8f);
        result.rgb=color*((.38f+.62f*fabsf(n.dot(worldDirection)))*edge);
        result.alpha=1.f;
        return result;
    } while(hdda.step());
    return result;
}

template<typename BuildT>
__device__ Pixel trace(const nanovdb::NanoGrid<BuildT>& grid, Channels channels,
                      Vec origin, Vec direction, const RenderSettings& s, int* exhausted) {
    Field<BuildT> field(grid, channels);
    const auto sample = nanovdb::math::createSampler<1>(field);
    const float dx = float(grid.voxelSize()[0]);
    const Vec o = grid.worldToIndexF(origin), d = unit(grid.worldToIndexDirF(direction));
    Vec lo = Vec(grid.indexBBox().min()) - Vec(1.f);
    Vec hi = Vec(grid.indexBBox().max()) + Vec(1.f);
    Pixel result;
    if (s.mode == 4) return traceVoxels(grid,field,o,d,direction,s,exhausted);
    if (s.mode == 3 || s.mode == 5) {
        const int axis = s.clipAxis < 0 ? 2 : s.clipAxis;
        if (fabsf(d[axis]) < 1.e-12f) return result;
        float t = (s.clipPosition-o[axis])/d[axis];
        Vec p = o + d*t;
        if (t < 0 || p[0]<lo[0] || p[1]<lo[1] || p[2]<lo[2] || p[0]>hi[0] || p[1]>hi[1] || p[2]>hi[2]) return result;
        // Nearest voxel preserves the stored sign, without interpolation hiding errors.
        Coord c = floorCoord(p+Vec(.5f));
        if (s.mode == 5 && !field.acc.isActive(c)) return result;
        float v = field.getValue(c);
        Vec color = signbit(v) ? Vec(.85f,.15f,.045f) : Vec(.04f,.32f,.8f);
        float band = s.mode == 5 ? 0.f : expf(-fabsf(v)/dx);
        result.rgb = color*(1.f-.65f*band)+Vec(.9f)*(.65f*band);
        result.alpha = 1.f;
        return result;
    }
    if (s.clipAxis >= 0) hi[s.clipAxis] = fminf(hi[s.clipAxis],s.clipPosition);
    if (hi[0]<=lo[0] || hi[1]<=lo[1] || hi[2]<=lo[2]) return result;
    float nearT, farT;
    if (!clipBox(o,d,lo,hi,nearT,farT)) return result;
    Ray ray(o,d,nearT,farT);
    // Leaf-level HDDA, with larger steps through missing lower/upper/root nodes.
    auto dimAt = [&](Coord p) { int n = int(field.acc.getDim(p,ray)); return n == 0 ? 4096 : (n < 8 ? 8 : n); };
    nanovdb::math::HDDA<Ray> hdda(ray, dimAt(floorCoord(ray.start())));
    float processed = nearT;
    const float iso = s.iso*dx;
    int iterations = 0;
    do {
        if (++iterations > 2000000) { atomicExch(exhausted,1); return result; }
        const Coord cell = hdda.voxel();
        hdda.update(ray,dimAt(cell));
        if (!field.acc.probeLeaf(cell)) continue;
        // Trilinear support extends outside the leaf. Overlap the intervals and
        // integrate each ray segment once so empty-space skipping cannot cut a seam.
        float a = fmaxf(processed,fmaxf(nearT,hdda.time()-1.75f));
        const float end = fminf(farT,hdda.next()+1.75f);
        if (end <= a) continue;
        float va = sample(ray(a))-iso;
        while (a < end) {
            if (++iterations > 2000000) { atomicExch(exhausted,1); return result; }
            const float b = fminf(end,a+s.step);
            if (b <= a) { atomicExch(exhausted,1); return result; }
            const float vb = sample(ray(b))-iso;
            if (s.mode != 1) {
                if ((va < 0.f) != (vb < 0.f) || va == 0.f || vb == 0.f) {
                    float left = a, right = b, vl = va;
                    for (int i=0; i<9; ++i) {
                        float middle=(left+right)*.5f, vm=sample(ray(middle))-iso;
                        if ((vl<0.f)==(vm<0.f)) { left=middle; vl=vm; } else right=middle;
                    }
                    float hit = va == 0.f ? a : (vb == 0.f ? b : (left+right)*.5f);
                    result.rgb = shade(grid,sample,ray(hit),-direction,s,dx);
                    result.alpha = 1.f;
                    return result;
                }
            } else {
                Vec p = ray((a+b)*.5f);
                float distance = fabsf(sample(p)-iso)/dx;
                // Compact shell avoids turning the truncated SDF background into fog.
                float density = fmaxf(0.f,1.f-distance/s.shell);
                float alpha = -expm1f(-s.density*density*(b-a));
                if (alpha > .00001f) {
                    Vec color = shade(grid,sample,p,-direction,s,dx);
                    result.rgb += color*((1.f-result.alpha)*alpha);
                    result.alpha += (1.f-result.alpha)*alpha;
                    if (result.alpha > .9995f) return result;
                }
            }
            a=b; va=vb;
        }
        processed = end;
    } while(hdda.step());
    return result;
}

__device__ inline float radicalInverse(uint32_t n, uint32_t base) {
    float value=0, weight=1.f/float(base);
    while(n) { value+=float(n%base)*weight; n/=base; weight/=float(base); }
    return value;
}
__device__ inline float linearToSrgb(float x) {
    x=clamp01(x);
    return x <= .0031308f ? 12.92f*x : 1.055f*powf(x,1.f/2.4f)-.055f;
}

template<typename BuildT>
__global__ void renderKernel(const nanovdb::NanoGrid<BuildT>* grid, Channels channels,
                             RenderSettings s, int width, int height, int tileX, int tileY,
                             int tileWidth, int tileHeight, int samples, uchar4* out, int* exhausted) {
    const int id=int(blockIdx.x*blockDim.x+threadIdx.x);
    if (id>=tileWidth*tileHeight) return;
    const int x=tileX+id%tileWidth, y=tileY+id/tileWidth;
    Vec eye=vec(s.eye), forward=unit(vec(s.target)-eye);
    Vec right=unit(forward.cross(vec(s.up))), up=right.cross(forward);
    float perspectiveScale=tanf(s.fov*.00872664626f);
    Vec color(0.f); float alpha=0;
    for(int k=0;k<samples;++k) {
        float jx=samples==1?.5f:radicalInverse(k+1,2);
        float jy=samples==1?.5f:radicalInverse(k+1,3);
        float u=(2.f*(x+jx)/width-1.f)*float(width)/height;
        float v=1.f-2.f*(y+jy)/height;
        Vec origin=eye, direction;
        if(s.orthographic) { origin+=(right*u+up*v)*(s.orthoScale*.5f); direction=forward; }
        else direction=unit(forward+(right*u+up*v)*perspectiveScale);
        Pixel hit=trace(*grid,channels,origin,direction,s,exhausted);
        color+=hit.rgb; alpha+=hit.alpha;
    }
    color/=float(samples); alpha/=float(samples);
    if(s.transparent) { if(alpha>0) color/=alpha; }
    else { color+=vec(s.background)*(1.f-alpha); alpha=1.f; }
    color*=exp2f(s.exposure);
    out[id]=make_uchar4(uint8_t(255.f*linearToSrgb(color[0])+.5f),
                       uint8_t(255.f*linearToSrgb(color[1])+.5f),
                       uint8_t(255.f*linearToSrgb(color[2])+.5f),uint8_t(255.f*clamp01(alpha)+.5f));
}
