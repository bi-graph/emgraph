import pandas as pd

def import_files():
    """
    Import links and labels from csv files
    :return: links and label dataframes
    """
    print('Importing files and making dataframes...')
    df = pd.read_csv('./inputs/neighbour_matrix.csv', sep=',')
    df_nodes = pd.read_csv('./inputs/id_labels.csv', sep=',')
    # df = df.drop(['Weight'], axis=1)

    label_dictionary = {}
    for row in df_nodes.iterrows():
        label_dictionary.update({row[1][0]: row[1][1]})
    return df, label_dictionary