// SPDX-License-Identifier: Apache-2.0
// CPU double-precision triangle/BVH oracle, independent of MeshToSDF signing.
#pragma once
#include <algorithm>
#include <array>
#include <cmath>
#include <fstream>
#include <map>
#include <numeric>
#include <sstream>
#include <stdexcept>
#include <vector>

namespace mesh_oracle {
struct V {
    double x[3]{};
    double& operator[](int a) {return x[a];}
    double operator[](int a) const {return x[a];}
};
inline V operator+(V a,V b) {return {{a[0]+b[0],a[1]+b[1],a[2]+b[2]}};}
inline V operator-(V a,V b) {return {{a[0]-b[0],a[1]-b[1],a[2]-b[2]}};}
inline V operator*(V a,double s) {return {{a[0]*s,a[1]*s,a[2]*s}};}
inline double dot(V a,V b) {return a[0]*b[0]+a[1]*b[1]+a[2]*b[2];}
inline V cross(V a,V b) {return {{a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]}};}
struct Box {
    V lo{{1e300,1e300,1e300}},hi{{-1e300,-1e300,-1e300}};
    void add(V p) {for(int a=0;a<3;++a) {lo[a]=std::min(lo[a],p[a]);hi[a]=std::max(hi[a],p[a]);}}
    bool overlap(V c,double r) const {for(int a=0;a<3;++a) if(lo[a]>c[a]+r || hi[a]<c[a]-r)return false;return true;}
    bool ray(V p,V d) const {
        double loT=0,hiT=1e300;
        for(int a=0;a<3;++a) {double u=(lo[a]-p[a])/d[a],v=(hi[a]-p[a])/d[a];if(u>v)std::swap(u,v);loT=std::max(loT,u);hiT=std::min(hiT,v);}
        return hiT>=loT;
    }
};
struct Mesh {
    struct Node {Box b;int begin,end,left=-1,right=-1;};
    std::vector<V> vertices;std::vector<std::array<int,3>> faces;
    std::vector<int> order;std::vector<Node> nodes;Box bounds;double area=0,volume=0;
    explicit Mesh(const char* path) {
        std::ifstream file(path);if(!file)throw std::runtime_error("Cannot open mesh");
        std::string line;
        while(std::getline(file,line)) {
            std::istringstream s(line);std::string tag;s>>tag;
            if(tag=="v") {V p;if(!(s>>p[0]>>p[1]>>p[2]))throw std::runtime_error("Invalid vertex");vertices.push_back(p);bounds.add(p);}
            if(tag=="f") {std::vector<int> f;std::string token;while(s>>token) {
                if(token[0]=='#')break;
                int i=std::stoi(token.substr(0,token.find('/')));i=i>0?i-1:int(vertices.size())+i;
                if(i<0 || i>=int(vertices.size()))throw std::runtime_error("Invalid face index");f.push_back(i);
            }for(size_t i=2;i<f.size();++i)faces.push_back({f[0],f[i-1],f[i]});}
        }
        if(faces.empty())throw std::runtime_error("No mesh triangles");
        std::map<std::pair<int,int>,std::pair<int,int>> edges;
        V center=(bounds.lo+bounds.hi)*.5;
        for(auto f:faces) {
            V a=vertices[f[0]],b=vertices[f[1]],c=vertices[f[2]],n=cross(b-a,c-a);
            double ar=std::sqrt(dot(n,n))/2;if(ar<=0)throw std::runtime_error("Degenerate triangle");area+=ar;volume+=dot(a-center,n)/6;
            for(int i=0;i<3;++i) {int a=f[i],b=f[(i+1)%3];auto& e=edges[std::minmax(a,b)];++e.first;e.second+=a<b?1:-1;}
        }
        for(auto e:edges)if(e.second.first!=2 || e.second.second!=0)throw std::runtime_error("Mesh needs closed, consistently oriented edges");
        order.resize(faces.size());std::iota(order.begin(),order.end(),0);build(0,int(order.size()));
    }
    int build(int begin,int end) {
        Node n;n.begin=begin;n.end=end;
        for(int k=begin;k<end;++k)for(int v:faces[order[k]])n.b.add(vertices[v]);
        int id=int(nodes.size());nodes.push_back(n);
        if(end-begin>8) {
            int axis=0;for(int a=1;a<3;++a)if(n.b.hi[a]-n.b.lo[a]>n.b.hi[axis]-n.b.lo[axis])axis=a;
            int mid=(begin+end)/2;
            auto center=[&](int f) {auto t=faces[f];return vertices[t[0]][axis]+vertices[t[1]][axis]+vertices[t[2]][axis];};
            std::nth_element(order.begin()+begin,order.begin()+mid,order.begin()+end,[&](int a,int b){return center(a)<center(b);});
            int l=build(begin,mid),r=build(mid,end);nodes[id].left=l;nodes[id].right=r;
        }return id;
    }
    bool triBox(int f,V center,double r) const {
        auto t=faces[f];V p[3]={vertices[t[0]]-center,vertices[t[1]]-center,vertices[t[2]]-center};
        auto separated=[&](V axis) {
            double a=dot(axis,p[0]),b=dot(axis,p[1]),c=dot(axis,p[2]);
            double radius=r*(std::abs(axis[0])+std::abs(axis[1])+std::abs(axis[2]));
            return std::min({a,b,c})>radius || std::max({a,b,c})<-radius;
        };
        const V axes[3]={{{1,0,0}},{{0,1,0}},{{0,0,1}}};
        for(auto a:axes)if(separated(a))return false;
        V e[3]={p[1]-p[0],p[2]-p[1],p[0]-p[2]};
        if(separated(cross(e[0],e[1])))return false;
        for(auto a:axes)for(auto edge:e)if(separated(cross(a,edge)))return false;
        return true;
    }
    bool surface(V c,double r,int id=0) const {
        const auto& n=nodes[id];if(!n.b.overlap(c,r))return false;
        if(n.left>=0)return surface(c,r,n.left)||surface(c,r,n.right);
        for(int k=n.begin;k<n.end;++k)if(triBox(order[k],c,r))return true;return false;
    }
    int intersections(V p,V d,int id=0) const {
        const auto& n=nodes[id];if(!n.b.ray(p,d))return 0;
        if(n.left>=0)return intersections(p,d,n.left)+intersections(p,d,n.right);
        int count=0;
        for(int k=n.begin;k<n.end;++k) {
            auto f=faces[order[k]];V a=vertices[f[0]],e=vertices[f[1]]-a,h=cross(d,vertices[f[2]]-a);
            double det=dot(e,h);if(std::abs(det)<1e-18)continue;
            V q=p-a;double u=dot(q,h)/det;if(u<0||u>1)continue;
            V t=cross(q,e);double v=dot(d,t)/det;if(v<0||u+v>1)continue;
            if(dot(vertices[f[2]]-a,t)/det>1e-12)++count;
        }return count;
    }
    bool inside(V p) const {return intersections(p,V{{1,.371390676354104,.694182942453127}})%2!=0;}
    // Independent solid-angle confirmation for final root centers.
    double winding(V p) const {
        double sum=0;
        for(auto f:faces) {
            V a=vertices[f[0]]-p,b=vertices[f[1]]-p,c=vertices[f[2]]-p;
            double la=std::sqrt(dot(a,a)),lb=std::sqrt(dot(b,b)),lc=std::sqrt(dot(c,c));
            sum+=2*std::atan2(dot(a,cross(b,c)),la*lb*lc+dot(a,b)*lc+dot(b,c)*la+dot(c,a)*lb);
        }return sum/(4*std::acos(-1.));
    }
    double radius(V c) const {
        if(!inside(c))return 0;
        double lo=0,hi=1e300;
        for(int a=0;a<3;++a)hi=std::min({hi,c[a]-bounds.lo[a],bounds.hi[a]-c[a]});
        for(int i=0;i<25;++i) {double mid=(lo+hi)/2;if(surface(c,mid))hi=mid;else lo=mid;}
        return lo;
    }
    std::pair<double,V> findCube() const {
        std::vector<std::pair<double,V>> seeds;
        for(int i=1;i<8;++i)for(int j=1;j<8;++j)for(int k=1;k<8;++k) {
            V p;int a[3]={i,j,k};for(int d=0;d<3;++d)p[d]=bounds.lo[d]+(bounds.hi[d]-bounds.lo[d])*a[d]/8;
            seeds.push_back({radius(p),p});
        }
        std::sort(seeds.begin(),seeds.end(),[](auto a,auto b){return a.first>b.first;});
        double step=0;for(int a=0;a<3;++a)step=std::max(step,(bounds.hi[a]-bounds.lo[a])/8);
        std::pair<double,V> best=seeds.front();
        for(int s=0;s<8;++s) {
            auto current=seeds[s];
            for(double h=step;h>step/4096;h*=.5) {
                for(int iteration=0;iteration<20;++iteration) {
                    auto next=current;
                    for(int axis=0;axis<3;++axis)for(int sign:{-1,1}) {
                        V p=current.second;p[axis]+=h*sign;double r=radius(p);if(r>next.first)next={r,p};
                    }
                    if(next.first<=current.first)break;current=next;
                }
            }if(current.first>best.first)best=current;
        }return best;
    }
};
}
