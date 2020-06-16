"""
site amplification functionality from wcc_siteamp.c
Acceleration amplification models.

@date 24 June 2016
@author Viktor Polak
@contact viktor.polak@canterbury.ac.nz

Implemented Models
==============================
cb_amp (version = "2008"):
    Based on Campbell and Bozorgnia 2008 - added 24 June 2016
cb_amp (version = "2014"):
    Based on Campbell and Bozorgnia 2014 - added 22 September 2016
ba18_amp (version 2018):
    Based on Bayless Fourier Amplitude Spectra Empirical Model - added 11 June 2020

Usage
==============================
from siteamp_models import cb_amp (or *)
cb_amp(variables, ...)
"""

# math functions faster than numpy for non-vector data
from math import ceil, exp, log
import os

import numpy as np
import pandas as pd

ba18_coefs_df = None


def init_ba18():
    global ba18_coefs_df
    __location__ = os.path.realpath(
        os.path.join(os.getcwd(), os.path.dirname(__file__))
    )
    ba18_coefs_file = os.path.join(
        __location__, "siteamp_coefs_files", "Bayless_ModelCoefs.csv"
    )
    ba18_coefs_df = pd.read_csv(ba18_coefs_file, index_col=0)


def nt2n(nt):
    """
    Length the fourier transform should be
    given timeseries length nt.
    """
    return int(2 ** ceil(log(nt) / log(2)))


def cb_amp(
    dt,
    n,
    vref,
    vsite,
    vpga,
    pga,
    version="2014",
    flowcap=0.0,
    fmin=0.2,
    fmidbot=0.5,
    fmid=1.0,
    fhigh=10 / 3.0,
    fhightop=10.0,
    fmax=15.0,
):
    # cb constants
    scon_c = 1.88
    scon_n = 1.18

    # fmt: off
    freqs = 1.0 / np.array([0.001, 0.01, 0.02, 0.03, 0.05, 0.075, 0.10,
                            0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.75,
                            1.00, 1.50, 2.00, 3.00, 4.00, 5.00, 7.50, 10.0])
    if version == '2008':
        c10 = np.array([1.058, 1.058, 1.102, 1.174, 1.272, 1.438, 1.604,
                        1.928, 2.194, 2.351, 2.460, 2.587, 2.544, 2.133,
                        1.571, 0.406,-0.456,-0.82, -0.82, -0.82, -0.82, -0.82])
    elif version == '2014':
        # named c11 in cb2014
        c10 = np.array([1.090, 1.094, 1.149, 1.290, 1.449, 1.535, 1.615,
                        1.877, 2.069, 2.205, 2.306, 2.398, 2.355, 1.995,
                        1.447, 0.330, -0.514, -0.848, -0.793, -0.748, -0.664,
                        -0.576])
    else:
        raise Exception('BAD CB AMP version specified.')
    k1 = np.array([865.0, 865.0, 865.0, 908.0, 1054.0, 1086.0, 1032.0,
                   878.0, 748.0, 654.0, 587.0,  503.0,  457.0,  410.0,
                   400.0, 400.0, 400.0, 400.0,  400.0,  400.0,  400.0, 400.0])
    k2 = np.array([-1.186, -1.186, -1.219, -1.273, -1.346, -1.471, -1.624,
                   -1.931, -2.188, -2.381, -2.518, -2.657, -2.669, -2.401,
                   -1.955, -1.025, -0.299,  0.0,    0.0,    0.0,    0.0, 0.0])
    # fmt: on

    # f_site function domains
    def fs_low(T, vs30, a1100):
        return c10[T] * log(vs30 / k1[T]) + k2[T] * log(
            (a1100 + scon_c * exp(scon_n * log(vs30 / k1[T]))) / (a1100 + scon_c)
        )

    def fs_mid(T, vs30, a1100=None):
        return (c10[T] + k2[T] * scon_n) * log(vs30 / k1[T])

    def fs_high(T, vs30=None, a1100=None):
        return (c10[T] + k2[T] * scon_n) * log(1100.0 / k1[T])

    def fs_auto(T, vs30):
        return fs_low if vs30 < k1[T] else fs_mid if vs30 < 1100.0 else fs_high

    #                 fs1100     - fs_vpga
    a1100 = pga * exp(fs_high(0) - fs_auto(0, vpga)(0, vpga, pga))

    # calculate factor for each period
    it = (
        exp(fs_auto(T, vsite)(T, vsite, a1100) - fs_auto(T, vref)(T, vref, a1100))
        for T in range(freqs.size)
    )
    ampf0 = np.fromiter(it, dtype=np.float)
    try:
        # T is the first occurance of a value <= flowcap
        T = np.flatnonzero((freqs <= flowcap))[0]
        ampf0[T:] = ampf0[T]
    except IndexError:
        pass

    ampf, ampv, ftfreq = interpolate_frequency(freqs, ampf0, dt, n)

    # amplification factors applied differently at different bands
    ampf[1:] += (
        np.where(
            (ftfreq >= fhightop) & (ftfreq < fmax),
            -1 + ampv + np.log(ftfreq / fhightop) * (1.0 - ampv) / log(fmax / fhightop),
            0,
        )
        + np.where((ftfreq >= fmidbot) & (ftfreq < fhightop), -1 + ampv, 0)
        + np.where(
            (ftfreq >= fmin) & (ftfreq < fmidbot),
            np.log(ftfreq / fmin) * (ampv - 1.0) / log(fmidbot / fmin),
            0,
        )
    )

    return ampf


def interpolate_frequency(freqs, ampf0, dt, n):

    # frequencies of fourier transform
    ftfreq = np.arange(1, n / 2) * (1.0 / (n * dt))
    # transition indexes
    digi = np.digitize(freqs, ftfreq)[::-1]
    # default amplification is 1.0 (keeping values the same)
    ampf = np.ones(ftfreq.size + 1, dtype=np.float)
    # only go down to 2nd frequency
    ampf0[0] = ampf0[1]
    freqs[0] = freqs[1]
    # special case, first frequency in transition range
    ftfreq0 = int(digi[0] == 0)
    # all possible dadf factors
    dadf0 = np.zeros(freqs.size)
    for i in range(1, freqs.size - 1):
        # start with dadf = 0.0 if no freq change at pos 0
        dadf0[-i - 1 - ftfreq0] = (ampf0[i] - ampf0[i + 1]) / log(
            freqs[i] / freqs[i + 1]
        )
    # calculate amplification factors
    digi = np.hstack((digi, [ftfreq.size]))
    a0 = np.zeros(ftfreq.size)
    f0 = np.zeros(ftfreq.size)
    dadf = np.zeros(ftfreq.size)
    start = 0
    start_dadf = 0
    for i in range(freqs.size):
        end = max(start + 1, digi[i + 1])
        end_dadf = max(start_dadf + 1, digi[i + ftfreq0])
        a0[start:end] = ampf0[-i - 1]
        f0[start:end] = freqs[-i - 1]
        dadf[start_dadf:end_dadf] = dadf0[i]
        start = max(end, digi[i + 1])
        start_dadf = end_dadf
    ampv = a0 + dadf * np.log(ftfreq / f0)
    return ampf, ampv, ftfreq


def cb_amp_old(
    dt,
    n,
    vref,
    vsite,
    vpga,
    pga,
    version="2008",
    flowcap=0.0,
    fmin=0.2,
    fmidbot=0.5,
    fmid=1.0,
    fhigh=10 / 3.0,
    fhightop=10.0,
    fmax=15.0,
):
    """
    DO NOT USE (SLOW), ONLY KEPT FOR UNVECTORISED LOGIC VISIBILITY
    """
    # cb08 constants
    n_per = 22
    scon_c = 1.88
    scon_n = 1.18
    # fmt:off
    per = np.array([0.00, 0.01, 0.02, 0.03, 0.05, 0.075, 0.10,
            0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.75,
            1.00, 1.50, 2.00, 3.00, 4.00, 5.00, 7.50, 10.0])
    m_freq = 1.0 / per
    f1_src = np.hstack(([1000.0], m_freq[1:]))
    if version == '2008':
        c10 = np.array([1.058, 1.058, 1.102, 1.174, 1.272, 1.438, 1.604,
                1.928, 2.194, 2.351, 2.460, 2.587, 2.544, 2.133,
                1.571, 0.406, -0.456, -0.82, -0.82, -0.82, -0.82, -0.82])
    elif version == '2014':
        c10 = np.array([1.090, 1.094, 1.149, 1.290, 1.449, 1.535, 1.615,
                1.877, 2.069, 2.205, 2.306, 2.398, 2.355, 1.995,
                1.447, 0.330, -0.514, -0.848, -0.793, -0.748, -0.664, -0.576])
    else:
        raise Exception('BAD CB AMP version specified.')
    k1 = np.array([865.0, 865.0, 865.0, 908.0, 1054.0, 1086.0, 1032.0,
            878.0, 748.0, 654.0, 587.0, 503.0, 457.0, 410.0,
            400.0, 400.0, 400.0, 400.0, 400.0, 400.0, 400.0, 400.0])
    k2 = np.array([-1.186, -1.186, -1.219, -1.273, -1.346, -1.471, -1.624,
            -1.931, -2.188, -2.381, -2.518, -2.657, -2.669, -2.401,
            -1.955, -1.025, -0.299, 0.0, 0.0, 0.0, 0.0, 0.0])
    # fmt: on

    # f_site function domains
    # TODO: normal functions for speed, will require testing
    fs_low = lambda T, vs30, a1100: c10[T] * log(vs30 / k1[T]) + k2[T] * log(
        (a1100 + scon_c * exp(scon_n * log(vs30 / k1[T]))) / (a1100 + scon_c)
    )
    fs_mid = lambda T, vs30, a1100=None: (c10[T] + k2[T] * scon_n) * log(vs30 / k1[T])
    fs_high = lambda T, vs30=None, a1100=None: (c10[T] + k2[T] * scon_n) * log(
        1100.0 / k1[T]
    )
    fs_auto = (
        lambda T, vs30: fs_low if vs30 < k1[T] else fs_mid if vs30 < 1100.0 else fs_high
    )
    fs1100 = fs_high(0)

    # default amplification is 1.0 (keeping values the same)
    ampf = np.ones(n / 2, np.float)

    fs_vpga = fs_auto(0, vpga)(0, vpga, pga)
    a1100 = pga * exp(fs1100 - fs_vpga)

    # calculate factor for each period
    it = (
        exp(fs_auto(T, vsite)(T, vsite, a1100) - fs_auto(T, vref)(T, vref, a1100))
        for T in range(n_per)
    )
    ampf0 = np.fromiter(it, np.float, count=n_per)

    try:
        # T is the first occurance of a value <= flowcap
        # throws IndexError if no results (the second [0])
        T = np.nonzero((m_freq[:-1] <= flowcap))[0][0]
        # T cannot be the last value because of the following logic
        ampf0[T + 1 :] = ampf0[T]
    except IndexError:
        pass
    # frequencies of fourier transform
    ftfreq = np.arange(1, n / 2) * (1.0 / (n * dt))

    # calculate ampv based on period group
    j = n_per - 1
    f0 = f1_src[j]
    a0 = ampf0[j]
    f1 = f0
    a1 = a0
    dadf = 0.0
    for i, ftf in enumerate(ftfreq):
        if ftf > f1:
            f0 = f1
            a0 = a1
            if j - 1:
                j -= 1
                a1 = ampf0[j]
                f1 = f1_src[j]
                dadf = (a1 - a0) / log(f1 / f0)
            else:
                dadf = 0.0
        ampv = a0 + dadf * log(ftf / f0)

        # scale amplification factor by frequency
        if ftf < fmin:
            continue
        if ftf < fmidbot:
            ampf[i + 1] = 1.0 + log(ftf / fmin) * (ampv - 1.0) / log(fmidbot / fmin)
        elif ftf < fhightop:
            ampf[i + 1] = ampv
        elif ftf < fmax:
            ampf[i + 1] = ampv + log(ftf / fhightop) * (1.0 - ampv) / log(
                fmax / fhightop
            )

    return ampf


# dt, n, vref, vsite, vpga, pga, version='2014', flowcap=0.0, fmin=0.2, fmidbot=0.5, fmid=1.0, fhigh=10 / 3., fhightop=10.0, fmax=15.0
def ba18_amp(
    dt,
    n,
    vref,
    vs,
    vpga,
    pga,
    version=None,
    flowcap=None,
    fmin=None,
    fmidbot=None,
    fmid=None,
    fhigh=None,
    fhightop=None,
    fmax=None,
):
    """

    :return:
    """
    if vs < 1000:
        vs = 999

    ref, __ = ba_18_siteamp(vref, pga)
    amp, freqs = ba_18_siteamp(vs, pga)

    ampf, ampv, ftfreq = interpolate_frequency(freqs, amp / ref, dt, n)

    return ampf


def ba_18_siteamp(vs, pga):
    vsref = 1000

    if ba18_coefs_df is None:
        print(
            "You need to call the init_ba18 function before using the site_amp functions"
        )
        exit()
    coefs = type("coefs", (object,), {})  # creates a custom object for coefs
    coefs.freq = ba18_coefs_df.index.values

    # Non-linear site parameters
    coefs.f3 = ba18_coefs_df.f3.values
    coefs.f4 = ba18_coefs_df.f4.values
    coefs.f5 = ba18_coefs_df.f5.values
    coefs.b8 = ba18_coefs_df.c8.values

    lnfas = coefs.b8 * np.log(min(vs, 1000) / vsref)

    maxfreq = 23.988321
    imax = np.where(coefs.freq == maxfreq)[0][0]
    fas_lin = np.exp(lnfas)

    # Extrapolate to 100 Hz
    fas_maxfreq = fas_lin[imax]
    # Kappa
    kappa = np.exp(-0.4 * np.log(vs / 760) - 3.5)
    # Diminuition operator
    D = np.exp(-np.pi * kappa * (coefs.freq[imax:] - maxfreq))

    fas_lin = np.append(fas_lin[:imax], fas_maxfreq * D)
    lnfas = np.log(fas_lin)

    # Compute non-linear site response
    # get the EAS_rock at 5 Hz (no c8, c11 terms)
    vref = 760

    IR = pga

    coefs.f2 = coefs.f4 * (
        np.exp(coefs.f5 * (min(vs, vref) - 360)) - np.exp(coefs.f5 * (vref - 360))
    )
    fnl0 = coefs.f2 * np.log((IR + coefs.f3) / coefs.f3)

    fnl0[np.where(fnl0 == min(fnl0))[0][0] :] = min(fnl0)
    return fnl0 + lnfas, coefs.freq


def hashash_get_pgv(fnorm, mag, rrup, ztor):
    b4a = -0.5
    mbreak = 6.0

    coefs = type("coefs", (object,), {})  # creates a custom object for coefs
    coefs.freq = ba18_coefs_df.index.values

    coefs.b1 = ba18_coefs_df.c1.values
    coefs.b2 = ba18_coefs_df.c2.values
    coefs.b3quantity = ba18_coefs_df["(c2-c3)/cn"].values
    coefs.bn = ba18_coefs_df.cn.values
    coefs.bm = ba18_coefs_df.cM.values
    coefs.b4 = ba18_coefs_df.c4.values
    coefs.b5 = ba18_coefs_df.c5.values
    coefs.b6 = ba18_coefs_df.c6.values
    coefs.bhm = ba18_coefs_df.chm.values
    coefs.b7 = ba18_coefs_df.c7.values
    coefs.b8 = ba18_coefs_df.c8.values
    coefs.b9 = ba18_coefs_df.c9.values
    coefs.b10 = ba18_coefs_df.c10.values
    # row = df.iloc[df.index == 5.011872]
    i5 = np.where(coefs.freq == 5.011872)
    lnfasrock5Hz = coefs.b1[i5]
    lnfasrock5Hz += coefs.b2[i5] * (mag - mbreak)
    lnfasrock5Hz += coefs.b3quantity[i5] * np.log(
        1 + np.exp(coefs.bn[i5] * (coefs.bm[i5] - mag))
    )
    lnfasrock5Hz += coefs.b4[i5] * np.log(
        rrup + coefs.b5[i5] * np.cosh(coefs.b6[i5] * max(mag - coefs.bhm[i5], 0))
    )
    lnfasrock5Hz += (b4a - coefs.b4[i5]) * np.log(np.sqrt(rrup ** 2 + 50 ** 2))
    lnfasrock5Hz += coefs.b7[i5] * rrup
    lnfasrock5Hz += coefs.b9[i5] * min(ztor, 20)
    lnfasrock5Hz += coefs.b10[i5] * fnorm
    # Compute PGA_rock extimate from 5 Hz FAS
    IR = np.exp(1.238 + 0.846 * lnfasrock5Hz)
    return IR
