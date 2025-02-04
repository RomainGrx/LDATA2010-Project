import random
import math
import numpy as np
import numpy_indexed as npi
import pandas as pd
import networkx as nx
from bokeh.models import Range1d
from functools import partial
from abc import ABC, abstractclassmethod
from threading import Thread
from multiprocessing import Process

from .settings import CACHE, LOGGER
from .graphs import EdgesHelper, NodesHelper, GraphHelper
from .utils import AttrDict, resize, timestep_cache, dummy_timelog
from .algorithms import louvain_partition, katz_centrality
from .layout_algorithms import community_layout

from fa2 import ForceAtlas2

def random_layout(G:nx.Graph):
    return dict(zip(G, np.random.random((len(G.nodes), 2))))


class Layout:
    def __name__(self):
        return self.__class__.__name__


class SpringLayout(Layout):
    def __call__(self, G):
        k = math.sqrt(len(G.nodes))
        W = GraphHelper.multigraph_to_weighted_graph(G)
        return nx.drawing.layout.spring_layout(W, k=k)

class ForceLayoutGPU(Layout):
    def __init__(self):
        pass
    
    def __call__(self, G):
        pass

class ForceLayout(Layout):
    def __init__(self):
        self.fa2 = ForceAtlas2(
                          # Behavior alternatives
                          outboundAttractionDistribution=True,  # Dissuade hubs
                          linLogMode=False,  # NOT IMPLEMENTED
                          adjustSizes=False,  # Prevent overlap (NOT IMPLEMENTED)
                          edgeWeightInfluence=2.0,

                          # Performance
                          jitterTolerance=1.0,  # Tolerance
                          barnesHutOptimize=True,
                          barnesHutTheta=1.4,
                          multiThreaded=False,  # NOT IMPLEMENTED

                          # Tuning
                          scalingRatio=1.0,
                          strongGravityMode=True,
                          gravity=.5,

                          # Log
                          verbose=True)
    
    
    def __call__(self, G):
        layout = self.fa2.forceatlas2_networkx_layout(G, pos=None, iterations=200)
        return layout

class LouvainLayout(Layout):
    def __init__(self):
        pass
    def __call__(self, G):
        node_clusters = louvain_partition(G, as_dict=True)
        pos = community_layout(G, node_clusters)
        return pos

class KatzCentralityLayout(Layout):
    def __call__(self, G):
        nodes_centrality = katz_centrality(G, as_dict=True)
        pos = community_layout(G, nodes_centrality)
        return pos

#class SpectralClustering(Layout):
#    def __call__(self, G):
#        nodes_spectral_clusters = spectral_cluster(G, as_dict=True)
#        pos = community_layout(G, nodes_spectral_clusters)
#        return pos

class Kmeans(Layout):
    def __init__(self):
        raise Exception("Not implemented yet")
    def __call__(self, G):
        raise Exception("Not implemented yet")




# ----------------------------------------------------------------------------------------------------
# ----------------------------------------------------------------------------------------------------

def update_edges(G, nodes, x, y):
    # TODO : update edges coords  

    #x = CACHE.plot.nodes.source.data["x"]
    #y = CACHE.plot.nodes.source.data["y"]

    #[u, v, count] = EdgesHelper.count_attribute(CACHE.graph, "timestep", leq=CACHE.plot.timestep, sort=True)
    [u, v, c] = np.array(G.edges).T
    [u, v] = np.unique(np.c_[u, v], axis=0).T

    u_idx = npi.indices(nodes, u)
    v_idx = npi.indices(nodes, v)

    y0, y1 = y[u_idx], y[v_idx]
    x0, x1 = x[u_idx], x[v_idx]
    xs = np.c_[x0, x1]
    ys = np.c_[y0, y1]


    return xs, ys, x0, x1, y0, y1


def apply_on_edges(xs, ys, x0, x1, y0, y1):
    CACHE.plot.nodes.source.data["xs"] = xs
    CACHE.plot.nodes.source.data["ys"] = ys
    CACHE.plot.nodes.source.data["x0"] = x0
    CACHE.plot.nodes.source.data["x1"] = x1
    CACHE.plot.nodes.source.data["y0"] = y0
    CACHE.plot.nodes.source.data["y1"] = y1

def apply_on_nodes(xs, ys):
    CACHE.plot.network.edges.source.data["xs"] = xs
    CACHE.plot.network.edges.source.data["ys"] = ys

def resize_x_y_fig(x=None, y=None):
    if "p" not in CACHE.plot:
        return
    if x is None or y is None:
        x = CACHE.plot.nodes.source.data["x"]
        y = CACHE.plot.nodes.source.data["y"]
    p = CACHE.plot.p

    sizes = CACHE.plot.nodes.source.data.get("size", None)

    x_range = resize(x, sizes, alpha=1.5)
    y_range = resize(y, sizes, alpha=1.5)

    [CACHE.plot.p.x_range.start, CACHE.plot.p.x_range.end] = x_range
    [p.y_range.start, p.y_range.end] = y_range

    #CACHE.plot.p.x_range = Range1d(*x_range)
    #p.y_range = Range1d(*y_range)

    #p.x_range = Range1d(x_range[0], x_range[1])
    #p.y_range = Range1d(y_range[0], y_range[1])

    LOGGER.info(f"Resized network graph :: x_range {x_range} :: y_range {y_range}")

def apply_on_graph(G, update=False):
    # TODO : a thread to apply a continuous update?  (force layout); if so, share an updater thread in the cache
    #G = GraphHelper.subgraph_from_timestep(CACHE.graph, CACHE.plot.timestep)

    # Try getting it from the cache
    #if CACHE.layout.__name__ in CACHE.plot.layouts:
    if False:
        computed_layout = CACHE.plot.layouts[CACHE.layout.__name__]
        x, y = computed_layout.x, computed_layout.y
        xs, ys = computed_layout.xs, computed_layout.ys
    else: # Compute the new layout
        with dummy_timelog("get pos from layout"):
            pos = CACHE.layout(G)
        # TODO : Speedup this shit (no sorting?)
        #sorted_pos = sorted(pos.items(), key=lambda x:x[0])
        nodes, pos = list(zip(*pos.items()))
        pos = np.array(pos); nodes = np.array(nodes)

        [x, y] = pos.T # shape (2, V)
        with dummy_timelog("update edges"):
            xs, ys, x0, x1, y0, y1 = update_edges(G, nodes, x, y)

        # Save the computed layout in the cache in order to compute only once
        xs, ys, x0, x1, y0, y1 = list(xs), list(ys), list(x0), list(x1), list(y0), list(y1)
        timestep_cache().layouts[CACHE.layout.__name__] = AttrDict(
            x=x,
            y=y,
            xs=xs,
            ys=ys,
            x0=x0,
            x1=x1,
            y0=y0,
            y1=y1
        )

    if update:
         te = Thread(target=apply_on_edges, args=(xs, ys, x0, x1, y0, y1))
         te.start()
         tn = Thread(target=apply_on_nodes, args=(x, y))
         tn.start()
         if "p" in CACHE.plot:
             resize_x_y_fig(x, y)

         te.join(); tn.join()


    return AttrDict(nodes=AttrDict(x=x, y=y), edges=AttrDict(xs=xs, ys=ys, x0=x0, x1=x1, y0=y0, y1=y1, cx0=[w+.5 for w in x0]))

class Twopi(Layout):
    def __call__(self, G):
        return nx.drawing.nx_agraph.graphviz_layout(G, prog="twopi")

AVAILABLE = dict(
    # Simple layouts
    simple_layouts=None,

    random=random_layout,
    circular=nx.circular_layout,
    twopi=Twopi(),

    networkx_layouts=None,

    # Networkx layouts
    spectral=nx.drawing.layout.spectral_layout,

    # Force layouts
    force_layouts=None,
    spring=SpringLayout(),
    forceatlas2=ForceLayout(),
    #fruchterman_reingold=nx.layout.fruchterman_reingold_layout,
    #kamada_kawai=nx.layout.kamada_kawai_layout,

    # Cluster layouts
    cluster_layouts=None,
    louvain=LouvainLayout(),
    katz_centrality=KatzCentralityLayout(),
    #kmeans=Kmeans(),

    # Experimental
    exp=None,
)

def get(key:str):
    return AVAILABLE.get(key, None)

def get_random():
    fct = None
    while fct is None:
        fct = random.choice(list(AVAILABLE.values()))
    return fct
