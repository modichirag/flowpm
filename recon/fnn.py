import numpy as np
import os, sys
import math, time
from scipy.interpolate import InterpolatedUnivariateSpline as iuspline

import tensorflow.compat.v1 as tf
tf.disable_v2_behavior()
import tensorflow_probability as tfp
import mesh_tensorflow as mtf



def setupfnn():

    ppath = '/project/projectdirs/m3058/chmodi/cosmo4d/train/L0400_N0128_05step-n10/width_3/Wts_30_10_1/r1rf1/hlim-13_nreg-43_batch-5/'
    pwts, pbias = [], []
    # act = [lambda x: relu(x), lambda x: relu(x), lambda x: sigmoid(x)]
    act = [lambda x: relu(x), lambda x: relu(x), lambda x: relu(x)]

    for s in [0, 2, 4]:
        pwts.append(np.load(ppath + 'w%d.npy'%s))
        pbias.append(np.load(ppath + 'b%d.npy'%s))
    pmx = np.load(ppath + 'mx.npy')
    psx = np.load(ppath + 'sx.npy')


    mpath = '/project/projectdirs/m3058/chmodi/cosmo4d/train/L0400_N0128_05step-n10/width_3/Wts_30_10_1/r1rf1/hlim-13_nreg-43_batch-5/eluWts-10_5_1/blim-20_nreg-23_batch-100/'
    mwts, mbias = [], []
    # act = [lambda x: relu(x), lambda x: relu(x), lambda x: sigmoid(x)]
    act = [lambda x: elu(x), lambda x: elu(x), lambda x: linear(x)]

    for s in [0, 2, 4]:
        mwts.append(np.load(mpath + 'w%d.npy'%s))
        mbias.append(np.load(mpath + 'b%d.npy'%s))
    mmx = np.load(mpath + 'mx.npy')
    msx = np.load(mpath + 'sx.npy')
    mmy = np.load(mpath + 'my.npy')
    msy = np.load(mpath + 'sy.npy')

    size = 3
    kernel = np.zeros([size, size, size, 1, size**3])
    for i in range(size):
        for j in range(size):
            for k in range(size):
                kernel[i, j, k, 0, i*size**2+j*size+k] = 1

    return [pwts, pbias, pmx, psx],  [mwts, mbias, mmx, msx, mmy, msy], kernel


def setnoise(datasm, noisefile, noisevar=0.25):
    
    noise3d = np.ones_like(datasm)*noisevar**0.5

    noise = np.loadtxt(noisefile)
    noise[:, -1] *=np.sqrt(2) #Add hoc factor of 2 to increase noise! 
    #As it happens, the factor of \sqrt(2) is cz of def of gaussian - \sqrt(2)*\sigma^2 in exp
    for foo in range(noise.shape[0]):
        #file format is mhigh, mlow, mean, std
        mhigh = noise[foo][0]
        mlow = noise[foo][1]
        pos = np.where((datasm[...] > mlow) & (datasm[...] < mhigh))
        noise3d[pos] = noise[foo][3]

    ivar3d = noise3d ** -2

    #
    mean3d = np.zeros_like(datasm)

    # for foo in range(len(mbinsm) -2):
    for foo in range(noise.shape[0]):
        mhigh = noise[foo][0]
        mlow = noise[foo][1]
        pos = np.where((datasm[...] > mlow) & (datasm[...] <= mhigh))
        mean3d[pos] = noise[foo][2]

    return mean3d, ivar3d



def tfwrap3D(image, padding=1):
    
    upper_pad = image[:, -padding:,:, :]
    lower_pad = image[:, :padding,:, :]
    
    partial_image = tf.concat([upper_pad, image, lower_pad], axis=1)
    
    left_pad = partial_image[:, :,-padding:, :]
    right_pad = partial_image[:, :,:padding, :]
    
    partial_image = tf.concat([left_pad, partial_image, right_pad], axis=2)
    
    front_pad = partial_image[:, :,:, -padding:]
    back_pad = partial_image[:, :,:, :padding]
    
    padded_image = tf.concat([front_pad, partial_image, back_pad], axis=3)
    return padded_image

def sinc(x):
    x = x + 1e-3 #x = tf.where(tf.abs(x) < 1e-20, 1e-20 * tf.ones_like(x), x)
    return tf.sin(np.pi*x) / x/np.pi

def float_to_mtf(x, mesh, scalar):
    return mtf.import_tf_tensor(mesh, tf.constant(x, shape=[1]), shape=[scalar])

def cwise_gauss(kfield, R, kx, ky, kz, nc, bs):
    kx = tf.reshape(kx, [-1, 1, 1]) *nc/bs
    ky = tf.reshape(ky, [1, -1, 1]) *nc/bs 
    kz = tf.reshape(kz, [1, 1, -1]) *nc/bs
    kk = tf.sqrt(kx**2 + ky**2 + kz**2)
    wts = tf.exp(-0.5 * R**2 * kk**2)
    return kfield * tf.cast(wts, kfield.dtype)

def cwise_decic(kfield, kx, ky, kz, nc, bs):
    kx = tf.reshape(kx, [-1, 1, 1]) *nc/bs 
    ky = tf.reshape(ky, [1, -1, 1]) *nc/bs 
    kz = tf.reshape(kz, [1, 1, -1]) *nc/bs 
    wts = sinc(kx*bs/(2*np.pi*nc)) *sinc(ky*bs/(2*np.pi*nc)) *sinc(kz*bs/(2*np.pi*nc))
    wts = tf.pow(wts, -2.)
    return kfield * tf.cast(wts, kfield.dtype)

def cwise_fingauss(kfield, R, kx, ky, kz, nc, bs):
    kny = 1*np.pi*nc/bs
    kx = tf.reshape(kx, [-1, 1, 1]) *nc/bs 
    ky = tf.reshape(ky, [1, -1, 1]) *nc/bs 
    kz = tf.reshape(kz, [1, 1, -1]) *nc/bs 
    kk = tf.sqrt((2*kny/np.pi*tf.sin(kx*np.pi/(2*kny)))**2 + (2*kny/np.pi*tf.sin(ky*np.pi/(2*kny)))**2 + (2*kny/np.pi*tf.sin(kz*np.pi/(2*kny)))**2)
    wts = tf.exp(-0.5 * R**2 * kk**2)
    return kfield * tf.cast(wts, kfield.dtype)



def shear(pm, base):
    '''Takes in a PMesh object in real space. Returns am array of shear'''
    s2 = pm.create(mode='real', value=0)
    kk = base.r2c().x
    k2 = sum(ki**2 for ki in kk)
    k2[0,0,0] =  1
    for i in range(3):
        for j in range(i, 3):
            basec = base.r2c()
            basec *= (kk[i]*kk[j] / k2 - diracdelta(i, j)/3.)
            baser = basec.c2r()
            s2[...] += baser**2
            if i != j:
                s2[...] += baser**2
            
    return s2
