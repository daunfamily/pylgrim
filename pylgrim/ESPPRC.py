# Solve Elementary Shortest Path Problem with resource constraints.
# The algorithm is based on [1].
# Features:
#   * single source / single target
#   * with resources
#   * elementary paths are sought by intelligently adding node resources to nodes that have been found to be in a NCC (negative cost cycle).
#
# Author:
#   Toon Weyens
#
# References: 
#   [1]: "Accelerated label setting algorithms for the elementary resource constrained shortest path problem" by Boland, Natashia (DOI: 10.1016/j.orl.2004.11.011)
import networkx as nx
import numpy as np
import logging
from . import path_tools as pt

# logging
log_lvl = ''
#log_lvl = 'INFO'
#log_lvl = 'DEBUG'
if log_lvl == 'DEBUG' or log_lvl == 'INFO':
    logging.basicConfig(format='%(asctime)s %(message)s',
        datefmt='%d/%m/%Y %H:%M:%S',
        filename='ESPPRC.log',
        filemode='w',
        level=log_lvl)

# global variables
resource_treated = 0

# preprocess graph
# (based on algorithm 2.1, step 0, from [1])
#   1. Reducing the number of nodes and arcs in the graph by considering least resource paths from the path start node to each node in the graph and from each node in the graph to the path destination node, for each resource.
#   2. Solve the all-pairs shortest path problem on the graph, with lengths set to wr , for each resource r.
# Note: In this first, quick implementation all possible edges between nodes that are reachable are used in the new network.
# The actual number of feasible edges is only a subset of this. The system used here, therefore, is not minimal.
def preprocess_ESPPRC(G, source, target, max_res):
    global resource_treated
    
    logging.info('Pre-process graph')
    logging.info('')
    
    # to start with, all nodes are assumed to be reachable
    reachable_nodes = set(G.nodes())
    n_res = G.graph['n_res']
    
    # iterate over all resources and delete nodes that are not reachable
    logging.info('  delete unreachable nodes')
    for res in range(0,n_res):
        logging.info('    treating resource {}'.format(res))
        resource_treated = res
        
        logging.debug('      Calculate feasible paths from source')
        lengths = set(nx.single_source_dijkstra_path_length(G, source, cutoff=max_res[res], weight = _res_cost_i))
        reachable_nodes = reachable_nodes.intersection(lengths)
        if source not in reachable_nodes:
            reachable_nodes.append(source)
        
        logging.debug('      Calculate feasible paths to target')
        lengths = set(nx.single_source_dijkstra_path_length(G.reverse(copy=True), target, cutoff=max_res[res], weight = _res_cost_i))
        reachable_nodes = reachable_nodes.intersection(lengths)
        if target not in reachable_nodes:
            reachable_nodes.append(target)
        
    logging.info('    {} reachable nodes:'.format(len(reachable_nodes)))
    logging.info('      {}'.format(reachable_nodes))
    logging.info('')
    
    # set up reduced graph
    logging.info('  Set up reduced graph')
    H = nx.DiGraph(n_res=n_res)
    for node in reachable_nodes:
        for node2 in reachable_nodes:
            if G.has_edge(node, node2) and not H.has_edge(node,node2): 
                weight_e = G.get_edge_data(node,node2)['weight']
                res_cost_e = G.get_edge_data(node,node2)['res_cost']
                H.add_edge(node, node2, weight=weight_e, res_cost=res_cost_e)
    #nx.draw_circular(H,with_labels=True)
    logging.info('')
    
    # iterate over all resources and calculate least-resource paths for all pairs
    logging.info('  Calculate least-resource pairs')
    res_min = list()
    for res in range(0,n_res):
        logging.info('    treating resource {}'.format(res))
        resource_treated = res
        res_min.append(dict(nx.all_pairs_dijkstra_path_length(H, weight=_res_cost_i)))
    
    logging.info('')
    
    # return preprocessed network and least-resource paths
    return H, res_min

# General Label Setting Algorithm
# (based on algorithm 2.1, step 1 and 2, from [1])
def GLSA(G, S, source, target, max_res, res_min):
    logging.info('  Initialize')
    logging.info('')
    
    # 1. Initialization
    inf = float('inf')
    n_res = G.graph['n_res']
    # paths for each node
    paths = {source: list()}
    paths[source].append([source])
    # labels for each path (cost, resources):
    labels = {source: list()}
    labels[source].append((0,np.zeros(n_res+len(S))))
    # labels to treat: start with 0th label of path ending at source
    L = set([(source,0)])
    
    # 2. select lexicographically minimal label
    logging.info('  Loop over labels to be extended')
    while L:
        # select lexicographically minimal label
        logging.info('    Select lexicographically minimal label:')
        LML_for_prev_res= L
        for res in range(0,n_res+len(S)):
            res_LML = inf
            LML_for_this_res = []
            for label in LML_for_prev_res:
                res_loc = labels[label[0]][label[1]][1][res]
                logging.debug('      consumption of resource {}: {}'.format(res,res_loc))
                if res_loc <= res_LML:
                    # better or equivalent label
                    res_LML = res_loc
                    LML_for_this_res.append(label)
            # set u_label to first element found
            u_label = LML_for_this_res[0]
            u = u_label[0]
            l = u_label[1]
            if len(LML_for_this_res) == 1:
                # found lexicographically minimal label
                break
            else:
                # multiple labels equivalent for this res
                LML_for_prev_res = LML_for_this_res
        L.remove(u_label)
        
        logging.debug('      {}th label of node {} chosen:'.format(l,u))
        logging.debug('        {} (C {} | R {})'.format(pt.print_path(paths[u][l]),labels[u][l][0],labels[u][l][1]))
        
        # extend label for each child
        for v, e in G.succ[u].items():
            logging.info('    treating edge {} -> {} (C {} | R {})'.format(u,v,e['weight'],e['res_cost']))
            if len(paths.get(v,[])) > 0: logging.debug('      with current paths:')
            for n in range(0,len(paths.get(v,[]))):
                logging.debug('        {} (C {} | R {})'.format(pt.print_path(paths[v][n]),labels[v][n][0],labels[v][n][1]))
            
            # error if the source is a child. The in-edges of the source need to be separated from the out-edges.
            if v == source:
                logging.critical('ERROR: source cannot be a child')
                quit()
            
            # determine whether to create a new label on the child node
            e_loc = np.zeros(n_res+len(S))
            e_loc[0:n_res] = G[u][v]['res_cost']
            if v in S:
                e_loc[n_res+S.index(v)] = 1
            v_label = (labels[u][l][0] +  G[u][v]['weight'], labels[u][l][1] +  e_loc)
            add_label = True
            
            # check edge resources
            for res in range(0,n_res):
                if v_label[1][res] + res_min[res][v].get(target,0.0) > max_res[res]:
                    add_label = False
                    logging.debug('      at least {} more of resource {} is needed to reach target'.format(res_min[res][v].get(target,0.0),res))
                    break
            
            # check node resources
            for res in range(0,len(S)):
                if v_label[1][n_res+res] > 1:
                    add_label = False
                    logging.debug('      node {} was used twice'.format(S[res]))
                    break
            
            # add
            if add_label:
                # check subset of all labels that belong to the same node for domination
                label_dominated = False
                if len(labels.get(v,[])) > 0:
                    for label in labels.get(v,[]):
                        label_dominated = _is_dominated(v_label, label)
                        if label_dominated: break
                
                if label_dominated:
                    logging.debug('      but label was dominated')
                else:
                    # setup label and path
                    if labels.get(v, None) == None:
                        paths[v] = list()
                        labels[v] = list()
                    v_path = list(paths[u][l])
                    v_path.append(v)
                    
                    logging.debug('      add undominated label {} (C {} | R {})'.format(pt.print_path(v_path),v_label[0],v_label[1]))
                    
                    # strong dominance: set node resource to one for nodes in S that cannot
                    # be feasibly visited with edge resources
                    for n in S:
                        for res in range(0,n_res):
                            if v_label[1][res] + res_min[res][n].get(n,0.0) > max_res[res]:
                                if v_label[1][n_res+S.index(n)] == 0:
                                    logging.debug('      set strong dominace for node resource {}'.format(S.index(n)))
                                    v_label[1][n_res+S.index(n)] = 1
                    
                    # remove dominated labels
                    # Note: It is possible that two labels are identical but have different paths.
                    # The iteration therefore has to be using i_label, and not, for example, using
                    #   for label in labels.get(v,[]):
                    i_label = 0
                    n_labels = len(labels.get(v,[]))
                    while i_label < n_labels:
                        label = labels[v][i_label]
                        if _is_dominated(label, v_label):
                            logging.debug('      remove dominated label {} (C {} | R {})'.format(pt.print_path(paths[v][i_label]),label[0],label[1]))
                            labels[v].pop(i_label)
                            paths[v].pop(i_label)
                            L_rename = set()
                            if (v, i_label) in L:
                                L.remove((v, i_label))
                            for i in range(i_label+1, len(labels[v])+1):
                                if (v, i) in L:
                                    L_rename.add((v,i-1))
                                    L.remove((v,i))
                            L.update(L_rename)
                            i_label -= 1
                            n_labels -= 1
                        i_label += 1
                    
                    # add label and path
                    paths[v].append(v_path)
                    labels[v].append(v_label)
                    
                    # add to list L
                    L.add((v, len(labels[v])-1))
            else:
                logging.debug('      therefore do not add unfeasible label {}'.format(v_label[1]))
            
            logging.debug('')
    
    # return cheapest paths with label
    logging.info('  Select cheapest path to {}'.format(target))
    logging.info('')
    
    least_cost = inf
    for p in range(0,len(labels[target])):
        if labels[target][p][0] < least_cost:
            best_path = paths[target][p]
            best_label = labels[target][p]
            least_cost = best_label[0]
    return best_path, best_label

# General State Space Augmenting Algorithm
# (based on algorithm 2.2, from [1])
# Note: The graph must have been preprocessed so that it is reduced and has the minimal resource information in "res_min".
def GSSA(G, source, target, max_res, res_min):
    logging.info('Searching for shortest path {} -> {}'.format(source, target))
    logging.info('')
    
    # initialize node resources and not done
    S = list([])
    DLA_done = False

    while not DLA_done:
        # Run dynamic labelling algorithm
        path, label = GLSA(G, S, source, target, max_res, res_min)
        logging.info('  found path {} (C {} | R {})'.format(pt.print_path(path, max_path_len_for_print=len(path)), label[0], label[1]))
        path_elems = pt.count_elems(path)
        path_max_mult = max(path_elems.values())
        if path_max_mult == 1:
            logging.info('    it is elementary')
            logging.info('')
            DLA_done = True
        else:
            logging.info('    but is it not elementary')
            node_max_mult = max(path_elems, key=path_elems.get)
            S.append(node_max_mult)
            logging.info('')
            logging.info('    Incrementing node {}, which had multiplicity {}:'.format(node_max_mult, path_max_mult))
            logging.info('      S = {}'.format(S))
            logging.info('')
        #input('PAUSED')
    
    return path, label

# returns whether a label a is dominated by another label b
def _is_dominated(a, b):
    logging.debug('        >> check for domination of {} by {}'.format(a,b))
    if a[0] == b[0] and all(a[1] == b[1]):
        label_dominated = False
    else:
        label_dominated = True
        if a[0] < b[0]:
            label_dominated = False
        if any(a[1] < b[1]):
            label_dominated = False
    return label_dominated

# returns weight of certain resource of edge, given by global variable "resource_treated".
def _res_cost_i(u,v,e):
    global resource_treated
    
    return e['res_cost'][resource_treated]