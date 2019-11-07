def getAdj2(graph, input_list, n):
    """
    Find hop-N neighbours of each item in input_list
    :param graph: NetworkX graph object
    :param input_list: Input list
    :param n: Hop N
    :return: N hop neighbours of the input list's items
    """
    full_list = []
    while (n > 0):
        n -= 1
        output_list = []
        for node in graph.nbunch_iter(input_list):
            for neighbour in graph[node]:
                if neighbour not in full_list:
                    full_list.append(neighbour)
                    output_list.append(neighbour)
    return output_list
