import numpy as np
import scipy.sparse as sparse
import scipy.sparse.linalg as splinalg

def baseline_als(y, lam, p, niter=10):
	L = len(y)
	D = sparse.csc_matrix(np.diff(np.eye(L), 2))
	w = np.ones(L)
	for i in range(niter):
		W = sparse.spdiags(w, 0, L, L)
		Z = W + lam * D.dot(D.transpose())
		z = splinalg.spsolve(Z, w*y)
		w = p * (y > z) + (1-p) * (y < z)
	return z

def baseline_ials(y, lam, p, niter=10):
	L = len(y)
	D = sparse.csc_matrix(np.diff(np.eye(L), 2))
	D1 = sparse.csc_matrix(np.diff(np.eye(L), 1))
	w = np.ones(L)
	for i in range(niter):
		W = sparse.spdiags(w, 0, L, L)
		Z = W + lam * D.dot(D.transpose())
		z = splinalg.spsolve(Z, w*y)
		w = p * (y > z) + (1-p) * (y < z)
	return z