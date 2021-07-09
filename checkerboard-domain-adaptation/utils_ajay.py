# Classifier calibration utilities
# Kiri Wagstaff
# June 21, 2021
import sys
import scipy
import numpy as np
from KDEpy import FFTKDE


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
    t = scipy.optimize.minimize(nll_fn, 1.0, args=(logits, y),
                                method='L-BFGS-B', bounds=((0.05, 55.0),),
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
def kernel_ece(probs, labels, classes, calc_acc=False, order=1,
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
    # Numerically integrate to get ECE estimate
    integral = np.zeros(x.shape)
    for i in range(x.shape[0]):
        conf = x[i]
        if np.max([pp1[i], pp2[i]]) > 1e-6:
            acc = np.min([perc * pp1[i] / pp2[i], 1.0])
            if not np.isnan(acc):
                integral[i] = np.abs(conf - acc) ** order * pp2[i]
        else: # Numbers are very small, so just carry forward
            if i > 1:
                integral[i] = integral[i-1]

    # Restrict to the range [0, 1]
    ind = np.where((x >= low_bound) & (x <= up_bound))
    ece = np.trapz(integral[ind], x[ind]) / np.trapz(pp2[ind], x[ind])

    # Find the closest x value and use it for the estimate
    if calc_acc:
        # Note: it is finding the closest, but if
        # pr is really close to 0 or 1, and 0/1 are not in x,
        # it could find the "closest" outside of that range.
        # Fixed above to ensure 0 and 1 are in x.
        est_acc = [perc *
                   pp1[np.abs(x - pr).argmin()] /
                   pp2[np.abs(x - pr).argmin()] for pr in max_prob]
        closest = [np.abs(x - pr).argmin() for pr in max_prob]
        z = [np.sum(pp2[c]) for c in closest]
        return ece, est_acc, z, np.arange(0.0, 1.0 + step, step)

    return ece
