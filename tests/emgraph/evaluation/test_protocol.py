from itertools import islice

import numpy as np
import pytest
import tensorflow as tf

from emgraph.datasets import load_fb15k_237, load_wn18, load_wn18rr, load_yago3_10
from emgraph.evaluation import (
    create_mappings, evaluate_performance, filter_unseen_entities,
    generate_corruptions_for_eval, generate_corruptions_for_fit, hits_at_n_score, mrr_score, select_best_model_ranking,
    to_idx,
)
from emgraph.evaluation import train_test_split_no_unseen
from emgraph.evaluation.protocol import (
    ParamHistory, _flatten_nested_keys, _get_param_hash, _next_hyperparam,
    _next_hyperparam_random, _remove_unused_params, _sample_parameters, _scalars_into_lists, _unflatten_nested_keys,
)
from emgraph.models import ComplEx, TransE, reset_entity_threshold, set_entity_threshold


# test for #186
def test_evaluate_performance_too_many_entities_warning():
    X = load_yago3_10()
    model = TransE(batches_count=200, seed=0, epochs=1, k=5, eta=1, verbose=True)
    model.fit(X['train'])

    # no entity list declared
    with pytest.warns(UserWarning):
        evaluate_performance(X['test'][::100], model, verbose=True, corrupt_side='o')

    # with larger than threshold entity list
    with pytest.warns(UserWarning):
        # TOO_MANY_ENT_TH threshold is set to 50,000 entities. Using explicit value to comply with linting
        # and thus avoiding exporting unused global variable.
        entities_subset = np.union1d(np.unique(X["train"][:, 0]), np.unique(X["train"][:, 2]))[:50000]
        evaluate_performance(X['test'][::100], model, verbose=True, corrupt_side='o', entities_subset=entities_subset)

    # with small entity list (no exception expected)
    evaluate_performance(X['test'][::100], model, verbose=True, corrupt_side='o', entities_subset=entities_subset[:10])

    # with smaller dataset, no entity list declared (no exception expected)
    X_wn18rr = load_wn18rr()
    model_wn18 = TransE(batches_count=200, seed=0, epochs=1, k=5, eta=1, verbose=True)
    model_wn18.fit(X_wn18rr['train'])
    evaluate_performance(X_wn18rr['test'][::100], model_wn18, verbose=True, corrupt_side='o')


def test_evaluate_performance_filter_without_xtest():
    X = load_wn18()
    model = ComplEx(
        batches_count=10, seed=0, epochs=1, k=20, eta=10, loss='nll',
        regularizer=None, optimizer='adam', optimizer_params={'lr': 0.01}, verbose=True
    )
    model.fit(X['train'])

    X_filter = np.concatenate((X['train'], X['valid']))  # filter does not contain X_test
    from emgraph.evaluation import mrr_score
    ranks = evaluate_performance(X['test'][::1000], model, X_filter, verbose=True, corrupt_side='s,o')
    assert (mrr_score(ranks) > 0)


def test_evaluate_performance_ranking_against_specified_entities():
    X = load_wn18()
    model = ComplEx(
        batches_count=10, seed=0, epochs=1, k=20, eta=10, loss='nll',
        regularizer=None, optimizer='adam', optimizer_params={'lr': 0.01}, verbose=True
    )
    model.fit(X['train'])

    X_filter = np.concatenate((X['train'], X['valid'], X['test']))
    entities_subset = np.concatenate([X['test'][::1000, 0], X['test'][::1000, 2]], 0)

    ranks = evaluate_performance(
        X['test'][::1000], model, X_filter, verbose=True, corrupt_side='s,o',
        entities_subset=entities_subset
    )
    ranks = ranks.reshape(-1)
    assert (np.sum(ranks > len(entities_subset)) == 0)


def test_evaluate_performance_ranking_against_shuffled_all_entities():
    """ Compares mrr of test set by using default protocol against all entities vs
        mrr of corruptions generated by corrupting using entities_subset = all entities shuffled
    """
    import random
    X = load_wn18()
    model = ComplEx(
        batches_count=10, seed=0, epochs=1, k=20, eta=10, loss='nll',
        regularizer=None, optimizer='adam', optimizer_params={'lr': 0.01}, verbose=True
    )
    model.fit(X['train'])

    X_filter = np.concatenate((X['train'], X['valid'], X['test']))
    entities_subset = random.shuffle(list(model.ent_to_idx.keys()))

    from emgraph.evaluation import mrr_score
    ranks_all = evaluate_performance(X['test'][::1000], model, X_filter, verbose=True, corrupt_side='s,o')

    ranks_suffled_ent = evaluate_performance(
        X['test'][::1000], model, X_filter, verbose=True, corrupt_side='s,o',
        entities_subset=entities_subset
    )
    assert (mrr_score(ranks_all) == mrr_score(ranks_suffled_ent))


def test_evaluate_performance_default_protocol_without_filter():
    wn18 = load_wn18()

    model = TransE(
        batches_count=10, seed=0, epochs=1,
        k=50, eta=10, verbose=True,
        embedding_model_params={'normalize_ent_emb': False, 'norm': 1},
        loss='self_adversarial', loss_params={'margin': 1, 'alpha': 0.5},
        optimizer='adam',
        optimizer_params={'lr': 0.0005}
    )

    model.fit(wn18['train'])

    from emgraph.evaluation import evaluate_performance
    ranks_sep = []
    ranks = evaluate_performance(wn18['test'][::100], model, verbose=True, corrupt_side='o')

    ranks_sep.extend(ranks)
    from emgraph.evaluation import evaluate_performance

    from emgraph.evaluation import hits_at_n_score, mrr_score, mr_score
    ranks = evaluate_performance(wn18['test'][::100], model, verbose=True, corrupt_side='s')
    ranks_sep.extend(ranks)
    print('----------EVAL WITHOUT FILTER-----------------')
    print('----------Subj and obj corrupted separately-----------------')
    mr_sep = mr_score(ranks_sep)
    print('MAR:', mr_sep)
    print('Mrr:', mrr_score(ranks_sep))
    print('hits10:', hits_at_n_score(ranks_sep, 10))
    print('hits3:', hits_at_n_score(ranks_sep, 3))
    print('hits1:', hits_at_n_score(ranks_sep, 1))

    from emgraph.evaluation import evaluate_performance

    from emgraph.evaluation import hits_at_n_score, mrr_score, mr_score
    ranks = evaluate_performance(wn18['test'][::100], model, verbose=True, corrupt_side='s,o')
    print('----------corrupted with default protocol-----------------')
    mr_joint = mr_score(ranks)
    mrr_joint = mrr_score(ranks)
    print('MAR:', mr_joint)
    print('Mrr:', mrr_score(ranks))
    print('hits10:', hits_at_n_score(ranks, 10))
    print('hits3:', hits_at_n_score(ranks, 3))
    print('hits1:', hits_at_n_score(ranks, 1))

    np.testing.assert_equal(mr_sep, mr_joint)
    assert (mrr_joint is not np.Inf)


def test_evaluate_performance_default_protocol_with_filter():
    wn18 = load_wn18()

    X_filter = np.concatenate((wn18['train'], wn18['valid'], wn18['test']))

    model = TransE(
        batches_count=10, seed=0, epochs=1,
        k=50, eta=10, verbose=True,
        embedding_model_params={'normalize_ent_emb': False, 'norm': 1},
        loss='self_adversarial', loss_params={'margin': 1, 'alpha': 0.5},
        optimizer='adam',
        optimizer_params={'lr': 0.0005}
    )

    model.fit(wn18['train'])

    from emgraph.evaluation import evaluate_performance
    ranks_sep = []
    ranks = evaluate_performance(wn18['test'][::100], model, X_filter, verbose=True, corrupt_side='o')

    ranks_sep.extend(ranks)
    from emgraph.evaluation import evaluate_performance

    from emgraph.evaluation import hits_at_n_score, mrr_score, mr_score
    ranks = evaluate_performance(wn18['test'][::100], model, X_filter, verbose=True, corrupt_side='s')
    ranks_sep.extend(ranks)
    print('----------EVAL WITH FILTER-----------------')
    print('----------Subj and obj corrupted separately-----------------')
    mr_sep = mr_score(ranks_sep)
    print('MAR:', mr_sep)
    print('Mrr:', mrr_score(ranks_sep))
    print('hits10:', hits_at_n_score(ranks_sep, 10))
    print('hits3:', hits_at_n_score(ranks_sep, 3))
    print('hits1:', hits_at_n_score(ranks_sep, 1))

    from emgraph.evaluation import evaluate_performance

    from emgraph.evaluation import hits_at_n_score, mrr_score, mr_score
    ranks = evaluate_performance(wn18['test'][::100], model, X_filter, verbose=True, corrupt_side='s,o')
    print('----------corrupted with default protocol-----------------')
    mr_joint = mr_score(ranks)
    mrr_joint = mrr_score(ranks)
    print('MAR:', mr_joint)
    print('Mrr:', mrr_joint)
    print('hits10:', hits_at_n_score(ranks, 10))
    print('hits3:', hits_at_n_score(ranks, 3))
    print('hits1:', hits_at_n_score(ranks, 1))

    np.testing.assert_equal(mr_sep, mr_joint)
    assert (mrr_joint is not np.Inf)


def test_evaluate_performance_so_side_corruptions_with_filter():
    X = load_wn18()
    model = ComplEx(
        batches_count=10, seed=0, epochs=5, k=200, eta=10, loss='nll',
        regularizer=None, optimizer='adam', optimizer_params={'lr': 0.01}, verbose=True
    )
    model.fit(X['train'])

    ranks = evaluate_performance(X['test'][::20], model=model, verbose=True, corrupt_side='s+o')
    mrr = mrr_score(ranks)
    hits_10 = hits_at_n_score(ranks, n=10)
    print("ranks: %s" % ranks)
    print("MRR: %f" % mrr)
    print("Hits@10: %f" % hits_10)
    assert (mrr is not np.Inf)


@pytest.mark.skip(reason="CircleCI free tier upper bound investigation")
def test_evaluate_performance_so_side_corruptions_without_filter():
    X = load_wn18()
    model = ComplEx(
        batches_count=10, seed=0, epochs=5, k=200, eta=10, loss='nll',
        regularizer=None, optimizer='adam', optimizer_params={'lr': 0.01}, verbose=True
    )
    model.fit(X['train'])

    X_filter = np.concatenate((X['train'], X['valid'], X['test']))
    ranks = evaluate_performance(X['test'][::20], model, X_filter, verbose=True, corrupt_side='s+o')
    mrr = mrr_score(ranks)
    hits_10 = hits_at_n_score(ranks, n=10)
    print("ranks: %s" % ranks)
    print("MRR: %f" % mrr)
    print("Hits@10: %f" % hits_10)
    assert (mrr is not np.Inf)


@pytest.mark.skip(reason="Speeding up jenkins")
def test_evaluate_performance_nll_complex():
    X = load_wn18()
    model = ComplEx(
        batches_count=10, seed=0, epochs=10, k=150, optimizer_params={'lr': 0.1}, eta=10, loss='nll',
        optimizer='adagrad', verbose=True
    )
    model.fit(np.concatenate((X['train'], X['valid'])))

    filter_triples = np.concatenate((X['train'], X['valid'], X['test']))
    ranks = evaluate_performance(X['test'][:200], model=model, filter_triples=filter_triples, verbose=True)

    mrr = mrr_score(ranks)
    hits_10 = hits_at_n_score(ranks, n=10)
    print("ranks: %s" % ranks)
    print("MRR: %f" % mrr)
    print("Hits@10: %f" % hits_10)


@pytest.mark.skip(reason="Speeding up jenkins")
def test_evaluate_performance_TransE():
    X = load_wn18()
    model = TransE(
        batches_count=10, seed=0, epochs=100, k=100, eta=5, optimizer_params={'lr': 0.1},
        loss='pairwise', loss_params={'margin': 5}, optimizer='adagrad'
    )
    model.fit(np.concatenate((X['train'], X['valid'])))

    filter_triples = np.concatenate((X['train'], X['valid'], X['test']))
    ranks = evaluate_performance(X['test'][:200], model=model, filter_triples=filter_triples, verbose=True)

    # ranks = evaluate_performance(X['test'][:200], model=model)

    mrr = mrr_score(ranks)
    hits_10 = hits_at_n_score(ranks, n=10)
    print("ranks: %s" % ranks)
    print("MRR: %f" % mrr)
    print("Hits@10: %f" % hits_10)

    # TODO: add test condition (MRR raw for WN18 and TransE should be ~ 0.335 - check papers)


def test_generate_corruptions_for_eval():
    X = np.array(
        [['a', 'x', 'b'],
         ['c', 'x', 'd'],
         ['e', 'x', 'f'],
         ['b', 'y', 'h'],
         ['a', 'y', 'l']]
    )

    rel_to_idx, ent_to_idx = create_mappings(X)
    X = to_idx(X, ent_to_idx=ent_to_idx, rel_to_idx=rel_to_idx)

    with tf.Session() as sess:
        all_ent = tf.constant(list(ent_to_idx.values()), dtype=tf.int64)
        x = tf.constant(np.array([X[0]]), dtype=tf.int64)
        x_n_actual = sess.run(generate_corruptions_for_eval(x, all_ent))
        x_n_expected = np.array(
            [[0, 0, 0],
             [0, 0, 1],
             [0, 0, 2],
             [0, 0, 3],
             [0, 0, 4],
             [0, 0, 5],
             [0, 0, 6],
             [0, 0, 7],
             [0, 0, 1],
             [1, 0, 1],
             [2, 0, 1],
             [3, 0, 1],
             [4, 0, 1],
             [5, 0, 1],
             [6, 0, 1],
             [7, 0, 1]]
        )
    np.testing.assert_array_equal(x_n_actual, x_n_expected)


@pytest.mark.skip(reason="Needs to change to account for prime-product evaluation strategy")
def test_generate_corruptions_for_eval_filtered():
    x = np.array([0, 0, 1])
    idx_entities = np.array([0, 1, 2, 3])
    filter_triples = np.array(([1, 0, 1], [2, 0, 1]))

    x_n_actual = generate_corruptions_for_eval(x, idx_entities=idx_entities, filter=filter_triples)
    x_n_expected = np.array(
        [[3, 0, 1],
         [0, 0, 0],
         [0, 0, 2],
         [0, 0, 3]]
    )
    np.testing.assert_array_equal(np.sort(x_n_actual, axis=0), np.sort(x_n_expected, axis=0))


@pytest.mark.skip(reason="Needs to change to account for prime-product evaluation strategy")
def test_generate_corruptions_for_eval_filtered_object():
    x = np.array([0, 0, 1])
    idx_entities = np.array([0, 1, 2, 3])
    filter_triples = np.array(([1, 0, 1], [2, 0, 1]))

    x_n_actual = generate_corruptions_for_eval(x, idx_entities=idx_entities, filter=filter_triples, side='o')
    x_n_expected = np.array(
        [[0, 0, 0],
         [0, 0, 2],
         [0, 0, 3]]
    )
    np.testing.assert_array_equal(np.sort(x_n_actual, axis=0), np.sort(x_n_expected, axis=0))


def test_to_idx():
    X = np.array([['a', 'x', 'b'], ['c', 'y', 'd']])
    X_idx_expected = [[0, 0, 1], [2, 1, 3]]
    rel_to_idx, ent_to_idx = create_mappings(X)
    X_idx = to_idx(X, ent_to_idx=ent_to_idx, rel_to_idx=rel_to_idx)

    np.testing.assert_array_equal(X_idx, X_idx_expected)


@pytest.mark.skip(reason="deprecated")
def test_filter_unseen_entities_with_strict_mode():
    from collections import namedtuple
    base_model = namedtuple('test_model', 'ent_to_idx')

    X = np.array(
        [['a', 'x', 'b'],
         ['c', 'y', 'd'],
         ['e', 'y', 'd']]
    )

    model = base_model({'a': 1, 'b': 2, 'c': 3, 'd': 4})

    with pytest.raises(RuntimeError):
        _ = filter_unseen_entities(X, model, strict=True)


def test_filter_unseen_entities():
    from collections import namedtuple
    base_model = namedtuple('test_model', 'ent_to_idx')

    X = np.array(
        [['a', 'x', 'b'],
         ['c', 'y', 'd'],
         ['e', 'y', 'd']]
    )

    model = base_model({'a': 1, 'b': 2, 'c': 3, 'd': 4})

    X_filtered = filter_unseen_entities(X, model)

    X_expected = np.array(
        [['a', 'x', 'b'],
         ['c', 'y', 'd']]
    )

    np.testing.assert_array_equal(X_filtered, X_expected)


# @pytest.mark.skip(reason="excluded to try out jenkins.")   # TODO: re-enable this
def test_generate_corruptions_for_fit_corrupt_side_so():
    tf.reset_default_graph()
    X = np.array(
        [['a', 'x', 'b'],
         ['c', 'x', 'd'],
         ['e', 'x', 'f'],
         ['b', 'y', 'h'],
         ['a', 'y', 'l']]
    )
    rel_to_idx, ent_to_idx = create_mappings(X)
    X = to_idx(X, ent_to_idx=ent_to_idx, rel_to_idx=rel_to_idx)
    eta = 1
    with tf.Session() as sess:
        all_ent = tf.squeeze(tf.constant(list(ent_to_idx.values()), dtype=tf.int32))
        dataset = tf.constant(X, dtype=tf.int32)
        X_corr = sess.run(
            generate_corruptions_for_fit(dataset, eta=eta, corrupt_side='s,o', entities_size=len(X), rnd=0)
        )
        print(X_corr)
    # these values occur when seed=0

    X_corr_exp = [[0, 0, 1],
                  [2, 0, 3],
                  [3, 0, 5],
                  [1, 1, 0],
                  [0, 1, 3]]

    np.testing.assert_array_equal(X_corr, X_corr_exp)


def test_generate_corruptions_for_fit_curropt_side_s():
    tf.reset_default_graph()
    X = np.array(
        [['a', 'x', 'b'],
         ['c', 'x', 'd'],
         ['e', 'x', 'f'],
         ['b', 'y', 'h'],
         ['a', 'y', 'l']]
    )
    rel_to_idx, ent_to_idx = create_mappings(X)
    X = to_idx(X, ent_to_idx=ent_to_idx, rel_to_idx=rel_to_idx)
    eta = 1
    with tf.Session() as sess:
        all_ent = tf.squeeze(tf.constant(list(ent_to_idx.values()), dtype=tf.int32))
        dataset = tf.constant(X, dtype=tf.int32)
        X_corr = sess.run(generate_corruptions_for_fit(dataset, eta=eta, corrupt_side='s', entities_size=len(X), rnd=0))
        print(X_corr)

    # these values occur when seed=0

    X_corr_exp = [[1, 0, 1],
                  [3, 0, 3],
                  [3, 0, 5],
                  [0, 1, 6],
                  [3, 1, 7]]

    np.testing.assert_array_equal(X_corr, X_corr_exp)


def test_generate_corruptions_for_fit_curropt_side_o():
    tf.reset_default_graph()
    X = np.array(
        [['a', 'x', 'b'],
         ['c', 'x', 'd'],
         ['e', 'x', 'f'],
         ['b', 'y', 'h'],
         ['a', 'y', 'l']]
    )
    rel_to_idx, ent_to_idx = create_mappings(X)
    X = to_idx(X, ent_to_idx=ent_to_idx, rel_to_idx=rel_to_idx)
    eta = 1
    with tf.Session() as sess:
        all_ent = tf.squeeze(tf.constant(list(ent_to_idx.values()), dtype=tf.int32))
        dataset = tf.constant(X, dtype=tf.int32)
        X_corr = sess.run(generate_corruptions_for_fit(dataset, eta=eta, corrupt_side='o', entities_size=len(X), rnd=0))
        print(X_corr)
    # these values occur when seed=0

    X_corr_exp = [[0, 0, 1],
                  [2, 0, 3],
                  [4, 0, 3],
                  [1, 1, 0],
                  [0, 1, 3]]
    np.testing.assert_array_equal(X_corr, X_corr_exp)


def test_train_test_split():
    # Graph
    X = np.array(
        [['a', 'y', 'b'],
         ['a', 'y', 'c'],
         ['c', 'y', 'a'],
         ['d', 'y', 'e'],
         ['e', 'y', 'f'],
         ['f', 'y', 'c'],
         ['f', 'y', 'c']]
    )

    expected_X_train = np.array(
        [['a', 'y', 'b'],
         ['c', 'y', 'a'],
         ['d', 'y', 'e'],
         ['e', 'y', 'f'],
         ['f', 'y', 'c']]
    )

    expected_X_test = np.array(
        [['a', 'y', 'c'],
         ['f', 'y', 'c']]
    )

    X_train, X_test = train_test_split_no_unseen(X, test_size=2, seed=0, backward_compatible=True)

    np.testing.assert_array_equal(X_train, expected_X_train)
    np.testing.assert_array_equal(X_test, expected_X_test)


def test_train_test_split_fast():
    X = load_fb15k_237()
    x_all = np.concatenate([X['train'], X['valid'], X['test']], 0)
    unique_entities = len(set(x_all[:, 0]).union(x_all[:, 2]))
    unique_rels = len(set(x_all[:, 1]))

    x_train, x_test = train_test_split_no_unseen(x_all, 0.90)

    assert x_train.shape[0] + x_test.shape[0] == x_all.shape[0]

    unique_entities_train = len(set(x_train[:, 0]).union(x_train[:, 2]))
    unique_rels_train = len(set(x_train[:, 1]))

    assert unique_entities_train == unique_entities and unique_rels_train == unique_rels

    with pytest.raises(Exception) as e:
        x_train, x_test = train_test_split_no_unseen(x_all, 0.99, allow_duplication=False)

    assert str(e.value) == "Cannot create a test split of the desired size. " \
                           "Some entities will not occur in both training and test set. " \
                           "Set allow_duplication=True," \
                           "remove filter on test predicates or " \
                           "set test_size to a smaller value."

    x_train, x_test = train_test_split_no_unseen(x_all, 0.99, allow_duplication=True)
    assert x_train.shape[0] + x_test.shape[0] > x_all.shape[0]

    unique_entities_train = len(set(x_train[:, 0]).union(x_train[:, 2]))
    unique_rels_train = len(set(x_train[:, 1]))

    assert unique_entities_train == unique_entities and unique_rels_train == unique_rels


def test_remove_unused_params():
    params1 = {
        "batches_count": 50,
        "epochs": 4000,
        "k": 200,
        "eta": 15,
        "loss": "nll",
        "loss_params": {
            "margin": 2
        },
        "embedding_model_params": {
        },
        "regularizer": "LP",
        "regularizer_params": {
            "p": 1,
            "lambda": 1e-5
        },
        "optimizer": "adam",
        "optimizer_params": {
            "lr": 0.001
        },
        "verbose": False,
        "model_name": "ComplEx"
    }
    param = _remove_unused_params(params1)

    assert param["loss_params"] == {}
    assert param["embedding_model_params"] == {}
    assert param["regularizer_params"] == {
        "p": 1,
        "lambda": 1e-5
    }
    assert param["optimizer_params"] == {
        "lr": 0.001
    }

    params2 = {
        "batches_count": 50,
        "epochs": 4000,
        "k": 200,
        "eta": 15,
        "loss": "self_adversarial",
        "loss_params": {
            "margin": 2
        },
        "regularizer": None,
        "regularizer_params": {
            "p": 1,
            "lambda": 1e-5
        },
        "optimizer": "adam",
        "optimizer_params": {
            "lr": 0.001
        },
        "verbose": False,
        "model_name": "unknown_model"
    }

    param = _remove_unused_params(params2)

    assert param["loss_params"] == {
        "margin": 2
    }
    assert param["regularizer_params"] == {}
    assert param["optimizer_params"] == {
        "lr": 0.001
    }


def test_flatten_nested_keys():
    params = {
        "batches_count": 50,
        "epochs": 4000,
        "k": 200,
        "eta": 15,
        "loss": "nll",
        "loss_params": {
            "margin": 2
        },
        "embedding_model_params": {
        },
        "regularizer": "LP",
        "regularizer_params": {
            "p": 1,
            "lambda": 1e-5
        },
        "optimizer": "adam",
        "optimizer_params": {
            "lr": 0.001
        },
        "verbose": False,
        "model_name": "ComplEx"
    }

    flattened_params = _flatten_nested_keys(params)

    expected = {
        "batches_count": 50,
        "epochs": 4000,
        "k": 200,
        "eta": 15,
        "loss": "nll",
        ("loss_params", "margin"): 2,
        "regularizer": "LP",
        ("regularizer_params", "p"): 1,
        ("regularizer_params", "lambda"): 1e-5,
        "optimizer": "adam",
        ("optimizer_params", "lr"): 0.001,
        "verbose": False,
        "model_name": "ComplEx"
    }

    assert flattened_params == expected


def test_unflatten_nested_keys():
    flattened_params = {
        "batches_count": 50,
        "epochs": 4000,
        "k": 200,
        "eta": 15,
        "loss": "nll",
        ("loss_params", "margin"): 2,
        "regularizer": "LP",
        ("regularizer_params", "p"): 1,
        ("regularizer_params", "lambda"): 1e-5,
        "optimizer": "adam",
        ("optimizer_params", "lr"): 0.001,
        "verbose": False,
        "model_name": "ComplEx"
    }

    params = _unflatten_nested_keys(flattened_params)

    expected = {
        "batches_count": 50,
        "epochs": 4000,
        "k": 200,
        "eta": 15,
        "loss": "nll",
        "loss_params": {
            "margin": 2
        },
        "regularizer": "LP",
        "regularizer_params": {
            "p": 1,
            "lambda": 1e-5
        },
        "optimizer": "adam",
        "optimizer_params": {
            "lr": 0.001
        },
        "verbose": False,
        "model_name": "ComplEx"
    }

    assert params == expected


def test_get_param_hash():
    params1 = {
        "batches_count": 50,
        "epochs": 4000,
        "k": 200,
        "eta": 15,
        "loss": "nll",
        "loss_params": {
            "margin": 2
        },
        "embedding_model_params": {
        },
        "regularizer": "LP",
        "regularizer_params": {
            "p": 1,
            "lambda": 1e-5
        },
        "optimizer": "adam",
        "optimizer_params": {
            "lr": 0.001
        },
        "verbose": False,
        "model_name": "ComplEx"
    }

    params2 = {
        "batches_count": 50,
        "epochs": 4000,
        "k": 200,
        "eta": 15,
        "loss": "nll",
        "loss_params": {
            "margin": 2
        },
        "embedding_model_params": {
            "useless": 2
        },
        "regularizer": "LP",
        "regularizer_params": {
            "p": 1,
            "lambda": 1e-5
        },
        "optimizer": "adam",
        "optimizer_params": {
            "lr": 0.001
        },
        "verbose": False,
        "model_name": "ComplEx"
    }

    params3 = {
        "batches_count": 50,
        "epochs": 4000,
        "k": 200,
        "eta": 15,
        "loss": "nll",
        "loss_params": {
            "margin": 2
        },
        "embedding_model_params": {
            "useless": 2
        },
        "regularizer": "LP",
        "regularizer_params": {
            "p": 1,
            "lambda": 1e-4
        },
        "optimizer": "adam",
        "optimizer_params": {
            "lr": 0.001
        },
        "verbose": False,
        "model_name": "ComplEx"
    }

    assert _get_param_hash(params1) == _get_param_hash(params2)
    assert _get_param_hash(params1) != _get_param_hash(params3)


def test_param_hist():
    ph = ParamHistory()

    params1 = {
        "batches_count": 50,
        "epochs": 4000,
        "k": 200,
        "eta": 15,
        "loss": "nll",
        "loss_params": {
            "margin": 2
        },
        "embedding_model_params": {
        },
        "regularizer": "LP",
        "regularizer_params": {
            "p": 1,
            "lambda": 1e-5
        },
        "optimizer": "adam",
        "optimizer_params": {
            "lr": 0.001
        },
        "verbose": False,
        "model_name": "ComplEx"
    }

    params2 = {
        "batches_count": 50,
        "epochs": 4000,
        "k": 200,
        "eta": 15,
        "loss": "nll",
        "loss_params": {
            "margin": 2
        },
        "embedding_model_params": {
            "useless": 2
        },
        "regularizer": "LP",
        "regularizer_params": {
            "p": 1,
            "lambda": 1e-5
        },
        "optimizer": "adam",
        "optimizer_params": {
            "lr": 0.001
        },
        "verbose": False,
        "model_name": "ComplEx"
    }

    params3 = {
        "batches_count": 50,
        "epochs": 4000,
        "k": 200,
        "eta": 15,
        "loss": "nll",
        "loss_params": {
            "margin": 2
        },
        "embedding_model_params": {
            "useless": 2
        },
        "regularizer": "LP",
        "regularizer_params": {
            "p": 1,
            "lambda": 1e-4
        },
        "optimizer": "adam",
        "optimizer_params": {
            "lr": 0.001
        },
        "verbose": False,
        "model_name": "ComplEx"
    }

    assert params1 not in ph
    ph.add(params1)
    assert params1 in ph
    assert params2 in ph
    assert params3 not in ph
    ph.add(params3)
    assert params1 in ph
    assert params2 in ph
    assert params3 in ph


def test_sample_hyper_param():
    np.random.seed(0)

    param_grid = {
        "batches_count": [50],
        "epochs": [4000],
        "k": [100, 200],
        "eta": lambda: np.random.choice([5, 10, 15]),
        "loss": ["pairwise", "nll"],
        "loss_params": {
            "margin": [2]
        },
        "embedding_model_params": {
        },
        "regularizer": ["LP", None],
        "regularizer_params": {
            "p": [1, 3],
            "lambda": [1e-4, 1e-5]
        },
        "optimizer": ["adagrad", "adam"],
        "optimizer_params": {
            "lr": lambda: np.random.uniform(0.001, 0.1)
        },
        "verbose": False,
        "model_name": "ComplEx"
    }

    for _ in range(10):
        param = _sample_parameters(param_grid)
        assert param["batches_count"] == 50
        assert param["k"] in (100, 200)
        assert param["eta"] in (5, 10, 15)
        assert param["loss"] in ("pairwise", "nll")
        if param["loss"] == "pairwise":
            assert param["loss_params"]["margin"] == 2
        assert param["embedding_model_params"] == {}
        assert param["regularizer"] in ("LP", None)
        if param["regularizer"] == "LP":
            assert param["regularizer_params"]["p"] in (1, 3)
            assert param["regularizer_params"]["lambda"] in (1e-4, 1e-5)
        assert param["optimizer"] in ("adagrad", "adam")
        assert 0.001 < param["optimizer_params"]["lr"] < 0.1
        assert not param["verbose"]
        assert param["model_name"] == "ComplEx"


def test_next_hyperparam():
    param_grid = {
        "batches_count": [50],
        "epochs": [4000],
        "k": [100, 200],
        "eta": [5, 10, 15],
        "loss": ["pairwise", "nll"],
        "loss_params": {
            "margin": [2]
        },
        "embedding_model_params": {
        },
        "regularizer": ["LP", None],
        "regularizer_params": {
            "p": [1, 3],
            "lambda": [1e-4, 1e-5]
        },
        "optimizer": ["adagrad", "adam"],
        "optimizer_params": {
            "lr": [0.01, 0.001, 0.0001]
        },
        "verbose": [False],
        "model_name": ["ComplEx"]
    }

    combinations = [i for i in _next_hyperparam(param_grid)]

    assert len(combinations) == 360
    assert len(set(frozenset(_flatten_nested_keys(i).items()) for i in combinations)) == 360
    assert all(type(d) is dict for d in combinations)
    assert all(all(type(k) is str for k in d.keys()) for d in combinations)


def test_next_hyperparam_random():
    param_grid = {
        "batches_count": [50],
        "epochs": [4000],
        "k": [100, 200],
        "eta": [5, 10, 15],
        "loss": ["pairwise", "nll"],
        "loss_params": {
            "margin": [2]
        },
        "embedding_model_params": {
        },
        "regularizer": ["LP", None],
        "regularizer_params": {
            "p": [1, 3],
            "lambda": [1e-4, 1e-5]
        },
        "optimizer": ["adagrad", "adam"],
        "optimizer_params": {
            "lr": [0.01, 0.001, 0.0001]
        },
        "verbose": [False],
        "model_name": ["ComplEx"]
    }

    combinations = [i for i in islice(_next_hyperparam_random(param_grid), 200)]

    assert len(combinations) == 200
    assert len(set(frozenset(_flatten_nested_keys(i).items()) for i in combinations)) == 200
    assert all(type(d) is dict for d in combinations)
    assert all(all(type(k) is str for k in d.keys()) for d in combinations)


def test_scalars_into_lists():
    eta_fn = lambda: np.random.choice([5, 10, 15])

    param_grid = {
        "batches_count": 50,
        "epochs": [4000],
        "k": [100, 200],
        "eta": eta_fn,
        "loss": "nll",
        "loss_params": {
            "margin": 2
        },
        "embedding_model_params": {
        },
        "regularizer": ["LP", None],
        "regularizer_params": {
            "p": [1, 3],
            "lambda": [1e-4, 1e-5]
        },
        "optimizer": ["adagrad", "adam"],
        "optimizer_params": {
            "lr": "wrong"
        },
        "verbose": False
    }

    _scalars_into_lists(param_grid)

    expected = {
        "batches_count": [50],
        "epochs": [4000],
        "k": [100, 200],
        "eta": eta_fn,
        "loss": ["nll"],
        "loss_params": {
            "margin": [2]
        },
        "embedding_model_params": {
        },
        "regularizer": ["LP", None],
        "regularizer_params": {
            "p": [1, 3],
            "lambda": [1e-4, 1e-5]
        },
        "optimizer": ["adagrad", "adam"],
        "optimizer_params": {
            "lr": ["wrong"]
        },
        "verbose": [False]
    }

    assert param_grid == expected


def test_select_best_model_ranking_grid():
    X = load_wn18rr()
    model_class = TransE
    param_grid = {
        "batches_count": [50],
        "seed": 0,
        "epochs": [1],
        "k": [2, 50],
        "eta": [1],
        "loss": ["nll"],
        "loss_params": {
        },
        "embedding_model_params": {
        },
        "regularizer": [None],

        "regularizer_params": {
        },
        "optimizer": ["adagrad"],
        "optimizer_params": {
            "lr": [1000.0, 0.0001]
        }
    }

    best_model, best_params, best_mrr_train, ranks_test, test_results, experimental_history = select_best_model_ranking(
        model_class,
        X['train'],
        X['valid'][::5],
        X['test'][::10],
        param_grid
    )

    assert best_params['k'] in (2, 50)
    assert best_params['optimizer_params']['lr'] == 0.0001
    assert len(experimental_history) == 4
    assert set(i["model_params"]["k"] for i in experimental_history) == {2, 50}
    assert set(i["model_params"]["optimizer_params"]["lr"] for i in experimental_history) == {1000.0, 0.0001}
    assert len(set(frozenset(_flatten_nested_keys(i["model_params"]).items()) for i in experimental_history)) == 4
    assert set(test_results.keys()) == {"mrr", "mr", "hits_1", "hits_3", "hits_10"}
    print(test_results.values())
    assert all(r >= 0 for r in test_results.values())
    assert all(not np.isnan(r) for r in test_results.values())


def test_select_best_model_ranking_random():
    X = load_wn18rr()
    model_class = TransE
    param_grid = {
        "batches_count": [50],
        "seed": 0,
        "epochs": [1],
        "k": [2, 50],
        "eta": [1],
        "loss": ["nll"],
        "loss_params": {
        },
        "embedding_model_params": {
        },
        "regularizer": [None],

        "regularizer_params": {
        },
        "optimizer": ["adagrad"],
        "optimizer_params": {
            "lr": lambda: np.log(np.random.uniform(1.00001, 1.1))
        }
    }

    best_model, best_params, best_mrr_train, ranks_test, test_results, experimental_history = select_best_model_ranking(
        model_class,
        X['train'],
        X['valid'][::5],
        X['test'][::10],
        param_grid,
        max_combinations=10
    )
    assert best_params['k'] in (2, 50)
    assert np.log(1.00001) <= best_params['optimizer_params']['lr'] <= np.log(100)
    assert len(experimental_history) == 10
    assert set(i["model_params"]["k"] for i in experimental_history) == {2, 50}
    assert np.all(
        [np.log(1.00001) <= i["model_params"]["optimizer_params"]["lr"] <= np.log(100)
         for i in experimental_history]
    )
    assert len(set(frozenset(_flatten_nested_keys(i["model_params"]).items()) for i in experimental_history)) == 10
    assert set(test_results.keys()) == {"mrr", "mr", "hits_1", "hits_3", "hits_10"}
    assert all(r >= 0 for r in test_results.values())
    assert all(not np.isnan(r) for r in test_results.values())


def test_evaluate_with_ent_subset_large_graph():
    set_entity_threshold(1)
    X = load_wn18()
    model = ComplEx(
        batches_count=10, seed=0, epochs=2, k=10, eta=1,
        optimizer='sgd', optimizer_params={'lr': 1e-5},
        loss='pairwise', loss_params={'margin': 0.5},
        regularizer='LP', regularizer_params={'p': 2, 'lambda': 1e-5},
        verbose=True
    )

    model.fit(X['train'])

    X_filter = np.concatenate((X['train'], X['valid'], X['test']))
    all_nodes = set(X_filter[:, 0]).union(X_filter[:, 2])

    entities_subset = np.random.choice(list(all_nodes), 100, replace=False)

    ranks = evaluate_performance(
        X['test'][::10],
        model=model,
        filter_triples=X_filter,
        corrupt_side='o',
        use_default_protocol=False,
        entities_subset=list(entities_subset),
        verbose=True
    )
    assert np.sum(ranks > (100 + 1)) == 0, "No ranks must be greater than 101"
    reset_entity_threshold()
