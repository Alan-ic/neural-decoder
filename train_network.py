import argparse

parser = argparse.ArgumentParser(description='Train a neural network to decode a code.',
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog='''\
''')
parser.add_argument('dist', type=int,
                    help='the distance of the code')
parser.add_argument('out', type=str,
                    help='the name of the output file (used as a prefix for the log file as well)')
parser.add_argument('--trainset', type=str,
                    help='the name of the training set file (generated by `generate_training_data.py`); if not specified --onthefly is assumed')
parser.add_argument('--onthefly', type=int, nargs=2, default=[2000000, 50000],
                    help='generate the training set on the fly, specify training and validation size (default: %(default)s)')
parser.add_argument('--prob', type=float, default=0.9,
                    help='the probability of no error on the physical qubit when generating training data (considered only if --onthefly is present) (default: %(default)s)')
parser.add_argument('--load', type=str, default='',
                    help='the file from which to load a pretrained model weights (optional, requires correct hyperparameters)')
parser.add_argument('--eval', action='store_true',
                    help='if present, calculate the fraction of successful corrections based on sampling the NN using the validation set')
parser.add_argument('--giveup', type=int, default=1000000,
                    help='after how many samples to give up decoding a given test error vector (considered only if --eval is present) (default: %(default)s)')
parser.add_argument('--batch', type=int, default=512,
                    help='the batch size (default: %(default)s)')
parser.add_argument('--epochs', type=int, default=20,
                    help='the number of epochs (default: %(default)s)')
parser.add_argument('--learningrate', type=float, default=0.002,
                    help='the learning rate (default: %(default)s)')
parser.add_argument('--hact', type=str, default='tanh',
                    help='the activation for hidden layers (default: %(default)s)')
parser.add_argument('--act', type=str, default='sigmoid',
                    help='the activation for the output layer (default: %(default)s)')
parser.add_argument('--loss', type=str, default='binary_crossentropy',
                    help='the loss to be optimized (default: %(default)s)')
parser.add_argument('--layers', type=float, default=[4, 4, 4], nargs='+',
                    help='the list of sizes of the hidden layers (as a factor of the output layer) (default: %(default)s)')
parser.add_argument('--Zstab', action='store_true',
                    help='if present, include the Z stabilizer in the neural network')
parser.add_argument('--Xstab', action='store_true',
                    help='if present, include the X stabilizer in the neural network')

args = parser.parse_args()
print(args)

from neural import create_model, data_generator
from codes import ToricCode
import numpy as np
import tqdm


if args.trainset:
    f = np.load(args.trainset)
    x_test = []
    y_test = []
    if args.Zstab:
        x_test.append(f['arr_4'])
        y_test.append(f['arr_5'])
    if args.Xstab:
        x_test.append(f['arr_6'])
        y_test.append(f['arr_7'])
    x_test = np.hstack(x_test)
    y_test = np.hstack(y_test)

model = create_model(L=args.dist,
                     hidden_sizes=args.layers,
                     hidden_act=args.hact,
                     act=args.act,
                     loss=args.loss,
                     Z=args.Zstab, X=args.Xstab,
                     learning_rate=args.learningrate)
if args.load:
    model.load_weights(args.load)
if args.epochs:
    if args.trainset:
        x_train = []
        y_train = []
        if args.Zstab:
            x_train.append(f['arr_0'])
            y_train.append(f['arr_1'])
        if args.Xstab:
            x_train.append(f['arr_2'])
            y_train.append(f['arr_3'])
        x_train = np.hstack(x_train)
        y_train = np.hstack(y_train)
        hist = model.fit(x_train, y_train,
                         nb_epoch=args.epochs,
                         batch_size=args.batch,
                         validation_data=(x_test, y_test)
                        )
    else:
        dat = data_generator(ToricCode, args.dist, args.prob, args.batch,
                             args.Zstab, args.Xstab)
        val = data_generator(ToricCode, args.dist, args.prob, args.batch,
                             args.Zstab, args.Xstab)
        hist = model.fit_generator(dat, args.onthefly[0], args.epochs,
                                   validation_data=val, nb_val_samples=args.onthefly[1])
    model.save_weights(args.out)
    with open(args.out+'.log', 'w') as f:
        f.write(str((hist.params, hist.history)))
if args.eval:
    L = args.dist
    H = ToricCode(L).H(args.Zstab,args.Xstab)
    E = ToricCode(L).E(args.Zstab,args.Xstab)
    both = args.Zstab and args.Xstab
    if both:
        Hz = ToricCode(L).H(True, False)
        Hx = ToricCode(L).H(False, True)
    outlen = 2*L**2*(args.Zstab+args.Xstab)
    inlen = L**2*(args.Zstab+args.Xstab)
    c = cz = cx = 0
    giveup = args.giveup
    if args.trainset:
        stabflipgen = zip(x_test, y_test)
        size = len(y_test)
    else:
        size = args.onthefly[1]
        stabflipgen = data_generator(ToricCode, args.dist, args.prob, 1, args.Zstab, args.Xstab, size=size)
    full_log = np.zeros((size, E.shape[0]+args.Zstab+args.Xstab), dtype=int)
    for i, (stab, flips) in tqdm.tqdm(enumerate(stabflipgen), total=size):
        stab.shape = 1, inlen # TODO this should be unnecessary
        pred = model.predict(stab).ravel() # TODO those seem like unnecessary shape changes
        sample = pred>np.random.uniform(size=outlen)
        if both:
            attemptsZ = 1
            attemptsX = 1
            while np.any(stab[0,:inlen//2]!=Hz.dot(sample[:outlen//2])%2) and attemptsZ < giveup: # TODO the zero index in stab should not be necessary
                sample[:outlen//2] = pred[:outlen//2]>np.random.uniform(size=outlen//2)
                attemptsZ += 1
            while np.any(stab[0,inlen//2:]!=Hx.dot(sample[outlen//2:])%2) and attemptsX < giveup: # TODO the zero index in stab should not be necessary
                sample[outlen//2:] = pred[outlen//2:]>np.random.uniform(size=outlen//2)
                attemptsX += 1
        else:
            attempts = 1
            while np.any(stab!=H.dot(sample)%2) and attempts < giveup:
                sample = pred>np.random.uniform(size=outlen)
                attempts += 1
        errors = E.dot((sample+flips.ravel())%2)%2 # TODO this also seems like an unnecessary ravel
        if np.any(errors) or np.any(stab!=H.dot(sample)%2):
            c += 1
            if both:
                cz += np.any(errors[:len(errors)//2])
                cx += np.any(errors[len(errors)//2:])
        if both:
            full_log[i,:-2] = errors
            full_log[i,-2] = attemptsZ
            full_log[i,-1] = attemptsX
        else:
            full_log[i,:-1] = errors
            full_log[i,-1] = attempts
    with open(args.out+'.eval', 'w') as f:
        if both:
            f.write(str(((1-c/size),(1-cz/size),(1-cx/size))))
        else:
            f.write(str(((1-c/size),)))
    np.savetxt(args.out+'.eval.log', full_log, fmt='%d')
