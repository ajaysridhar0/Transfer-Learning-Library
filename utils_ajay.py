# Classifier calibration utilities
# Kiri Wagstaff and Ajay Sridhar
# June 21, 2021
import sys
import os
from typing import List, Tuple, Optional

from scipy.optimize import minimize
from scipy.stats import norm
from statsmodels.stats.proportion import proportion_confint
from sklearn.metrics import confusion_matrix
import numpy as np
from KDEpy import FFTKDE

import seaborn as sn
import pandas as pd
import matplotlib.pyplot as plt
import torch
import torch.nn.functional as F


# To optimize NLL for temperature scaling (Guo et al., 2017)
# Inspired by implementation of Zhang et al. (2020)
def nll_fn(t, *args):
    # find optimal temperature with NLL loss function
    logit, label = args
    # adjust logits by T
    logit = logit / t
    # convert logits to probabilities
    probs = np.exp(logit) / np.sum(np.exp(logit), 1)[:, None]
    # avoid values too close to 0 or 1
    eps = 1e-20
    probs = np.clip(probs, eps, 1 - eps)
    # NLL
    nll = -np.sum(label * np.log(probs)) / probs.shape[0]

    return nll


# Use temperature scaling to modify probs, given labels.
# If probs_test is given, return its calibrated version too.
# Inspired by implementation of Zhang et al. (2020)
# with additional clipping of input probs.
def temp_scaling(logits, labels, n_classes, probs_test=[]):

    y = np.eye(n_classes)[labels] # one-hot encoding
    eps = 1e-20
    # ts_probs = np.clip(probs, eps, 1 - eps)
    # ts_logits = np.log(ts_probs) - np.log(1 - ts_probs)
    t = minimize(nll_fn, 1.0, args=(logits, y),
                    method='L-BFGS-B', bounds=((0.05, 5.0),),
                    tol=1e-12)
    t = t.x

    # If provided, generate calibrated probs for the test set
    if probs_test != []:
        ts_test_probs = np.clip(probs_test, eps, 1 - eps)
        test_logits = np.log(ts_test_probs) - np.log(1 - ts_test_probs)
        test_logits = test_logits / t
        new_test_probs = np.exp(test_logits) / \
            np.sum(np.exp(test_logits), 1)[:, None]
        return t, new_test_probs

    return t

# Mirror data about a domain boundary
def mirror_1d(d, xmin=None, xmax=None):
    """If necessary apply reflecting boundary conditions."""
    if xmin is not None and xmax is not None:
        xmed = (xmin+xmax)/2
        return np.concatenate(((2*xmin-d[d < xmed]).reshape(-1,1), d, (2*xmax-d[d >= xmed]).reshape(-1,1)))
    elif xmin is not None:
        return np.concatenate((2*xmin-d, d))
    elif xmax is not None:
        return np.concatenate((d, 2*xmax-d))
    else:
        return d


# Compute the kernel ECE as described by Zhang et al. (2020)
# https://github.com/zhang64-llnl/Mix-n-Match-Calibration
# Kernel = triweight
# bandwidth (h) = 1.06 * (std(prob vals)*2)^(1/5)
# Updates include:
# 1) Support for binary problems (in which the
# reliablity diagram is based on prob(class 1) instead of
# prob(most likely class).
# 2) Evenly-spaced probability grid that ensures 0 and 1 endpoints
# are included
# 3) If calc_acc is specified, return estimated accuarcy
# for each item as well as its density (z)
def kernel_ece(probs, labels, classes, give_kde_points=False, order=1,
               binary=False, verbose=False):

    # X values for KDE evaluation points
    # These values are based on the triweight kernel but may omit 0,1
    #x = np.linspace(-0.6, 1.6, num=2**14)
    # Instead, ensure that 0.0 and 1.0 are included
    # Grid has to be evenly spaced
    step = 0.0001
    x1 = np.arange(-0.6, 0.0, step)
    x2 = np.arange(0.0, 1.0, step)
    x3 = np.arange(1.0, 1.6, step)
    x = np.concatenate((x1, x2, x3))
    N = len(labels)

    kernel = 'triweight'

    # 1. Do KDE for accuracy using only correct predictions
    max_pred = np.argmax(probs, axis=1)
    if binary:
        if probs.shape[1] != 2:
            print('Error: kernel ECE with binary=True requires nx2 probs.')
            sys.exit(1)

        # Store the indicator of presence of class 1
        correct = [l == 1 for l in labels]
        # Store the probability of class 1 instead of the argmax prob
        max_prob = probs[:, 1]
    else:
        correct = [classes[p] == l for (p, l) in zip(max_pred, labels)]
        max_prob = np.max(probs, axis=1)
    probs_correct = max_prob[correct]
    if verbose:
        print('  %d accurate of %d preds' % (probs_correct.shape[0], N))
    # Specify a minimum value so it doesn't go to 0
    n_correct = np.sum(correct)
    # 1.06 is a magic number in Zhang et al.'s code.
    kbw = max(1.06 * np.std(probs_correct) * (n_correct * 2) ** -0.2,
              1e-4)
    if verbose:
        print('  bandwidth based on std of %d accurate preds x %f: %.4f' %
              (int(n_correct), 1.06 * (n_correct * 2) ** -0.2, kbw))

    # Mirror the data about the domain boundary to avoid edge effects
    low_bound = 0.0
    up_bound = 1.0
    probs_correct_m = mirror_1d(probs_correct.reshape(-1, 1),
                                low_bound, up_bound)
    if verbose:
        print('  mirror changes range from %.2f-%.2f to %.2f-%.2f' %
              (np.min(probs_correct), np.max(probs_correct),
               np.min(probs_correct_m), np.max(probs_correct_m)))
    # Compute KDE using the bandwidth found, and twice as many grid points
    kde1 = FFTKDE(bw=kbw, kernel=kernel).fit(probs_correct_m)
    pp1 = kde1.evaluate(x)
    pp1[x < low_bound] = 0 # Set the KDE to zero outside of the domain
    pp1[x > up_bound] = 0  # Set the KDE to zero outside of the domain
    if verbose:
        print('  integral: %.2f -> %.2f' % (np.sum(pp1) / sum(pp1 > 0),
                                            np.sum(pp1 * 2) / sum(pp1 > 0)))
    pp1 = pp1 * 2  # Double the y-values to get integral of ~1

    # 2. Do KDE for all predictions
    preds_m = mirror_1d(max_prob.reshape(-1, 1), low_bound, up_bound)
    if verbose:
        print('  mirror changes range from %.2f-%.2f to %.2f-%.2f' %
              (np.min(max_prob), np.max(max_prob),
               np.min(preds_m), np.max(preds_m)))
    # Compute KDE using the bandwidth found, and twice as many grid points
    kde2 = FFTKDE(bw=kbw, kernel=kernel).fit(preds_m)
    pp2 = kde2.evaluate(x)
    pp2[x < low_bound] = 0  # Set the KDE to zero outside of the domain
    pp2[x > up_bound] = 0  # Set the KDE to zero outside of the domain
    pp2 = pp2 * 2  # Double the y-values to get integral of ~1

    # Avg prob of being correct
    perc = np.mean(correct)
    #perc = 1.0 # ?
    # Sum the differences between confidence and accuracy
    # to get the (empirical) ECE for this data set,
    # using the closest grid point (x) to each prediction (pr)
    closest = [np.abs(x - pr).argmin() for pr in max_prob]
    est_acc = [perc * pp1[c] / pp2[c] for c in closest]
    ece = np.sum(np.abs(max_prob - est_acc) ** order) / N

    if give_kde_points:
        # Return accuracy and estimated mass at each test point
        z = [np.sum(pp2[c]) for c in closest]
        return ece, est_acc, max_prob, z

    return ece

def squared_error(probs, labels, num_classes):
    probs = np.array(probs)
    labels = np.array(labels)
    shape = (labels.size, num_classes)
    one_hot_targets = np.zeros(shape)
    rows = np.arange(labels.size)
    one_hot_targets[rows, labels] = 1
    return np.sum((probs - one_hot_targets)**2, axis=1)

def brier_multi(probs, labels, num_classes):
    return np.mean(squared_error(probs, labels, num_classes))

def mean_confidence_interval(data, confidence=0.95):
    lower = max(0, 0.5 - confidence/2)
    upper = min(1, 0.5 + confidence/2)
    return np.average(data), np.quantile(data, lower, interpolation='midpoint'), np.quantile(data, upper, interpolation='midpoint')

def bootstrap_conf_interval(data_getter, data_size, confidence=0.95, size=1000):
    bootstrap_distro = np.zeros(size)
    for i in range(size):
        data_indices = np.random.choice(data_size, size=data_size)
        bootstrap_distro[i] = data_getter(data_indices)
    return mean_confidence_interval(bootstrap_distro, confidence)

def kernel_ece_conf_interval(probs, labels, classes, order=1, binary=False, confidence=0.95, size=1000):
    
    def data_getter(data_indices):
        probs_star = []
        labels_star = []
        for i in data_indices:
            probs_star.append(probs[i])
            labels_star.append(labels[i])
        return kernel_ece(probs_star, labels_star, classes, 
                          False, order, binary)
        
    return bootstrap_conf_interval(data_getter, len(probs), confidence, size)

def brier_conf_interval(probs, labels, num_classes, confidence=0.95, size=1000):
    squared_error_arr = squared_error(probs, labels, num_classes)
    
    def data_getter(data_indices):
        return np.average(squared_error_arr[data_indices])
    
    return bootstrap_conf_interval(data_getter, len(probs), confidence, size)


def rejection_data(probs: List[List[int]], labels: List[int], classes: List[int], use_fraction_rejected: Optional[bool]=False,
                   confidence: Optional[float] = 0.95):
    assert len(probs) == len(labels)
    data = [(max(probs[i]), float(max(classes, key=lambda j: probs[i][j]) == labels[i]), 0.) for i in range(len(labels))]
    dtype = [('max_prob', float), ('acc', float), ('ci', float)]
    data = np.array(data, dtype=dtype)
    data = np.sort(data, order='max_prob')
    total = data[-1][1]
    
    for i in range(1, data.size):
        total += data[data.size - 1 - i][1]
        data[data.size - 1 - i][1] = total
        
    for i in range(data.size):
        if use_fraction_rejected:
            data[i][0] = (i + 1)/data.size
        count = data[i][1]
        nobs = data.size - i
        # calculate the agresti_coull interval for the accuracy
        ci_low, ci_upper = proportion_confint(count, nobs, 1 - confidence, 'agresti_coull')
        data[i][1] = count/nobs
        data[i][2] = (ci_upper - ci_low)/2
        
    return data

def generate_conf_mat(pred: List[int], y_true: List[int], 
    class_labels: str, folder_path: str, title: str, 
    normalize: Optional[bool]=None, 
    figsize: Optional[Tuple[int]]=(15, 12)):
    conf_mat = confusion_matrix(y_true, pred, normalize=normalize)
    df_conf_mat = pd.DataFrame(conf_mat, index=class_labels, columns=class_labels)
    if not os.path.exists(folder_path):
        os.makedirs(folder_path)
    df_conf_mat.to_csv(os.path.join(folder_path, title))
    plt.figure(figsize=figsize)
    sn.heatmap(df_conf_mat, annot=True)
    plt.title(title)
    plt.xlabel('Predicted')
    plt.ylabel('True')
    plt.savefig(os.path.join(folder_path, title))

def reliability_diag(conf: List[int], est_acc: List[int], density: List[int],
                      scaled_conf: List[int], scaled_est_acc: List[int], scaled_density: List[int],
                      log_path: str, dataset_type: str, figsize: Optional[Tuple[int]]=(7,7)):
    plt.figure(figsize=figsize)
    plt.plot([0, 1], [0, 1], color='blue', label='Perfect Calibration')
    plt.scatter(conf, est_acc, density, color='red', label='Non-Calibrated')
    plt.scatter(scaled_conf, scaled_est_acc, scaled_density, color='green', label='Calibrated')
    title = f"Reliability Diagram ({dataset_type} Set)"
    plt.title(title)
    plt.xlabel("Confidence")
    plt.ylabel("Expected Accuracy")
    plt.legend()
    
    graph_folder_path = os.path.join(log_path, 'reliability-diagram', 'graph')
    data_folder_path = os.path.join(log_path, 'reliability-diagram', 'data')
    if not os.path.exists(graph_folder_path):
        os.makedirs(graph_folder_path)
    if not os.path.exists(data_folder_path):
        os.makedirs(data_folder_path)
        
    plt.savefig(os.path.join(graph_folder_path, f'{title}.png'))
    np.save(os.path.join(data_folder_path, f'{title}_est_acc.npy'), est_acc)
    np.save(os.path.join(data_folder_path, f'{title}_conf_npy.npy'), conf)
    np.save(os.path.join(data_folder_path, f'{title}_density.npy'), density)
    np.save(os.path.join(data_folder_path, f'{title}_scaled_est_acc.npy'), scaled_est_acc)
    np.save(os.path.join(data_folder_path, f'{title}_scaled_conf.npy'), scaled_conf)
    np.save(os.path.join(data_folder_path, f'{title}_scaled_density.npy'), scaled_density)

def calibration_evaluation(class_probs: List[List[int]], 
                           class_labels: List[int], 
                           classes: List[int],
                           dataset_type: str,
                           temp_scaled: Optional[bool] = False,
                           use_ci: Optional[bool] = False,
                           confidence: Optional[float] = 0.95,
                           bootstrap_size: Optional[int] = 1000):
    log = {}
    ece, est_acc, conf, density = kernel_ece(class_probs, class_labels, classes, give_kde_points=True)
    
    add_on = ''
    if temp_scaled:
        add_on = 'Post-Temperature-Scaling ' 
    
    if use_ci:
        ece, ece_lower, ece_upper = kernel_ece_conf_interval(class_probs, class_labels, classes, 
                                                     confidence=confidence, size=bootstrap_size)
        brier, brier_lower, brier_upper = brier_conf_interval(class_probs, class_labels, len(classes), confidence, bootstrap_size)
        ece_lbound_title = f'KDE Expected Calibration Error Lower Bound {add_on}({dataset_type}, Confidence = {confidence})'
        ece_upbound_title = f'KDE Expected Calibration Error Upper Bound {add_on}({dataset_type}, Confidence = {confidence})'
        brier_lbound_title =  f'Brier Score Lower Bound {add_on}({dataset_type}, Confidence = {confidence})'
        brier_upbound_title = f'Brier Score Upper Bound {add_on}({dataset_type}, Confidence = {confidence})'
        print(f'{ece_lbound_title} : {ece_lower}')
        print(f'{ece_upbound_title} : {ece_upper}')
        print(f'{brier_lbound_title} : {brier_lower}')
        print(f'{brier_upbound_title} : {brier_upper}')
        log.update({ece_lbound_title : ece_lower,
                    ece_upbound_title : ece_upper,
                    brier_lbound_title : brier_lower,
                    brier_upbound_title : brier_upper})
    else:
        brier = brier_multi(class_probs, class_labels, len(classes))    
    
    print(f"KDE Expected Calibration Error {add_on}({dataset_type} Set): {ece}")
    print(f"Brier Score {add_on}({dataset_type} Set): {brier}")
    
    log.update({
        f'KDE Expected Calibration Error {add_on}({dataset_type})': ece,
        f'Brier Score {add_on}({dataset_type})': brier
    })

    return log, est_acc, conf, density

def temp_scale_probs(logits: torch.Tensor, temperature: int):
    scaled_logits = logits / temperature
    return F.softmax(scaled_logits, dim=1).tolist() 

def rejection_curve(probs: List[List[int]], labels: List[int], classes: List[int],
                     log_path: str, dataset_type: str, temp_scaled: Optional[bool]=False, 
                     use_fraction_rejected: Optional[bool]=False, figsize: Optional[Tuple[int]]=(10,10),
                     confidence: Optional[float] = 0.95):
    data = rejection_data(probs, labels, classes, use_fraction_rejected=use_fraction_rejected, confidence=confidence)
    add_on = ''
    if temp_scaled:
        add_on = 'Post-Temperature-Scaling '
    
    plt.figure(figsize=figsize)
    # unzip the probabilities and rejection probabilites
    xy_data = [(x, y) for x, y, conf in data]
    conf_data = [conf for x, y, conf in data]
    plt.scatter(*zip(*xy_data), s=0.5)
    plt.errorbar(*zip(*xy_data), yerr=conf_data, ecolor='#a2c1f2')
    
    if use_fraction_rejected:
        title = f'{add_on}Rejection Curve with Fraction Rejected ({dataset_type} Set)'
        plt.xlabel("Fraction Rejected")
    else:
        title = f'{add_on}Rejection Curve with Rejection Threshold ({dataset_type} Set)'
        plt.xlabel("Rejection Threshold")
    plt.ylabel("Accuracy")
    plt.title(title)
    
    graph_folder_path = os.path.join(log_path, 'rejection-curve', 'graph', dataset_type)
    data_folder_path = os.path.join(log_path, 'rejection-curve', 'data', dataset_type)
    if not os.path.exists(graph_folder_path):
        os.makedirs(graph_folder_path)
    if not os.path.exists(data_folder_path):
        os.makedirs(data_folder_path)
    np.save(os.path.join(data_folder_path, f'{title}_data.npy'), data)
    plt.savefig(os.path.join(graph_folder_path, f'{title}.png'))
# statsmodels.stats.proportion.proportion_confint
# method = "agresti_coull"
# ci_low, ci_upp = statsmodels.stats.proportion.proportion_confint(count, nobs, 1 - confidence, 'agresti_coull')
    
